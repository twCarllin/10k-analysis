"""test_extract_tables_1b1.py — extract_tables 1B-1 擴充（item 4.2，Spec §2.3.5）。

契約 row：
  E1: 真實 fs＋ar fixture＋gov_anchors → T4／T5／合併關鍵列非 None、guarantees_loans 3 列、pledges.status=="rows"、top_shareholders 非 None
  E2: 1A 合成 fixture（lines==[]）→ 列通道回 None、退回 table 通道，結果同 1A
  E3: gov_anchors=None → pledges／top_shareholders 為 None、missing 含 T10_pledge、T10_top10
  E4: pledges.status=="unknown" → missing 含 T10_pledge
  E5: [邊界] 財報缺檔 → missing 含 T9、不 raise
  E6: [組合] gov_anchors=None 且財報缺檔 → 兩組缺表名稱同時出現
  另：TablesBundle 新欄位預設 None、to_dict 含三欄
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import (
    ANNUAL_REPORT_ANCHORS,
    FS_HEADING_ANCHORS,
    GOVERNANCE_HEADING_ANCHORS,
    PageRange,
    find_heading_sections,
    find_sections,
)
from runtime.tw_equity.pdf_doc import Page, PdfDoc, from_json
from runtime.tw_equity.tables import TablesBundle, extract_tables

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tw_equity"


def _load(name: str) -> PdfDoc:
    doc = from_json(json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


@pytest.fixture(scope="module")
def real() -> dict:
    ar = _load("ar_3653_pages.json")
    fs = _load("fs_3653_pages.json")
    ar_anchors = find_sections(
        ar, ANNUAL_REPORT_ANCHORS,
        required={"ar_customers", "ar_fin_position", "ar_fin_performance"},
        order=list(ANNUAL_REPORT_ANCHORS),
    )
    gov = find_heading_sections(ar, GOVERNANCE_HEADING_ANCHORS, required=set())
    fs_anchors = find_heading_sections(fs, FS_HEADING_ANCHORS, required={"fs_bs", "fs_is"})
    return {"ar": ar, "fs": fs, "ar_anchors": ar_anchors, "gov": gov, "fs_anchors": fs_anchors}


def _run(real: dict, *, gov: bool = True, with_fs: bool = True) -> TablesBundle:
    return extract_tables(
        real["ar"], real["ar_anchors"],
        real["fs"] if with_fs else None,
        real["fs_anchors"] if with_fs else None,
        None, None,
        roc_year=114,
        gov_anchors=real["gov"] if gov else None,
    )


def test_real_fixtures_populate_all_new_channels(real: dict) -> None:
    b = _run(real)
    assert b.expense_nature is not None
    assert b.inventory is not None
    assert b.consolidated_key_lines["營業成本"] == (11841587, 8912721)
    assert b.guarantees_loans is not None
    assert len(b.guarantees_loans.guarantees) == 3
    assert b.pledges is not None and b.pledges.status == "rows"
    assert b.top_shareholders is not None
    for name in ("T4", "T5", "T9", "T10_pledge", "T10_top10"):
        assert name not in b.missing_tables
    d = b.to_dict()
    assert d["guarantees_loans"] is not None
    assert d["pledges"]["status"] == "rows"
    assert d["top_shareholders"] is not None


def test_synthetic_fs_without_lines_falls_back_to_table_channel() -> None:
    fs = _load("fs_pages_synthetic.json")
    assert all(p.lines == [] for p in fs.pages)
    ar = _load("ar_3653_pages.json")
    ar_anchors = find_sections(
        ar, ANNUAL_REPORT_ANCHORS,
        required={"ar_customers", "ar_fin_position", "ar_fin_performance"},
        order=list(ANNUAL_REPORT_ANCHORS),
    )
    fs_anchors = find_sections(
        fs, {"fs_note_expense_nature": ["費用性質附註"], "fs_note_inventory": ["存貨附註"]},
        required=set(), order=["fs_note_expense_nature", "fs_note_inventory"],
    )
    b = extract_tables(ar, ar_anchors, fs, fs_anchors, None, None, roc_year=114)
    assert b.expense_nature is not None
    assert b.inventory is not None
    assert "T4" not in b.missing_tables and "T5" not in b.missing_tables


def test_gov_anchors_none_marks_t10_missing_and_fields_none(real: dict) -> None:
    b = _run(real, gov=False)
    assert b.pledges is None
    assert b.top_shareholders is None
    assert "T10_pledge" in b.missing_tables
    assert "T10_top10" in b.missing_tables
    d = b.to_dict()
    assert d["pledges"] is None and d["top_shareholders"] is None


def test_pledge_status_unknown_counts_as_missing(real: dict) -> None:
    blank = Page(number=1, text="無相關內容", tables=[])
    ar = PdfDoc(path=Path("x.pdf"), pages=[blank])
    gov = {"ar_pledge": PageRange(1, 1), "ar_top10": None}
    b = extract_tables(ar, {}, None, None, None, None, roc_year=114, gov_anchors=gov)
    assert b.pledges is not None and b.pledges.status == "unknown"
    assert "T10_pledge" in b.missing_tables


@pytest.mark.parametrize("gov", [True, False])
def test_fs_missing_marks_t9_no_raise(real: dict, gov: bool) -> None:
    """E5 邊界（gov=True）與 E6 組合（gov=False：兩組缺表名稱同時出現）。"""
    b = _run(real, gov=gov, with_fs=False)
    assert b.guarantees_loans is None
    assert "T9" in b.missing_tables
    if not gov:
        assert "T10_pledge" in b.missing_tables
        assert "T10_top10" in b.missing_tables
    else:
        assert "T10_pledge" not in b.missing_tables


def test_new_bundle_fields_default_none() -> None:
    b = TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None, customers_purchase=None,
        production_sales=None, expense_nature=None, inventory=None,
        cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=[], unit_notes={},
    )
    assert b.guarantees_loans is None and b.pledges is None and b.top_shareholders is None
    d = b.to_dict()
    assert d["guarantees_loans"] is None and d["pledges"] is None and d["top_shareholders"] is None
