import pytest

from nspb_rest_toolkit.config import (
    ConnectionConfig,
    OAuth2Config,
    ToolkitConfig,
    load_config,
    load_config_from_env,
    resolve_basic_credentials,
    resolve_bearer_token,
    resolve_credential,
    resolve_oauth2_client_secret,
    save_config,
)
from nspb_rest_toolkit.exceptions import EPMConfigError

BASIC_YAML = """
connections:
  acme-corp:
    display_name: "Acme Corp"
    base_url: "https://acme-corp.epm.us-ashburn-1.ocs.oraclecloud.com/"
    auth_method: basic
    credential_ref: "ACME_CORP_EPM"
    default_application: "Vision"
"""

OAUTH2_YAML = """
connections:
  mfa-corp:
    display_name: "MFA Corp"
    base_url: "https://mfa-corp.epm.us-ashburn-1.ocs.oraclecloud.com"
    auth_method: oauth2
    credential_ref: "MFA_CORP_EPM"
    oauth2:
      idcs_base_url: "https://idcs-abc123.identity.oraclecloud.com"
      client_id: "mfa-corp-client-id"
      service_instance_id: "mfa-corp-service-instance"
"""

OAUTH2_MISSING_BLOCK_YAML = """
connections:
  mfa-corp:
    display_name: "MFA Corp"
    base_url: "https://mfa-corp.epm.us-ashburn-1.ocs.oraclecloud.com"
    auth_method: oauth2
    credential_ref: "MFA_CORP_EPM"
"""

BEARER_YAML = """
connections:
  bearer-corp:
    display_name: "Bearer Corp"
    base_url: "https://bearer-corp.epm.us-ashburn-1.ocs.oraclecloud.com"
    auth_method: bearer_token
    credential_ref: "BEARER_CORP_TOKEN"
"""

PLAINTEXT_YAML = """
connections:
  bad-corp:
    display_name: "Bad Corp"
    base_url: "https://bad-corp.example.com"
    auth_method: basic
    credential_ref: "BAD_CORP"
    password: "hunter2"
"""

PLAINTEXT_OAUTH2_YAML = """
connections:
  bad-corp:
    display_name: "Bad Corp"
    base_url: "https://bad-corp.example.com"
    auth_method: oauth2
    credential_ref: "BAD_CORP"
    oauth2:
      idcs_base_url: "https://idcs-abc123.identity.oraclecloud.com"
      client_id: "bad-corp-client-id"
      service_instance_id: "bad-corp-service-instance"
      refresh_token: "should-not-be-here"
"""


def test_load_config_basic(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(BASIC_YAML, encoding="utf-8")

    cfg = load_config(path)
    conn = cfg.get("acme-corp")

    assert conn.display_name == "Acme Corp"
    assert conn.base_url == "https://acme-corp.epm.us-ashburn-1.ocs.oraclecloud.com"  # trailing slash stripped
    assert conn.planning_base_url() == "https://acme-corp.epm.us-ashburn-1.ocs.oraclecloud.com/HyperionPlanning/rest/v3"
    assert conn.migration_base_url() == "https://acme-corp.epm.us-ashburn-1.ocs.oraclecloud.com/interop/rest/v2"


def test_load_config_unknown_connection_raises(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(BASIC_YAML, encoding="utf-8")
    cfg = load_config(path)

    with pytest.raises(EPMConfigError, match="acme-corp"):
        cfg.get("does-not-exist")


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(EPMConfigError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_rejects_plaintext_secret(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(PLAINTEXT_YAML, encoding="utf-8")

    with pytest.raises(EPMConfigError, match="plaintext"):
        load_config(path)


def test_auth_method_oauth2_accepted_at_config_layer(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(OAUTH2_YAML, encoding="utf-8")
    cfg = load_config(path)
    conn = cfg.get("mfa-corp")

    assert conn.auth_method == "oauth2"
    assert conn.oauth2 is not None
    assert conn.oauth2.idcs_base_url == "https://idcs-abc123.identity.oraclecloud.com"
    assert conn.oauth2.client_id == "mfa-corp-client-id"
    assert conn.oauth2.service_instance_id == "mfa-corp-service-instance"
    # Slug is populated from the connections.yaml mapping key.
    assert conn.slug == "mfa-corp"


def test_auth_method_oauth2_missing_block_fails_config_load(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(OAUTH2_MISSING_BLOCK_YAML, encoding="utf-8")

    with pytest.raises(EPMConfigError, match="oauth2"):
        load_config(path)


def test_auth_method_bearer_token_works_with_just_credential_ref(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(BEARER_YAML, encoding="utf-8")
    cfg = load_config(path)
    conn = cfg.get("bearer-corp")

    assert conn.auth_method == "bearer_token"
    assert conn.credential_ref == "BEARER_CORP_TOKEN"


def test_load_config_rejects_plaintext_secret_nested_in_oauth2_block(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(PLAINTEXT_OAUTH2_YAML, encoding="utf-8")

    with pytest.raises(EPMConfigError, match="plaintext"):
        load_config(path)


def test_resolve_bearer_token(monkeypatch):
    monkeypatch.setenv("BEARER_CORP_TOKEN", "eyJ.the.jwt")
    assert resolve_bearer_token("BEARER_CORP_TOKEN") == "eyJ.the.jwt"


def test_resolve_credential_from_env(monkeypatch):
    monkeypatch.setenv("SOME_REF", "s3cr3t")
    assert resolve_credential("SOME_REF") == "s3cr3t"


def test_resolve_credential_missing_raises(monkeypatch):
    monkeypatch.delenv("MISSING_REF", raising=False)
    with pytest.raises(EPMConfigError, match="MISSING_REF"):
        resolve_credential("MISSING_REF")


def test_resolve_credential_error_never_contains_a_value(monkeypatch):
    monkeypatch.setenv("OTHER_REF", "should-not-leak")
    monkeypatch.delenv("MISSING_REF", raising=False)
    with pytest.raises(EPMConfigError) as exc_info:
        resolve_credential("MISSING_REF")
    assert "should-not-leak" not in str(exc_info.value)


def test_resolve_basic_credentials(monkeypatch):
    monkeypatch.setenv("ACME_CORP_EPM_USERNAME", "alice")
    monkeypatch.setenv("ACME_CORP_EPM_PASSWORD", "hunter2")
    username, password = resolve_basic_credentials("ACME_CORP_EPM")
    assert username == "alice"
    assert password == "hunter2"


def test_resolve_oauth2_client_secret(monkeypatch):
    monkeypatch.setenv("BPC_OAUTH2_SECRET", "s3cr3t")
    assert resolve_oauth2_client_secret("BPC_OAUTH2_SECRET") == "s3cr3t"


# ---- save_config (dashboard write path) -----------------------------------------


def test_save_config_round_trips_basic_connection(tmp_path):
    path = tmp_path / "connections.yaml"
    path.write_text(BASIC_YAML, encoding="utf-8")
    cfg = load_config(path)

    save_config(cfg, path)
    reloaded = load_config(path)

    assert reloaded.get("acme-corp").display_name == "Acme Corp"
    assert reloaded.get("acme-corp").base_url == cfg.get("acme-corp").base_url
    assert reloaded.get("acme-corp").default_application == "Vision"


def test_save_config_round_trips_oauth2_connection_with_new_fields(tmp_path):
    path = tmp_path / "connections.yaml"
    cfg = ToolkitConfig(
        connections={
            "bpc-oauth2": ConnectionConfig(
                display_name="BPC OAuth2",
                base_url="https://bpc.example.com",
                auth_method="oauth2",
                credential_ref="BPC",
                oauth2=OAuth2Config(
                    idcs_base_url="https://idcs-abc.identity.oraclecloud.com",
                    client_id="client-1",
                    service_instance_id="123456",
                    allow_refresh=False,
                    client_secret_ref="BPC_OAUTH2_SECRET",
                ),
            )
        }
    )

    save_config(cfg, path)
    reloaded = load_config(path)
    conn = reloaded.get("bpc-oauth2")

    assert conn.oauth2.allow_refresh is False
    assert conn.oauth2.client_secret_ref == "BPC_OAUTH2_SECRET"
    # Never a plaintext secret on disk -- only the *_ref name.
    assert "s3cr3t" not in path.read_text(encoding="utf-8")


def test_save_config_never_writes_slug_as_a_field(tmp_path):
    path = tmp_path / "connections.yaml"
    cfg = ToolkitConfig(
        connections={
            "acme-corp": ConnectionConfig(
                display_name="Acme Corp", base_url="https://acme.example.com",
                auth_method="basic", credential_ref="ACME",
            )
        }
    )
    save_config(cfg, path)
    raw = path.read_text(encoding="utf-8")
    assert "slug" not in raw  # it's the mapping key, not a field, on disk


def test_load_config_from_env_returns_none_when_no_base_url(monkeypatch):
    monkeypatch.delenv("NSPB_BASE_URL", raising=False)
    assert load_config_from_env() is None


def test_load_config_from_env_basic(monkeypatch):
    monkeypatch.setenv("NSPB_BASE_URL", "https://demo.epm.us-ashburn-1.ocs.oraclecloud.com")
    monkeypatch.delenv("NSPB_AUTH_METHOD", raising=False)
    cfg = load_config_from_env()
    conn = cfg.get("default")
    assert conn.auth_method == "basic"
    assert conn.base_url == "https://demo.epm.us-ashburn-1.ocs.oraclecloud.com"
    assert conn.credential_ref == "NSPB"  # resolves NSPB_USERNAME / NSPB_PASSWORD


def test_load_config_from_env_bearer_token_uses_distinct_ref(monkeypatch):
    monkeypatch.setenv("NSPB_BASE_URL", "https://demo.example.com")
    monkeypatch.setenv("NSPB_AUTH_METHOD", "bearer_token")
    cfg = load_config_from_env()
    conn = cfg.get("default")
    assert conn.auth_method == "bearer_token"
    assert conn.credential_ref == "NSPB_TOKEN"


def test_load_config_from_env_oauth2_requires_idcs_fields(monkeypatch):
    monkeypatch.setenv("NSPB_BASE_URL", "https://demo.example.com")
    monkeypatch.setenv("NSPB_AUTH_METHOD", "oauth2")
    monkeypatch.delenv("NSPB_OAUTH2_IDCS_BASE_URL", raising=False)
    with pytest.raises(EPMConfigError, match="NSPB_OAUTH2_IDCS_BASE_URL"):
        load_config_from_env()


def test_load_config_from_env_oauth2_full(monkeypatch):
    monkeypatch.setenv("NSPB_BASE_URL", "https://demo.example.com")
    monkeypatch.setenv("NSPB_AUTH_METHOD", "oauth2")
    monkeypatch.setenv("NSPB_OAUTH2_IDCS_BASE_URL", "https://idcs-demo.identity.oraclecloud.com")
    monkeypatch.setenv("NSPB_OAUTH2_CLIENT_ID", "client-1")
    monkeypatch.setenv("NSPB_OAUTH2_SERVICE_INSTANCE_ID", "123456")
    monkeypatch.setenv("NSPB_OAUTH2_ALLOW_REFRESH", "false")
    monkeypatch.setenv("NSPB_OAUTH2_CLIENT_SECRET", "s3cr3t")
    cfg = load_config_from_env()
    conn = cfg.get("default")
    assert conn.oauth2.idcs_base_url == "https://idcs-demo.identity.oraclecloud.com"
    assert conn.oauth2.allow_refresh is False
    assert conn.oauth2.client_secret_ref == "NSPB_OAUTH2_CLIENT_SECRET"


def test_load_config_from_env_custom_getenv_source(monkeypatch):
    # Confirms the getenv override is genuinely used instead of os.environ --
    # openwebui_tool.py relies on this to source values from Valves.
    monkeypatch.delenv("NSPB_BASE_URL", raising=False)  # not set in the real environment
    values = {"NSPB_BASE_URL": "https://from-valves.example.com", "NSPB_AUTH_METHOD": "basic"}
    cfg = load_config_from_env(getenv=lambda key: values.get(key))
    assert cfg.get("default").base_url == "https://from-valves.example.com"


def test_load_config_from_env_display_name_default(monkeypatch):
    monkeypatch.setenv("NSPB_BASE_URL", "https://demo.example.com")
    monkeypatch.delenv("NSPB_DISPLAY_NAME", raising=False)
    monkeypatch.delenv("NSPB_AUTH_METHOD", raising=False)
    cfg = load_config_from_env()
    assert cfg.get("default").display_name == "Default Connection"


def test_save_config_is_atomic_no_leftover_tmp_file(tmp_path):
    path = tmp_path / "connections.yaml"
    cfg = ToolkitConfig(
        connections={
            "acme-corp": ConnectionConfig(
                display_name="Acme Corp", base_url="https://acme.example.com",
                auth_method="basic", credential_ref="ACME",
            )
        }
    )
    save_config(cfg, path)
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()
