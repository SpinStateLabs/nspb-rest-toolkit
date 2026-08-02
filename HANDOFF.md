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

5. **Full multi-customer SaaS on Netlify, all 3 Claude surfaces (Code CLI, Desktop, claude.ai), marketplace-
   based plugin distribution.** User explicitly confirmed the big-scope version (not the smaller "personal
   remote access" reading this file previously defaulted to) and asked for it directly, unblocking the
   "remote/HTTP MCP connector" question `[[nspb-rest-toolkit]]` memory had said to park.

   **Blocked on two things only the user can do (account creation is outside what the assistant does itself):**
   - **GitHub repo + push access.** Generated a dedicated SSH deploy key (`~/.ssh/nspb_rest_toolkit_deploy`,
     this repo's `core.sshCommand` already points at it) -- user needs to create an empty repo (chose
     `spinstatelabs/nspb-rest-toolkit` as the working name, not yet confirmed as final) and add the deploy
     key with write access, then send the repo URL. First commit is already made locally, ready to push the
     moment a remote exists.
   - **Auth0 tenant**, for OAuth 2.1 (chosen over hand-rolling an authorization server -- this product will
     store customers' real Oracle EPM credentials, so using a proven, audited identity platform is a
     deliberate security choice, not just convenience). User needs to sign up, create a tenant + application,
     and give the domain + client ID. `AUTH0_DOMAIN` / `AUTH0_AUDIENCE` env vars are already referenced by
     the code below, unset until then. Dynamic Client Registration approach for claude.ai's auto-connect flow
     is NOT yet decided -- needs to be resolved once real tenant access exists (Auth0 doesn't support
     anonymous DCR the way the MCP spec's reference flow assumes; likely either a pre-registered "claude.ai"
     client or a thin custom DCR shim calling Auth0's Management API -- don't guess this blind).

   **Scaffolded and locally verified (TypeScript compiles clean, `tsc --noEmit` passes) but NOT deployed or
   live-tested yet -- everything below is unverified against a real Auth0 tenant or real Netlify deploy:**
   - `package.json` / `tsconfig.json` / `netlify.toml` -- Node/TypeScript, `@netlify/functions` +
     `@netlify/database` + `jose` (JWKS-based JWT verification, no shared secret with Auth0).
   - `netlify/database/migrations/20260801000000_create_customers_and_connections/migration.sql` --
     `customers` (keyed by Auth0 `sub`) + `connections` (per-customer, mirrors `ConnectionConfig`'s shape,
     credentials encrypted) + `oauth2_token_cache` (remote equivalent of the local surface's on-disk token
     cache, since there's no per-customer filesystem here).
   - `netlify/functions/lib/crypto.ts` -- AES-256-GCM for credentials at rest, key from
     `CREDENTIALS_ENCRYPTION_KEY` (Netlify env var, not yet generated/set -- generate with
     `node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"` once ready to deploy).
   - `netlify/functions/lib/auth.ts` -- verifies Auth0-issued Bearer tokens via JWKS, upserts a `customers`
     row on first sight of a new `sub`.
   - `netlify/functions/mcp.mts` -- the remote MCP endpoint (Streamable HTTP, JSON-response mode, no SSE
     needed yet). Tool set is a deliberate **starting subset** (`list_connections`, `list_applications`) that
     proves the full pipeline end to end, NOT full parity with the ~30 operations the local Python surface
     has -- see `netlify/functions/lib/oracle-client.ts`'s docstring for how to extend it, following the same
     already-proven-correct patterns (`unwrap_items`, explicit charset, etc.) from `src/nspb_rest_toolkit/client.py`.
     `auth_method: oauth2` is NOT implemented on this surface yet (`basic`/`bearer_token` only) -- the schema
     has the columns for it but `lib/oracle-client.ts`'s `authHeader()` throws a clear 501 if attempted.
   - `netlify/functions/connections.mts` -- per-customer CRUD API, the DB-backed equivalent of
     `dashboard_api.py`. No customer-facing web UI for this yet (no equivalent of `static/dashboard.html`) --
     API only.
   - `netlify/functions/oauth-protected-resource.mts` -- RFC 9728 discovery endpoint so an MCP client knows
     to authenticate against Auth0.
   - `.claude-plugin/marketplace.json` -- passes `claude plugin validate`, points at `./` (this repo) as the
     plugin source. Not yet installable via `/plugin marketplace add owner/repo` since there's no remote yet.

   **Explicitly not started:** Desktop's remote-connector wiring (separate from the already-working local
   `.mcpb`), a customer-facing signup/connections-management web page for the SaaS surface, and porting the
   remaining ~28 Oracle operations beyond the two-tool proof-of-pipeline subset.

   **Update, same day, after the user completed both account-creation steps:**
   - GitHub repo live at `github.com/SpinStateLabs/nspb-rest-toolkit`, deploy key working, first commit
     pushed (`master`).
   - Auth0 tenant: `dev-ya4wqjm000nn3amg.us.auth0.com`, API audience
     `https://nspb-rest-toolkit.spinstatelabs.com/api`. **Resolved the DCR question flagged above by actually
     checking the docs (WebFetch, not a guess): Auth0 has real, spec-compliant OIDC Dynamic Client
     Registration built in** (`POST /oidc/register`, no manual per-client setup) -- this means claude.ai
     registers itself automatically and my server never needs a hand-rolled DCR shim, just the
     protected-resource-metadata endpoint already built pointing at Auth0. Two dashboard steps needed from
     the user to turn it on, given at the time: (1) Applications -> APIs -> the API -> Settings -> Default
     Permissions for Third-Party Applications -> Authorized for User-Delegated Access -> `openid profile
     email`; (2) Settings -> Advanced -> enable Dynamic Client Registration. **Known follow-up, not yet
     done**: Auth0's own docs warn that DCR without extra protection means anyone on the internet can
     register a client against the tenant -- fine for getting the pipeline working, but should be tightened
     (Auth0 mentions a "CIMD" alternative with domain-verified identities) before onboarding real customers.
     The two pre-existing Application client IDs the user initially sent (a "Default App" / Generic type, and
     an M2M "Test Application") turned out to be **not needed** for this flow -- DCR creates claude.ai's
     client automatically, and M2M apps are for server-to-server calls, not user login.
   - Netlify: site created (`nspb-rest-toolkit`, id `7e508972-17a1-46fd-a5b9-8aec97ae77bc`,
     `nspb-rest-toolkit.netlify.app`), all three env vars set (`AUTH0_DOMAIN`, `AUTH0_AUDIENCE`,
     `CREDENTIALS_ENCRYPTION_KEY` -- the last one generated locally via Node's `crypto.randomBytes`, set
     directly through the Netlify env-var API, never shown to the user or logged anywhere). Netlify DB will
     auto-provision on first deploy (confirmed via `initialize-database` -- just needs the `@netlify/database`
     dependency present, which it is). **Still needed, one more one-time UI step**: the available Netlify MCP
     tools can create a site and set env vars but don't expose git-repo linking -- the user needs to link the
     GitHub repo for continuous deployment themselves (Site configuration -> Build & deploy -> Continuous
     deployment -> Link repository -> GitHub -> `SpinStateLabs/nspb-rest-toolkit`). Once linked, every push
     auto-deploys with no further manual steps.
   - Not yet verified live: the actual deploy (no build has run yet), the DB migration applying successfully,
     Auth0 token verification against a real token, or an actual end-to-end claude.ai connector test. All of
     this needs the repo-link step above before it can be tested.

   **Update, same day, after the repo link: build ran and failed at DB provisioning.** `Provisioning
   database... API error on "createSiteDatabase"... 403 database feature not available for this account`.
   Root cause (confirmed by checking Netlify's own extension page, not guessed): **Netlify DB's
   auto-provisioning (`@netlify/database`, the whole "installing the package + deploying auto-provisions
   Postgres" mechanism this was originally built around) has been discontinued for new databases.** Installing
   the "Neon" extension via the Netlify API didn't fix it -- same 403 persisted -- because the extension
   itself shows "Deprecation Notice: This Netlify DB extension (powered by @netlify/neon) has been
   discontinued. New database creation is no longer available through this extension... An improved Netlify DB
   experience is coming soon." `npx netlify db init` (the alternative the deprecation notice itself points at)
   needs interactive browser login this session can't complete.

   **Pivoted away from `@netlify/database` entirely** rather than depend on Netlify's mid-transition DB story:
   - New `netlify/functions/lib/db.ts` -- plain `pg.Pool` against a manually-set `DATABASE_URL`, exposing the
     same `getDatabase().sql` tagged-template shape `connections-repo.ts`/`auth.ts` already used, so both
     files needed only an import-line change.
   - `package.json`: removed `@netlify/database`, added `pg` + `@types/pg`. `tsc --noEmit` clean.
   - **Moved the migration out of `netlify/database/migrations/`** to `db/migrations/` -- Netlify's build
     system auto-scans that exact path and retries the now-broken auto-provisioning regardless of whether
     `@netlify/database` is even a dependency; leaving the migration there would keep failing every build.
     `db/migrations/README.md` explains the new manual-apply process (`psql "$DATABASE_URL" -f
     db/migrations/<dir>/migration.sql`, or paste into a web SQL editor).

   **Still needed to actually go live, all account-level actions only the user can do:**
   1. A real Postgres database -- Neon directly (neon.tech) is the natural choice (that's literally what the
      deprecated extension was wrapping); the user may already have a Neon account/project from having
      interacted with the extension ("any claimed databases remain in your Neon account" per Netlify's own
      notice) -- worth checking before creating a new one.
   2. Run `db/migrations/20260801000000_create_customers_and_connections/migration.sql` once against that
      database -- Neon's own web SQL editor works fine for this, no local `psql` needed, and means the
      connection string never has to be pasted anywhere outside Neon's own UI.
   3. Set `DATABASE_URL` (the connection string Neon gives after creating the project) as a Netlify env var
      for this site, same as the three already set -- never through chat.
   4. Push (or just re-trigger a deploy) once `DATABASE_URL` is set to get a clean build.

   **Update, same day: the deploy actually succeeded** (58 files, 3 functions, 36s build) once
   `@netlify/database` was dropped -- confirmed live: `/mcp` and `/api/connections` correctly 401
   "Missing or malformed Authorization header" on an unauthenticated request (real auth.ts code running).
   **But found a real problem with the Netlify env-var tooling**: `manage-env-vars`'s `upsertEnvVar`
   consistently reports "Environment variable upserted" (success) for `AUTH0_DOMAIN`/`AUTH0_AUDIENCE`/
   `CREDENTIALS_ENCRYPTION_KEY`, but an immediate `getAllEnvVars` read-back shows an empty array every time
   -- and a live authenticated request to `/mcp` throws a real, unhandled `Error: AUTH0_AUDIENCE is not set`
   from inside `requireEnv()`, confirming this isn't just a read-tool display bug: the values genuinely never
   reached the deployed function's runtime environment despite the tool's success response. **Don't trust this
   MCP tool's env-var writes for this site again without verifying against a live function error afterward**
   -- asked the user to set all three (plus `DATABASE_URL` once available) directly in Netlify's dashboard UI
   instead, which is also consistent with the standing "config screen, not through me" pattern for anything
   secret-adjacent.
   - `npx netlify db init` was also retried properly (in case it could sidestep the whole DATABASE_URL/Neon
     dashboard dance) -- hit an unrelated, pre-existing environment issue on this machine first: bare
     `npx netlify-cli ...` and `npx --package=netlify-cli -c "..."` both fail with `Cannot find module
     'C:\Program Files\nodejs\node_modules\netlify-cli\bin\run.js'`, even though that directory doesn't
     actually contain a netlify-cli folder (`ls` confirms) and `npm list -g netlify-cli` shows nothing
     installed there either -- some Node/npm path-resolution quirk on this Windows machine unrelated to the
     project itself, not diagnosed further since the DATABASE_URL-via-dashboard path already works and
     doesn't depend on this CLI at all.

   **Update, same day: fully wired up and verified.** User set all four env vars directly in Netlify's
   dashboard (confirming the "don't trust this tool's writes" finding above). Verified live, after a
   redeploy:
   - `GET /.well-known/oauth-protected-resource` returns 200 with the correct Auth0 domain -- `AUTH0_DOMAIN`
     confirmed reaching the deployed function.
   - `POST /mcp` with a garbage Bearer token returns `401 Invalid Compact JWS` (real `jose` JWT parsing, not
     the earlier `AUTH0_AUDIENCE is not set` crash) -- confirms both Auth0 env vars are live and the resource-
     server validation path is genuinely running, correctly rejecting invalid tokens before touching the DB.
   - `DATABASE_URL`: user pasted the raw Neon connection string directly into chat despite being asked not
     to -- flagged plainly, recommended rotating it once things are stable (Neon lets you reset the password
     from the project's connection-details page). Used it transiently (one local `pg` script, nothing written
     to disk) to confirm connectivity, discovered the migration had never actually been run (`Tables: []`),
     and applied `db/migrations/20260801000000_create_customers_and_connections/migration.sql` directly --
     all three tables (`customers`, `connections`, `oauth2_token_cache`) now exist.
   - **Not yet tested**: an actual authenticated request all the way through (a real Auth0-issued token
     hitting `tools/call`, exercising `connections-repo.ts`'s DB reads/writes and the AES-256-GCM
     encryption round-trip). Couldn't simulate this myself without either a real user login (Auth0 Universal
     Login, needs a browser) or a client_secret for the M2M test app (deliberately never requested/handled).
     **The natural real test now is connecting from claude.ai's own remote-connector UI** -- that drives the
     genuine DCR + login + token flow this was all built for, and is the actual target user journey, not a
     synthetic stand-in for it.
   - `oauth_metadata` note: DCR itself (the two Auth0 dashboard toggles from earlier) was configured by the
     user but never independently re-verified working end-to-end -- worth confirming during the claude.ai
     connector test above, since that's the first time a real dynamic registration would actually fire.

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
