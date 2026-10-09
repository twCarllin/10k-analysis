"""fh_notes 多銀行逾放比測試（Spec 2026-10-09-tw-equity-fh-schema §4.2 末段、F8；fixture fh_notes_pages.json）。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.fh_notes import extract_fh_notes

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity" / "fh_notes_pages.json"
_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _doc(ticker: str):
    return pdf_doc.from_json(copy.deepcopy(_DATA[ticker]["doc"]))


def _by_entity(npl):
    return {e["entity"]: {p["period"]: (p["npl_ratio"], p["coverage_ratio"]) for p in e["periods"]} for e in npl["entities"]}


def test_2887_main_is_largest_loans_bank_with_prior():
    npl = extract_fh_notes(_doc("2887")).npl
    assert npl["entity"] == "台新銀行"
    got = {p["period"]: (p["npl_ratio"], p["coverage_ratio"]) for p in npl["periods"]}
    assert got == {"115-06-30": (0.13, 922.63), "114-06-30": (0.14, 921.53)}
    assert npl["periods"][0]["total_loans"] == 2018299557.0


def test_2887_entities_include_both_banks_new_light_without_prior():
    ents = _by_entity(extract_fh_notes(_doc("2887")).npl)
    assert set(ents) == {"台新銀行", "臺灣新光商銀"}
    assert ents["臺灣新光商銀"] == {"115-06-30": (0.13, 997.97)}
    assert "114-06-30" in ents["台新銀行"]


def test_single_bank_entities_is_single_item():
    npl = extract_fh_notes(pdf_doc.from_json(_DATA["2881"]["doc"])).npl
    assert len(npl["entities"]) == 1
    assert npl["entities"][0]["periods"] == npl["periods"]


def test_equal_total_loans_first_appearing_wins_deterministic():
    doc = _doc("2887")
    for pg in doc.pages:
        if pg.number == 259:
            pg.lines = [ln.replace("$943,395,001", "$2,018,299,557") for ln in pg.lines]
    first = extract_fh_notes(doc).npl
    second = extract_fh_notes(doc).npl
    assert first == second
    assert first["entity"] == "台新銀行"
    assert first["periods"][0]["total_loans"] == 2018299557.0


def _append_lines(doc, number, lines):
    for pg in doc.pages:
        if pg.number == number:
            pg.lines = pg.lines + lines


def test_heading_after_table_on_same_page_does_not_relabel_table():
    doc = _doc("2887")
    _append_lines(doc, 242, ["(2) 臺灣新光商銀"])   # 同頁、表之後的標題
    npl = extract_fh_notes(doc).npl
    assert npl["entity"] == "台新銀行"
    ents = _by_entity(npl)
    assert set(ents) == {"台新銀行", "臺灣新光商銀"}
    assert ents["台新銀行"]["115-06-30"] == (0.13, 922.63)


def test_bank_heading_on_non_quality_page_does_not_change_entity():
    doc = _doc("2887")
    for pg in doc.pages:
        if pg.number == 240:   # 非資產品質頁：頁尾（非小節起始）追加另一銀行標題
            pg.lines = pg.lines + ["(2) 臺灣新光商銀"]
    npl = extract_fh_notes(doc).npl
    ents = _by_entity(npl)
    assert npl["entity"] == "台新銀行"
    assert ents["台新銀行"]["115-06-30"] == (0.13, 922.63)
    assert ents["臺灣新光商銀"]["115-06-30"] == (0.13, 997.97)
