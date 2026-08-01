"""Device Code + Refresh Token OAuth2 flow for auth_method=oauth2 connections.

Implements exactly the flow Oracle documents for EPM Cloud (there is no
client-credentials grant -- see docs/endpoint-inventory.md section 2):

1. Device code request (`request_device_code`) -- interactive bootstrap
   step 1, run once per connection via `oauth2_bootstrap.py`.
2. Device code polling (`poll_for_tokens`) -- RFC 8628 polling loop,
   interactive bootstrap step 2. Backs off on `slow_down`, keeps waiting on
   `authorization_pending`, fails fast and clearly on `access_denied` /
   `expired_token`.
3. Refresh token exchange (`refresh_tokens`) -- the unattended re-auth path
   used by `OAuth2TokenManager` on every `EPMClient` construction/expiry.
   Oracle's refresh tokens are single-use/rotating: every exchange returns
   a NEW refresh token and invalidates the old one, so the caller MUST
   persist the new one immediately -- `OAuth2TokenManager` does this via
   `save_token_cache` right after every refresh, before returning control.

`OAuth2TokenManager` is the piece `EPMClient` actually talks to: it owns an
in-memory access-token cache (so `_auth_header()` doesn't hit the network on
every call -- only when the cached token is missing or within
`_REFRESH_MARGIN_SECONDS` of expiry) and an `asyncio.Lock` that makes
concurrent `EPMClient.call()` invocations single-flight through refresh --
the second concurrent caller waits for the first's refresh to land and
reuses its result instead of attempting its own exchange (and burning the
just-rotated refresh token).

Token cache file: JSON at `ConnectionConfig.oauth2_token_cache_path()`
(default `~/.nspb-rest-toolkit/tokens/<slug>.json`), holding
`{access_token, refresh_token, expires_at, updated_at}`. This file is a
credential, equivalent to a password -- `save_token_cache` writes it with
`os.chmod(path, 0o600)` on POSIX; that call is a no-op on Windows (NTFS has
no POSIX permission bits), so on Windows rely on filesystem ACLs / user
profile isolation instead. See the repo's `.gitignore` for the defensive
`*.token_cache.json` / `.nspb-rest-toolkit/` patterns -- this file should
never live inside the repo, but nothing stops a misconfigured
`token_cache_path` from pointing there.

Nothing in this module logs a raw access_token, refresh_token, or response
body that could contain one -- see `_safe_body_preview`, which reuses
client.py's existing `_redact_body_preview` (deferred import to avoid a
circular import, since client.py imports `OAuth2TokenManager` from here).
Authorization headers built from these tokens flow through
`EPMClient.call()`'s existing `_redact_headers(...)` debug-log call, same as
Basic auth -- no separate logging path to keep in sync.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from .config import ConnectionConfig, OAuth2Config, resolve_oauth2_client_secret
from .exceptions import EPMAuthError

logger = logging.getLogger("nspb_rest_toolkit")

_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
_DEFAULT_POLL_INTERVAL = 5.0
_DEFAULT_DEVICE_CODE_EXPIRES_IN = 600.0
_REFRESH_MARGIN_SECONDS = 60.0


def _safe_body_preview(resp: httpx.Response) -> str:
    """Redacted preview of a token-endpoint response body, for error messages only.

    Deferred import to avoid a circular import at module-load time (client.py
    imports OAuth2TokenManager from this module) -- reuses the same
    redaction machinery client.py uses for HTTP error bodies rather than
    duplicating it.
    """
    from .client import _redact_body_preview

    return _redact_body_preview(resp)


def _device_endpoint(oauth2: OAuth2Config) -> str:
    return f"{oauth2.idcs_base_url}/oauth2/v1/device"


def _token_endpoint(oauth2: OAuth2Config) -> str:
    return f"{oauth2.idcs_base_url}/oauth2/v1/token"


def _client_auth(oauth2: OAuth2Config) -> httpx.BasicAuth | None:
    """HTTP Basic (client_secret_basic) auth for Confidential Application registrations.

    Returns None for the default public-client setup (no client_secret_ref
    configured) -- httpx.AsyncClient.post treats auth=None as a no-op, so
    every existing public-client caller is unaffected.
    """
    if not oauth2.client_secret_ref:
        return None
    secret = resolve_oauth2_client_secret(oauth2.client_secret_ref)
    return httpx.BasicAuth(oauth2.client_id, secret)


def _error_field(resp: httpx.Response) -> tuple[str | None, str]:
    try:
        payload = resp.json()
    except ValueError:
        return None, ""
    if not isinstance(payload, dict):
        return None, ""
    return payload.get("error"), str(payload.get("error_description", ""))


# ---- device code flow (interactive bootstrap) ------------------------------


async def request_device_code(http: httpx.AsyncClient, oauth2: OAuth2Config) -> dict[str, Any]:
    """Step 1 of the Device Code flow -- docs/endpoint-inventory.md section 2.

    Requests the offline_access scope (needed for a refresh_token) only when
    oauth2.allow_refresh is True. Some IDCS app registrations have "Allow
    token refresh: Disallowed" and reject the whole device-code request with
    unauthorized_client if offline_access is asked for at all -- omitting it
    gets a plain session-scoped access token instead.
    """
    scope = f"urn:opc:serviceInstanceID={oauth2.service_instance_id}urn:opc:resource:consumer::all"
    if oauth2.allow_refresh:
        scope += " offline_access"
    resp = await http.post(
        _device_endpoint(oauth2),
        data={"response_type": "device_code", "scope": scope, "client_id": oauth2.client_id},
        auth=_client_auth(oauth2),
    )
    if resp.status_code >= 400:
        raise EPMAuthError(f"Device code request failed: HTTP {resp.status_code} {_safe_body_preview(resp)}")
    return resp.json()


async def poll_for_tokens(
    http: httpx.AsyncClient,
    oauth2: OAuth2Config,
    device_code: str,
    *,
    interval: float = _DEFAULT_POLL_INTERVAL,
    expires_in: float = _DEFAULT_DEVICE_CODE_EXPIRES_IN,
    sleep: Any = asyncio.sleep,
) -> dict[str, Any]:
    """Step 2 -- poll the token endpoint per RFC 8628 until browser approval lands.

    Honors `authorization_pending` (keep waiting), `slow_down` (back off),
    and fails fast with a clear EPMAuthError on `access_denied`,
    `expired_token`, or any other error.
    """
    deadline = time.monotonic() + expires_in
    while True:
        resp = await http.post(
            _token_endpoint(oauth2),
            data={"grant_type": _DEVICE_GRANT_TYPE, "device_code": device_code, "client_id": oauth2.client_id},
            auth=_client_auth(oauth2),
        )
        if resp.status_code < 400:
            return resp.json()

        error, _description = _error_field(resp)
        if error == "authorization_pending":
            pass
        elif error == "slow_down":
            interval += 5.0
        elif error in ("access_denied", "expired_token"):
            raise EPMAuthError(
                f"Device Code authorization did not complete ({error}). Re-run the bootstrap "
                f"command and approve the request in your browser before it expires."
            )
        else:
            raise EPMAuthError(
                f"Device Code token poll failed: HTTP {resp.status_code} {_safe_body_preview(resp)}"
            )

        if time.monotonic() >= deadline:
            raise EPMAuthError(
                "Device Code authorization timed out waiting for browser approval. Re-run the "
                "bootstrap command."
            )
        await sleep(interval)


async def bootstrap_device_flow(connection: ConnectionConfig, *, http: httpx.AsyncClient | None = None) -> Path:
    """Interactive one-time Device Code bootstrap for a single connection.

    Prints the verification URL and user code to the terminal, polls until
    the user approves in their browser, then writes the initial
    access+refresh token to the on-disk cache. This step is inherently
    interactive -- a human has to approve in a browser -- and is
    deliberately not automated further; run it once per connection via
    `python -m nspb_rest_toolkit.oauth2_bootstrap`, then `EPMClient` handles
    unattended refresh from here on.

    Returns the path the token cache was written to.
    """
    if connection.oauth2 is None:
        raise EPMAuthError(
            f"Connection '{connection.display_name}' has no 'oauth2:' block to bootstrap."
        )

    owns_http = http is None
    http = http or httpx.AsyncClient(timeout=30.0)
    try:
        device = await request_device_code(http, connection.oauth2)
        verification_uri = device.get("verification_uri_complete") or device.get("verification_uri")
        user_code = device.get("user_code")
        print(f"Authorizing connection '{connection.display_name}':")
        print(f"  1. Open: {verification_uri}")
        if not device.get("verification_uri_complete"):
            print(f"  2. Enter code: {user_code}")
        print("Waiting for browser approval...")

        interval = float(device.get("interval", _DEFAULT_POLL_INTERVAL))
        expires_in = float(device.get("expires_in", _DEFAULT_DEVICE_CODE_EXPIRES_IN))
        tokens = await poll_for_tokens(
            http, connection.oauth2, device["device_code"], interval=interval, expires_in=expires_in
        )

        cache_path = connection.oauth2_token_cache_path()
        save_token_cache(
            cache_path,
            {
                "access_token": tokens["access_token"],
                # Absent when allow_refresh=False -- offline_access wasn't
                # requested, so IDCS never issues a refresh_token.
                "refresh_token": tokens.get("refresh_token"),
                "expires_at": time.time() + float(tokens.get("expires_in", 3600)),
                "updated_at": time.time(),
            },
        )
        print(f"Authorized. Token cache written to {cache_path}")
        return cache_path
    finally:
        if owns_http:
            await http.aclose()


# ---- refresh token exchange (unattended re-auth) ----------------------------


async def refresh_tokens(
    http: httpx.AsyncClient, oauth2: OAuth2Config, refresh_token: str, *, label: str = "connection"
) -> dict[str, Any]:
    """Exchange a refresh token for a new access+refresh token pair.

    Refresh tokens are single-use/rotating -- the response's refresh_token
    is a NEW value and the one passed in is now spent. Callers MUST persist
    the new value before it's needed again (see OAuth2TokenManager._refresh).
    """
    resp = await http.post(
        _token_endpoint(oauth2),
        data={"grant_type": "refresh_token", "client_id": oauth2.client_id, "refresh_token": refresh_token},
        auth=_client_auth(oauth2),
    )
    if resp.status_code < 400:
        return resp.json()

    error, description = _error_field(resp)
    if error == "invalid_grant":
        lowered = description.lower()
        if "already been consumed" in lowered or "already consumed" in lowered:
            raise EPMAuthError(
                f"OAuth2 refresh token for '{label}' has already been used (Oracle's refresh "
                f"tokens are single-use/rotating). This usually means the on-disk token cache "
                f"is stale, was reverted, or two processes refreshed concurrently outside this "
                f"client. Re-run the bootstrap command to obtain a fresh token:\n"
                f"  python -m nspb_rest_toolkit.oauth2_bootstrap --config <path> --connection <slug>"
            )
        if "expired" in lowered:
            raise EPMAuthError(
                f"OAuth2 refresh token for '{label}' has expired (Oracle expires refresh tokens "
                f"after 7 days). Re-run the bootstrap command:\n"
                f"  python -m nspb_rest_toolkit.oauth2_bootstrap --config <path> --connection <slug>"
            )

    raise EPMAuthError(f"OAuth2 refresh failed for '{label}': HTTP {resp.status_code} {_safe_body_preview(resp)}")


# ---- on-disk token cache -----------------------------------------------------


def load_token_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_token_cache(path: Path, data: dict[str, Any]) -> None:
    """Write the token cache and lock down permissions -- this file is a credential.

    `os.chmod(path, 0o600)` restricts to owner-read/write on POSIX; it's a
    no-op on Windows (no POSIX permission bits on NTFS) and failures there
    are swallowed rather than raised -- rely on filesystem ACLs / user
    profile isolation on Windows instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---- in-memory + on-disk manager used by EPMClient ---------------------------


class OAuth2TokenManager:
    """Per-EPMClient in-memory access-token cache with single-flight refresh.

    `get_access_token()` is what `EPMClient._auth_header()` calls on every
    request attempt -- it's cheap (no network) unless the cached token is
    missing or within `_REFRESH_MARGIN_SECONDS` of expiry, in which case it
    refreshes (persisting the rotated refresh token immediately) and hands
    back the new access token. The whole check-and-maybe-refresh sequence
    runs under `self._lock`, so concurrent `EPMClient.call()` invocations
    are single-flight: the second caller blocks on the lock, then sees the
    first caller's already-refreshed token and returns it without spending
    another (already-rotated) refresh token.
    """

    def __init__(self, connection: ConnectionConfig, http: httpx.AsyncClient):
        if connection.oauth2 is None:
            raise EPMAuthError(f"Connection '{connection.display_name}' has no 'oauth2:' block.")
        self._connection = connection
        self._oauth2 = connection.oauth2
        self._http = http
        self._cache_path = connection.oauth2_token_cache_path()
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._loaded_from_disk = False

    async def get_access_token(self) -> str:
        async with self._lock:
            if not self._loaded_from_disk:
                self._load_from_disk()
            if self._access_token and (self._expires_at - time.time()) > _REFRESH_MARGIN_SECONDS:
                return self._access_token
            await self._refresh()
            assert self._access_token is not None
            return self._access_token

    def _load_from_disk(self) -> None:
        self._loaded_from_disk = True
        cache = load_token_cache(self._cache_path)
        if cache is None:
            return
        self._access_token = cache.get("access_token")
        self._refresh_token = cache.get("refresh_token")
        try:
            self._expires_at = float(cache.get("expires_at", 0.0))
        except (TypeError, ValueError):
            self._expires_at = 0.0

    async def _refresh(self) -> None:
        bootstrap_hint = (
            f"  python -m nspb_rest_toolkit.oauth2_bootstrap --config <path> "
            f"--connection {self._connection.slug or '<slug>'}"
        )
        if not self._oauth2.allow_refresh:
            raise EPMAuthError(
                f"Connection '{self._connection.display_name}' is configured with "
                f"oauth2.allow_refresh: false (session-only access, no refresh token) -- the "
                f"cached access token is missing or has expired. Re-run the Device Code bootstrap "
                f"to get a new one:\n{bootstrap_hint}"
            )
        if not self._refresh_token:
            raise EPMAuthError(
                f"No cached OAuth2 token found for connection '{self._connection.display_name}'. "
                f"Run the one-time Device Code bootstrap first:\n{bootstrap_hint}"
            )
        logger.debug("Refreshing OAuth2 access token for connection %r", self._connection.display_name)
        result = await refresh_tokens(
            self._http, self._oauth2, self._refresh_token, label=self._connection.display_name
        )
        self._access_token = result["access_token"]
        self._refresh_token = result["refresh_token"]
        self._expires_at = time.time() + float(result.get("expires_in", 3600))
        save_token_cache(
            self._cache_path,
            {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expires_at": self._expires_at,
                "updated_at": time.time(),
            },
        )
