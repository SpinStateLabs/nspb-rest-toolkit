"""End-to-end plumbing checks for the OpenAPI and MCP surfaces.

These use respx to mock the outbound Oracle EPM HTTP call and a tmp_path
connections.yaml + monkeypatched env vars/NSPB_CONFIG_PATH for credentials
-- no real network access anywhere.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

CONNECTIONS_YAML = """
connections:
  acme-corp:
    display_name: "Acme Corp"
    base_url: "https://acme.example.com"
    auth_method: basic
    credential_ref: "ACME"
"""


@pytest.fixture
def configured_env(tmp_path, monkeypatch):
    path = tmp_path / "connections.yaml"
    path.write_text(CONNECTIONS_YAML, encoding="utf-8")
    monkeypatch.setenv("NSPB_CONFIG_PATH", str(path))
    monkeypatch.setenv("ACME_USERNAME", "alice")
    monkeypatch.setenv("ACME_PASSWORD", "hunter2")
    return path


def test_openapi_schema_lists_every_tool_route():
    import nspb_rest_toolkit.openapi_server as s

    client = TestClient(s.app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = [p for p in resp.json()["paths"] if p.startswith("/tools/")]
    assert len(paths) >= 30  # full endpoint-inventory coverage, see docs/endpoint-inventory.md


def test_openapi_list_applications_round_trip(configured_env):
    import nspb_rest_toolkit.openapi_server as s

    client = TestClient(s.app)
    with respx.mock:
        respx.get("https://acme.example.com/HyperionPlanning/rest/v3/applications").mock(
            return_value=httpx.Response(200, json={"items": [{"name": "Vision"}], "links": [], "type": "HP"})
        )
        resp = client.post("/tools/list_applications", json={"connection": "acme-corp"})
    assert resp.status_code == 200
    assert resp.json() == [{"name": "Vision"}]


def test_openapi_destructive_without_confirm_rejected(configured_env):
    import nspb_rest_toolkit.openapi_server as s

    client = TestClient(s.app)
    with respx.mock:
        # No route mocked -- a real network attempt would fail differently.
        resp = client.post(
            "/tools/run_business_rule",
            json={"connection": "acme-corp", "application": "Vision", "rule_name": "CalcAll"},
        )
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"].lower()


def test_openapi_connections_endpoint_never_leaks_credentials(configured_env):
    import nspb_rest_toolkit.openapi_server as s

    client = TestClient(s.app)
    resp = client.get("/connections")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"slug": "acme-corp", "display_name": "Acme Corp"}]
    assert "hunter2" not in resp.text


async def test_mcp_list_applications_round_trip(configured_env):
    import nspb_rest_toolkit.mcp_server as m

    # @mcp.tool() registers the function but returns it unmodified, so the
    # plain async function is directly callable -- no unwrapping needed.
    with respx.mock:
        respx.get("https://acme.example.com/HyperionPlanning/rest/v3/applications").mock(
            return_value=httpx.Response(200, json={"items": [{"name": "Vision"}], "links": [], "type": "HP"})
        )
        result = await m.list_applications(connection="acme-corp")
    assert result == [{"name": "Vision"}]


async def test_mcp_destructive_without_confirm_raises(configured_env):
    import nspb_rest_toolkit.mcp_server as m
    from nspb_rest_toolkit.exceptions import EPMConfirmationRequiredError

    with respx.mock:
        with pytest.raises(EPMConfirmationRequiredError):
            await m.run_business_rule(connection="acme-corp", application="Vision", rule_name="CalcAll")


def test_mcp_registers_full_operation_set():
    import nspb_rest_toolkit.mcp_server as m

    # FastMCP/MCPServer wraps each decorated function in a Tool object;
    # inspect the underlying registry rather than calling the async
    # list_tools() from a sync test.
    tool_names = set(m.mcp._tool_manager._tools.keys())
    assert "write_form_data" in tool_names
    assert "run_business_rule" in tool_names
    assert "export_snapshot" in tool_names
    assert len(tool_names) >= 30
