"""agent_runner 的 azure provider 分支（Responses API）。

不打 API：以 MagicMock 取代 openai 模組，config.json 以 patched read_text 注入。
run: 2026-10-08-azure-llm-provider（task/2026-10-08.md item 1.3）
"""
import importlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent

_AZURE_CFG = {
    "provider": "azure",
    "azure": {
        "endpoint": "https://x/openai/v1",
        "deployment_name": "gpt-5.5",
        "api_key": "k",
    },
    "max_tokens": 4096,
    "max_tokens_by_skill": {"risk_analysis": 8192},
}


def _import_with(cfg: dict):
    """以指定 config 匯入 agent_runner，回傳 (module, fake_openai_module)。"""
    runtime_path = str(REPO / "runtime")
    if runtime_path not in sys.path:
        sys.path.insert(0, runtime_path)
    sys.modules.pop("agent_runner", None)
    fake_openai = mock.MagicMock()
    real_read_text = Path.read_text

    def fake_read_text(self, *a, **kw):
        if self.name == "config.json":
            return json.dumps(cfg)
        return real_read_text(self, *a, **kw)

    with mock.patch.dict("sys.modules", {"openai": fake_openai, "anthropic": mock.MagicMock()}), \
            mock.patch.object(Path, "read_text", fake_read_text):
        mod = importlib.import_module("agent_runner")
    return mod, fake_openai


@pytest.fixture
def azure_runner():
    mod, fake_openai = _import_with(_AZURE_CFG)
    yield mod, fake_openai
    sys.modules.pop("agent_runner", None)


def _resp(text, usage=None):
    r = mock.MagicMock()
    r.output_text = text
    r.usage = usage
    return r


def test_client_built_with_endpoint_and_timeout(azure_runner):
    mod, fake_openai = azure_runner
    fake_openai.OpenAI.assert_called_once_with(
        api_key="k", base_url="https://x/openai/v1", timeout=300)
    assert mod._model == "gpt-5.5"


def test_responses_create_args_and_defaults(azure_runner, tmp_path):
    mod, _ = azure_runner
    mod.client.responses.create.return_value = _resp('```json\n{"a": 1}\n```')
    with mock.patch.object(mod, "_save_context"):
        out = mod.run_agent("analyst_agent", "financial_analysis", {"x": "y"})
    assert out == {"a": 1}
    kw = mod.client.responses.create.call_args.kwargs
    assert kw["model"] == "gpt-5.5"
    assert kw["max_output_tokens"] == 16384
    assert kw["reasoning"] == {"effort": "medium"}
    assert "max_tokens" not in kw
    assert kw["input"].startswith("[INPUT]")
    assert "[SKILL]" in kw["instructions"]


def test_azure_overrides_from_config():
    cfg = json.loads(json.dumps(_AZURE_CFG))
    cfg["azure"].update({"max_output_tokens": 2048, "reasoning_effort": "low", "chat_timeout": 30})
    mod, fake_openai = _import_with(cfg)
    try:
        assert fake_openai.OpenAI.call_args.kwargs["timeout"] == 30
        mod.client.responses.create.return_value = _resp("{}")
        with mock.patch.object(mod, "_save_context"):
            mod.run_agent("analyst_agent", "financial_analysis", {})
        kw = mod.client.responses.create.call_args.kwargs
        assert kw["max_output_tokens"] == 2048
        assert kw["reasoning"] == {"effort": "low"}
    finally:
        sys.modules.pop("agent_runner", None)


def test_usage_missing_does_not_raise(azure_runner):
    mod, _ = azure_runner
    mod.client.responses.create.return_value = _resp("{}", usage=None)
    captured = {}
    with mock.patch.object(mod, "_save_context",
                           side_effect=lambda label, s, u, raw, usage, ver: captured.update(usage=usage)):
        out = mod.run_agent("analyst_agent", "financial_analysis", {})
    assert out == {}
    assert captured["usage"].input_tokens == 0
    assert captured["usage"].output_tokens == 0


def test_usage_forwarded(azure_runner):
    mod, _ = azure_runner
    u = mock.MagicMock(); u.input_tokens = 12; u.output_tokens = 34
    mod.client.responses.create.return_value = _resp("{}", usage=u)
    captured = {}
    with mock.patch.object(mod, "_save_context",
                           side_effect=lambda label, s, usr, raw, usage, ver: captured.update(usage=usage)):
        mod.run_agent("analyst_agent", "financial_analysis", {})
    assert (captured["usage"].input_tokens, captured["usage"].output_tokens) == (12, 34)
