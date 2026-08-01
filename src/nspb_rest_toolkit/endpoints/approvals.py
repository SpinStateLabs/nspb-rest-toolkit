"""Approvals (Planning Unit workflow). Source: docs/endpoint-inventory.md section 11.

Oracle documents this feature under "Planning Units," not "Approvals" --
same promote/reject/sign-off workflow. All three confirmed operations are
POST requests, and **all three use `application/x-www-form-urlencoded`
bodies, not JSON** -- confirmed against Oracle's own documentation
(2026-08-01) after a JSON body on `list_planning_units` returned HTTP 415
against a real tenant (a bare WebLogic/JAX-RS media-type rejection, not an
Oracle application error). Only change_planning_unit_status actually
mutates state -- list/available-actions are tagged read despite the POST
verb.
"""

from __future__ import annotations

import json as json_module
from typing import Any
from urllib.parse import quote

from ..client import EPMClient

# actionId values from docs/endpoint-inventory.md section 11. Oracle's docs
# confirm both the string keyword ("PROMOTE") and this numeric code are
# valid -- sending the numeric form here is fine, not a guess.
PLANNING_UNIT_ACTIONS: dict[str, int] = {
    "APPROVE": 2,
    "SIGN_OFF": 3,
    "PROMOTE": 6,
    "DELEGATE": 7,
    "TAKE_OWNERSHIP": 8,
    "ORIGINATE": 9,
    "FREEZE": 10,
}


def _format_filter(f: dict[str, Any]) -> str:
    """Build Oracle's filter value shape: `{name:"X",type:N,values:[...]}`.

    NOT valid JSON -- the `name`/`type`/`values` keys are deliberately
    unquoted, matching Oracle's own documented example for List All
    Planning Units exactly. `f` needs `name` (str), `type` (int filter-type
    code per Oracle's docs), and `values` (list).
    """
    name = json_module.dumps(f["name"])
    values = json_module.dumps(f["values"])
    return f'{{name:{name},type:{f["type"]},values:{values}}}'


async def list_planning_units(
    client: EPMClient,
    application: str,
    scenario: str,
    version: str,
    *,
    filter: list[dict[str, Any]] | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List planning units owned by the requesting user for a scenario/version. Read-only.

    Confirmed against Oracle's documented request shape (2026-08-01):
    `scenario`/`version` go in a `q` query parameter as JSON
    (`{"scenario": ..., "version": ...}`), NOT the body. `filter`, if
    given, is sent as an `application/x-www-form-urlencoded` body with one
    repeated `filter=` field per entry (see `_format_filter`) -- Oracle's
    documented example: `filter={name:"Status",type:4,values:[2,5]}
    &filter={name:"SubStatus",type:3,values:[0,4]}`.
    """
    params: dict[str, Any] = {"q": json_module.dumps({"scenario": scenario, "version": version})}
    if offset is not None:
        params["offset"] = offset
    if limit is not None:
        params["limit"] = limit

    data = [("filter", _format_filter(f)) for f in filter] if filter else None

    resp = await client.call("POST", f"/applications/{application}/planningunits", params=params, data=data)
    return resp.json()


async def get_available_actions(
    client: EPMClient,
    application: str,
    pu_identifier: str,
    *,
    pm_members: list[str] | None = None,
    full_approvals: bool = True,
) -> dict[str, Any]:
    """List the next valid workflow actions for a planning unit owned by the caller. Read-only.

    Possible actions: Promote, Sign Off, Reject, Delegate, Take Ownership,
    Originate, Freeze.

    Confirmed against Oracle's documented request shape (2026-08-01):
    optional `q={"options": 0|1}` query param (1 = full approvals, the
    default; 0 = limited, for mobile clients) and an optional
    `application/x-www-form-urlencoded` `pmMembers=A,B,C` body for
    secondary members -- NOT JSON. `pu_identifier` (e.g.
    `Forecast::"BU Version_1"`) is URL-encoded before insertion into the
    path since it can contain `:`, `"`, and spaces, none of which are safe
    unescaped in a URL path segment.
    """
    params = {"q": json_module.dumps({"options": 1 if full_approvals else 0})}
    data = [("pmMembers", ",".join(pm_members))] if pm_members else None

    resp = await client.call(
        "POST",
        f"/applications/{application}/planningunits/{quote(pu_identifier, safe='')}/availableactions",
        params=params,
        data=data,
    )
    return resp.json()


async def change_planning_unit_status(
    client: EPMClient,
    application: str,
    puh_identifier: str,
    action: str,
    *,
    pm_members: list[str] | None = None,
    comments: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Execute a Planning Unit workflow action (promote/sign off/reject/etc.). DESTRUCTIVE.

    `action` must be one of PLANNING_UNIT_ACTIONS' keys (e.g. "PROMOTE").
    Call get_available_actions() first to confirm this action is actually
    valid for the unit's current status before describing it to the user.
    Never call with confirm=True on the same turn as the user's first
    request.

    Confirmed against Oracle's documented request shape (2026-08-01):
    `application/x-www-form-urlencoded` body (`actionId`, `pmMembers`,
    `comments`), NOT JSON -- same class of fix applied to the other two
    Planning Unit endpoints above after `list_planning_units`'s JSON body
    returned HTTP 415 against a real tenant. This function itself has NOT
    been live-tested (it's destructive) -- the request shape is
    documentation-confirmed, not live-confirmed, unlike the read-only two
    above. `puh_identifier` is URL-encoded before insertion into the path.
    """
    if action not in PLANNING_UNIT_ACTIONS:
        raise ValueError(f"Unknown planning unit action '{action}'. Valid actions: {sorted(PLANNING_UNIT_ACTIONS)}")

    data: list[tuple[str, str]] = [("actionId", str(PLANNING_UNIT_ACTIONS[action]))]
    if pm_members is not None:
        data.append(("pmMembers", ",".join(pm_members)))
    if comments is not None:
        data.append(("comments", comments))

    resp = await client.call(
        "POST",
        f"/applications/{application}/planningunits/{quote(puh_identifier, safe='')}/actions",
        data=data,
        destructive=True,
        confirm=confirm,
    )
    return resp.json()
