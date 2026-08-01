"""runtime.get_config()'s file-vs-zero-config fallback priority."""

import pytest

from nspb_rest_toolkit.exceptions import EPMConfigError
from nspb_rest_toolkit.runtime import get_config

YAML = """
connections:
  acme-corp:
    display_name: "Acme Corp"
    base_url: "https://acme.example.com"
    auth_method: basic
    credential_ref: "ACME"
"""


def _clear_zero_config_env(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("NSPB_"):
            monkeypatch.delenv(key, raising=False)


def test_get_config_uses_real_file_when_present(tmp_path, monkeypatch):
    path = tmp_path / "connections.yaml"
    path.write_text(YAML, encoding="utf-8")
    _clear_zero_config_env(monkeypatch)
    monkeypatch.setenv("NSPB_CONFIG_PATH", str(path))

    cfg = get_config()
    assert "acme-corp" in cfg.connections


def test_get_config_falls_back_to_zero_config_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("NSPB_CONFIG_PATH", str(tmp_path / "does-not-exist.yaml"))
    monkeypatch.setenv("NSPB_BASE_URL", "https://demo.example.com")

    cfg = get_config()
    assert cfg.get("default").base_url == "https://demo.example.com"


def test_get_config_real_file_takes_priority_over_zero_config_env(tmp_path, monkeypatch):
    path = tmp_path / "connections.yaml"
    path.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("NSPB_CONFIG_PATH", str(path))
    # Even if zero-config env vars are ALSO set, the real file wins.
    monkeypatch.setenv("NSPB_BASE_URL", "https://should-not-be-used.example.com")

    cfg = get_config()
    assert "acme-corp" in cfg.connections
    assert "default" not in cfg.connections


def test_get_config_raises_clear_error_when_neither_present(tmp_path, monkeypatch):
    monkeypatch.setenv("NSPB_CONFIG_PATH", str(tmp_path / "does-not-exist.yaml"))
    monkeypatch.delenv("NSPB_BASE_URL", raising=False)

    with pytest.raises(EPMConfigError, match="NSPB_BASE_URL"):
        get_config()
