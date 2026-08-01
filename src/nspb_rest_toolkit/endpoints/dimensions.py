"""Dimensions / Members. Source: docs/endpoint-inventory.md section 4.

No dedicated edit/delete-member REST resource is documented -- member edits
beyond add route through the IMPORT_METADATA job type (see jobs.py).
"""

from __future__ import annotations

from typing import Any

from ..client import EPMClient, unwrap_items


async def list_plan_types(client: EPMClient, application: str) -> list[dict[str, Any]]:
    """List plan types (cubes) for an application. Read-only."""
    resp = await client.call("GET", f"/applications/{application}/plantypes")
    return unwrap_items(resp.json())


async def list_dimensions(
    client: EPMClient,
    application: str,
    plantype: str,
    *,
    q: str | None = None,
) -> list[dict[str, Any]]:
    """List dimensions associated with a plan type. Read-only."""
    params = {"q": q} if q else None
    resp = await client.call("GET", f"/applications/{application}/plantypes/{plantype}/dimensions", params=params)
    return unwrap_items(resp.json())


async def get_dimension(
    client: EPMClient,
    application: str,
    plantype: str,
    dimension: str,
) -> dict[str, Any]:
    """Get a dimension's hierarchy/details, including hidden and attribute dimensions. Read-only."""
    resp = await client.call("GET", f"/applications/{application}/plantypes/{plantype}/dimensions/{dimension}")
    return resp.json()


async def get_member(client: EPMClient, application: str, dimension: str, member: str) -> dict[str, Any]:
    """Get a single member's properties (parent, data storage, data type, etc.). Read-only.

    Requires Service Administrator role on the connection's credentials.
    """
    resp = await client.call("GET", f"/applications/{application}/dimensions/{dimension}/members/{member}")
    return resp.json()


async def add_member(
    client: EPMClient,
    application: str,
    dimension: str,
    member_name: str,
    parent_name: str,
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    """Add a new member under a specified parent in a dimension outline. DESTRUCTIVE.

    The parent must already be enabled for dynamic children and the cube
    must be refreshed beforehand, or Oracle will reject the request. Never
    call with confirm=True on the same turn as the user's first request --
    describe the change, wait for explicit confirmation, then retry with
    confirm=True.
    """
    body = {"memberName": member_name, "parentName": parent_name}
    resp = await client.call(
        "POST",
        f"/applications/{application}/dimensions/{dimension}/members",
        json=body,
        destructive=True,
        confirm=confirm,
    )
    return resp.json()
