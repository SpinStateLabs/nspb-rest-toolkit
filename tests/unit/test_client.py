import base64

import httpx
import pytest
import respx

from nspb_rest_toolkit.client import EPMClient, unwrap_items
from nspb_rest_toolkit.config import ConnectionConfig, OAuth2Config
from nspb_rest_toolkit.exceptions import (
    EPMAuthError,
    EPMConfirmationRequiredError,
    EPMHTTPError,
    EPMJobError,
)

BASIC_CONN = ConnectionConfig(
    display_name="Acme Corp",
    base_url="https://acme.example.com",
    auth_method="basic",
    credential_ref="ACME",
)

BEARER_CONN = ConnectionConfig(
    display_name="Bearer Corp",
    base_url="https://bearer.example.com",
    auth_method="bearer_token",
    credential_ref="BEARER_CORP_TOKEN",
)

PLANNING_BASE = "https://acme.example.com/HyperionPlanning/rest/v3"
MIGRATION_BASE = "https://acme.example.com/interop/rest/v2"
BEARER_PLANNING_BASE = "https://bearer.example.com/HyperionPlanning/rest/v3"


def make_oauth2_conn(tmp_path, **overrides) -> ConnectionConfig:
    """Build an auth_method=oauth2 ConnectionConfig with an isolated tmp_path token cache."""
    kwargs = dict(
        display_name="MFA Corp",
        base_url="https://mfa.example.com",
        auth_method="oauth2",
        credential_ref="MFA",
        oauth2=OAuth2Config(
            idcs_base_url="https://idcs-abc123.identity.oraclecloud.com",
            client_id="test-client-id",
            service_instance_id="test-service-instance",
            token_cache_path=str(tmp_path / "mfa-corp.token_cache.json"),
        ),
    )
    kwargs.update(overrides)
    return ConnectionConfig(**kwargs)


@pytest.fixture(autouse=True)
def basic_creds(monkeypatch):
    monkeypatch.setenv("ACME_USERNAME", "alice")
    monkeypatch.setenv("ACME_PASSWORD", "hunter2")


async def test_destructive_without_confirm_raises_and_never_calls_network():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        # No route registered -- if the client tried to call the network,
        # respx would raise its own "not mocked" error, not our exception.
        with pytest.raises(EPMConfirmationRequiredError):
            await client.call("POST", "/applications/Vision/forms/Budget/data", destructive=True)
    await client.aclose()


async def test_destructive_with_confirm_calls_network():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        route = respx.post(f"{PLANNING_BASE}/applications/Vision/forms/Budget/data").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        resp = await client.call(
            "POST", "/applications/Vision/forms/Budget/data", destructive=True, confirm=True
        )
        assert route.called
        assert resp.json() == {"ok": True}
    await client.aclose()


async def test_basic_auth_header_built_fresh_each_call():
    client = EPMClient(BASIC_CONN)
    expected = "Basic " + base64.b64encode(b"alice:hunter2").decode("ascii")
    with respx.mock:
        route = respx.get(f"{PLANNING_BASE}/applications").mock(return_value=httpx.Response(200, json=[]))
        await client.call("GET", "/applications")
        sent_headers = route.calls[0].request.headers
        assert sent_headers["authorization"] == expected
    await client.aclose()


async def test_bearer_token_auth_header_shape(monkeypatch):
    monkeypatch.setenv("BEARER_CORP_TOKEN", "the-static-jwt")
    client = EPMClient(BEARER_CONN)
    with respx.mock:
        route = respx.get(f"{BEARER_PLANNING_BASE}/applications").mock(return_value=httpx.Response(200, json=[]))
        await client.call("GET", "/applications")
        sent_headers = route.calls[0].request.headers
        assert sent_headers["authorization"] == "Bearer the-static-jwt"
    await client.aclose()


async def test_bearer_token_401_surfaces_as_epm_auth_error(monkeypatch):
    monkeypatch.setenv("BEARER_CORP_TOKEN", "an-expired-jwt")
    client = EPMClient(BEARER_CONN, backoff_base=0.001)
    with respx.mock:
        respx.get(f"{BEARER_PLANNING_BASE}/applications").mock(
            return_value=httpx.Response(401, json={"error": "invalid_token"})
        )
        with pytest.raises(EPMAuthError, match="bearer_token") as exc_info:
            await client.call("GET", "/applications")
        # Actionable guidance, not a raw HTTP-error dump.
        assert "regenerate" in str(exc_info.value).lower()
        assert "an-expired-jwt" not in str(exc_info.value)
    await client.aclose()


async def test_oauth2_connection_sends_bearer_header_from_cached_token(tmp_path):
    # Full Device Code / refresh / single-flight coverage lives in
    # test_oauth2.py -- this is just a smoke test that EPMClient actually
    # wires an oauth2 connection's cached access token into the standard
    # Authorization: Bearer header via the same call() chokepoint.
    import time

    from nspb_rest_toolkit.oauth2 import save_token_cache

    conn = make_oauth2_conn(tmp_path)
    save_token_cache(
        conn.oauth2_token_cache_path(),
        {"access_token": "cached-access-token", "refresh_token": "rt-1", "expires_at": time.time() + 3600},
    )
    client = EPMClient(conn)
    with respx.mock:
        route = respx.get("https://mfa.example.com/HyperionPlanning/rest/v3/applications").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.call("GET", "/applications")
        assert route.calls[0].request.headers["authorization"] == "Bearer cached-access-token"
    await client.aclose()


async def test_retries_on_502_then_succeeds():
    client = EPMClient(BASIC_CONN, backoff_base=0.001)
    with respx.mock:
        route = respx.get(f"{PLANNING_BASE}/applications").mock(
            side_effect=[httpx.Response(502), httpx.Response(200, json=[])]
        )
        resp = await client.call("GET", "/applications")
        assert resp.status_code == 200
        assert route.call_count == 2
    await client.aclose()


async def test_non_retryable_4xx_fails_fast_with_redacted_body():
    client = EPMClient(BASIC_CONN, backoff_base=0.001)
    with respx.mock:
        route = respx.get(f"{PLANNING_BASE}/applications").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        with pytest.raises(EPMHTTPError) as exc_info:
            await client.call("GET", "/applications")
        assert route.call_count == 1  # no retry on 404
        assert exc_info.value.status_code == 404
    await client.aclose()


async def test_401_error_message_never_contains_credentials():
    client = EPMClient(BASIC_CONN, backoff_base=0.001)
    with respx.mock:
        respx.get(f"{PLANNING_BASE}/applications").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(EPMHTTPError) as exc_info:
            await client.call("GET", "/applications")
        message = str(exc_info.value)
        assert "hunter2" not in message
        assert "alice" not in message
    await client.aclose()


async def test_poll_job_planning_completes():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        respx.get(f"{PLANNING_BASE}/jobs/42").mock(
            side_effect=[
                httpx.Response(200, json={"status": "Processing"}),
                httpx.Response(200, json={"status": "Completed", "jobId": 42}),
            ]
        )
        result = await client.poll_job("planning", "/jobs/42", poll_interval=0)
        assert result["status"] == "Completed"
    await client.aclose()


async def test_poll_job_planning_error_raises():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        respx.get(f"{PLANNING_BASE}/jobs/43").mock(return_value=httpx.Response(200, json={"status": "Error"}))
        with pytest.raises(EPMJobError):
            await client.poll_job("planning", "/jobs/43", poll_interval=0)
    await client.aclose()


async def test_poll_job_migration_family_contract():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        respx.get(f"{MIGRATION_BASE}/jobs/7").mock(
            side_effect=[
                httpx.Response(200, json={"status": -1}),
                httpx.Response(200, json={"status": 1}),  # completed with issues
            ]
        )
        result = await client.poll_job("migration", "/jobs/7", poll_interval=0)
        assert result["status"] == 1
    await client.aclose()


async def test_absolute_url_escape_hatch_bypasses_family_base_url():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        route = respx.get("https://acme.example.com/interop/rest/").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        resp = await client.call("GET", "https://acme.example.com/interop/rest/")
        assert route.called
        assert resp.json() == {"items": []}
    await client.aclose()


async def test_poll_job_migration_unexpected_status_raises():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        respx.get(f"{MIGRATION_BASE}/jobs/8").mock(return_value=httpx.Response(200, json={"status": 99}))
        with pytest.raises(EPMJobError):
            await client.poll_job("migration", "/jobs/8", poll_interval=0)
    await client.aclose()


async def test_json_body_sends_explicit_charset_content_type():
    # Confirmed live (2026-08-01): Oracle rejected httpx's default bare
    # "application/json" (no charset) on a POST-with-body call with HTTP
    # 415. This affects every write endpoint, not just the one that
    # surfaced it, since it's set unconditionally in call() whenever a JSON
    # body is present.
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        route = respx.post(f"{PLANNING_BASE}/applications/Vision/planningunits").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        await client.call("POST", "/applications/Vision/planningunits", json={})
        assert route.called
        assert route.calls[0].request.headers["content-type"] == "application/json; charset=utf-8"
    await client.aclose()


async def test_no_json_body_sends_no_content_type():
    client = EPMClient(BASIC_CONN)
    with respx.mock:
        route = respx.get(f"{PLANNING_BASE}/applications").mock(return_value=httpx.Response(200, json={"items": []}))
        await client.call("GET", "/applications")
        assert route.called
        assert "content-type" not in route.calls[0].request.headers
    await client.aclose()


def test_unwrap_items_handles_oracle_envelope():
    # Confirmed live (2026-08-01) against a real tenant: GET .../applications
    # returns {"items": [...], "links": [...], "type": ...}, not a bare array.
    payload = {"items": [{"name": "NetSuite"}], "links": [{"rel": "self"}], "type": "HP"}
    assert unwrap_items(payload) == [{"name": "NetSuite"}]


def test_unwrap_items_tolerates_bare_array():
    # Endpoints not yet independently live-verified might genuinely return a
    # bare array -- unwrap_items must not break those.
    assert unwrap_items([{"name": "Vision"}]) == [{"name": "Vision"}]


def test_unwrap_items_raises_on_unexpected_shape():
    with pytest.raises(EPMHTTPError):
        unwrap_items({"unexpected": "shape"})
    with pytest.raises(EPMHTTPError):
        unwrap_items("not even a dict or list")
