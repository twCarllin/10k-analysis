"""3653 正確性錨離線整合（Spec 2026-10-09-tw-equity-period-model §0.3／§4；item 2.4）。

fixture（唯一副本，皆由既有 producer 產出）：
  - tests/fixtures/tw_equity/ar_3653_pages.json：依據 make_ar_fixture.py，來源 tw_report/2025_3653_健策年報.pdf（含第 93 頁）
  - tests/fixtures/tw_equity/fs_3653_pages.json：依據 make_fs_fixture.py，來源 tw_report/3653_2025Q4合併財報.pdf
契約 row：3653 的 revenue／cogs／gross_profit／operating_income／pretax_income／income_tax／net_income
與帳本 current（經 normalize_sign）逐項相等，容差 0。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import (
    FS_HEADING_ANCHORS,
    find_annual_report_sections,
    find_heading_sections,
)
from runtime.tw_equity.fy_acceptance import ANCHOR_KEYS, anchor_compare
from runtime.tw_equity.fy_income import extract_fy_income
from runtime.tw_equity.pdf_doc import Page, PdfDoc, from_json
from runtime.tw_equity.statements import extract_statements

_FIXDIR = Path(__file__).parent.parent / "fixtures" / "tw_equity"

# 3653 FY 損益（仟元，正規化後：收入為正、費用為負）；依據 ar_3653_pages.json 第 93 頁
_EXPECTED = {
    "revenue": 20275577,
    "cogs": -11841587,
    "gross_profit": 8433990,
    "operating_income": 6498133,
    "pretax_income": 6606955,
    "income_tax": -1296613,
    "net_income": 5310342,
}


def _load(name: str) -> PdfDoc:
    return from_json(json.loads((_FIXDIR / name).read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ar_doc() -> PdfDoc:
    return _load("ar_3653_pages.json")


@pytest.fixture(scope="module")
def fy(ar_doc):
    anchors = find_annual_report_sections(ar_doc, required=set())
    return extract_fy_income(ar_doc, anchors, roc_year=114)


@pytest.fixture(scope="module")
def ledger():
    doc = _load("fs_3653_pages.json")
    return extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))


def test_3653_anchor_seven_items_equal(fy, ledger):
    assert fy is not None and fy.page == 93
    result = anchor_compare(fy, ledger)
    assert tuple(result["items"]) == ANCHOR_KEYS
    for key, it in result["items"].items():
        assert it["equal"] is True, (key, it)
    assert result["all_equal"] is True


def test_3653_normalized_values_absolute(fy):
    from runtime.tw_equity.fy_income import normalize_sign

    for key, expected in _EXPECTED.items():
        row = next(r for r in fy.rows if r["key"] == key)
        assert normalize_sign(key, row["label"], row["current"]) == expected, key
    assert fy.usable is True


def test_multi_candidate_picks_larger_page_on_tie(ar_doc):
    # 同一頁文字複製到較小頁碼：key 數相同 → 取頁碼大者（Spec §2.2.2 ③）
    p93 = next(p for p in ar_doc.pages if p.number == 93)
    doc = PdfDoc(
        path=ar_doc.path,
        pages=[Page(number=10, text="", tables=[], lines=list(p93.lines)), p93],
    )
    fy = extract_fy_income(doc, None, roc_year=114)
    assert fy.page == 93


def test_normalized_income_tax_uses_same_page_cogs_sign():
    # cogs 原值為正（表內費用以正數表示）且稅為負（稅利益）→ 正值；與勾稽共用同一入口
    from runtime.tw_equity.fy_income import FyIncome

    rows = [
        {"label": "營業成本", "key": "cogs", "current": 600, "prior": 500},
        {"label": "所得稅費用", "key": "income_tax", "current": -40, "prior": 50},
    ]
    fy = FyIncome(114, 1, "仟元", 1.0, "consolidated", rows)
    assert fy.normalized("income_tax", "current") == 40
    assert fy.normalized("income_tax", "prior") == -50
    assert fy.normalized("cogs", "current") == -600
    assert fy.normalized("revenue", "current") is None


def test_3653_anchor_via_shared_normalized(fy, ledger):
    assert fy.normalized("income_tax", "current") == _EXPECTED["income_tax"]
    result = anchor_compare(fy, ledger)
    assert result["all_equal"] is True
    for key, it in result["items"].items():
        assert it["fy"] == fy.normalized(key, "current") == _EXPECTED[key], key
