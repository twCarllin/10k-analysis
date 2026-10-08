"""test_tables_integration.py — find_sections → extract_tables 跨真實年報＋合成財報整合測試（item 3.4）。

契約 row（§2.4）：
  I1: 真實 3653 年報 T7a/T7b 數字（營業收入、資產總額 diff_pct）
  I2: 真實 3653 p82 T8 銷貨客戶（A客戶、B客戶、others_pct、total）
  I3: 合成財報齊 → T1–T5 解析、missing_tables 只剩年報確實無的 T6
  I4: 缺財報檔 → T1–T5 進 missing_tables、不 raise
  I5: parent_cost_coverage＝個體營業成本／合併營業成本；缺個體 → None
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import ANNUAL_REPORT_ANCHORS, find_sections
from runtime.tw_equity.pdf_doc import PdfDoc, from_json
from runtime.tw_equity.tables import TablesBundle, extract_tables

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tw_equity"

# 合成財報頁標題無對應正式錨點關鍵字 → 測試內構造 anchors dict
_FS_TEST_ANCHORS = {
    "fs_note_expense_nature": ["費用性質附註"],
    "fs_note_inventory": ["存貨附註"],
}
_PS_TEST_ANCHORS = {
    "ps_is": ["個體損益表"],
    "ps_cogs_detail": ["個體損益表"],
    "ps_mfg_overhead": ["製造費用明細表"],
    "ps_opex_detail": ["營業費用明細表"],
}


def _load(name: str) -> PdfDoc:
    doc = from_json(json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


@pytest.fixture(scope="module")
def ar_doc() -> PdfDoc:
    return _load("ar_3653_pages.json")


@pytest.fixture(scope="module")
def ar_anchors(ar_doc: PdfDoc) -> dict:
    return find_sections(
        ar_doc,
        ANNUAL_REPORT_ANCHORS,
        required={"ar_customers", "ar_fin_position", "ar_fin_performance"},
        order=list(ANNUAL_REPORT_ANCHORS),
    )


@pytest.fixture(scope="module")
def fs_doc() -> PdfDoc:
    return _load("fs_pages_synthetic.json")


@pytest.fixture(scope="module")
def ps_doc() -> PdfDoc:
    return _load("ps_pages_synthetic.json")


@pytest.fixture(scope="module")
def fs_anchors(fs_doc: PdfDoc) -> dict:
    return find_sections(fs_doc, _FS_TEST_ANCHORS, required=set(), order=list(_FS_TEST_ANCHORS))


@pytest.fixture(scope="module")
def ps_anchors(ps_doc: PdfDoc) -> dict:
    return find_sections(ps_doc, _PS_TEST_ANCHORS, required=set(), order=list(_PS_TEST_ANCHORS))


@pytest.fixture(scope="module")
def full_bundle(ar_doc, ar_anchors, fs_doc, fs_anchors, ps_doc, ps_anchors) -> TablesBundle:
    return extract_tables(
        ar_doc, ar_anchors, fs_doc, fs_anchors, ps_doc, ps_anchors, roc_year=114
    )


@pytest.fixture(scope="module")
def ar_only_bundle(ar_doc, ar_anchors) -> TablesBundle:
    return extract_tables(ar_doc, ar_anchors, None, None, None, None, roc_year=114)


# ── I1: T7a / T7b 真實年報 ───────────────────────────────────────────────────


def test_t7b_revenue_real_values(full_bundle: TablesBundle) -> None:
    """I1: 營業收入 current/prior/diff_pct 為真實值。"""
    assert full_bundle.fin_performance is not None
    row = next(r for r in full_bundle.fin_performance.rows if r.label == "營業收入")
    assert row.current == 20275577
    assert row.prior == 14278187
    assert row.diff_pct == 42.00


def test_t7a_total_assets_diff_pct(full_bundle: TablesBundle) -> None:
    """I1: 資產總額 diff_pct=51.49。"""
    assert full_bundle.fin_position is not None
    row = next(r for r in full_bundle.fin_position.rows if "資產總" in r.label)
    assert row.diff_pct == 51.49


# ── I2: T8 真實年報 ──────────────────────────────────────────────────────────


def test_t8_sales_real_values(full_bundle: TablesBundle) -> None:
    """I2: p82 銷貨客戶 A客戶 114 年度、B客戶 113 年度、others_pct、total。"""
    cs = full_bundle.customers_sales
    assert cs is not None
    y114 = next(y for y in cs.years if "114" in y.label)
    y113 = next(y for y in cs.years if "113" in y.label)
    a = next(e for e in y114.entries if e.name == "A客戶")
    assert a.amount == 4627203
    assert a.pct == 22.82
    b = next(e for e in y113.entries if e.name == "B客戶")
    assert b.pct == 16.62
    assert y114.others_pct == 63.62
    assert y114.total == 20275577


def test_t8_purchase_real_values_from_p81(full_bundle: TablesBundle) -> None:
    """I2: 進貨表在 p81（ar_market 範圍）；114 年度甲廠商 amount=2158100、pct=24.93。"""
    cp = full_bundle.customers_purchase
    assert cp is not None
    y114 = next(y for y in cp.years if "114" in y.label)
    e = next(e for e in y114.entries if e.name == "甲廠商")
    assert e.amount == 2158100
    assert e.pct == 24.93


def test_t8_without_ar_market_anchor_still_uses_ar_customers(ar_doc, ar_anchors) -> None:
    """ar_market 為 None → T8 只從 ar_customers 取表（銷貨表仍解析；p81 進貨表不在範圍）。"""
    anchors = {**ar_anchors, "ar_market": None}
    b = extract_tables(ar_doc, anchors, None, None, None, None, roc_year=114)
    assert b.customers_sales is not None
    assert "T8_sales" not in b.missing_tables


# ── I3: 全流程齊（真實年報＋合成財報） ───────────────────────────────────────


def test_full_flow_fs_ps_tables_parsed(full_bundle: TablesBundle) -> None:
    """I3: T1–T5 皆由合成財報解析出來。"""
    assert full_bundle.expense_nature is not None
    assert full_bundle.inventory is not None
    assert full_bundle.cost_detail_cogs is not None
    assert full_bundle.cost_detail_mfg is not None
    assert full_bundle.cost_detail_opex is not None
    labels = [r.label for r in full_bundle.cost_detail_cogs.rows]
    assert "營業成本" in labels


def test_full_flow_missing_tables_only_ar_absent(full_bundle: TablesBundle) -> None:
    """I3: 年報確無的 T6 進 missing_tables；T1–T5、T7、T8（含 T8_purchase）不在。"""
    assert sorted(full_bundle.missing_tables) == ["T6"]


def test_full_flow_to_dict_roundtrips_json(full_bundle: TablesBundle) -> None:
    """I3: to_dict 可 JSON 序列化且 missing_tables 保留。"""
    d = json.loads(json.dumps(full_bundle.to_dict()))
    assert sorted(d["missing_tables"]) == ["T6"]


# ── I4: 缺財報檔 ─────────────────────────────────────────────────────────────


def test_missing_fs_ps_files_listed_no_raise(ar_only_bundle: TablesBundle) -> None:
    """I4: 缺 fs/ps → T1–T5 進 missing_tables，年報表仍解析。"""
    assert set(ar_only_bundle.missing_tables) == {
        "T1", "T2", "T3", "T4", "T5", "T6"
    }
    assert ar_only_bundle.fin_performance is not None
    assert ar_only_bundle.customers_sales is not None


def test_missing_only_ps_lists_only_t1_t2_t3(
    ar_doc, ar_anchors, fs_doc, fs_anchors
) -> None:
    """I4: 只缺 ps → 僅 T1–T3 額外進 missing_tables。"""
    b = extract_tables(ar_doc, ar_anchors, fs_doc, fs_anchors, None, None, roc_year=114)
    assert set(b.missing_tables) == {"T1", "T2", "T3", "T6"}


# ── I5: parent_cost_coverage ─────────────────────────────────────────────────


def test_parent_cost_coverage_value(full_bundle: TablesBundle) -> None:
    """I5: 個體營業成本 11,841,587／合併營業成本（ps 與年報同值）＝1.0。"""
    assert full_bundle.parent_cost_coverage == pytest.approx(1.0)


def test_parent_cost_coverage_none_when_ps_missing(ar_only_bundle: TablesBundle) -> None:
    """I5: 缺個體 → None。"""
    assert ar_only_bundle.parent_cost_coverage is None
