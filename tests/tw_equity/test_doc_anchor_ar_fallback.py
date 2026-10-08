"""test_doc_anchor_ar_fallback.py — find_annual_report_sections 真實 fixture 測試（item 3.1，Spec §2.4）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import (
    ANNUAL_REPORT_ANCHORS,
    AnchorError,
    find_annual_report_sections,
    find_sections,
)
from runtime.tw_equity.ocr import markdown_to_page

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"
_AR_REQ = {"ar_letter", "ar_business", "ar_market"}


def _load(name: str):
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


def _doc_2024(with_ocr: bool):
    doc = _load("ar2024_3653_pages.json")
    if not with_ocr:
        return pdf_doc.apply_ocr_policy(doc, None)
    md = json.loads((_FIX / "mistral_3653_2024_p51_p79.json").read_text(encoding="utf-8"))["pages"]
    fake = {int(n): markdown_to_page(int(n), t) for n, t in md.items()}
    return pdf_doc.apply_ocr_policy(doc, lambda path, pages: fake)


def _starts(r):
    return {k: (v.start if v else None) for k, v in r.items()}


def test_2025_same_as_find_sections():
    doc = _load("ar_3653_pages.json")
    base = find_sections(doc, ANNUAL_REPORT_ANCHORS, required=set(),
                         order=list(ANNUAL_REPORT_ANCHORS))
    got = find_annual_report_sections(doc, required=set())
    assert got == base


def test_2024_no_ocr_market_start_68_and_end():
    got = find_annual_report_sections(_doc_2024(False), required=set())
    assert got["ar_market"] is not None and got["ar_market"].start == 68
    later = sorted(v.start for v in got.values() if v and v.start > 68)
    assert got["ar_market"].end == later[0] - 1


def test_2024_with_ocr_mdna_pages():
    got = _starts(find_annual_report_sections(_doc_2024(True), required=set()))
    assert got["ar_mdna"] == 79
    assert got["ar_fin_position"] == 79
    assert got["ar_fin_performance"] == 80


def test_required_missing_raises_listing_key():
    with pytest.raises(AnchorError) as e:
        find_annual_report_sections(_doc_2024(False), required={"ar_market", "ar_mdna"})
    assert "ar_mdna" in str(e.value)


def test_required_empty_returns_none_for_missing():
    got = find_annual_report_sections(_doc_2024(False), required=set())
    missing = [k for k, v in got.items() if v is None]
    assert len(missing) >= 2
    assert set(got) == set(ANNUAL_REPORT_ANCHORS)
