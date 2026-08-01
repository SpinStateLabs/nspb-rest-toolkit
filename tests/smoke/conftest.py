"""Fixtures for optional live-tenant smoke tests.

These tests are NOT part of the default `pytest` run (pyproject.toml scopes
`testpaths` to tests/unit) and require real credentials via environment
variables. Run explicitly with:

    pytest tests/smoke -v

Required env vars:
    NSPB_SMOKE_CONNECTION_CONFIG  Path to a connections.yaml with a real connection.
    NSPB_SMOKE_CONNECTION         Connection slug within that file to test against.
    NSPB_SMOKE_APPLICATION        A real Planning application name on that tenant.
    NSPB_SMOKE_PLANTYPE           A real plan type (cube) name within that application.
    NSPB_SMOKE_FORM               A real form name/ID readable by the test credentials.

    <CREDENTIAL_REF>_USERNAME / <CREDENTIAL_REF>_PASSWORD -- resolved per
    connections.yaml's credential_ref for the chosen connection (Basic auth
    only -- see docs/SKILL.md section 6 for the OAuth2 gap).

Optional, for the destructive round-trip test (skipped unless both are set):
    NSPB_SMOKE_ALLOW_DESTRUCTIVE=1
    NSPB_SMOKE_BUSINESS_RULE      Name of a real, safe-to-run business rule.

This file intentionally never runs anything itself -- it only wires up
fixtures. Whether/when to actually execute these against a live tenant is a
decision for whoever runs pytest, not for this test suite.
"""

from __future__ import annotations

import os

import pytest

from nspb_rest_toolkit.client import EPMClient
from nspb_rest_toolkit.config import load_config


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"smoke test requires env var {name}")
    return value


@pytest.fixture
def smoke_application() -> str:
    return _require_env("NSPB_SMOKE_APPLICATION")


@pytest.fixture
def smoke_plantype() -> str:
    return _require_env("NSPB_SMOKE_PLANTYPE")


@pytest.fixture
def smoke_form() -> str:
    return _require_env("NSPB_SMOKE_FORM")


@pytest.fixture
async def smoke_client():
    config_path = _require_env("NSPB_SMOKE_CONNECTION_CONFIG")
    connection_slug = _require_env("NSPB_SMOKE_CONNECTION")

    cfg = load_config(config_path)
    conn = cfg.get(connection_slug)
    client = EPMClient(conn)
    try:
        yield client
    finally:
        await client.aclose()
