r"""Ad hoc live check of every safe read-only endpoint against a real tenant.

Not part of the pytest suite -- this is a discovery-driven script (each step
feeds real names discovered from an earlier step into the next), run
directly by whoever holds the credentials, in their own terminal:

    $env:NSPB_SMOKE_CONNECTION_CONFIG = "connections.yaml"
    $env:NSPB_SMOKE_CONNECTION = "bpc"
    # + <credential_ref>_USERNAME / <credential_ref>_PASSWORD (or the
    #   connection's oauth2/bearer_token credential) already set
    .\.venv\Scripts\python.exe scripts\live_read_only_check.py

Deliberately excludes:
- Every DESTRUCTIVE operation (writes, business rules, imports, clears,
  status changes) -- this script never sets confirm=True.
- export_security / export_cell_level_security -- tagged read (they don't
  touch plan data) but they write a CSV/ZIP file into Oracle's Planning
  repository as a side effect, which isn't a "pure" read.
- Anything needing an ID this script has no way to discover safely (a form
  name -- Oracle's REST API has no "list forms" resource per
  docs/endpoint-inventory.md section 5 -- or a job ID from a job this
  script never submitted).

Each check is independent and best-effort: one failure doesn't stop the
rest, and every result is printed with a clear PASS/FAIL/SKIP so a human can
read the full picture at the end. Never prints credentials -- only the JSON
payloads Oracle returns, which don't contain any.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nspb_rest_toolkit.client import EPMClient  # noqa: E402
from nspb_rest_toolkit.config import load_config  # noqa: E402
from nspb_rest_toolkit.endpoints import applications, dimensions, migration, approvals, substitution_variables  # noqa: E402
from nspb_rest_toolkit.exceptions import EPMHTTPError, EPMToolkitError  # noqa: E402

_results: list[tuple[str, str, str]] = []  # (label, status, detail)


def _preview(value: Any, limit: int = 300) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


async def _check(label: str, coro) -> Any:
    try:
        result = await coro
        _results.append((label, "PASS", _preview(result)))
        print(f"[PASS] {label}\n       {_preview(result)}\n")
        return result
    except EPMHTTPError as exc:
        # exc's own message doesn't include Oracle's response body -- surface
        # it explicitly, it usually explains *why* (e.g. a 415's expected
        # media type, a 400's validation message).
        detail = f"{exc} | body={exc.redacted_body!r}"
        _results.append((label, "FAIL", detail))
        print(f"[FAIL] {label}\n       {detail}\n")
        return None
    except EPMToolkitError as exc:
        _results.append((label, "FAIL", str(exc)))
        print(f"[FAIL] {label}\n       {exc}\n")
        return None
    except Exception as exc:  # noqa: BLE001 -- best-effort discovery script
        _results.append((label, "FAIL", f"{type(exc).__name__}: {exc}"))
        print(f"[FAIL] {label}\n       {type(exc).__name__}: {exc}\n")
        return None


def _skip(label: str, reason: str) -> None:
    _results.append((label, "SKIP", reason))
    print(f"[SKIP] {label}\n       {reason}\n")


async def main() -> None:
    try:
        config_path = os.environ["NSPB_SMOKE_CONNECTION_CONFIG"]
        connection_slug = os.environ["NSPB_SMOKE_CONNECTION"]
    except KeyError as exc:
        print(f"Missing required env var {exc}. Set NSPB_SMOKE_CONNECTION_CONFIG and NSPB_SMOKE_CONNECTION first.")
        raise SystemExit(1) from exc

    cfg = load_config(config_path)
    conn = cfg.get(connection_slug)
    print(f"Testing connection '{connection_slug}' ({conn.display_name}) at {conn.base_url}\n")

    client = EPMClient(conn)
    try:
        apps = await _check("applications.list_applications", applications.list_applications(client))
        app_name = apps[0]["name"] if apps else None

        if app_name:
            await _check(
                f"applications.get_application_summary({app_name!r})",
                applications.get_application_summary(client, app_name),
            )
            plan_types = await _check(
                f"dimensions.list_plan_types({app_name!r})",
                dimensions.list_plan_types(client, app_name),
            )
        else:
            _skip("applications.get_application_summary", "no application discovered")
            plan_types = None
            _skip("dimensions.list_plan_types", "no application discovered")

        plantype_name = None
        if plan_types:
            # planTypeName is the string identifier the URL path expects
            # ("Plan"); planType is a numeric ID, not usable in the path --
            # this fallback chain got that backwards in an earlier version
            # of this script and caused a spurious 404.
            plantype_name = plan_types[0].get("planTypeName") or plan_types[0].get("cubeName")
        if app_name and plantype_name:
            dims = await _check(
                f"dimensions.list_dimensions({app_name!r}, {plantype_name!r})",
                dimensions.list_dimensions(client, app_name, plantype_name),
            )
        else:
            _skip("dimensions.list_dimensions", "no plan type discovered")
            dims = None

        if app_name and plantype_name and dims:
            dim_name = dims[0].get("name")
            if dim_name:
                await _check(
                    f"dimensions.get_dimension({app_name!r}, {plantype_name!r}, {dim_name!r})",
                    dimensions.get_dimension(client, app_name, plantype_name, dim_name),
                )
            else:
                _skip("dimensions.get_dimension", "first dimension result had no 'name' key")
        else:
            _skip("dimensions.get_dimension", "no dimension discovered")

        if app_name:
            subvars = await _check(
                f"substitution_variables.list_substitution_variables({app_name!r})",
                substitution_variables.list_substitution_variables(client, app_name),
            )
            if subvars:
                var_name = subvars[0].get("name")
                if var_name:
                    await _check(
                        f"substitution_variables.get_substitution_variable({app_name!r}, {var_name!r})",
                        substitution_variables.get_substitution_variable(client, app_name, var_name),
                    )
                else:
                    _skip("substitution_variables.get_substitution_variable", "first result had no 'name' key")
            else:
                _skip("substitution_variables.get_substitution_variable", "no substitution variables defined")
        else:
            _skip("substitution_variables.*", "no application discovered")

        await _check("migration.get_migration_status", migration.get_migration_status(client))
        await _check("migration.get_migration_api_versions", migration.get_migration_api_versions(client))

        scenario = os.environ.get("NSPB_SMOKE_SCENARIO")
        version = os.environ.get("NSPB_SMOKE_VERSION")
        if app_name and scenario and version:
            planning_units = await _check(
                f"approvals.list_planning_units({app_name!r}, {scenario!r}, {version!r})",
                approvals.list_planning_units(client, app_name, scenario, version),
            )
            pu_identifier = None
            if isinstance(planning_units, dict):
                items = planning_units.get("items") or planning_units.get("planningUnits")
                if isinstance(items, list) and items:
                    first = items[0]
                    pu_identifier = first.get("puName") or first.get("pu") or first.get("id") or first.get("name")
                    if not pu_identifier:
                        print(f"       (planning unit found but no recognized identifier field -- raw keys: {list(first.keys())})\n")
            if pu_identifier:
                await _check(
                    f"approvals.get_available_actions({app_name!r}, {pu_identifier!r})",
                    approvals.get_available_actions(client, app_name, pu_identifier),
                )
            else:
                _skip("approvals.get_available_actions", "no planning unit identifier discovered (or none exist for this scenario/version)")
        else:
            _skip(
                "approvals.*",
                "needs NSPB_SMOKE_SCENARIO and NSPB_SMOKE_VERSION env vars (real scenario/version names on this tenant) -- not discoverable from any other read call",
            )

        _skip("security.export_security / export_cell_level_security", "writes a file into the Planning repository as a side effect -- excluded on purpose")
        _skip("forms.read_form_grid_shape / read_form_data", "no 'list forms' REST resource exists -- needs a known form name (set NSPB_SMOKE_FORM and extend this script if you want it covered)")
        _skip("jobs.get_job_status / migration.get_migration_job_status", "needs a real job ID from a job this script never submitted")
    finally:
        await client.aclose()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for label, status, _ in _results:
        print(f"  [{status}] {label}")
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    skipped = sum(1 for _, s, _ in _results if s == "SKIP")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")


if __name__ == "__main__":
    asyncio.run(main())
