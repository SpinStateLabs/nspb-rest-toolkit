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
