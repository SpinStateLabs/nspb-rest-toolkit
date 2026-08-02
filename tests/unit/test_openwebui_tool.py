"""Loads openwebui_tool.py the same way Open WebUI would (exec as a standalone
module) and exercises a couple of methods end-to-end with respx-mocked HTTP.
"""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
import respx

from nspb_rest_toolkit.exceptions import EPMConfirmationRequiredError

CONNECTIONS_YAML = """
connections:
  acme-corp:
    display_name: "Acme Corp"
    base_url: "https://acme.example.com"
    auth_method: basic
    credential_ref: "ACME"
"""

TOOL_PATH = Path(__file__).resolve().parents[2] / "src" / "nspb_rest_toolkit" / "openwebui_tool.py"


@pytest.fixture
def tool_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("ACME_USERNAME", "alice")
    monkeypatch.setenv("ACME_PASSWORD", "hunter2")

    config_path = tmp_path / "connections.yaml"
    config_path.write_text(CONNECTIONS_YAML, encoding="utf-8")

    spec = importlib.util.spec_from_file_location("openwebui_tool_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["openwebui_tool_under_test"] = module
    spec.loader.exec_module(module)

    tools = module.Tools()
    tools.valves.config_path = str(config_path)
    return tools


def test_module_loads_with_no_import_errors():
    spec = importlib.util.spec_from_file_location("openwebui_tool_smoke", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "Tools")
    assert hasattr(module.Tools, "Valves")


async def test_list_applications_round_trip(tool_instance):
    with respx.mock:
        respx.get("https://acme.example.com/HyperionPlanning/rest/v3/applications").mock(
            return_value=httpx.Response(200, json={"items": [{"name": "Vision"}], "links": [], "type": "HP"})
        )
        result = await tool_instance.list_applications("acme-corp")
    assert '"Vision"' in result


async def test_run_business_rule_without_confirm_raises(tool_instance):
    with respx.mock:
        with pytest.raises(EPMConfirmationRequiredError):
            await tool_instance.run_business_rule("acme-corp", "Vision", "CalcAll")


def test_list_connections_never_leaks_credentials(tool_instance):
    result = tool_instance.list_connections()
    assert "acme-corp" in result
    assert "hunter2" not in result


# ---- zero-config Valves fallback (no connections.yaml at all) -----------------------


def _load_tool_module():
    spec = importlib.util.spec_from_file_location("openwebui_tool_zero_config", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zero_config_valves_used_when_config_path_missing(tmp_path):
    module = _load_tool_module()
    tools = module.Tools()
    tools.valves.config_path = str(tmp_path / "does-not-exist.yaml")
    tools.valves.base_url = "https://demo.example.com"

    cfg = tools._load_config()
    conn = cfg.get("default")
    assert conn.base_url == "https://demo.example.com"
    assert conn.auth_method == "basic"


async def test_zero_config_valves_list_applications_round_trip(tmp_path):
    module = _load_tool_module()
    tools = module.Tools()
    tools.valves.config_path = str(tmp_path / "does-not-exist.yaml")
    tools.valves.base_url = "https://demo.example.com"
    tools.valves.username = "alice"
    tools.valves.password = "hunter2"

    with respx.mock:
        respx.get("https://demo.example.com/HyperionPlanning/rest/v3/applications").mock(
            return_value=httpx.Response(200, json={"items": [{"name": "Vision"}], "links": [], "type": "HP"})
        )
        result = await tools.list_applications("default")
    assert '"Vision"' in result
    assert "hunter2" not in result


def test_real_config_file_takes_priority_over_valves(tool_instance):
    # tool_instance's config_path points at a real file (acme-corp) -- even
    # with base_url also set in Valves, the file wins.
    tool_instance.valves.base_url = "https://should-not-be-used.example.com"
    cfg = tool_instance._load_config()
    assert "acme-corp" in cfg.connections
    assert "default" not in cfg.connections


def test_no_config_and_no_valves_raises_clear_error(tmp_path):
    module = _load_tool_module()
    tools = module.Tools()
    tools.valves.config_path = str(tmp_path / "does-not-exist.yaml")
    # base_url left at its default empty string.

    from nspb_rest_toolkit.exceptions import EPMConfigError

    with pytest.raises(EPMConfigError, match="base_url"):
        tools._load_config()
