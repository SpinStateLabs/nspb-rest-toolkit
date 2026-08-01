"""Access Permissions. Source: docs/endpoint-inventory.md section 9.

No dedicated, synchronous per-object (form/dimension/member) security CRUD
endpoint is documented. ACL/security data moves entirely through the
generic Jobs framework -- these are thin, discoverability-oriented wrappers
over endpoints.jobs.submit_job for the four security-related job types.
"""

from __future__ import annotations

from typing import Any

from ..client import EPMClient
from . import jobs


async def import_security(
    client: EPMClient,
    application: str,
    file_name: str,
    *,
    clear_all: bool | None = None,
    error_file: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Import ACL/security records from a CSV file already in the Planning repository. DESTRUCTIVE.

    `clear_all=True` wipes existing permissions before importing -- treat
    that as a significantly bigger blast radius when describing this action
    to the user. Never call with confirm=True on the same turn as the
    user's first request.
    """
    parameters: dict[str, Any] = {"fileName": file_name}
    if clear_all is not None:
        parameters["clearAll"] = clear_all
    if error_file is not None:
        parameters["errorFile"] = error_file
    return await jobs.submit_job(
        client, application, "IMPORT_SECURITY", file_name, parameters=parameters, confirm=confirm
    )


async def export_security(client: EPMClient, application: str, file_name: str) -> dict[str, Any]:
    """Export ACL/security records to a CSV file in the Planning repository. Read-only."""
    return await jobs.submit_job(client, application, "EXPORT_SECURITY", file_name, parameters={"fileName": file_name})


async def import_cell_level_security(
    client: EPMClient, application: str, file_name: str, *, confirm: bool = False
) -> dict[str, Any]:
    """Import cell-level security from a ZIP file in the Planning repository. DESTRUCTIVE."""
    return await jobs.submit_job(
        client,
        application,
        "IMPORT_CELL_LEVEL_SECURITY",
        file_name,
        parameters={"fileName": file_name},
        confirm=confirm,
    )


async def export_cell_level_security(client: EPMClient, application: str, file_name: str) -> dict[str, Any]:
    """Export cell-level security to a ZIP file. Read-only."""
    return await jobs.submit_job(
        client, application, "EXPORT_CELL_LEVEL_SECURITY", file_name, parameters={"fileName": file_name}
    )
