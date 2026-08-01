r"""One-off diagnostic for the approvals.list_planning_units HTTP 415.

Bypasses EPMClient.call() entirely (it discards the httpx.Request on a
non-2xx response, so there's no way to inspect what was actually sent once
call() raises) and makes the identical request by hand, then prints the
REAL outgoing request headers httpx recorded -- not what we intended to
send, what actually went over the wire.

Run exactly like scripts/live_read_only_check.py (same env vars already
set in your window):

    .\.venv\Scripts\python.exe scripts\diag_planning_units_415.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nspb_rest_toolkit.config import load_config  # noqa: E402
from nspb_rest_toolkit.client import EPMClient  # noqa: E402


async def main() -> None:
    config_path = os.environ["NSPB_SMOKE_CONNECTION_CONFIG"]
    connection_slug = os.environ["NSPB_SMOKE_CONNECTION"]
    cfg = load_config(config_path)
    conn = cfg.get(connection_slug)

    client = EPMClient(conn)
    try:
        headers = await client._auth_header()  # noqa: SLF001 -- diagnostic only
        headers["Content-Type"] = "application/json; charset=utf-8"
        url = f"{conn.planning_base_url()}/applications/NetSuite/planningunits"

        print("Sending POST to:", url)
        print("Headers we're asking httpx to send:", {k: ("***" if k.lower() == "authorization" else v) for k, v in headers.items()})

        resp = await client._http.request("POST", url, json={}, headers=headers)  # noqa: SLF001

        # BUG FIXED 2026-08-01: this used to print dict(resp.request.headers)
        # unredacted, which leaked the real Basic Auth header (base64 of
        # username:password -- trivially decodable, not encryption) to the
        # terminal and, from there, into a screenshot and a pasted chat
        # message. Redact exactly like client.py's own _redact_headers does.
        sent_headers = {
            k: ("***REDACTED***" if k.lower() == "authorization" else v) for k, v in resp.request.headers.items()
        }
        print("\n--- What httpx actually put on the wire ---")
        print("Request headers:", sent_headers)
        print("Request body:", resp.request.content)
        print("\n--- Response ---")
        print("Status:", resp.status_code)
        print("Response headers:", dict(resp.headers))
        print("Response body:", resp.text[:500])
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
