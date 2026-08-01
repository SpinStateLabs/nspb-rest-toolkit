"""Endpoint-wrapper tests for behavior confirmed only via live testing.

Not exhaustive coverage of every endpoints/ module (that's what
tests/smoke + scripts/live_read_only_check.py are for) -- these specifically
pin down response-shape quirks discovered against a real tenant on
2026-08-01, so a regression doesn't silently reappear.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from nspb_rest_toolkit.client import EPMClient
from nspb_rest_toolkit.config import ConnectionConfig
from nspb_rest_toolkit.endpoints import substitution_variables

pytestmark = pytest.mark.asyncio

BASIC_CONN = ConnectionConfig(
    display_name="Acme Corp",
    base_url="https://acme.example.com",
    auth_method="basic",
    credential_ref="ACME",
)
PLANNING_BASE = "https://acme.example.com/HyperionPlanning/rest/v3"


async def test_get_substitution_variable_returns_none_on_204(monkeypatch):
    monkeypatch.setenv("ACME_USERNAME", "user")
    monkeypatch.setenv("ACME_PASSWORD", "pass")
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        respx.get(f"{PLANNING_BASE}/applications/Vision/substitutionvariables/Benefit").mock(
            return_value=httpx.Response(204, headers={"content-type": "application/json; charset=UTF-8"})
        )
        result = await substitution_variables.get_substitution_variable(client, "Vision", "Benefit")
        assert result is None
    await client.aclose()


async def test_get_substitution_variable_returns_json_on_200(monkeypatch):
    monkeypatch.setenv("ACME_USERNAME", "user")
    monkeypatch.setenv("ACME_PASSWORD", "pass")
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        respx.get(f"{PLANNING_BASE}/applications/Vision/substitutionvariables/CurYr").mock(
            return_value=httpx.Response(200, json={"name": "CurYr", "value": "FY26", "planType": "ALL"})
        )
        result = await substitution_variables.get_substitution_variable(client, "Vision", "CurYr")
        assert result == {"name": "CurYr", "value": "FY26", "planType": "ALL"}
    await client.aclose()
