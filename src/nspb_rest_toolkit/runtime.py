"""Shared runtime helpers for the OpenAPI, MCP, and Open WebUI surfaces.

Every operation is stateless per call: resolve a `connection` slug from the
multi-tenant config, construct a short-lived EPMClient, run one operation,
close it. This matches Basic Auth's "build the header fresh every call"
design and avoids holding credentials/connections in memory between calls.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

from .client import EPMClient
from .config import ToolkitConfig, load_config, load_config_from_env
from .exceptions import EPMConfigError

CONFIG_PATH_ENV = "NSPB_CONFIG_PATH"
DEFAULT_CONFIG_PATH = "connections.yaml"


def config_path() -> str:
    return os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH)


def get_config() -> ToolkitConfig:
    """A real connections.yaml always wins when present (the multi-tenant
    path); otherwise fall back to zero-config env-var mode (see
    config.load_config_from_env) for the common single-customer case.
    """
    path = config_path()
    if Path(path).exists():
        return load_config(path)

    zero_config = load_config_from_env()
    if zero_config is not None:
        return zero_config

    raise EPMConfigError(
        f"No configuration found -- '{path}' doesn't exist and NSPB_BASE_URL isn't set. Either "
        f"create a connections.yaml (see README.md's multi-tenant setup) or set NSPB_BASE_URL "
        f"(+ credentials, e.g. NSPB_USERNAME/NSPB_PASSWORD for Basic Auth) as environment "
        f"variables for single-connection zero-config mode."
    )


@contextlib.asynccontextmanager
async def connected_client(connection: str) -> AsyncIterator[EPMClient]:
    """Resolve `connection` from config and yield a short-lived EPMClient."""
    cfg = get_config()
    conn = cfg.get(connection)
    client = EPMClient(conn)
    try:
        yield client
    finally:
        await client.aclose()
