"""test_fh_anchors.py — 金控年報章名錨點（run 2026-10-09-tw-equity-fh-schema item 4.1，Spec §5／§0.4 F10）。

fixture：tests/fixtures/tw_equity/fh_ar_headings.json（6 家章名頁＋目錄頁，產生器 make_fh_anchor_fixture.py）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import find_annual_report_sections

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"

# (ar_business 起頁, ar_mdna 起頁, ar_fin_performance 起頁)：Spec §0.4 F10 章名起始頁／F9 財務績效節頁
_EXPECTED_STARTS = {
    "2881": (157, 240, 243),
    "2882": (159, 230, 231),
    "2885": (168, 264, 266),
    "2886": (62, 118, 120),
    "2887": (132, 240, 242),
    "2891": (95, 160, 160),
}
# F10 對應章的起訖頁（含）：(營運概況章, 財務狀況及財務績效檢討分析章)
_CHAPTERS = {
    "2881": ((157, 239), (240, 266)),
    "2882": ((159, 229), (230, 252)),
    "2885": ((168, 263), (264, 281)),
    "2886": ((62, 117), (118, 150)),
    "2887": ((130, 239), (240, 277)),
    "2891": ((95, 159), (160, 177)),
}
# 工業 3653 年報 fixture 在本 item 前（HEAD 12cadec）的 find_annual_report_sections 結果（起, 迄）
_INDUSTRIAL_3653_BEFORE = {
    "ar_letter": (5, 64), "ar_governance": None, "ar_business": (65, 75), "ar_market": (76, 81),
    "ar_customers": (82, 91), "ar_mdna": (92, 92), "ar_fin_position": (92, 92),
    "ar_fin_performance": (93, 93), "ar_cashflow": (94, 98), "ar_risk": (92, 98),
    "ar_special": (99, 99), "ar_production_sales": None,
}


def _fh_doc(ticker: str):
    raw = json.loads((_FIX / "fh_ar_headings.json").read_text(encoding="utf-8"))
    doc = pdf_doc.from_json(raw[ticker]["doc"])
    assert doc is not None
    return doc


def _sections(ticker: str, group: str | None = "fh"):
    return find_annual_report_sections(_fh_doc(ticker), required=set(), group=group)


@pytest.mark.parametrize("ticker", sorted(_EXPECTED_STARTS))
def test_six_fh_three_keys_found_with_expected_start(ticker):
    got = _sections(ticker)
    starts = tuple(
        got[k].start if got[k] else None
        for k in ("ar_business", "ar_mdna", "ar_fin_performance")
    )
    assert starts == _EXPECTED_STARTS[ticker]


@pytest.mark.parametrize("ticker", sorted(_CHAPTERS))
def test_six_fh_starts_inside_f10_chapters(ticker):
    got = _sections(ticker)
    (b_lo, b_hi), (m_lo, m_hi) = _CHAPTERS[ticker]
    assert b_lo <= got["ar_business"].start <= b_hi
    assert m_lo <= got["ar_mdna"].start <= m_hi
    assert m_lo <= got["ar_fin_performance"].start <= m_hi


def test_2881_arabic_numbered_chapters():
    got = _sections("2881")
    assert got["ar_business"].start == 157     # 4.1 本公司營運概況
    assert got["ar_mdna"].start == 240         # 5. 財務狀況及財務績效檢討分析與風險管理事項（無「之」）
    assert got["ar_fin_performance"].start == 243  # 5.2 財務績效


def test_2886_mdna_without_shi_xiang_found_despite_char_spacing():
    assert _sections("2886")["ar_mdna"].start == 118


def test_2882_roman_chapters():
    got = _sections("2882")
    assert got["ar_business"].start == 159
    assert got["ar_mdna"].start == 230


def test_2885_mdna_not_anchored_on_toc_page():
    got = _sections("2885")
    assert got["ar_mdna"].start == 264
    assert got["ar_fin_performance"].start == 266


@pytest.mark.parametrize("group", [None, "industrial"])
def test_industrial_3653_fixture_unchanged(group):
    doc = pdf_doc.from_json(json.loads((_FIX / "ar_3653_pages.json").read_text(encoding="utf-8")))
    got = find_annual_report_sections(doc, required=set(), group=group)
    now = {k: (v.start, v.end) if v else None for k, v in got.items()}
    assert now == _INDUSTRIAL_3653_BEFORE


@pytest.mark.parametrize("group", [None, "industrial"])
def test_non_fh_group_ignores_fh_keywords(group):
    # 2885 含「肆、 營運概況」章名頁（p168）：group=="fh" 才會被金控關鍵字錨到；其他一律走既有流程
    got = _sections("2885", group=group)
    fh = _sections("2885")
    assert got["ar_business"] is None
    assert fh["ar_business"].start == 168
    assert got["ar_mdna"] is None or got["ar_mdna"].start != fh["ar_mdna"].start  # 不鎖舊值，只要求與 fh 結果不同
