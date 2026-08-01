"""Applications. Source: docs/endpoint-inventory.md section 3."""

from __future__ import annotations

from typing import Any

from ..client import EPMClient, unwrap_items


async def list_applications(client: EPMClient) -> list[dict[str, Any]]:
    """List the Planning applications the calling user is assigned to.

    Read-only. Requires Service Administrator role on the connection's
    credentials. Returns key app metadata (type, theme, storage type, etc.).
    """
    resp = await client.call("GET", "/applications")
    return unwrap_items(resp.json())


async def get_application_summary(client: EPMClient, application: str) -> str:
    """Get an automation-oriented summary of an application's structure.

    Read-only. Returns markdown-ish text, not JSON -- confirmed live
    (2026-08-01): the original implementation called `resp.json()` here,
    which threw `JSONDecodeError` against a real tenant's non-JSON response
    body. Oracle notes this response's exact formatting may change between
    releases -- treat it as a discovery aid, not a stable contract to parse
    rigidly.
    """
    resp = await client.call("GET", f"/applications/{application}/summary")
    return resp.text
