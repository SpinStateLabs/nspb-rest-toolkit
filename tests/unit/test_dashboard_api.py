"""Connections dashboard API -- CRUD over connections.yaml plus the connectivity
test endpoint. respx-mocked, tmp_path connections.yaml + monkeypatched
NSPB_CONFIG_PATH -- no real network, no real secrets.
"""

import httpx
import pytest
import respx
import yaml
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


def _client():
    import nspb_rest_toolkit.openapi_server as s

    return TestClient(s.app)


# ---- dashboard page ---------------------------------------------------------------


def test_dashboard_root_serves_html():
    resp = _client().get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Connections" in resp.text


# ---- list / get ---------------------------------------------------------------------


def test_list_connections_returns_full_detail_no_secrets(configured_env):
    resp = _client().get("/api/connections")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slug"] == "acme-corp"
    assert body[0]["auth_method"] == "basic"
    assert body[0]["credential_ref"] == "ACME"
    assert "hunter2" not in resp.text


def test_get_connection_404_for_unknown_slug(configured_env):
    resp = _client().get("/api/connections/does-not-exist")
    assert resp.status_code == 404


def test_get_connection_found(configured_env):
    resp = _client().get("/api/connections/acme-corp")
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Acme Corp"


# ---- create -----------------------------------------------------------------------


def test_create_connection(configured_env):
    resp = _client().post(
        "/api/connections/new-corp",
        json={
            "display_name": "New Corp",
            "base_url": "https://new-corp.example.com",
            "auth_method": "basic",
            "credential_ref": "NEW_CORP",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "new-corp"

    # Persisted to disk, not just in-memory.
    reloaded = _client().get("/api/connections/new-corp")
    assert reloaded.status_code == 200
    assert reloaded.json()["base_url"] == "https://new-corp.example.com"


def test_create_connection_duplicate_slug_conflicts(configured_env):
    resp = _client().post(
        "/api/connections/acme-corp",
        json={"display_name": "Dup", "base_url": "https://dup.example.com", "credential_ref": "DUP"},
    )
    assert resp.status_code == 409


def test_create_oauth2_connection_with_new_fields(configured_env):
    resp = _client().post(
        "/api/connections/mfa-corp",
        json={
            "display_name": "MFA Corp",
            "base_url": "https://mfa.example.com",
            "auth_method": "oauth2",
            "credential_ref": "MFA",
            "oauth2": {
                "idcs_base_url": "https://idcs-abc.identity.oraclecloud.com",
                "client_id": "client-1",
                "service_instance_id": "123456",
                "allow_refresh": False,
                "client_secret_ref": "MFA_OAUTH2_SECRET",
            },
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["oauth2"]["allow_refresh"] is False
    assert body["oauth2"]["client_secret_ref"] == "MFA_OAUTH2_SECRET"


def test_create_oauth2_connection_without_oauth2_block_rejected(configured_env):
    resp = _client().post(
        "/api/connections/mfa-corp",
        json={"display_name": "MFA Corp", "base_url": "https://mfa.example.com",
              "auth_method": "oauth2", "credential_ref": "MFA"},
    )
    assert resp.status_code == 400


# ---- update -----------------------------------------------------------------------


def test_update_connection(configured_env, tmp_path):
    resp = _client().put(
        "/api/connections/acme-corp",
        json={
            "display_name": "Acme Corp Renamed",
            "base_url": "https://acme.example.com",
            "auth_method": "basic",
            "credential_ref": "ACME",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Acme Corp Renamed"

    raw = yaml.safe_load((configured_env).read_text(encoding="utf-8"))
    assert raw["connections"]["acme-corp"]["display_name"] == "Acme Corp Renamed"


def test_update_connection_404_for_unknown_slug(configured_env):
    resp = _client().put(
        "/api/connections/does-not-exist",
        json={"display_name": "X", "base_url": "https://x.example.com", "credential_ref": "X"},
    )
    assert resp.status_code == 404


# ---- delete -----------------------------------------------------------------------


def test_delete_connection(configured_env):
    resp = _client().delete("/api/connections/acme-corp")
    assert resp.status_code == 204
    assert _client().get("/api/connections/acme-corp").status_code == 404


def test_delete_connection_404_for_unknown_slug(configured_env):
    resp = _client().delete("/api/connections/does-not-exist")
    assert resp.status_code == 404


# ---- test-connection endpoint ------------------------------------------------------


def test_test_connection_success(configured_env):
    with respx.mock:
        respx.get("https://acme.example.com/HyperionPlanning/rest/v3/applications").mock(
            return_value=httpx.Response(200, json={"items": [{"name": "Vision"}], "links": [], "type": "HP"})
        )
        resp = _client().post("/api/connections/acme-corp/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["application_count"] == 1
    assert "hunter2" not in resp.text


def test_test_connection_failure_surfaces_as_200_not_500(configured_env):
    with respx.mock:
        respx.get("https://acme.example.com/HyperionPlanning/rest/v3/applications").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        resp = _client().post("/api/connections/acme-corp/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "hunter2" not in resp.text


def test_test_connection_404_for_unknown_slug(configured_env):
    resp = _client().post("/api/connections/does-not-exist/test")
    assert resp.status_code == 404


def test_test_connection_missing_credentials_reported_not_raised(tmp_path, monkeypatch):
    path = tmp_path / "connections.yaml"
    path.write_text(CONNECTIONS_YAML, encoding="utf-8")
    monkeypatch.setenv("NSPB_CONFIG_PATH", str(path))
    monkeypatch.delenv("ACME_USERNAME", raising=False)
    monkeypatch.delenv("ACME_PASSWORD", raising=False)

    with respx.mock:
        resp = _client().post("/api/connections/acme-corp/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "ACME_USERNAME" in body["message"]
