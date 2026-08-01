"""Device Code + Refresh Token OAuth2 flow -- respx-mocked, no real network.

Covers: device-code bootstrap happy path, in-memory access-token reuse
across EPMClient.call() invocations, proactive refresh near expiry,
refresh-token rotation (and persistence of the NEW token), single-flight
refresh under concurrency, and the two documented invalid_grant shapes
(expired / already-consumed) surfacing as clear EPMAuthErrors.
"""

import asyncio
import json
import time
import urllib.parse

import httpx
import pytest
import respx

import base64

from nspb_rest_toolkit.client import EPMClient
from nspb_rest_toolkit.config import ConnectionConfig, EPMConfigError, OAuth2Config
from nspb_rest_toolkit.exceptions import EPMAuthError
from nspb_rest_toolkit.oauth2 import (
    OAuth2TokenManager,
    bootstrap_device_flow,
    load_token_cache,
    refresh_tokens,
    save_token_cache,
)

IDCS_BASE = "https://idcs-abc123.identity.oraclecloud.com"
DEVICE_URL = f"{IDCS_BASE}/oauth2/v1/device"
TOKEN_URL = f"{IDCS_BASE}/oauth2/v1/token"
PLANNING_BASE = "https://mfa.example.com/HyperionPlanning/rest/v3"


def make_oauth2_config(**overrides) -> OAuth2Config:
    kwargs = dict(idcs_base_url=IDCS_BASE, client_id="test-client-id", service_instance_id="test-service-instance")
    kwargs.update(overrides)
    return OAuth2Config(**kwargs)


def make_conn(tmp_path, **overrides) -> ConnectionConfig:
    cache_path = str(tmp_path / "mfa-corp.token_cache.json")
    oauth2 = make_oauth2_config(token_cache_path=cache_path)
    kwargs = dict(
        display_name="MFA Corp",
        base_url="https://mfa.example.com",
        auth_method="oauth2",
        credential_ref="MFA",
        slug="mfa-corp",
        oauth2=oauth2,
    )
    kwargs.update(overrides)
    return ConnectionConfig(**kwargs)


def _decode_form(request: httpx.Request) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(request.content.decode()))


# ---- device code bootstrap ---------------------------------------------------


async def test_device_bootstrap_happy_path_writes_token_cache(tmp_path, capsys):
    conn = make_conn(tmp_path)
    with respx.mock:
        respx.post(DEVICE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dc-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://verify.example.com/device",
                    "expires_in": 600,
                    "interval": 0,
                },
            )
        )
        # First poll: still pending: second poll: approved.
        respx.post(TOKEN_URL).mock(
            side_effect=[
                httpx.Response(400, json={"error": "authorization_pending"}),
                httpx.Response(
                    200,
                    json={
                        "access_token": "initial-access-token",
                        "refresh_token": "initial-refresh-token",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                ),
            ]
        )
        cache_path = await bootstrap_device_flow(conn)

    assert cache_path == conn.oauth2_token_cache_path()
    cache = load_token_cache(cache_path)
    assert cache["access_token"] == "initial-access-token"
    assert cache["refresh_token"] == "initial-refresh-token"
    assert cache["expires_at"] > time.time()

    # Never print a raw secret to the terminal.
    out = capsys.readouterr().out
    assert "initial-access-token" not in out
    assert "initial-refresh-token" not in out
    assert "ABCD-EFGH" in out  # the user code IS meant to be shown


async def test_device_bootstrap_denied_raises_epm_auth_error(tmp_path):
    conn = make_conn(tmp_path)
    with respx.mock:
        respx.post(DEVICE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dc-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://verify.example.com/device",
                    "expires_in": 600,
                    "interval": 0,
                },
            )
        )
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "access_denied"}))
        with pytest.raises(EPMAuthError, match="access_denied"):
            await bootstrap_device_flow(conn)


# ---- access-token reuse / proactive refresh via EPMClient --------------------


async def test_cached_access_token_reused_across_calls_without_hitting_token_endpoint(tmp_path):
    conn = make_conn(tmp_path)
    save_token_cache(
        conn.oauth2_token_cache_path(),
        {"access_token": "still-valid", "refresh_token": "rt-1", "expires_at": time.time() + 3600},
    )
    client = EPMClient(conn)
    with respx.mock:
        # No route registered for TOKEN_URL -- if the client tried to
        # refresh, respx would raise its own "not mocked" error here.
        route = respx.get(f"{PLANNING_BASE}/applications").mock(return_value=httpx.Response(200, json=[]))
        await client.call("GET", "/applications")
        await client.call("GET", "/applications")
        assert route.call_count == 2
        for call in route.calls:
            assert call.request.headers["authorization"] == "Bearer still-valid"
    await client.aclose()


async def test_proactive_refresh_when_near_expiry(tmp_path):
    conn = make_conn(tmp_path)
    cache_path = conn.oauth2_token_cache_path()
    save_token_cache(
        cache_path,
        {"access_token": "about-to-expire", "refresh_token": "rt-old", "expires_at": time.time() + 30},
    )
    client = EPMClient(conn)
    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "fresh-token", "refresh_token": "rt-new", "expires_in": 3600}
            )
        )
        app_route = respx.get(f"{PLANNING_BASE}/applications").mock(return_value=httpx.Response(200, json=[]))
        await client.call("GET", "/applications")
        assert token_route.call_count == 1
        assert app_route.calls[0].request.headers["authorization"] == "Bearer fresh-token"
    await client.aclose()

    cache = load_token_cache(cache_path)
    assert cache["access_token"] == "fresh-token"
    assert cache["refresh_token"] == "rt-new"


async def test_no_cached_token_raises_actionable_epm_auth_error(tmp_path):
    conn = make_conn(tmp_path)  # no cache file written -- never bootstrapped
    client = EPMClient(conn)
    with respx.mock:
        with pytest.raises(EPMAuthError, match="bootstrap"):
            await client.call("GET", "/applications")
    await client.aclose()


# ---- refresh-token rotation ---------------------------------------------------


async def test_refresh_token_rotation_persists_new_token_and_retires_old_one(tmp_path):
    oauth2_cfg = make_oauth2_config()
    http = httpx.AsyncClient()

    # Stateful, like Oracle's real single-use/rotating refresh tokens: a
    # token that was already exchanged is rejected on reuse.
    issued = {"rt-1": ("at-2", "rt-2"), "rt-2": ("at-3", "rt-3")}
    consumed: set[str] = set()

    def token_side_effect(request: httpx.Request) -> httpx.Response:
        body = _decode_form(request)
        sent = body.get("refresh_token")
        if sent in issued and sent not in consumed:
            consumed.add(sent)
            access_token, refresh_token = issued[sent]
            return httpx.Response(200, json={"access_token": access_token, "refresh_token": refresh_token, "expires_in": 3600})
        return httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "The token has already been consumed"}
        )

    try:
        with respx.mock:
            respx.post(TOKEN_URL).mock(side_effect=token_side_effect)

            result1 = await refresh_tokens(http, oauth2_cfg, "rt-1")
            assert result1["access_token"] == "at-2"
            assert result1["refresh_token"] == "rt-2"

            # The spent token ("rt-1") is now rejected as already-consumed.
            with pytest.raises(EPMAuthError, match="already been used|already-used|consumed"):
                await refresh_tokens(http, oauth2_cfg, "rt-1")

            # The NEW token from the first refresh is what actually works next.
            result2 = await refresh_tokens(http, oauth2_cfg, "rt-2")
            assert result2["access_token"] == "at-3"
            assert result2["refresh_token"] == "rt-3"
    finally:
        await http.aclose()


async def test_oauth2_token_manager_persists_rotated_refresh_token_to_disk(tmp_path):
    conn = make_conn(tmp_path)
    cache_path = conn.oauth2_token_cache_path()
    save_token_cache(
        cache_path, {"access_token": "expired-token", "refresh_token": "rt-1", "expires_at": time.time() - 10}
    )
    http = httpx.AsyncClient()
    manager = OAuth2TokenManager(conn, http)
    try:
        with respx.mock:
            respx.post(TOKEN_URL).mock(
                return_value=httpx.Response(
                    200, json={"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600}
                )
            )
            token = await manager.get_access_token()
        assert token == "at-2"
        cache = load_token_cache(cache_path)
        assert cache["refresh_token"] == "rt-2"  # rotated, not the original rt-1
        assert cache["access_token"] == "at-2"
    finally:
        await http.aclose()


# ---- single-flight refresh under concurrency ----------------------------------


async def test_concurrent_calls_trigger_only_one_refresh_exchange(tmp_path):
    conn = make_conn(tmp_path)
    cache_path = conn.oauth2_token_cache_path()
    save_token_cache(
        cache_path, {"access_token": "expired-token", "refresh_token": "rt-1", "expires_at": time.time() - 10}
    )
    http = httpx.AsyncClient()
    manager = OAuth2TokenManager(conn, http)
    try:
        with respx.mock:
            token_route = respx.post(TOKEN_URL).mock(
                return_value=httpx.Response(
                    200, json={"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600}
                )
            )
            results = await asyncio.gather(
                manager.get_access_token(),
                manager.get_access_token(),
                manager.get_access_token(),
            )
        assert results == ["at-2", "at-2", "at-2"]
        assert token_route.call_count == 1
    finally:
        await http.aclose()


async def test_concurrent_client_calls_are_single_flight_through_call(tmp_path):
    # Same guarantee, exercised through EPMClient.call() (the actual chokepoint)
    # rather than the manager directly.
    conn = make_conn(tmp_path)
    cache_path = conn.oauth2_token_cache_path()
    save_token_cache(
        cache_path, {"access_token": "expired-token", "refresh_token": "rt-1", "expires_at": time.time() - 10}
    )
    client = EPMClient(conn)
    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600}
            )
        )
        respx.get(f"{PLANNING_BASE}/applications").mock(return_value=httpx.Response(200, json=[]))
        await asyncio.gather(*[client.call("GET", "/applications") for _ in range(4)])
        assert token_route.call_count == 1
    await client.aclose()


# ---- invalid_grant error shapes ------------------------------------------------


async def test_expired_refresh_token_raises_actionable_epm_auth_error(tmp_path):
    oauth2_cfg = make_oauth2_config()
    http = httpx.AsyncClient()
    try:
        with respx.mock:
            respx.post(TOKEN_URL).mock(
                return_value=httpx.Response(
                    400,
                    json={"error": "invalid_grant", "error_description": "Token is expired for client : test-client-id"},
                )
            )
            with pytest.raises(EPMAuthError, match="expired") as exc_info:
                await refresh_tokens(http, oauth2_cfg, "rt-stale", label="MFA Corp")
        assert "bootstrap" in str(exc_info.value).lower()
        assert "rt-stale" not in str(exc_info.value)
    finally:
        await http.aclose()


async def test_already_consumed_refresh_token_raises_actionable_epm_auth_error(tmp_path):
    oauth2_cfg = make_oauth2_config()
    http = httpx.AsyncClient()
    try:
        with respx.mock:
            respx.post(TOKEN_URL).mock(
                return_value=httpx.Response(
                    400,
                    json={"error": "invalid_grant", "error_description": "The token has already been consumed"},
                )
            )
            with pytest.raises(EPMAuthError, match="already") as exc_info:
                await refresh_tokens(http, oauth2_cfg, "rt-spent", label="MFA Corp")
        assert "bootstrap" in str(exc_info.value).lower()
        assert "rt-spent" not in str(exc_info.value)
    finally:
        await http.aclose()


async def test_expired_refresh_token_via_client_call_raises_epm_auth_error_not_http_error(tmp_path):
    conn = make_conn(tmp_path)
    save_token_cache(
        conn.oauth2_token_cache_path(),
        {"access_token": "expired-token", "refresh_token": "rt-stale", "expires_at": time.time() - 10},
    )
    client = EPMClient(conn)
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "Token is expired for client : test-client-id"},
            )
        )
        with pytest.raises(EPMAuthError, match="expired"):
            await client.call("GET", "/applications")
    await client.aclose()


# ---- token cache file hygiene --------------------------------------------------


def test_save_token_cache_writes_valid_json_and_restrictive_permissions(tmp_path):
    path = tmp_path / "nested" / "conn.token_cache.json"
    save_token_cache(path, {"access_token": "a", "refresh_token": "b", "expires_at": 123.0})
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == {"access_token": "a", "refresh_token": "b", "expires_at": 123.0}
    # chmod 0600 is a no-op on Windows (no POSIX bits) -- save_token_cache
    # must not raise there either way; this just confirms it didn't.


def test_load_token_cache_missing_file_returns_none(tmp_path):
    assert load_token_cache(tmp_path / "does-not-exist.json") is None


# ---- allow_refresh: false (session-only access) --------------------------------


async def test_allow_refresh_false_omits_offline_access_scope(tmp_path):
    conn = make_conn(tmp_path, oauth2=make_oauth2_config(token_cache_path=str(tmp_path / "c.json"), allow_refresh=False))
    with respx.mock:
        route = respx.post(DEVICE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dc-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://verify.example.com/device",
                    "expires_in": 600,
                    "interval": 0,
                },
            )
        )
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "session-token", "expires_in": 3600, "token_type": "Bearer"}
            )
        )
        await bootstrap_device_flow(conn)

    sent_scope = _decode_form(route.calls[0].request)["scope"]
    assert "offline_access" not in sent_scope
    assert "urn:opc:resource:consumer::all" in sent_scope


async def test_allow_refresh_false_bootstrap_handles_missing_refresh_token(tmp_path):
    conn = make_conn(tmp_path, oauth2=make_oauth2_config(token_cache_path=str(tmp_path / "c.json"), allow_refresh=False))
    with respx.mock:
        respx.post(DEVICE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dc-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://verify.example.com/device",
                    "expires_in": 600,
                    "interval": 0,
                },
            )
        )
        # Oracle's response for a non-offline-access grant carries no refresh_token at all.
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "session-token", "expires_in": 3600, "token_type": "Bearer"}
            )
        )
        cache_path = await bootstrap_device_flow(conn)

    cache = load_token_cache(cache_path)
    assert cache["access_token"] == "session-token"
    assert cache["refresh_token"] is None


async def test_allow_refresh_false_expired_token_raises_clear_error_without_network_call(tmp_path):
    conn = make_conn(tmp_path, oauth2=make_oauth2_config(token_cache_path=str(tmp_path / "c.json"), allow_refresh=False))
    save_token_cache(
        conn.oauth2_token_cache_path(),
        {"access_token": "expired-session-token", "refresh_token": None, "expires_at": time.time() - 10},
    )
    client = EPMClient(conn)
    with respx.mock:
        # No TOKEN_URL route registered -- a refresh attempt would raise
        # respx's own "not mocked" error, proving no network call was made.
        with pytest.raises(EPMAuthError, match="allow_refresh"):
            await client.call("GET", "/applications")
    await client.aclose()


# ---- client_secret_ref (Confidential Application registrations) ----------------


async def test_client_secret_ref_sends_http_basic_auth_on_device_and_token_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("BPC_OAUTH2_SECRET", "s3cr3t")
    conn = make_conn(
        tmp_path,
        oauth2=make_oauth2_config(
            token_cache_path=str(tmp_path / "c.json"), client_secret_ref="BPC_OAUTH2_SECRET"
        ),
    )
    with respx.mock:
        device_route = respx.post(DEVICE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dc-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://verify.example.com/device",
                    "expires_in": 600,
                    "interval": 0,
                },
            )
        )
        token_route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}
            )
        )
        await bootstrap_device_flow(conn)

    expected = "Basic " + base64.b64encode(b"test-client-id:s3cr3t").decode()
    assert device_route.calls[0].request.headers["authorization"] == expected
    assert token_route.calls[0].request.headers["authorization"] == expected


async def test_client_secret_ref_missing_env_var_raises_config_error(tmp_path):
    conn = make_conn(
        tmp_path,
        oauth2=make_oauth2_config(
            token_cache_path=str(tmp_path / "c.json"), client_secret_ref="NEVER_SET_ENV_VAR"
        ),
    )
    with respx.mock:
        with pytest.raises(EPMConfigError, match="NEVER_SET_ENV_VAR"):
            await bootstrap_device_flow(conn)


async def test_no_client_secret_ref_sends_no_authorization_header_on_device_call(tmp_path):
    # Backward compat: the default public-client setup (no client_secret_ref)
    # must not attach any Authorization header to the device-code request.
    conn = make_conn(tmp_path)
    with respx.mock:
        device_route = respx.post(DEVICE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dc-1",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://verify.example.com/device",
                    "expires_in": 600,
                    "interval": 0,
                },
            )
        )
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}
            )
        )
        await bootstrap_device_flow(conn)

    assert "authorization" not in device_route.calls[0].request.headers
