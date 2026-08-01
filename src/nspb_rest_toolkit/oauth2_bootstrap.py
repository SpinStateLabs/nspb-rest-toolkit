"""One-time interactive Device Code bootstrap CLI for auth_method=oauth2 connections.

Usage:
    python -m nspb_rest_toolkit.oauth2_bootstrap --config connections.yaml --connection acme-corp

Prints a verification URL and user code, polls Oracle's token endpoint
until you approve the request in a browser, then writes the initial
access + refresh token to the connection's on-disk token cache (see
oauth2.py). Run this once per oauth2 connection -- `EPMClient` handles
unattended refresh automatically from then on via `OAuth2TokenManager`.

This step is inherently interactive (a human has to approve in a browser)
and is deliberately not automated further. Follows the same `python -m`
entry-point pattern as mcp_server.py and openapi_server.py.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import load_config
from .exceptions import EPMToolkitError
from .oauth2 import bootstrap_device_flow


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m nspb_rest_toolkit.oauth2_bootstrap",
        description="One-time OAuth2 Device Code bootstrap for an auth_method=oauth2 connection.",
    )
    parser.add_argument("--config", required=True, help="Path to connections.yaml")
    parser.add_argument(
        "--connection", required=True, help="Connection slug to bootstrap (must be auth_method: oauth2)"
    )
    return parser.parse_args(argv)


async def _run(config_path: str, connection_slug: str) -> None:
    cfg = load_config(config_path)
    conn = cfg.get(connection_slug)
    if conn.auth_method != "oauth2":
        raise EPMToolkitError(
            f"Connection '{connection_slug}' has auth_method={conn.auth_method!r}, not "
            f"'oauth2' -- nothing to bootstrap."
        )
    await bootstrap_device_flow(conn)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    try:
        asyncio.run(_run(args.config, args.connection))
    except EPMToolkitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
