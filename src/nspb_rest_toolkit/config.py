"""Multi-tenant connection configuration.

Config is YAML, one entry per customer connection. Credentials are never
written in plaintext to this file:

- `basic` and `bearer_token` connections carry a `credential_ref`, a name
  resolved at runtime against (in order): (1) an environment variable with
  that exact name, (2) the OS-appropriate secrets store, via the optional
  `keyring` package (`pip install nspb-rest-toolkit[secrets]` equivalent --
  keyring is an optional import so the toolkit has no hard OS-keychain
  dependency).
- `oauth2` connections carry a plain (non-secret) `oauth2:` block naming the
  IDCS tenant/client -- the actual access/refresh tokens never live here;
  see oauth2.py for the on-disk token cache they're persisted to instead.

Nothing in this module logs or returns a resolved secret in an exception
message -- callers get an `EPMConfigError` naming the *ref*, never the value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .exceptions import EPMConfigError

# Field names that must never appear in the config file itself -- their
# presence means a plaintext secret was pasted in by mistake. Checked both
# at the top level of a connection entry and one level down, inside an
# `oauth2:` block (where a customer might mistakenly paste a live
# access/refresh token instead of the non-secret client identifiers that
# actually belong there).
_FORBIDDEN_PLAINTEXT_KEYS = {
    "password",
    "client_secret",
    "token",
    "api_key",
    "secret",
    "refresh_token",
    "access_token",
}

# Three auth methods:
# - "basic": HTTP Basic, username/password via credential_ref. Fully
#   supported, unchanged since the first release.
# - "oauth2": Oracle's documented user-context flow for EPM Cloud (Device
#   Code grant for interactive first-auth, Refresh Token grant for
#   unattended reuse) -- see docs/endpoint-inventory.md section 2 and
#   oauth2.py. Requires an `oauth2:` block (validated below).
# - "bearer_token": a single pre-obtained static JWT (e.g. downloaded by a
#   customer from their Oracle Identity Domain console's "Tokens and keys"
#   page), sent as-is on every call via credential_ref. No refresh logic --
#   if it expires, the operator regenerates and re-sets it manually.
AuthMethod = Literal["basic", "oauth2", "bearer_token"]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug or "connection"


class OAuth2Config(BaseModel):
    """Device Code + Refresh Token flow parameters -- docs/endpoint-inventory.md section 2.

    None of these fields are secrets and they may live in plain YAML:
    `idcs_base_url`, `client_id`, and `service_instance_id` identify the
    OAuth2 client/tenant, not a credential. The live access/refresh tokens
    never touch this config; they're written to (and read from) the on-disk
    token cache managed by oauth2.py, populated once via the interactive
    Device Code bootstrap (`python -m nspb_rest_toolkit.oauth2_bootstrap`).
    """

    idcs_base_url: str
    client_id: str
    service_instance_id: str
    # Optional override of the default
    # ~/.nspb-rest-toolkit/tokens/<slug>.json cache location.
    token_cache_path: str | None = None
    # False for session-only access (or for an IDCS app registration with
    # "Allow token refresh: Disallowed") -- the bootstrap requests an access
    # token without the offline_access scope, no refresh_token is stored, and
    # EPMClient raises an actionable EPMAuthError once the token expires
    # rather than attempting a refresh IDCS would reject anyway. Default True
    # matches the original unattended-reuse design.
    allow_refresh: bool = True
    # Set only for Confidential Application registrations (the ones with a
    # "Client secret" in the IDCS console). Oracle's *documented* Device Code
    # flow is public-client and needs no secret (docs/endpoint-inventory.md
    # section 2), but a Confidential Application rejects the token endpoint
    # with invalid_client unless authenticated -- when set, this names an env
    # var (same credential_ref convention as ConnectionConfig.credential_ref)
    # resolved via resolve_oauth2_client_secret and sent as HTTP Basic auth on
    # the device/token endpoint calls. Never a secret value itself.
    client_secret_ref: str | None = None

    @field_validator("idcs_base_url")
    @classmethod
    def _no_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class ConnectionConfig(BaseModel):
    # Populated from the connections.yaml mapping key by ToolkitConfig, not
    # meant to be set directly in YAML. Used as the default OAuth2 token
    # cache filename so multiple connections never collide.
    slug: str = ""
    display_name: str
    base_url: str
    auth_method: AuthMethod = "basic"
    credential_ref: str
    default_application: str | None = None
    oauth2: OAuth2Config | None = None

    @field_validator("base_url")
    @classmethod
    def _no_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @model_validator(mode="after")
    def _require_oauth2_block(self) -> "ConnectionConfig":
        if self.auth_method == "oauth2" and self.oauth2 is None:
            raise ValueError(
                "auth_method=oauth2 requires an 'oauth2:' block with idcs_base_url, "
                "client_id, and service_instance_id -- see README.md's auth_method section."
            )
        return self

    def planning_base_url(self) -> str:
        return f"{self.base_url}/HyperionPlanning/rest/v3"

    def migration_base_url(self) -> str:
        return f"{self.base_url}/interop/rest/v2"

    def data_management_base_url(self) -> str:
        # Version casing per docs/endpoint-inventory.md section 1: fetched
        # examples print "V1" but Oracle's versioning.html says version
        # segments are case-sensitive and lowercase ("v3" valid, "V3" not)
        # for the Planning/Migration families -- assumed to hold here too,
        # not independently re-verified against a live aif/rest/ response.
        return f"{self.base_url}/aif/rest/v1"

    def oauth2_token_cache_path(self) -> Path:
        """Resolve the on-disk path for this connection's OAuth2 token cache.

        This file is a credential -- it holds the live access + (rotating)
        refresh token -- see oauth2.py's save_token_cache for the
        restrictive-permissions handling. Defaults to
        ~/.nspb-rest-toolkit/tokens/<slug>.json; override per-connection via
        oauth2.token_cache_path.
        """
        assert self.oauth2 is not None
        if self.oauth2.token_cache_path:
            return Path(self.oauth2.token_cache_path).expanduser()
        key = self.slug or _slugify(self.display_name)
        return Path.home() / ".nspb-rest-toolkit" / "tokens" / f"{key}.json"


class ToolkitConfig(BaseModel):
    connections: dict[str, ConnectionConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _assign_slugs(self) -> "ToolkitConfig":
        for slug, conn in self.connections.items():
            if not conn.slug:
                conn.slug = slug
        return self

    def get(self, slug: str) -> ConnectionConfig:
        try:
            return self.connections[slug]
        except KeyError as exc:
            known = ", ".join(sorted(self.connections)) or "(none configured)"
            raise EPMConfigError(
                f"No connection named '{slug}' in config. Known connections: {known}"
            ) from exc


def _reject_plaintext_secrets(raw: dict, path: Path) -> None:
    for slug, entry in (raw.get("connections") or {}).items():
        if not isinstance(entry, dict):
            continue
        leaked = _FORBIDDEN_PLAINTEXT_KEYS & entry.keys()
        if leaked:
            raise EPMConfigError(
                f"{path}: connection '{slug}' has plaintext secret field(s) "
                f"{sorted(leaked)}. Use 'credential_ref' to name an environment "
                f"variable or secrets-store key instead -- never put the actual "
                f"secret value in this file."
            )
        oauth2_block = entry.get("oauth2")
        if isinstance(oauth2_block, dict):
            nested_leaked = _FORBIDDEN_PLAINTEXT_KEYS & oauth2_block.keys()
            if nested_leaked:
                raise EPMConfigError(
                    f"{path}: connection '{slug}' oauth2 block has plaintext secret "
                    f"field(s) {sorted(nested_leaked)}. Only idcs_base_url, client_id, "
                    f"service_instance_id, and token_cache_path belong here -- the "
                    f"live tokens are written to the on-disk token cache by the Device "
                    f"Code bootstrap, never to this file."
                )


def load_config(path: str | Path) -> ToolkitConfig:
    path = Path(path)
    if not path.exists():
        raise EPMConfigError(f"Config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EPMConfigError(f"{path}: invalid YAML ({exc})") from exc

    _reject_plaintext_secrets(raw, path)

    try:
        return ToolkitConfig.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError
        raise EPMConfigError(f"{path}: {exc}") from exc


ZERO_CONFIG_SLUG = "default"
ZERO_CONFIG_CREDENTIAL_REF = "NSPB"


def load_config_from_env(getenv: Callable[[str], str | None] | None = None) -> ToolkitConfig | None:
    """Zero-config single-connection mode -- no connections.yaml at all.

    For the common single-customer case: add this as an MCP server / Open
    WebUI tool and fill in a handful of values directly in that host's own
    config UI (Claude Desktop's server config screen, Open WebUI's tool
    Valves) -- never a YAML file, never a value typed into a chat message.
    Returns None if NSPB_BASE_URL isn't set, which is the signal that
    zero-config mode isn't in use -- runtime.get_config() then falls through
    to the normal file-based multi-tenant path (and a real connections.yaml
    always takes priority when both are present, since it's checked first).

    `getenv` defaults to `os.environ.get` -- pass a different single-arg
    lookup function to source these same NSPB_* keys from somewhere other
    than real environment variables (openwebui_tool.py does this to read
    from its Valves instead, since Open WebUI's Valves ARE that host's
    native config-screen mechanism, not env vars).

    Keys, all read fresh on every call (nothing cached) so a host that lets
    an operator edit values and restart/reinstantiate picks up changes
    immediately, matching every other "reload every time" convention in this
    module:
      NSPB_BASE_URL            required -- the tenant base URL
      NSPB_AUTH_METHOD         optional, default "basic"
      NSPB_DISPLAY_NAME        optional, default "Default Connection"
      NSPB_USERNAME / NSPB_PASSWORD          -- for auth_method=basic
      NSPB_TOKEN                             -- for auth_method=bearer_token
      NSPB_OAUTH2_IDCS_BASE_URL, NSPB_OAUTH2_CLIENT_ID,
      NSPB_OAUTH2_SERVICE_INSTANCE_ID        -- for auth_method=oauth2
      NSPB_OAUTH2_ALLOW_REFRESH              -- optional, default true
      NSPB_OAUTH2_CLIENT_SECRET              -- optional (Confidential
                                                 Application registrations)
    """
    get = getenv or os.environ.get

    base_url = get("NSPB_BASE_URL")
    if not base_url:
        return None

    auth_method = get("NSPB_AUTH_METHOD") or "basic"
    display_name = get("NSPB_DISPLAY_NAME") or "Default Connection"

    oauth2 = None
    if auth_method == "oauth2":
        idcs_base_url = get("NSPB_OAUTH2_IDCS_BASE_URL")
        client_id = get("NSPB_OAUTH2_CLIENT_ID")
        service_instance_id = get("NSPB_OAUTH2_SERVICE_INSTANCE_ID")
        if not (idcs_base_url and client_id and service_instance_id):
            raise EPMConfigError(
                "Zero-config mode (NSPB_BASE_URL set, no connections.yaml) with "
                "NSPB_AUTH_METHOD=oauth2 requires NSPB_OAUTH2_IDCS_BASE_URL, "
                "NSPB_OAUTH2_CLIENT_ID, and NSPB_OAUTH2_SERVICE_INSTANCE_ID."
            )
        allow_refresh_raw = (get("NSPB_OAUTH2_ALLOW_REFRESH") or "true").strip().lower()
        oauth2 = OAuth2Config(
            idcs_base_url=idcs_base_url,
            client_id=client_id,
            service_instance_id=service_instance_id,
            allow_refresh=allow_refresh_raw not in ("false", "0", "no"),
            client_secret_ref="NSPB_OAUTH2_CLIENT_SECRET" if get("NSPB_OAUTH2_CLIENT_SECRET") else None,
        )

    # bearer_token resolves credential_ref AS the literal env var name (see
    # resolve_bearer_token) -- "NSPB_TOKEN" reads far better in a config UI
    # than the bare "NSPB" used for basic's _USERNAME/_PASSWORD suffixing.
    credential_ref = "NSPB_TOKEN" if auth_method == "bearer_token" else ZERO_CONFIG_CREDENTIAL_REF

    conn = ConnectionConfig(
        slug=ZERO_CONFIG_SLUG,
        display_name=display_name,
        base_url=base_url,
        auth_method=auth_method,
        credential_ref=credential_ref,
        oauth2=oauth2,
    )
    return ToolkitConfig(connections={ZERO_CONFIG_SLUG: conn})


def _to_raw_dict(config: ToolkitConfig) -> dict:
    return {
        "connections": {
            slug: conn.model_dump(exclude={"slug"}, exclude_none=True)
            for slug, conn in config.connections.items()
        }
    }


def save_config(config: ToolkitConfig, path: str | Path) -> None:
    """Write `config` back to `path` as YAML -- the dashboard's write path.

    Re-runs the same no-plaintext-secrets check load_config() applies (defense
    in depth; the schema has no field to put a secret in, so this should never
    actually trigger) and writes atomically (temp file + os.replace) so a
    crash mid-write can never leave a truncated/corrupt connections.yaml on
    disk.
    """
    path = Path(path)
    raw = _to_raw_dict(config)
    _reject_plaintext_secrets(raw, path)

    text = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def resolve_credential(ref: str) -> str:
    """Resolve a credential_ref to its secret value.

    Tries the environment first, then an OS secrets store via `keyring` if
    installed. Raises EPMConfigError naming the ref (never a value) if
    nothing is found.
    """
    value = os.environ.get(ref)
    if value:
        return value

    try:
        import keyring  # optional dependency
    except ImportError:
        keyring = None

    if keyring is not None:
        value = keyring.get_password("nspb-rest-toolkit", ref)
        if value:
            return value

    raise EPMConfigError(
        f"Could not resolve credential '{ref}': not set as an environment "
        f"variable and not found in the OS secrets store under service "
        f"'nspb-rest-toolkit'."
    )


def resolve_basic_credentials(ref: str) -> tuple[str, str]:
    """Resolve a Basic-auth credential_ref to (username, password).

    Convention: two underlying secrets, `{ref}_USERNAME` and
    `{ref}_PASSWORD`, each resolved via `resolve_credential`.
    """
    username = resolve_credential(f"{ref}_USERNAME")
    password = resolve_credential(f"{ref}_PASSWORD")
    return username, password


def resolve_oauth2_client_secret(ref: str) -> str:
    """Resolve a Confidential Application's client_secret_ref to its value.

    Single secret, resolved via resolve_credential -- same env-var/keyring
    lookup as every other credential_ref in this module.
    """
    return resolve_credential(ref)


def resolve_bearer_token(ref: str) -> str:
    """Resolve a bearer_token credential_ref to the raw token string.

    Unlike Basic auth's two-part `{ref}_USERNAME`/`{ref}_PASSWORD`
    convention, bearer_token is a single pre-obtained secret (a JWT a
    customer downloaded from their Oracle Identity Domain console) -- `ref`
    is resolved as-is via `resolve_credential`.
    """
    return resolve_credential(ref)
