"""runtime/tw_equity/ocr_adapters.py 契約測試（run 2026-10-12-remove-tw-credit）。

MistralOCRAdapter 與 _load_azure_config 自已移除的徵信模組搬來；extract_pages 三例移自原
TestMistralOCRExtractPages，全走 _http_post 注入，不打真實 API。
"""
import json
from unittest.mock import MagicMock

import pytest
import requests

import runtime.tw_equity.ocr_adapters as adapters_mod
from runtime.tw_equity.ocr_adapters import AdapterError, MistralOCRAdapter, _load_azure_config


def _write_config(tmp_path, monkeypatch, data):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(adapters_mod, "CONFIG_PATH", cfg)


def _make_adapter(tmp_path, monkeypatch, fake_post):
    _write_config(tmp_path, monkeypatch, {"azure": {
        "mistral_ocr_endpoint": "https://fake.example.com",
        "mistral_ocr_key": "fake-key",
        "mistral_ocr_model": "mistral-ocr-4-0",
    }})
    return MistralOCRAdapter(_http_post=fake_post)


def _fake_post_with_pages(pages_markdown):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"pages": [{"markdown": m} for m in pages_markdown]}
    return MagicMock(return_value=resp)


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(b"%PDF-fake")
    return str(p)


def test_extract_pages_preserves_page_list_and_order(tmp_path, monkeypatch, pdf):
    fake_post = _fake_post_with_pages(["第一頁內容", "", "第三頁內容"])
    adapter = _make_adapter(tmp_path, monkeypatch, fake_post)
    assert adapter.extract_pages(pdf) == ["第一頁內容", "", "第三頁內容"]
    # URL＝config endpoint 原樣（完整 Azure 路由，不拼 /v1/ocr——2026-07-21 404 bugfix）
    assert fake_post.call_args.args[0] == "https://fake.example.com"
    assert fake_post.call_args.kwargs["headers"] == {"Authorization": "Bearer fake-key"}


def test_extract_text_delegates_and_joins(tmp_path, monkeypatch, pdf):
    adapter = _make_adapter(tmp_path, monkeypatch, _fake_post_with_pages(["頁A", "頁B"]))
    assert adapter.extract_text(pdf) == "頁A\n\n頁B"


def test_extract_pages_http_error_raises_adapter_error(tmp_path, monkeypatch, pdf):
    resp = MagicMock()
    resp.status_code = 500
    resp.reason = "Internal Server Error"
    adapter = _make_adapter(tmp_path, monkeypatch, MagicMock(return_value=resp))
    with pytest.raises(AdapterError) as exc:
        adapter.extract_pages(pdf)
    assert "fake.example.com" not in str(exc.value) and "fake-key" not in str(exc.value)


@pytest.mark.parametrize("error", [requests.exceptions.Timeout(), requests.exceptions.ConnectionError()])
def test_extract_pages_timeout_or_network_error_raises_adapter_error(tmp_path, monkeypatch, pdf, error):
    adapter = _make_adapter(tmp_path, monkeypatch, MagicMock(side_effect=error))
    with pytest.raises(AdapterError) as exc:
        adapter.extract_pages(pdf)
    assert "fake.example.com" not in str(exc.value) and "fake-key" not in str(exc.value)


def test_load_azure_config_returns_azure_block(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, {"azure": {"di_key": "k"}, "model": "m"})
    assert _load_azure_config() == {"di_key": "k"}


def test_load_azure_config_missing_block_returns_empty(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, {"model": "m"})
    assert _load_azure_config() == {}
