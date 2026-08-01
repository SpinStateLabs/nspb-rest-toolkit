"""Core REST engine: auth (Basic, OAuth2, static Bearer token), retry,
base-url resolution, and the one chokepoint `call()` that every endpoint
wrapper in `endpoints/` routes through.

Design notes carried forward from a prior, live-tested implementation:
- Basic auth header is built fresh on every call (no session/cookie reuse).
- OAuth2 (auth_method=oauth2) implements Oracle's actual documented flow for
  EPM Cloud: a user-context access token via the Device Code grant for
  interactive first-auth (see oauth2_bootstrap.py, run once per connection)
  and the Refresh Token grant for unattended reuse -- see
  docs/endpoint-inventory.md section 2 and oauth2.py for the full
  implementation. `EPMClient` owns an `OAuth2TokenManager` per connection
  that caches the access token in memory (network only on
  missing/near-expiry) and single-flights refresh under concurrency via an
  asyncio.Lock, persisting Oracle's rotating refresh token to an on-disk
  cache immediately after every exchange.
- bearer_token (auth_method=bearer_token) sends a single pre-obtained static
  JWT as-is, resolved via credential_ref -- no refresh logic; an expired
  token surfaces as a clear EPMAuthError telling the operator to regenerate
  and re-set it, rather than a generic HTTP error.
- Jobs are async on Oracle's side and have two different status contracts
  depending on API family -- this is not a bug, it's how Oracle's Planning
  vs. Migration/LCM APIs actually behave. `poll_job()` handles both.
- Retry on 429/502/503/504 with backoff; everything else fails fast.
- The Authorization header and any credential value are never logged, at
  any log level, including debug output and error messages.

This client is async-first (httpx.AsyncClient) so the same implementation
serves the OpenAPI server, the MCP stdio server, and Open WebUI's Tools
class, all of which support async call sites.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from base64 import b64encode
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from .config import ConnectionConfig, resolve_basic_credentials, resolve_bearer_token
from .exceptions import EPMAuthError, EPMConfirmationRequiredError, EPMHTTPError, EPMJobError
from .oauth2 import OAuth2TokenManager

logger = logging.getLogger("nspb_rest_toolkit")

ApiFamily = Literal["planning", "migration", "data_management"]

_RETRYABLE_STATUS = {429, 502, 503, 504}
_REDACT_HEADER_NAMES = {"authorization"}
_REDACT_BODY_KEYS = ("password", "token", "access_token", "client_secret", "refresh_token")


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: ("***REDACTED***" if k.lower() in _REDACT_HEADER_NAMES else v) for k, v in headers.items()}


def unwrap_items(payload: Any, key: str = "items") -> list[Any]:
    """Unwrap Oracle's collection envelope for list-returning GET endpoints.

    Confirmed live (2026-08-01, against a real tenant) that GET
    .../applications returns `{"items": [...], "links": [...], "type": ...}`,
    not a bare JSON array as originally assumed -- the same "items" key
    Oracle's own docs show for the substitutionvariables *write* payload
    (docs/endpoint-inventory.md section 3/10), so this envelope is Oracle's
    established convention for this API, not a one-off. Tolerates a bare
    list too, so applying this to every list-typed endpoint wrapper is safe
    even for ones not yet independently live-verified -- it never breaks an
    endpoint that turns out to already return a bare array.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    raise EPMHTTPError(
        f"Expected a JSON array or an envelope object with a '{key}' array, got "
        f"{type(payload).__name__}: {payload!r:.200}"
    )


def _redact_body_preview(resp: httpx.Response, limit: int = 500) -> str:
    """Best-effort response body preview for error messages, credentials scrubbed."""
    text = resp.text[:limit]
    for key in _REDACT_BODY_KEYS:
        text = re.sub(rf'("{key}"\s*:\s*)"[^"]*"', r'\1"***REDACTED***"', text, flags=re.IGNORECASE)
    return text


class EPMClient:
    """One chokepoint for all Oracle EPM Cloud REST calls for a single connection."""

    def __init__(
        self,
        connection: ConnectionConfig,
        *,
        timeout: float = 60.0,
        max_retries: int = 4,
        backoff_base: float = 1.0,
    ):
        self.connection = connection
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._http = httpx.AsyncClient(timeout=timeout)
        self._oauth2_manager: OAuth2TokenManager | None = None
        if connection.auth_method == "oauth2":
            self._oauth2_manager = OAuth2TokenManager(connection, self._http)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "EPMClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---- auth ---------------------------------------------------------

    async def _auth_header(self) -> dict[str, str]:
        if self.connection.auth_method == "basic":
            username, password = resolve_basic_credentials(self.connection.credential_ref)
            token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {token}"}
        if self.connection.auth_method == "oauth2":
            assert self._oauth2_manager is not None  # set in __init__ whenever auth_method=oauth2
            access_token = await self._oauth2_manager.get_access_token()
            return {"Authorization": f"Bearer {access_token}"}
        if self.connection.auth_method == "bearer_token":
            token = resolve_bearer_token(self.connection.credential_ref)
            return {"Authorization": f"Bearer {token}"}
        raise EPMAuthError(f"Unknown auth_method '{self.connection.auth_method}'")

    # ---- base url -------------------------------------------------------

    def _base_url(self, family: ApiFamily) -> str:
        if family == "planning":
            return self.connection.planning_base_url()
        if family == "migration":
            return self.connection.migration_base_url()
        if family == "data_management":
            return self.connection.data_management_base_url()
        raise ValueError(f"Unknown API family '{family}'")

    # ---- chokepoint call --------------------------------------------------

    async def call(
        self,
        method: str,
        path: str,
        *,
        family: ApiFamily = "planning",
        json: Any = None,
        data: list[tuple[str, str]] | dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        destructive: bool = False,
        confirm: bool = False,
    ) -> httpx.Response:
        """The single chokepoint every endpoint wrapper must call through.

        `path` is relative to the family's base URL, e.g. "/applications" or
        "/applications/Vision/forms/{form}/data" -- OR an absolute
        "https://" URL, used as an escape hatch for endpoints that don't
        live under a versioned family base path (e.g. the unversioned
        Migration API-version-discovery resource at
        "{base_url}/interop/rest/", see endpoints/migration.py) and for any
        raw call a caller needs that isn't wrapped by endpoints/. Any
        non-GET absolute-URL call MUST still be marked destructive=True by
        the caller -- there's no way for this chokepoint to infer intent
        from an arbitrary URL. Set destructive=True for
        any non-GET / mutating operation -- this raises
        EPMConfirmationRequiredError unless confirm=True was ALSO passed on
        this same call. Callers (endpoint wrappers, MCP tools, Open WebUI
        tool functions) must never default confirm=True; it must come from
        an explicit, separate decision by whatever is upstream.

        `json` and `data` are mutually exclusive. `data` sends an
        `application/x-www-form-urlencoded` body (a list of `(key, value)`
        pairs -- use a list, not a dict, if the same key repeats, e.g.
        Oracle's `filter=...&filter=...` convention for planning units) --
        confirmed live (2026-08-01) that at least one Oracle resource
        (List All Planning Units) requires form-urlencoded, not JSON, and
        rejects a JSON body with HTTP 415 regardless of charset.

        `data` is deliberately NOT passed to httpx's own `data=` parameter.
        httpx 0.28.1 builds a sync-only `IteratorByteStream` for a
        list-of-tuples `data=` value (needed here for repeated keys) and
        raises `RuntimeError: Attempted to send an sync request with an
        AsyncClient instance` -- confirmed by direct reproduction outside
        this codebase, not a guess (`data=<dict>` alone doesn't hit this,
        but can't repeat a key). Instead, `data` is url-encoded here by
        hand via `urlencode()` and sent as raw `content=`, with
        `Content-Type: application/x-www-form-urlencoded` set explicitly
        -- no charset, since Oracle's own documented example for this
        shape doesn't show one, unlike its JSON responses.
        """
        if destructive and not confirm:
            raise EPMConfirmationRequiredError(
                f"{method} {path} is a destructive operation and requires confirm=True. "
                f"Describe the change to the user and wait for explicit confirmation "
                f"before retrying with confirm=True."
            )

        url = path if path.startswith(("http://", "https://")) else f"{self._base_url(family)}{path}"
        method = method.upper()

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            headers = await self._auth_header()
            if json is not None:
                # httpx's json= shorthand sends a bare "application/json"
                # with no charset; Oracle's own responses always carry
                # "application/json; charset=UTF-8". Set it explicitly to
                # match rather than relying on the httpx default. NOTE
                # (2026-08-01): this was originally added chasing a 415 on
                # List All Planning Units, which turned out to need
                # form-urlencoded (see `data=`), not JSON, at all -- the
                # charset theory was never actually confirmed correct by a
                # live success, it just seemed like reasonable practice and
                # hasn't broken anything. Revisit if a genuine JSON-body
                # write endpoint is live-tested and still rejects this.
                headers["Content-Type"] = "application/json; charset=utf-8"
            content: bytes | None = None
            if data is not None:
                # NOT passed via httpx's own data= -- see the docstring
                # above for why (a confirmed httpx 0.28.1 bug with
                # list-of-tuples data= under AsyncClient). Built and sent
                # by hand instead. No charset forced, matching Oracle's
                # documented example for this shape.
                content = urlencode(data).encode("ascii")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            logger.debug("%s %s headers=%s", method, url, _redact_headers(headers))
            try:
                resp = await self._http.request(
                    method, url, json=json, content=content, params=params, headers=headers
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise EPMHTTPError(
                        f"{method} {path} failed after {attempt + 1} attempt(s): {type(exc).__name__}"
                    ) from exc
                await self._sleep_backoff(attempt)
                continue

            if resp.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                await self._sleep_backoff(attempt, retry_after=resp.headers.get("Retry-After"))
                continue

            if resp.status_code == 401 and self.connection.auth_method == "bearer_token":
                # bearer_token has no refresh path -- an expired/invalid static
                # token needs a human to regenerate it, so surface that
                # actionable guidance instead of a generic EPMHTTPError.
                raise EPMAuthError(
                    f"Connection '{self.connection.display_name}' bearer_token was rejected "
                    f"(HTTP 401) -- it has likely expired. Regenerate a token from the Oracle "
                    f"Identity Domain console's 'Tokens and keys' page and update the value "
                    f"credential_ref '{self.connection.credential_ref}' resolves to."
                )

            if resp.status_code >= 400:
                raise EPMHTTPError(
                    f"{method} {path} -> HTTP {resp.status_code}",
                    status_code=resp.status_code,
                    redacted_body=_redact_body_preview(resp),
                )
            return resp

        raise EPMHTTPError(f"{method} {path} failed: {last_exc}")

    async def _sleep_backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self._backoff_base * (2**attempt)
        else:
            delay = self._backoff_base * (2**attempt)
        logger.warning("Retrying after %.1fs (attempt %d/%d)", delay, attempt + 1, self._max_retries)
        await asyncio.sleep(delay)

    # ---- job polling ---------------------------------------------------------

    async def poll_job(
        self,
        family: ApiFamily,
        status_path: str,
        *,
        poll_interval: float = 3.0,
        timeout: float = 900.0,
    ) -> dict[str, Any]:
        """Poll an async job to completion, handling both status contracts.

        Planning family: named states in the response's `status` (or
        `jobStatus`) field, terminal on "Completed" / "Error" / "Invalid".

        Migration family: numeric `status` field -- -1 = in progress,
        0 = success, 1 = completed with issues. A `1` is a valid terminal
        state returned to the caller, not raised here; the caller should
        fetch task detail (via the job's own links) to see what went wrong.

        Raises EPMJobError on a Planning "Error"/"Invalid" terminal state,
        an unrecognized Migration status, or timeout.
        """
        deadline = time.monotonic() + timeout
        while True:
            resp = await self.call("GET", status_path, family=family)
            payload: dict[str, Any] = resp.json()

            if family == "planning":
                state = payload.get("status") or payload.get("jobStatus")
                if state == "Completed":
                    return payload
                if state in ("Error", "Invalid"):
                    raise EPMJobError(f"Planning job at {status_path} ended in state '{state}'")
            elif family == "migration":
                state = payload.get("status")
                if state in (0, 1):
                    return payload
                if state != -1:
                    raise EPMJobError(f"Migration job at {status_path} returned unexpected status {state!r}")
            else:
                raise ValueError(f"Unknown API family '{family}'")

            if time.monotonic() >= deadline:
                raise EPMJobError(f"Job at {status_path} did not reach a terminal state within {timeout}s")

            await asyncio.sleep(poll_interval)
