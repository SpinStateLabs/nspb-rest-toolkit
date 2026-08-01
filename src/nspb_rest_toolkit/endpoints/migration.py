"""Migration / LCM. Source: docs/endpoint-inventory.md section 8.

Separate API family from Planning -- base path `interop/rest/v2`, NOT
`HyperionPlanning/rest/v3`. family="migration" on every call() here.

Migration jobs use a NUMERIC status contract (-1 in progress, 0 success,
1 completed with issues), different from Planning's named-state contract --
poll_migration_job() uses EPMClient.poll_job(family="migration", ...) which
handles this.
"""

from __future__ import annotations

from typing import Any

from ..client import EPMClient


async def export_snapshot(client: EPMClient, snapshot_name: str, *, confirm: bool = False) -> dict[str, Any]:
    """Trigger a repeat export of a Migration artifact snapshot. DESTRUCTIVE.

    Requires Service Administrator or the "Migrations - Administer"
    granular role on the connection's credentials. Never call with
    confirm=True on the same turn as the user's first request.
    """
    resp = await client.call(
        "POST",
        "/snapshots/export",
        family="migration",
        json={"SnapshotName": snapshot_name},
        destructive=True,
        confirm=confirm,
    )
    return resp.json()


async def import_snapshot(
    client: EPMClient,
    snapshot_name: str,
    *,
    import_users: bool | None = None,
    user_password: str | None = None,
    reset_password: bool | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Import the contents of an application snapshot. DESTRUCTIVE -- overwrites application content.

    Importing users requires Identity Domain Administrator role.
    `user_password` is passed straight through to Oracle in the request
    body per their documented API shape and is never logged by this client
    (Authorization header and known secret-shaped JSON keys are redacted in
    all error paths), but avoid passing it unless the customer's process
    actually requires resetting imported users' passwords. Never call with
    confirm=True on the same turn as the user's first request -- describe
    exactly what will be overwritten and wait for explicit confirmation.
    """
    body: dict[str, Any] = {"SnapshotName": snapshot_name}
    if import_users is not None:
        body["importUsers"] = import_users
    if user_password is not None:
        body["userPassword"] = user_password
    if reset_password is not None:
        body["resetPassword"] = reset_password

    resp = await client.call(
        "POST", "/snapshots/import", family="migration", json=body, destructive=True, confirm=confirm
    )
    return resp.json()


async def get_migration_status(client: EPMClient) -> dict[str, Any]:
    """Get migration (export/import) history: action, duration, status, per-artifact report. Read-only."""
    resp = await client.call("GET", "/migration/status", family="migration")
    return resp.json()


async def get_migration_job_status(client: EPMClient, job_id: str) -> dict[str, Any]:
    """Poll the status of an in-flight migration job by ID. Read-only."""
    resp = await client.call("GET", f"/status/migration/{job_id}", family="migration")
    return resp.json()


async def poll_migration_job(
    client: EPMClient,
    job_id: str,
    *,
    poll_interval: float = 5.0,
    timeout: float = 1800.0,
) -> dict[str, Any]:
    """Poll a migration job to a terminal state. Read-only.

    Uses the Migration numeric-status contract (-1/0/1). A returned status
    of 1 ("completed with issues") is a valid terminal state, not an
    exception -- call get_migration_job_task_details() to see what went
    wrong.
    """
    return await client.poll_job(
        "migration",
        f"/status/migration/{job_id}",
        poll_interval=poll_interval,
        timeout=timeout,
    )


async def get_migration_job_task_details(
    client: EPMClient,
    job_id: str,
    task_id: str,
    *,
    limit: int | None = None,
    offset: int | None = None,
    msgtype: str | None = None,
) -> dict[str, Any]:
    """Get detailed task-level messages for a migration job. Read-only.

    Call this after poll_migration_job() returns status 1 ("completed with
    issues") to see what actually happened.
    """
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if msgtype is not None:
        params["msgtype"] = msgtype

    resp = await client.call(
        "GET",
        f"/status/migration/{job_id}/{task_id}/details",
        family="migration",
        params=params or None,
    )
    return resp.json()


async def get_migration_api_versions(client: EPMClient) -> dict[str, Any]:
    """List available Migration API versions with lifecycle/latest metadata. Read-only.

    This resource is unversioned (GET {base_url}/interop/rest/, no /v2
    suffix) unlike every other call in this module, so it uses the client's
    absolute-URL escape hatch rather than the "migration" family base path.
    """
    resp = await client.call("GET", f"{client.connection.base_url}/interop/rest/")
    return resp.json()
