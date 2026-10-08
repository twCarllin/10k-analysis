"""test_ocr_checks.py — ocr_checks OCR 數字檢查（item 4.3，Spec §2.3b；含錨點補表）。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.cross_year import ocr_checks
from runtime.tw_equity.doc_anchor import (
    GOVERNANCE_HEADING_ANCHORS, PageRange, find_annual_report_sections, find_heading_sections,
)
from runtime.tw_equity.ocr import markdown_to_page
from runtime.tw_equity.pdf_doc import Page, PdfDoc
from runtime.tw_equity.tables import (
    ShareholderRow, TablesBundle, TopShareholders, TwoYearRow, TwoYearTable, extract_tables,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"
_ANCH = {"ar_fin_position": PageRange(79, 80), "ar_top10": PageRange(51, 51)}


def _bundle(**kw):
    base = {f.name: None for f in dataclasses.fields(TablesBundle)}
    base.update(consolidated_key_lines={}, parent_key_lines={}, missing_tables=[], unit_notes={})
    base.update(kw)
    return TablesBundle(**base)


def _doc(ocr_pages):
    return PdfDoc(Path("x.pdf"), [Page(79, "", [], [])], ocr_pages=list(ocr_pages))


def _t7a(*rows):
    return TwoYearTable("仟元", "114年度", "113年度",
                        [TwoYearRow(l, c, p, d, None) for l, c, p, d in rows])


def _top(*pcts):
    return TopShareholders([ShareholderRow(f"n{i}", False, None, p, None, None, None, None)
                            for i, p in enumerate(pcts)] +
                           [ShareholderRow("rep", True, None, 50.0, None, None, None, None)], [])


def test_t7a_row_off_by_more_than_1_fails():
    b = _bundle(fin_position=_t7a(("流動資產", 100, 60, 40), ("總資產", 200, 100, 105)))
    got = {r["label"]: r for r in ocr_checks(_doc([79]), b, _ANCH)}
    assert got["流動資產"]["passed"] is True and got["總資產"]["passed"] is False
    assert set(got["總資產"]) == {"check", "table", "label", "detail", "passed"}


def test_t7a_all_match_all_true():
    b = _bundle(fin_position=_t7a(("流動資產", 100, 60, 41), ("總資產", 200, 100, 100)))
    res = ocr_checks(_doc([79]), b, _ANCH)
    assert len(res) == 2 and all(r["passed"] is True for r in res)


def test_top10_sum_over_100_fails_and_100_passes():
    bad = ocr_checks(_doc([51]), _bundle(top_shareholders=_top(60.0, 41.5)), _ANCH)
    assert [r["passed"] for r in bad if r["table"] == "T10_top10"] == [False]
    ok = ocr_checks(_doc([51]), _bundle(top_shareholders=_top(60.0, 40.0)), _ANCH)
    assert [r["passed"] for r in ok if r["table"] == "T10_top10"] == [True]


def test_empty_ocr_pages_returns_empty():
    b = _bundle(fin_position=_t7a(("流動資產", 100, 60, 0)), top_shareholders=_top(200.0))
    assert ocr_checks(_doc([]), b, _ANCH) == []


def test_anchor_without_ocr_overlap_skips_that_table():
    b = _bundle(fin_position=_t7a(("總資產", 200, 100, 999)), top_shareholders=_top(200.0))
    only_79 = ocr_checks(_doc([79]), b, _ANCH)
    assert [r["table"] for r in only_79] == ["T7a"]
    only_51 = ocr_checks(_doc([51]), b, _ANCH)
    assert [r["table"] for r in only_51] == ["T10_top10"]
    assert ocr_checks(_doc([5]), b, _ANCH) == []
    assert ocr_checks(_doc([79]), b, {"ar_fin_position": None}) == []


def test_real_2024_fixture_with_mistral_ocr_all_passed():
    raw = pdf_doc.from_json(json.loads((_FIX / "ar2024_3653_pages.json").read_text(encoding="utf-8")))
    md = json.loads((_FIX / "mistral_3653_2024_p51_p79.json").read_text(encoding="utf-8"))["pages"]
    fake = {int(n): markdown_to_page(int(n), t) for n, t in md.items()}
    doc = pdf_doc.apply_ocr_policy(raw, lambda p, pg: fake)
    ar = find_annual_report_sections(doc, required=set())
    gov = find_heading_sections(doc, GOVERNANCE_HEADING_ANCHORS, required=set())
    bundle = extract_tables(doc, ar, None, None, None, None, roc_year=113, gov_anchors=gov)
    res = ocr_checks(doc, bundle, {**ar, **gov})
    assert {r["table"] for r in res} == {"T7a", "T10_top10"}
    assert all(r["passed"] is True for r in res)
