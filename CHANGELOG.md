# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - Unreleased

### Fixed
- **Live-discovered (2026-08-01):** `list_applications`, `list_plan_types`, `list_dimensions`, and
  `list_substitution_variables` were returning Oracle's raw response object unchanged, but a real tenant
  confirmed `GET .../applications` actually returns `{"items": [...], "links": [...], "type": ...}` -- a
  collection envelope, not a bare JSON array as the original mocked unit tests assumed. Every mocked-only
  endpoint carries this same unverified-shape risk (see docs/endpoint-inventory.md's per-section "not
  independently re-verified against a live response" notes). Added `client.unwrap_items()`, a shared helper
  that unwraps the envelope but also tolerates a genuine bare array, and applied it to all four affected
  functions -- safe to apply broadly since it can't break an endpoint that turns out to already return a bare
  list. Added `scripts/live_read_only_check.py`, a discovery-driven live sweep of every safe read-only
  endpoint, to surface any remaining shape mismatches against a real tenant before they reach a customer.
- **Live-discovered (2026-08-01), round 2:** `get_application_summary` called `resp.json()` on a response its
  own docstring already said was "markdown-ish" text -- now returns `resp.text`. `list_planning_units`
  collapsed an empty-but-valid `{}` filter body to `None` via `body or None`, sending no body at all; Oracle
  returned HTTP 500 for that and HTTP 415 once a real body was sent, because **every JSON POST body in this
  client was sent with a bare `application/json` Content-Type (httpx's default, no charset), and Oracle's
  REST layer rejects that** -- `EPMClient.call()` now sets `Content-Type: application/json; charset=utf-8`
  explicitly whenever a JSON body is present. This affects every write endpoint in the toolkit, not just the
  one that surfaced it. `get_substitution_variable` returns `204 No Content` for a real, existing variable
  name on this tenant -- a confirmed Oracle quirk, not a client bug -- so it now returns `None` on 204 instead
  of raising `JSONDecodeError`; `list_substitution_variables` remains the reliable way to get the value.
- **Live-discovered (2026-08-01), round 3:** the charset fix above did NOT actually fix
  `list_planning_units`'s HTTP 415 -- confirmed by direct wire-level inspection that the correct
  `application/json; charset=utf-8` header really was sent, and Oracle still rejected it with a bare
  WebLogic/JAX-RS-level "Unsupported Media Type" (no application error payload). Re-fetching Oracle's actual
  documentation for all three Planning Unit workflow endpoints (`endpoints/approvals.py`) found the real
  cause: **all three use `application/x-www-form-urlencoded`, not JSON**, and `list_planning_units`'s
  `scenario`/`version` belong in a `q` query parameter, not a body field the original implementation didn't
  even expose. Rewrote all three functions against Oracle's documented shapes; `EPMClient.call()` gained a
  `data=` parameter for form-encoded bodies. Also found and fixed a real **httpx 0.28.1 bug**: passing a
  list-of-tuples to httpx's own `data=` (needed for Oracle's repeated `filter=A&filter=B` convention) builds
  a sync-only `IteratorByteStream` and raises `RuntimeError: Attempted to send an sync request with an
  AsyncClient instance` -- reproduced directly outside this codebase, not a guess. Worked around by
  url-encoding `data` by hand and sending it via `content=` instead of httpx's `data=`. `get_available_actions`
  and `change_planning_unit_status` also gained percent-encoding of their path-segment planning-unit
  identifiers (`urllib.parse.quote`), which can contain `:`, `"`, and spaces (e.g. `Forecast::"BU
  Version_1"`) that aren't safe unescaped in a URL path. The two read operations are live-confirmed; the
  destructive `change_planning_unit_status` is documentation-confirmed only (not live-tested).

- **Live-discovered (2026-08-01), OAuth2 live-tested for the first time against BPC's `Planning_nspb` app
  registration:** three real gaps the unit-tested-only flow never hit. (1) That app registration has "Allow
  token refresh: Disallowed" -- requesting `offline_access` scope (needed for a refresh_token) got the whole
  device-code request rejected with `unauthorized_client: The resource does not support offline access`, not
  just a later refresh failure. Added `OAuth2Config.allow_refresh` (default `true`, unchanged behavior) --
  set `false` to omit `offline_access` entirely and accept session-only access with no refresh. (2) That same
  app is a Confidential Application (has a client secret) -- the token endpoint rejected every call with
  `invalid_client: Client authentication failed` because the toolkit's Device Code flow assumed a public
  client (matching Oracle's own documented example, which really is public-client-only) and sent no client
  authentication. Added `OAuth2Config.client_secret_ref` (a `credential_ref`-style env var name, never a
  secret in YAML) -- when set, sent as HTTP Basic auth on the device/token endpoint calls. (3) Even with both
  of the above fixed, every API call still 401'd with `WWW-Authenticate: Bearer error="invalid_token",
  error_description="Token Audience"` -- root cause confirmed by re-fetching Oracle's `authentication_oath.
  html`: the app registration needs a "secondary audience" (the EPM instance's base URL) configured in the
  Oracle Cloud Console's OAuth configuration screen, a one-time tenant-side setup step this toolkit can't do
  itself. Once the user added it, the full flow live-verified clean: `list_applications`,
  `get_application_summary`, `list_plan_types`, `list_dimensions`, `get_dimension`,
  `list_substitution_variables`, `get_substitution_variable`, `get_migration_status`,
  `get_migration_api_versions` all PASS via `auth_method: oauth2`.

- **Added (2026-08-01, follow-up session): connections-management dashboard.** `GET /` on the OpenAPI server
  now serves a self-contained HTML dashboard (no CDN dependencies) for listing, adding, editing, and deleting
  `connections.yaml` entries and running a lightweight connectivity test (`list_applications`) per
  connection, backed by a new `/api/connections` CRUD API (`dashboard_api.py`). Writes go through a new
  `config.save_config()` (atomic write, re-validates the no-plaintext-secrets rule on the way out, same as
  `load_config()` on the way in) -- no route ever accepts or returns a resolved secret value. Live-verified
  end to end in a real browser (list/add/edit/delete, plus the test endpoint's clean failure message when
  credentials aren't set) and against the real BPC config on GX10.

- **Added (2026-08-01, follow-up session): zero-config env-var mode + two one-click install packages.**
  Built after the user explicitly rejected the terminal-copy-paste workflow this project had been using and
  asked for install + config to happen entirely through Claude's own UI, never through chat.
  - `config.load_config_from_env()` / `runtime.get_config()` -- when no `connections.yaml` exists, a single
    `default` connection is built entirely from `NSPB_*` env vars (see README.md's new "Zero-config" section
    for the full var list). A real `connections.yaml` always takes priority when present -- fully backward
    compatible, no existing multi-tenant install is affected.
  - `.mcpb` **Claude Desktop Extension** (`mcpb/manifest.json` + `mcpb/server/main.py` +
    `scripts/build_mcpb.py`) -- packages the toolkit as a one-click-installable extension using the `uv`
    server type (no vendored dependencies, no PyInstaller). `user_config` fields map straight onto the
    zero-config env vars above via `${user_config.KEY}` substitution, with `sensitive: true` on
    password/token/client-secret fields (masked input, OS-keychain storage). Schema-validated against the
    official `@anthropic-ai/mcpb` CLI and live-tested end to end: `uv run` resolves and installs the package
    fresh, and the server correctly answers a real MCP `initialize` handshake.
  - **Claude Code plugin** (`.claude-plugin/plugin.json` + `.mcp.json` + `skills/nspb-rest-toolkit/SKILL.md`
    at the repo root) -- same zero-config env vars via the plugin manifest's `userConfig` field (identical
    schema/semantics to MCPB's `user_config`, confirmed against Anthropic's plugins-reference docs), same
    `${CLAUDE_PLUGIN_ROOT}`-relative `uv run` launch pattern. Schema-validated with `claude plugin validate`
    (required updating the local `claude` CLI from 2.1.38 to 2.1.220 -- `userConfig`/`displayName` are newer
    fields an older CLI rejects as unrecognized) and live-tested: a direct `tools/list` call against the
    plugin's exact launch command returns the full, correct tool registry.
  - `docs/SKILL.md`'s safety model (confirm-before-destructive, never guess a form grid shape, never ask a
    user to paste a credential) ported into `skills/nspb-rest-toolkit/SKILL.md` so it loads automatically
    with the plugin, no separate setup step.
  - **oauth2 still needs one manual, unautomatable step regardless of packaging**: Oracle's Device Code flow
    requires human browser approval once. `basic`/`bearer_token` have no such step -- fill in the config form
    and the connection works immediately.
  - Caught and fixed a self-inflicted footgun during this work: running `uv run --directory <path>` in a
    directory that already has a pip-managed `.venv` (this repo's own dev environment) can corrupt the
    pip editable-install's metadata, since `uv` and `pip` both default to managing the same `.venv` directory
    but use incompatible install-record formats -- confirmed by reproducing it, fixed by reinstalling
    (`pip install -e .`). Verification `uv run` commands for this work were run against throwaway copies in
    `/tmp` instead, both to avoid this and because the repo lives inside a Google-Drive-synced folder, whose
    file-locking intermittently breaks `uv`'s directory operations mid-build.

### Added
- Initial clean-room release: REST engine (`client.py`) with retry/backoff
  and dual job-polling contracts (Planning named states, Migration numeric
  states).
- Three `auth_method`s, all implemented (no client-credentials/
  machine-to-machine grant -- Oracle EPM Cloud doesn't support one):
  - `basic` -- HTTP Basic, username/password via `credential_ref`.
  - `oauth2` -- Oracle's actual documented user-context flow: Device Code
    grant for a one-time interactive bootstrap, Refresh Token grant for
    unattended reuse. New `oauth2.py` module provides an in-memory
    access-token cache on `EPMClient` (no network unless the cached token
    is missing or within 60s of expiry), an `asyncio.Lock`-based
    single-flight refresh so concurrent `call()`s never race to consume the
    same (single-use, rotating) refresh token, and a per-connection on-disk
    JSON token cache (default `~/.nspb-rest-toolkit/tokens/<slug>.json`,
    `chmod 600` on POSIX) rewritten immediately after every refresh. New
    `oauth2_bootstrap.py` CLI (`python -m nspb_rest_toolkit.oauth2_bootstrap
    --config ... --connection ...`) for the one-time interactive Device
    Code approval. `ConnectionConfig` gains an `oauth2:` block
    (`idcs_base_url`, `client_id`, `service_instance_id`, optional
    `token_cache_path`), required whenever `auth_method: oauth2` is set.
    Expired or already-consumed refresh tokens surface as a clear
    `EPMAuthError` pointing back at the bootstrap command, not a raw HTTP
    error.
  - `bearer_token` -- a single pre-obtained static JWT (e.g. from an Oracle
    Identity Domain console's "Tokens and keys" page), resolved via
    `credential_ref` (new `config.resolve_bearer_token`) and sent as-is with
    no refresh logic. A 401 surfaces as a clear `EPMAuthError` telling the
    operator to regenerate and re-set the token, rather than a generic
    `EPMHTTPError`.
- `config.py`: plaintext-secret rejection now also scans a connection's
  nested `oauth2:` block for a mistakenly pasted `refresh_token`/
  `access_token`, in addition to the existing top-level check.
- `.gitignore`: defensive patterns (`*.token_cache.json`,
  `.nspb-rest-toolkit/`) in case an oauth2 connection's `token_cache_path`
  is ever misconfigured to point inside the repo.
- Multi-tenant connection config (`config.py`), credentials resolved from
  environment variables or an OS secrets store -- never plaintext on disk.
- Endpoint wrappers for Applications, Dimensions/Members, Forms, Jobs
  (generic + typed), and Migration/LCM, generated from
  `docs/endpoint-inventory.md`.
- Three consumption surfaces: Open WebUI native Tool (`openwebui_tool.py`),
  OpenAPI tool server (`openapi_server.py`), and MCP stdio server
  (`mcp_server.py`).
- Read/destructive safety model with `confirm=true` gating on all destructive
  operations, plus `docs/SKILL.md` guidance for calling LLMs (auth method
  does not change this model -- see SKILL.md section 6).
- Unit tests (mocked HTTP, no network) and optional live smoke tests.
