"""Substitution Variables. Source: docs/endpoint-inventory.md section 10.

Only the application-scoped CRUD is implemented here (confirmed exact path
templates). Plan-type-scoped and derived-variable operations are confirmed
to exist in Oracle's docs but their exact path templates were not
independently re-fetched during Phase 0 research -- see the inventory doc's
section 10 note before adding them.
"""

from __future__ import annotations

from typing import Any

from ..client import EPMClient, unwrap_items


async def list_substitution_variables(client: EPMClient, application: str) -> list[dict[str, Any]]:
    """Get all substitution variables defined for the application, across all plan types. Read-only."""
    resp = await client.call("GET", f"/applications/{application}/substitutionvariables")
    return unwrap_items(resp.json())


async def get_substitution_variable(client: EPMClient, application: str, name: str) -> dict[str, Any] | None:
    """Get a single substitution variable by name. Read-only.

    Confirmed live (2026-08-01) against a real tenant: this endpoint
    responds `204 No Content` (empty body, `Content-Type: application/json`)
    for an existing, correctly-named variable -- not an error, but not
    usable to retrieve the value either. This looks like a genuine Oracle
    quirk on this specific resource, not a client-side request mistake
    (headers/path match the working `list_substitution_variables` call
    exactly). Returns None on a 204. Prefer `list_substitution_variables`
    and filter by name client-side -- confirmed to actually return the
    name/value/planType data this endpoint doesn't.
    """
    resp = await client.call("GET", f"/applications/{application}/substitutionvariables/{name}")
    if resp.status_code == 204 or not resp.text:
        return None
    return resp.json()


async def set_substitution_variables(
    client: EPMClient,
    application: str,
    variables: list[dict[str, Any]],
    *,
    confirm: bool = False,
) -> None:
    """Create or update (upsert by name+scope) substitution variables. DESTRUCTIVE.

    `variables` is a list of {"name": ..., "value": ..., "planType": ...}
    ("ALL" or a specific plan type). Returns None on success (Oracle returns
    HTTP 204). Never call with confirm=True on the same turn as the user's
    first request -- list the variable names/values that will change and
    wait for explicit confirmation.
    """
    await client.call(
        "POST",
        f"/applications/{application}/substitutionvariables",
        json={"items": variables},
        destructive=True,
        confirm=confirm,
    )


async def delete_substitution_variables(
    client: EPMClient,
    application: str,
    variables: list[dict[str, Any]],
    *,
    confirm: bool = False,
) -> None:
    """Delete one or more substitution variables. DESTRUCTIVE.

    `variables` identifies items by name+planType, e.g.
    [{"name": "CurYr", "planType": "ALL"}]. Never call with confirm=True on
    the same turn as the user's first request.
    """
    await client.call(
        "POST",
        f"/applications/{application}/substitutionvariables:delete",
        json={"items": variables},
        destructive=True,
        confirm=confirm,
    )
