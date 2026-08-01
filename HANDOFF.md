# Handoff — nspb-rest-toolkit

**Written:** 2026-08-01, end of the session that built this from scratch. Read this before doing anything
else in this repo — it captures state that isn't obvious from the code alone.

## Where things stand right now

- Repo: `Projects\NSPB\nspb-rest-toolkit\` — git-initialized, **zero commits**. Everything described below is
  uncommitted working-tree state. Don't commit without asking the user first (per standing git-safety rules)
  unless they've explicitly asked for a commit by the time you read this.
- **67/67 unit tests pass**, all respx-mocked, zero live network (`pytest tests/unit -v`).
- `connections.yaml` exists at the repo root with a real `bpc` connection (Basic Auth) pointed at Bipartisan
  Policy Center's tenant. It's gitignored — never remove that `.gitignore` line.
- Full project memory lives at `[[nspb-rest-toolkit]]` in the auto-memory system — read that too, it has the
  architecture overview this file doesn't repeat.

## What's built and live-verified (not just claimed — actually run against BPC)

Auth: three methods, all user-selectable per connection (`auth_method: basic | oauth2 | bearer_token`).
Basic Auth is what's been live-tested; BPC accepts it fine (no MFA on that tenant). OAuth2 (Device Code +
Refresh Token) and Bearer token are built and unit-tested but **never live-tested** — see "Next up" below.

Read-only endpoints confirmed working live against BPC (app name `NetSuite`):
`list_applications`, `get_application_summary`, `list_plan_types`, `list_dimensions`, `get_dimension`,
`list_substitution_variables`, `get_substitution_variable`, `get_migration_status`,
`get_migration_api_versions`. Run `scripts/live_read_only_check.py` to re-verify any of these after a change
(needs `NSPB_SMOKE_CONNECTION_CONFIG`, `NSPB_SMOKE_CONNECTION`, and the connection's credential env vars set
in the *user's own terminal* — see "Credential handling" below, do not try to acquire these yourself).

Still untested live: `security.export_security`/`export_cell_level_security` (excluded on purpose — they
write a file into Oracle's repository as a side effect), `forms.*` (no "list forms" REST resource exists, so
there's no name to discover without the user supplying one), job-status-by-ID endpoints (need a real job ID
this session never submitted), and the Approvals/Planning Units read endpoints (need real
`scenario`/`version` names for BPC — not discoverable from any other read call; set `NSPB_SMOKE_SCENARIO` /
`NSPB_SMOKE_VERSION` env vars if you get real values from the user).

## Three real bugs found by live testing that NO mocked test caught (all fixed now)

This is the important pattern to internalize before writing more endpoint code: **the original
`docs/endpoint-inventory.md` was built from Oracle's documentation pages, but several assumptions about
request/response shape turned out to be wrong once tested against a real tenant.** Don't trust an endpoint
wrapper's shape as correct just because it matches the inventory doc — the inventory doc itself has already
been wrong twice this session.

1. **Collection envelope, not a bare array.** `GET .../applications` and similar list endpoints return
   `{"items": [...], "links": [...]}`, not a bare JSON array. Fixed via `client.unwrap_items()`, a helper
   that tolerates both shapes (safe to apply broadly).
2. **`application/json` needs an explicit charset going out** (httpx's default is a bare `application/json`
   with no charset; Oracle's own responses always carry `; charset=UTF-8`). `EPMClient.call()` now sets this
   explicitly whenever a JSON body is sent. Caveat: this was never actually confirmed to fix anything by
   itself — see point 3.
3. **The Planning Unit workflow endpoints (`approvals.py`) don't take JSON at all — they take
   `application/x-www-form-urlencoded`.** This is what a persistent HTTP 415 on `list_planning_units` turned
   out to be, confirmed by re-fetching Oracle's actual docs (`list_all_planning_units.html`,
   `get_available_planning_unit_actions.html`, `change_planning_unit_status.html`) after the charset fix
   from point 2 didn't resolve it. All three functions in `approvals.py` were rewritten against the
   confirmed real shapes. `EPMClient.call()` gained a `data=` parameter for this.

**Bonus bug, not Oracle's fault:** while fixing #3, hit a genuine **httpx 0.28.1 bug** — passing a
list-of-tuples to httpx's own `data=` parameter (needed for Oracle's repeated `filter=A&filter=B`
convention) builds a sync-only stream and crashes under `AsyncClient` with `RuntimeError: Attempted to send
an sync request with an AsyncClient instance`. Reproduced directly outside this codebase to confirm it
wasn't a respx artifact. Worked around by url-encoding `data` by hand and sending it via `content=` instead
of httpx's `data=`. If httpx is ever upgraded, it's worth re-testing whether this workaround is still needed
(see the comment in `client.py`'s `call()` docstring).

## Security incident this session — status check needed

The real BPC password got exposed twice: once via a `Windows-MCP` `Snapshot` call that captured a KeePass
"Edit Entry" dialog's plaintext Password field (accessibility-tree text extraction, not just a screenshot
pixel), and once via a diagnostic script (`scripts/diag_planning_units_415.py`) that printed an unredacted
`Authorization` header, which then appeared in a screenshot and a user-pasted terminal transcript. The
script's redaction bug is fixed. **The user said "I will rotate the key in the meantime" — confirm this
actually happened before treating BPC credentials as trustworthy again.** Full writeup:
`[[feedback-desktop-automation-secret-exposure]]` in memory.

**Credential handling ground rule for this whole project, re-learned the hard way:** never touch, request,
or print live credentials in a hosted session. Real credentials stay in the user's own terminal; you give
them commands to run and they paste back output. If you write any diagnostic script that inspects a real
HTTP request/response, redact `Authorization` explicitly — it does not happen automatically.

## What the user asked for next, in the order they asked

1. ~~"dig in" on the `list_planning_units` 415~~ — **done**, see above. Root cause found and fixed via real
   Oracle documentation, not guessing.
2. **"deploy it to GB10 and test it there."** GB10 = the NVIDIA Grace Blackwell superchip inside the ASUS
   Ascent **GX10** box — the user uses "GB10" and "GX10" interchangeably for the whole machine; the correct
   project name and SSH alias is GX10. Access: `ssh gx10` (key-based, already set up per
   `Projects\GX10\GX10_Services_and_Clients.md`), host `10.0.0.62`, user `spinner`. There's also an
   `mcp__gx10__run_on_gx10` tool and a `gx10-compute` agent type available for this. **This aligns with
   `[[feedback-epm-operational-boundary]]`** — that memory says live EPM/PBCS/NSPB operations should run from
   GX10, not a hosted session, so deploying there and shifting live testing to happen *from* GX10 going
   forward is the right move, not just a nice-to-have.

   **Deployment done (2026-08-01, follow-up session):** repo tarred locally (excluding `.git`, `.venv`,
   caches, and `connections.yaml`) and streamed over `ssh gx10` into `~/projects/nspb-rest-toolkit` on the
   box. Python 3.12.3 confirmed available there. Created a fresh `.venv`, `pip install -e .`, then
   `pip install pytest pytest-asyncio respx` and ran `pytest tests/unit -q` — **67/67 pass**, matching the
   local result. Recreated `connections.yaml` at `~/projects/nspb-rest-toolkit/connections.yaml` (chmod 600)
   with the same `bpc` entry and `credential_ref: BPC` — no credentials baked in, same env-var pattern as
   local.

   **Live testing from GX10 is still blocked** — the user confirmed the BPC password has **NOT been rotated
   yet** despite the two prior exposures (see "Security incident" section below), so no live BPC calls were
   made or attempted from this session, and no credential env vars were set. Per the credential-handling
   ground rule, that has to happen in the user's own GX10 shell session, not here. Once rotation is
   confirmed, the user can run (from `ssh gx10`, in `~/projects/nspb-rest-toolkit`):

   ```
   export NSPB_SMOKE_CONNECTION_CONFIG=~/projects/nspb-rest-toolkit/connections.yaml
   export NSPB_SMOKE_CONNECTION=bpc
   export BPC_USERNAME=donhagell@gmail.com
   export BPC_PASSWORD=<the rotated password>
   .venv/bin/python scripts/live_read_only_check.py
   ```

   (env var names per `tests/smoke/conftest.py`'s docstring: `<CREDENTIAL_REF>_USERNAME` /
   `<CREDENTIAL_REF>_PASSWORD`, i.e. `BPC_USERNAME` / `BPC_PASSWORD` for this connection's `credential_ref:
   BPC`). Nothing further needed from the assistant side for this step until that's done — do not set these
   env vars or request the password in a hosted session.
3. ~~"need to test the oath too" (OAuth2)~~ — **done, live-verified 2026-08-01 (follow-up session)**, all
   9 applicable read-only checks PASS via `auth_method: oauth2` against BPC's `Planning_nspb` app
   registration. This needed three real fixes beyond the original unit-tested-only implementation — see
   CHANGELOG.md's "Live-discovered (2026-08-01), OAuth2 live-tested for the first time" entry for full
   detail, summary here:
   - `Planning_nspb` has "Allow token refresh: Disallowed" — requesting `offline_access` scope got the whole
     device-code request rejected outright. New `OAuth2Config.allow_refresh: false` (used for this
     connection) omits `offline_access` and accepts session-only access with no refresh — matches what the
     user actually asked for ("I do not need offline access... session level access for the user chat
     session"), not just a workaround.
   - `Planning_nspb` is a Confidential Application (has a client secret) — token endpoint rejected everything
     with `invalid_client` until authenticated. New `OAuth2Config.client_secret_ref` (a `credential_ref`-style
     env var name, never a secret in YAML) sends HTTP Basic auth on the device/token calls.
   - Root cause of a subsequent `Token Audience` 401 on every API call (even with a valid token): the app
     registration had no "secondary audience" configured — a one-time Oracle Cloud Console setup step (Oracle
     Cloud Services tab → the EPM service → OAuth configuration → Edit → Add secondary audience → the
     instance's base URL) that this toolkit can't do itself. User did this, then the flow worked clean.
   - `connections.yaml` now has a `bpc-oauth2` entry (alongside the original `bpc` Basic Auth entry) with
     `allow_refresh: false` and `client_secret_ref: "BPC_OAUTH2_CLIENT_SECRET"`. Token cache lives at
     `~/.nspb-rest-toolkit/tokens/bpc-oauth2.json` on GX10 (that's where the bootstrap was run, per item 2
     above) — expires ~1hr after each bootstrap since refresh is disallowed; re-run the bootstrap command
     (README.md's oauth2 section has the exact command) to get a fresh one when needed.
   - Discovered along the way: the SSH config for `ssh gx10` lives in `~/.ssh/config` on the user's own PC
     (hostname `rog-command`), not somewhere only the assistant can reach — the user can open their own
     terminal (PowerShell/Git Bash/Windows Terminal) and run `ssh gx10` directly. Worth remembering next time
     a "the user has no access" assumption comes up for GX10 specifically.
4. ~~"can you make a dashboard similar to the epmautomate dashboard? ... for managing and testing
   connections and saved connections."~~ — **done, 2026-08-01 follow-up session.** User chose full
   read/write scope (not just read-only + test) when asked. Built:
   - `config.save_config()` — writes a `ToolkitConfig` back to YAML, atomically (temp file + `os.replace`),
     re-running the same no-plaintext-secrets check `load_config()` applies on the way in.
   - `dashboard_api.py` — `/api/connections` CRUD (list/get/create/update/delete) plus
     `/api/connections/{slug}/test` (runs `list_applications` as a lightweight connectivity check, never
     raises — auth/connectivity failures come back as a normal `{success: false, message: ...}` JSON result,
     not a 500). Every route reloads `connections.yaml` fresh each call, matching `runtime.py`'s stateless
     convention. No route ever accepts or returns a resolved secret value.
   - `static/dashboard.html` — single self-contained page (no CDN dependencies), served at `GET /`. List
     table with inline Test results, an Add/Edit modal with auth-method-conditional fields (the `oauth2:`
     fieldset only shows for `auth_method: oauth2`, including the new `allow_refresh` checkbox and
     `client_secret_ref` field from earlier this session), Delete with confirm.
   - 21 new unit tests (`test_config.py`'s `save_config` round-trip tests, `test_dashboard_api.py`'s full CRUD
     + test-endpoint coverage) — 94/94 total now pass, both locally and on GX10.
   - Live-verified twice: once in a real browser locally against an isolated demo config (full
     add/edit/delete/test cycle, confirmed file writes on disk), and once against the **real BPC config on
     GX10** (user ran it themselves via `ssh gx10` on a free port — 8000 turned out to already be occupied by
     an unrelated service on that shared box — and confirmed in their own browser: `bpc`'s Test fails cleanly
     on missing credentials, `bpc-oauth2`'s Test succeeds live in ~250ms showing 1 application visible).

## Distribution packaging -- done, 2026-08-01 follow-up session (same day as the dashboard/OAuth2 work)

User pushback: the terminal-copy-paste workflow used for everything above ("ssh gx10, export a var, run this
command") "has to stop" -- they want install + config to happen entirely through Claude's own UI, never
through chat, and explicitly said they'd paste a credential into a config screen (fine) or to me directly
(refused -- see the standing credential rule at the top of this file, unchanged). Built:

1. **Zero-config env-var mode** (`config.load_config_from_env`, `runtime.get_config`) -- no
   `connections.yaml` needed for a single-customer install; `NSPB_BASE_URL` + a handful of `NSPB_*` env vars
   build a `default` connection at runtime. Real `connections.yaml` still takes priority when present.
2. **`.mcpb` Claude Desktop Extension** -- `mcpb/manifest.json`, `mcpb/server/main.py`,
   `scripts/build_mcpb.py` (run it, get `dist/nspb-rest-toolkit.mcpb`). One-click install, native settings
   form maps straight onto the zero-config env vars, sensitive fields go to the OS keychain. Verified against
   the real `@anthropic-ai/mcpb` CLI (`mcpb pack` / `mcpb validate` / `mcpb unpack`) and live-launch-tested
   (`uv run` from a clean `/tmp` copy correctly resolves deps and answers a real MCP `initialize` call).
3. **Claude Code plugin** -- `.claude-plugin/plugin.json` + `.mcp.json` + `skills/nspb-rest-toolkit/SKILL.md`
   at the repo root (this repo doubles as the plugin source -- no separate staging needed, unlike MCPB).
   Same env-var mapping via the manifest's `userConfig` field. `claude plugin validate .` passes (needed
   updating the local `claude` CLI 2.1.38 -> 2.1.220 first -- `userConfig`/`displayName` are version-gated
   fields an old CLI rejects). Live-tested: a direct `tools/list` call against the plugin's exact
   `${CLAUDE_PLUGIN_ROOT}`-relative launch command returns the full, correct tool registry (list_applications
   through change_planning_unit_status, confirm-gating intact).

**Known limitation, not fixable by packaging**: `oauth2` connections still need one manual, human-in-browser
step (the Device Code bootstrap) regardless of install method -- Oracle's flow requires it. `basic` and
`bearer_token` have no such step; the config form alone is enough.

**Gotcha hit and fixed**: running `uv run --directory <path>` against a directory that already has a
pip-managed `.venv` (this repo's own dev environment) corrupted the pip editable-install's metadata --
`uv` and `pip` both default to the same `.venv` directory name but use incompatible install-record formats.
Fixed via `pip install -e .` re-run. All verification `uv run` calls for this work now happen against
throwaway `/tmp` copies instead, which also sidesteps a separate issue: this repo lives inside a
Google-Drive-synced folder, and GDrive's file locking intermittently breaks `uv`'s directory operations
mid-build (`Access is denied` on a dist-info directory) -- if `uv` is ever run in-place in this repo again
and fails with a permissions error mid-build, re-run `pip install -e .` afterward to check for the same
corruption before assuming tests are broken.

**Not yet done**: publishing the plugin to a real git remote (currently only installable from this local
path) or an MCPB signing key (packages currently show "Not signed" -- fine for direct distribution, would
matter for a public marketplace listing). Neither was asked for yet.

## Still open, next up

5. **"public endpoint... deploy to netlify."** Not started. This reopens a question this project explicitly
   parked earlier (see `[[nspb-rest-toolkit]]` memory, "park this in favor of the local stdio MCP server
   model") -- the user has now asked for it directly, unblocking it, but the exact shape ("personal remote
   access for you" vs. "real multi-customer SaaS other people sign up for") was never confirmed; an
   AskUserQuestion about this went unanswered (the user moved straight to the plugin/MCPB ask instead).
   Default to the smaller-scope "personal remote access" reading unless told otherwise, since Netlify
   Functions are stateless (no persistent `connections.yaml`-equivalent filesystem, no place for an OAuth2
   token cache to live between invocations) -- a real multi-customer version needs a proper secrets backend
   and per-tenant isolation design, not just "click deploy."

## Open questions from the original task brief, still never answered

1. License/distribution model — open-source repo vs. handing over a built wheel/zip. Flagged explicitly in
   the original brief, never actually asked.
2. Whether to eventually build this as a true remote/HTTP MCP connector (claude.ai-style "Authorize" click,
   Claude manages the OAuth token itself) — user has Netlify wired in already but explicitly said to park
   this in favor of the local stdio MCP server model (2026-08-01). Revisit only if asked; don't let the
   dashboard work above accidentally turn into this without a separate explicit decision.

## Quick reference

- Run tests: `.venv\Scripts\python.exe -m pytest tests/unit -v`
- Live read-only sweep: `.venv\Scripts\python.exe scripts\live_read_only_check.py` (env vars per
  `tests/smoke/conftest.py`'s docstring)
- `docs/endpoint-inventory.md` — the endpoint catalog, now with several sections corrected/annotated with
  live-confirmed findings. Trust the "Live-confirmed" annotations over the plain doc-sourced rows.
- `docs/SKILL.md` — safety/usage guidance shipped to whatever LLM calls this toolkit's tools. Not touched
  this session beyond the auth-method section from the OAuth2 build; still accurate.
