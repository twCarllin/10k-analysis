"""make_ar_sections_fixture.py — 從 10 家年報抽三章節（現金流量、重要契約、特別記載事項）所在頁，序列化為 ar_sections_pages.json。

執行方式：
    ./.venv/bin/python tests/fixtures/tw_equity/make_ar_sections_fixture.py

輸出：tests/fixtures/tw_equity/ar_sections_pages.json（進版控）＝ {ticker: pdf_doc.to_json(只含所選頁的 PdfDoc)}
來源：tw_equity_inputs/<ticker>.json 的 annual_report_path（不進版控），經 pdf_doc.load_pdf 快取讀取。
所選頁：目錄頁 1–8 ＋ 金標（ar_sections_gold_expected.json）三章節的 pages 前後各 1 頁。

SSOT 原則：fixture 格式由 pdf_doc.to_json 決定，本腳本不自寫 JSON 形狀。
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from runtime.tw_equity.inputs import load_inputs  # noqa: E402

_HERE = Path(__file__).resolve().parent
_GOLD_PATH = _HERE / "ar_sections_gold_expected.json"
_OUT_PATH = _HERE / "ar_sections_pages.json"

_TOC_PAGES = range(1, 9)
_SECTIONS = ("cashflow", "contracts", "special")


def selected_pages(gold_entry: dict) -> list[int]:
    """目錄頁 1–8 ＋ 三章節 pages 前後各 1 頁（排序、去重）。"""
    pages = set(_TOC_PAGES)
    for sec in _SECTIONS:
        for n in gold_entry[sec].get("pages") or []:
            pages.update((n - 1, n, n + 1))
    return sorted(p for p in pages if p >= 1)


def extract_pages(doc: _pdf_doc.PdfDoc, page_numbers: list[int]) -> _pdf_doc.PdfDoc:
    """回傳只含 page_numbers 的 PdfDoc；garbled／ocr／image 頁清單同步裁切。"""
    keep = set(page_numbers)
    return replace(
        doc,
        pages=[p for p in doc.pages if p.number in keep],
        garbled_pages=[n for n in doc.garbled_pages if n in keep],
        ocr_pages=[n for n in doc.ocr_pages if n in keep],
        image_pages=[n for n in doc.image_pages if n in keep],
    )


def produce(out_path: Path = _OUT_PATH) -> dict:
    gold = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    out: dict = {}
    for ticker, entry in gold.items():
        doc = _pdf_doc.load_pdf(load_inputs(ticker).annual_report_path)
        out[ticker] = _pdf_doc.to_json(extract_pages(doc, selected_pages(entry)))
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    data = produce()
    for t, d in data.items():
        print(t, len(d["pages"]), "pages")
