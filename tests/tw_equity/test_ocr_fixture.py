"""Mistral OCR 真實回應 fixture 驗證（只讀 fixture，不打 API）。"""
import json
from pathlib import Path

import pytest

from runtime.tw_equity.ocr_adapters import _load_azure_config
from runtime.tw_equity.ocr import markdown_to_page
from runtime.tw_equity.tables import parse_top_shareholders

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity" / "mistral_3653_2024_p51_p79.json"


@pytest.fixture(scope="module")
def pages():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {int(k): markdown_to_page(int(k), v) for k, v in d["pages"].items()}


def test_page_set_and_lines_nonempty(pages):
    assert set(pages) == {51, 79}
    assert all(p.lines for p in pages.values())


def test_p51_top_shareholders_parse(pages):
    r = parse_top_shareholders(pages[51].tables, pages[51].text)
    assert r is not None
    assert sum(1 for s in r.rows if not s.is_representative) >= 10


def test_p79_has_chapter_heading(pages):
    assert any("財務狀況及財務績效之檢討分析" in ln for ln in pages[79].lines)


def test_fixture_has_no_secrets():
    text = FIXTURE.read_text(encoding="utf-8")
    try:
        cfg = _load_azure_config()
    except FileNotFoundError:
        pytest.skip("無 config.json，略過憑證比對")
    host = cfg.get("mistral_ocr_endpoint", "").split("//")[-1].split("/")[0]
    key = cfg.get("mistral_ocr_key", "")
    assert key and host, "config.json 缺 mistral_ocr_key／mistral_ocr_endpoint"
    assert key not in text
    assert host not in text
