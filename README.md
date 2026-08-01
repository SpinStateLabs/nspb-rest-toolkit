# nspb-rest-toolkit

A direct REST toolkit for Oracle EPM Cloud Planning & Budgeting (NSPB). No
Windows, no PowerShell, no EPM Automate CLI binary -- pure Python over
HTTPS against Oracle's own REST APIs, installable on any Linux box (or
anywhere Python 3.10+ runs).

Ships as three consumption surfaces from one codebase:

- **Open WebUI Tool** -- a single-file Python tool you paste into
  Workspace -> Tools.
- **OpenAPI tool server** -- a FastAPI app any OpenAPI-tool-calling client
  can point at.
- **MCP server** -- a stdio server for Claude Desktop / Claude Code.

...and two one-click install packages for the MCP server, built from that
same codebase -- see [Zero-config / one-click install](#zero-config--one-click-install)
below. Both let a customer configure credentials directly in Claude's own
config UI, never in a terminal:

- **`.mcpb` (Claude Desktop Extension)** -- `dist/nspb-rest-toolkit.mcpb`,
  built by `scripts/build_mcpb.py`. Double-click to install in Claude
  Desktop's Chat tab; fills in a native settings form.
- **Claude Code plugin** -- `.claude-plugin/plugin.json` +
  `skills/nspb-rest-toolkit/` + `.mcp.json` at this repo's root. Install
  directly from a local path or git URL in Claude Code / the Code tab of
  Claude Desktop; same native config-form experience.

Every operation is tagged `read` or `destructive` in
[docs/endpoint-inventory.md](docs/endpoint-inventory.md), and every
destructive call requires an explicit `confirm=true`. See
[docs/SKILL.md](docs/SKILL.md) for the full safety model.

## Zero-config / one-click install

For the common single-customer case, `connections.yaml` isn't needed at
all -- set `NSPB_BASE_URL` (+ credentials) as environment variables and the
toolkit builds a single `default` connection from them at runtime (see
`config.load_config_from_env`; a real `connections.yaml`, if present, always
takes priority). This is what both packages below fill in via their config
screens -- you never hand-edit env vars or YAML for a single-tenant install.

| Env var | Used for |
|---|---|
| `NSPB_BASE_URL` | required -- tenant base URL |
| `NSPB_AUTH_METHOD` | `basic` (default), `oauth2`, or `bearer_token` |
| `NSPB_USERNAME` / `NSPB_PASSWORD` | `auth_method: basic` |
| `NSPB_TOKEN` | `auth_method: bearer_token` |
| `NSPB_OAUTH2_IDCS_BASE_URL`, `NSPB_OAUTH2_CLIENT_ID`, `NSPB_OAUTH2_SERVICE_INSTANCE_ID` | `auth_method: oauth2` (required) |
| `NSPB_OAUTH2_ALLOW_REFRESH` | `auth_method: oauth2` (optional, default true -- see the `oauth2` section below) |
| `NSPB_OAUTH2_CLIENT_SECRET` | `auth_method: oauth2` (optional -- Confidential Application registrations only) |

**`oauth2` still needs one manual step regardless of packaging**: Oracle's
Device Code flow requires a human to approve in a real browser once
(`python -m nspb_rest_toolkit.oauth2_bootstrap`) -- this can't be automated
away by any installer. `basic` and `bearer_token` have no such step; fill in
the config form and the connection works immediately.

### Install the Claude Desktop Extension (`.mcpb`)

```bash
python scripts/build_mcpb.py
```

Builds `dist/nspb-rest-toolkit.mcpb` (validated against Anthropic's
`@anthropic-ai/mcpb` CLI, live-tested via `uv run` -- see CHANGELOG.md).
Double-click the file, or drag it into Claude Desktop's extensions screen;
fill in the settings form (base URL, auth method, credentials -- sensitive
fields are masked and stored in your OS keychain, never in plain text).

### Install the Claude Code plugin

From this repo (local path) or a git remote once you have one:

```
/plugin marketplace add /path/to/nspb-rest-toolkit
/plugin install nspb-rest-toolkit@nspb-rest-toolkit
```

or, to load it for a single session without installing:

```bash
claude --plugin-dir /path/to/nspb-rest-toolkit
```

Claude Code prompts for the same config fields (`base_url`, `auth_method`,
credentials) via `claude plugin enable`'s config prompt or `--config
key=value`, storing sensitive values in secure OS storage per
[Anthropic's plugin docs](https://code.claude.com/docs/en/plugins-reference#user-configuration).
The bundled `skills/nspb-rest-toolkit/SKILL.md` teaches Claude the same
safety model as `docs/SKILL.md` (reads are safe, destructive ops need
explicit confirmation) automatically -- no separate setup.

## Auth methods

Three `auth_method` values are supported, per connection:

- **`basic`** -- HTTP Basic, username/password. Simplest option; rejected
  by Oracle if your tenant enforces MFA.
- **`oauth2`** -- Oracle's actual documented user-context flow for EPM
  Cloud (there is no client-credentials machine-to-machine grant): Device
  Code for a one-time interactive bootstrap, Refresh Token for unattended
  reuse afterward. Required if your tenant enforces MFA. See section 2
  below for setup.
- **`bearer_token`** -- a single static, pre-obtained JWT (e.g. downloaded
  from your Oracle Identity Domain console's "Tokens and keys" page), sent
  as-is on every call. No refresh logic -- when it expires, regenerate it
  manually and update the stored credential.

See [docs/endpoint-inventory.md](docs/endpoint-inventory.md) section 2 for
the full OAuth2 flow Oracle documents, and
[src/nspb_rest_toolkit/oauth2.py](src/nspb_rest_toolkit/oauth2.py) for the
implementation.

## 1. Install

```bash
pip install nspb-rest-toolkit
```

For local development from a clone:

```bash
pip install -e ".[dev]"
pytest tests/unit
```

## 2. Add your tenant to config

Create a `connections.yaml` (path is configurable -- see below). Credentials
are **never** written in this file, regardless of auth method.

### `basic`

```yaml
connections:
  acme-corp:
    display_name: "Acme Corp"
    base_url: "https://acme-corp.epm.us-ashburn-1.ocs.oraclecloud.com"
    auth_method: basic
    credential_ref: "ACME_CORP_EPM"
    default_application: "Vision"
```

`credential_ref: ACME_CORP_EPM` resolves against two environment variables
(or an OS secrets store under service `nspb-rest-toolkit`, key names
matching the env var names below, via the optional `keyring` package):

```bash
export ACME_CORP_EPM_USERNAME="service.account@example.com"
export ACME_CORP_EPM_PASSWORD="..."
```

### `oauth2`

Required for MFA-enforcing tenants. `idcs_base_url`, `client_id`, and
`service_instance_id` are not secrets -- Oracle Identity Cloud Service
(IDCS) tenant/client identifiers, not credentials -- and can live in plain
YAML:

```yaml
connections:
  mfa-corp:
    display_name: "MFA Corp"
    base_url: "https://mfa-corp.epm.us-ashburn-1.ocs.oraclecloud.com"
    auth_method: oauth2
    credential_ref: "MFA_CORP_EPM"  # unused by oauth2 today; kept for schema consistency
    oauth2:
      idcs_base_url: "https://idcs-<tenant>.identity.oraclecloud.com"
      client_id: "<your IDCS client id>"
      service_instance_id: "<your EPM service instance id>"
      # Optional; defaults to ~/.nspb-rest-toolkit/tokens/mfa-corp.json
      # token_cache_path: "/path/to/mfa-corp.token_cache.json"
      # allow_refresh: false        # see "Session-only access" below
      # client_secret_ref: "..."    # see "Confidential Application registrations" below
```

**Before bootstrapping, the IDCS app registration needs a secondary audience configured** (a one-time
setup step, done by whoever administers the Oracle Cloud Console for that identity domain -- not something
this toolkit can do): Oracle Cloud Console -> Oracle Cloud Services tab -> the EPM Cloud service -> OAuth
configuration tab -> Edit OAuth configuration -> enable "Add secondary audience" -> add the EPM instance's
base URL (exactly `base_url` above, no trailing path) -> Save. Without this, every API call fails with
`WWW-Authenticate: Bearer error="invalid_token", error_description="Token Audience"` even though the device
code bootstrap itself succeeds -- the token gets issued, it's just not accepted by the Planning REST API.
Live-confirmed 2026-08-01 against BPC's `Planning_nspb` app registration.

**Session-only access (`allow_refresh: false`):** for apps with "Allow token refresh: Disallowed" in their
OAuth configuration, or when you deliberately don't want persistent unattended reuse (e.g. one access token
per chat session), set `allow_refresh: false`. The bootstrap requests an access token without the
`offline_access` scope -- omitting `offline_access` is required here, not just simpler, because IDCS
rejects the whole device-code request with `unauthorized_client: The resource does not support offline
access` if `offline_access` is asked for on an app where refresh is disallowed. No refresh_token is stored;
once the access token expires (1 hour), `EPMClient` raises a clear `EPMAuthError` telling you to re-run the
bootstrap, rather than attempting a refresh IDCS would reject anyway.

**Confidential Application registrations (`client_secret_ref`):** Oracle's *documented* Device Code flow is
public-client (no secret needed) -- see the quote below -- but an app registration created as a Confidential
Application (has a "Client secret" in the IDCS console) rejects every device/token endpoint call with
`invalid_client: Client authentication failed` unless authenticated. Set `client_secret_ref` to a
`credential_ref`-style env var name (same convention as `ConnectionConfig.credential_ref` -- never the
secret itself in YAML) and the toolkit sends it as HTTP Basic auth (`client_secret_basic`) on the
device/token endpoint calls. Leave unset for public-client apps (the default, unaffected).

Then run the **one-time interactive bootstrap** (a human has to approve in
a browser -- this can't be automated):

```bash
python -m nspb_rest_toolkit.oauth2_bootstrap --config connections.yaml --connection mfa-corp
```

This prints a verification URL and code, waits for you to approve in your
browser, then writes the initial access+refresh token to an on-disk cache
(default `~/.nspb-rest-toolkit/tokens/mfa-corp.json`). From then on,
`EPMClient` refreshes the access token automatically and unattended --
Oracle's refresh tokens are single-use/rotating and expire after 7 days of
inactivity, so re-run the bootstrap command if you ever see an
`EPMAuthError` about an expired or already-consumed refresh token. That
cache file is a credential, equivalent to a password -- it's written with
owner-only permissions on POSIX (`chmod 600`; this is a no-op on Windows,
where you should rely on filesystem ACLs / user-profile isolation instead)
and must never be committed to a repo (the default location is outside any
repo, and `.gitignore` here has a defensive pattern in case
`token_cache_path` is ever pointed inside one).

### `bearer_token`

For a single pre-obtained static JWT (e.g. downloaded from your Oracle
Identity Domain console's "Tokens and keys" page):

```yaml
connections:
  bearer-corp:
    display_name: "Bearer Corp"
    base_url: "https://bearer-corp.epm.us-ashburn-1.ocs.oraclecloud.com"
    auth_method: bearer_token
    credential_ref: "BEARER_CORP_TOKEN"
```

```bash
export BEARER_CORP_TOKEN="eyJ..."
```

No refresh logic -- when the token expires, calls fail with a clear
`EPMAuthError` telling you to regenerate it and update the environment
variable / secrets-store entry.

Add as many connections as you have customers, mixing auth methods freely
-- no code changes required.

## 3. Install into Open WebUI

1. Make sure `nspb-rest-toolkit` is installed in Open WebUI's Python
   environment (Open WebUI's tool loader reads the `requirements:` line at
   the top of [src/nspb_rest_toolkit/openwebui_tool.py](src/nspb_rest_toolkit/openwebui_tool.py)
   and pip-installs it automatically the first time the tool is added).
2. In Open WebUI: **Workspace -> Tools -> +**, then paste the full contents
   of `openwebui_tool.py`.
3. Open the tool's **Valves** and set `config_path` to the path of your
   `connections.yaml` on the Open WebUI host (or a volume-mounted path if
   running in a container).
4. Enable the tool for whichever model/workspace should use it.

## 4. Install into Claude (Desktop or Code)

```bash
claude mcp add nspb-rest -- python -m nspb_rest_toolkit.mcp_server
```

Set `NSPB_CONFIG_PATH` (defaults to `connections.yaml` in the working
directory) so the server can find your config, e.g. in Claude Desktop's MCP
server config:

```json
{
  "mcpServers": {
    "nspb-rest": {
      "command": "python",
      "args": ["-m", "nspb_rest_toolkit.mcp_server"],
      "env": { "NSPB_CONFIG_PATH": "/path/to/connections.yaml" }
    }
  }
}
```

## 5. Run the OpenAPI tool server standalone

```bash
export NSPB_CONFIG_PATH=/path/to/connections.yaml
python -m nspb_rest_toolkit.openapi_server
```

Serves on `http://0.0.0.0:8000`; `/openapi.json` lists every operation,
`/health` for a liveness check, `/connections` lists configured connection
slugs (no credentials).

**`GET /`** serves a connections-management dashboard -- list, add, edit, and
delete `connections.yaml` entries, and run a lightweight connectivity test
(`list_applications`) per connection, all from the browser. It's backed by
`/api/connections` (full CRUD -- see [dashboard_api.py](src/nspb_rest_toolkit/dashboard_api.py)),
which never accepts or returns a resolved secret value: writes go through
`config.save_config()`, the same schema validation `load_config()` applies to
a hand-edited file (including the no-plaintext-secrets check), and the test
endpoint reports auth/connectivity failures as a normal JSON result rather
than a 500 -- credentials are still set out-of-band via env var/keyring,
exactly as with every other surface in this toolkit.

## 6. Run the smoke test to confirm connectivity

Smoke tests require a real tenant and are not part of the default
`pytest` run:

```bash
export NSPB_SMOKE_CONNECTION_CONFIG=/path/to/connections.yaml
export NSPB_SMOKE_CONNECTION=acme-corp
export NSPB_SMOKE_APPLICATION=Vision
export NSPB_SMOKE_PLANTYPE=Plan1
export NSPB_SMOKE_FORM=SomeForm
export ACME_CORP_EPM_USERNAME=... ACME_CORP_EPM_PASSWORD=...

pytest tests/smoke -v
```

This confirms: list applications, list dimensions, read a form. The
business-rule-run + job-polling round trip is opt-in and skipped unless you
also set `NSPB_SMOKE_ALLOW_DESTRUCTIVE=1` and `NSPB_SMOKE_BUSINESS_RULE` to
a real, safe-to-run rule name -- see
[tests/smoke/conftest.py](tests/smoke/conftest.py) for the full list of env
vars.

## Project layout

```
src/nspb_rest_toolkit/
  client.py            REST engine: auth, retry, base-url resolution, call() chokepoint, job polling
  config.py             Multi-tenant connection config + credential resolution
  runtime.py             Shared per-call client construction for the server surfaces
  endpoints/              One module per category (applications, dimensions, forms, jobs, migration, security, substitution_variables, approvals, data_management)
  openwebui_tool.py      Single-file Open WebUI Tool
  openapi_server.py      FastAPI OpenAPI tool server
  mcp_server.py           MCP stdio server
docs/
  endpoint-inventory.md  Full REST endpoint catalog, sourced from Oracle's official docs
  SKILL.md                Safety/usage guidance for the calling LLM
tests/
  unit/                   Mocked HTTP, no network, runs in CI
  smoke/                  Optional live-tenant tests, requires real credentials
```

## License

MIT -- see [LICENSE](LICENSE).
