"""Tests for the Planning Unit workflow request shape corrected 2026-08-01.

All three endpoints use application/x-www-form-urlencoded, not JSON --
originally implemented as JSON (matching the task brief's general
assumption), which got HTTP 415 against a real tenant. These pin down the
corrected shape against Oracle's own documented examples so it can't
silently regress back to JSON.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
import respx

from nspb_rest_toolkit.client import EPMClient
from nspb_rest_toolkit.config import ConnectionConfig
from nspb_rest_toolkit.endpoints import approvals

pytestmark = pytest.mark.asyncio

CONN = ConnectionConfig(
    display_name="Acme Corp",
    base_url="https://acme.example.com",
    auth_method="basic",
    credential_ref="ACME",
)
PLANNING_BASE = "https://acme.example.com/HyperionPlanning/rest/v3"


@pytest.fixture(autouse=True)
def basic_creds(monkeypatch):
    monkeypatch.setenv("ACME_USERNAME", "alice")
    monkeypatch.setenv("ACME_PASSWORD", "hunter2")


async def test_list_planning_units_sends_scenario_version_as_q_param_not_body():
    client = EPMClient(CONN)
    with respx.mock:
        route = respx.post(f"{PLANNING_BASE}/applications/Vision/planningunits").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await approvals.list_planning_units(client, "Vision", "Forecast", "BU Version_1")
        request = route.calls[0].request
        assert request.url.params["q"] == '{"scenario": "Forecast", "version": "BU Version_1"}'
        assert request.content == b""
    await client.aclose()


async def test_list_planning_units_filter_is_form_urlencoded_not_json():
    client = EPMClient(CONN)
    with respx.mock:
        route = respx.post(f"{PLANNING_BASE}/applications/Vision/planningunits").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await approvals.list_planning_units(
            client,
            "Vision",
            "Forecast",
            "BU Version_1",
            filter=[{"name": "Status", "type": 4, "values": [2, 5]}],
        )
        request = route.calls[0].request
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        parsed = parse_qs(request.content.decode())
        assert parsed["filter"] == ['{name:"Status",type:4,values:[2, 5]}']
    await client.aclose()


async def test_list_planning_units_offset_limit_are_query_params():
    client = EPMClient(CONN)
    with respx.mock:
        route = respx.post(f"{PLANNING_BASE}/applications/Vision/planningunits").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await approvals.list_planning_units(client, "Vision", "Forecast", "BU Version_1", offset=10, limit=25)
        request = route.calls[0].request
        assert request.url.params["offset"] == "10"
        assert request.url.params["limit"] == "25"
    await client.aclose()


async def test_get_available_actions_url_encodes_pu_identifier():
    client = EPMClient(CONN)
    with respx.mock:
        route = respx.post(url__regex=r".*/planningunits/.*/availableactions(\?.*)?$").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await approvals.get_available_actions(client, "Vision", 'Forecast::"BU Version_1"')
        request = route.calls[0].request
        # The identifier's `:`/`"`/space must be percent-encoded on the
        # wire (raw_path), not passed through raw (which would produce an
        # invalid URL) -- httpx's .path property decodes it back for us,
        # which is the round-trip-correctness check.
        assert b'%3A%3A%22' in request.url.raw_path
        assert request.url.path == '/HyperionPlanning/rest/v3/applications/Vision/planningunits/Forecast::"BU Version_1"/availableactions'
    await client.aclose()


async def test_get_available_actions_pm_members_is_form_body():
    client = EPMClient(CONN)
    with respx.mock:
        route = respx.post(url__regex=r".*/availableactions(\?.*)?$").mock(return_value=httpx.Response(200, json={"items": []}))
        await approvals.get_available_actions(client, "Vision", "PU1", pm_members=["Dev", "Marketing"])
        request = route.calls[0].request
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert parse_qs(request.content.decode())["pmMembers"] == ["Dev,Marketing"]
    await client.aclose()


async def test_change_planning_unit_status_sends_form_body_not_json():
    client = EPMClient(CONN)
    with respx.mock:
        route = respx.post(url__regex=r".*/actions$").mock(return_value=httpx.Response(200, json={}))
        await approvals.change_planning_unit_status(
            client, "Vision", "PU1", "PROMOTE", comments="go", confirm=True
        )
        request = route.calls[0].request
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        parsed = parse_qs(request.content.decode())
        assert parsed["actionId"] == ["6"]  # PROMOTE's numeric code
        assert parsed["comments"] == ["go"]
    await client.aclose()


async def test_change_planning_unit_status_requires_confirm():
    client = EPMClient(CONN)
    with respx.mock:
        # No route registered -- if the client tried to call the network,
        # respx would raise its own "not mocked" error, not our exception.
        with pytest.raises(Exception) as exc_info:
            await approvals.change_planning_unit_status(client, "Vision", "PU1", "PROMOTE")
        assert "confirm" in str(exc_info.value).lower()
    await client.aclose()


async def test_change_planning_unit_status_rejects_unknown_action():
    client = EPMClient(CONN)
    with pytest.raises(ValueError):
        await approvals.change_planning_unit_status(client, "Vision", "PU1", "NOT_A_REAL_ACTION", confirm=True)
    await client.aclose()
