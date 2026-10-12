"""ar_acceptance 驗收工具的純邏輯測試（run 2026-10-12-tw-equity-ar-sections item 2.2）。

契約 row（item 2.2 DoD）：
  A1: SUMMARY 統計：三章節通過家數（cf／ct 為 parsed＋none；sp 4 項全部不是 not_found）、basis 三類家數、
      arith_ok 非 True 的家數；SUMMARY 行含這些數字；error 的家不計入通過與 basis 類別
  A2: 每家輸出行含 3 章節 status、arith_ok、basis、契約列數、特別記載 4 項 status
  A3: 金標比對：數字完全相等；文字 NFKC＋去空白；特別記載 text 以金標為前綴；不符輸出欄位路徑
  A4: Spec §2.6 已知不符標示 known（欄位路徑前綴整段相符）；其他不符 known=False
不在測試中跑 101 家（全量由主 flow 跑）。
"""

import copy
import json
from pathlib import Path

import pytest

from runtime.tw_equity.ar_acceptance import (
    GOLD_PATH,
    company_line,
    compare_gold,
    gold_summary_line,
    is_known,
    summarize,
    summary_line,
)

# ── builder（單一出處）──────────────────────────────────────────────────────

_SP_KEYS = ("affiliates", "private_placement", "other_supplement", "material_events_36")


def _rec(ticker="1111", cf="parsed", arith=True, basis="consolidated", ct="parsed", rows=3, sp_items=None, sp="parsed"):
    items = sp_items if sp_items is not None else {k: "none" for k in _SP_KEYS}
    return {"ticker": ticker, "group": "industrial",
            "cf": {"status": cf, "arith_ok": arith, "basis": basis, "basis_note": None},
            "ct": {"status": ct, "rows": rows}, "sp": {"status": sp, "items": items}}


def _gold() -> dict:
    return {
        "cashflow": {
            "status": "parsed", "pages": [10], "basis_label": "3.1 合併財務報表", "statement_basis_from_text": "consolidated",
            "actual": {"page": 10, "opening_cash": 1000, "cfo": 500, "cfi": -200, "cff": None, "cfi_cff": None,
                       "outflow": None, "fx": 0, "closing_cash": 1300, "remedy_invest": "無", "remedy_finance": "無"},
            "actual_explanations": {"operating": "營業活動：現金流入", "investing": "投資活動：購置設備", "financing": None},
            "forecast": {"applicable": True, "page": 10, "opening_cash": 1300, "cfo": 600, "cfi": None, "cff": None,
                         "cfi_cff": -100, "outflow": None, "fx": None, "closing_cash": 1800,
                         "remedy_invest": "無", "remedy_finance": "無"},
            "forecast_explanations": {"operating": "營業活動：預計穩定", "investing": None, "financing": None},
        },
        "contracts": {"status": "parsed", "pages": [20], "rows": [
            {"page": 20, "entity": None, "nature": "工程契約", "parties": ["甲公司", "乙公司"], "period": "112.9.25",
             "content": "廠房 興建", "restrictions": "無"}]},
        "special": {"status": "parsed", "pages": [30], "chapter_heading": "陸、特別記載事項", "items": {
            "affiliates": {"status": "see_mops", "page": 30, "text": "請參閱公開資訊觀測站"},
            "private_placement": {"status": "none", "page": 30, "text": "無。"},
            "other_supplement": {"status": "none", "page": 30, "text": "無。"},
            "material_events_36": {"status": "none", "page": 30, "text": "無。"}}},
    }


def _sections(gold: dict | None = None) -> dict:
    """與金標完全相符的章節 dict（金標欄位 ＋ 解析器多出的欄位）。"""
    s = copy.deepcopy(gold or _gold())
    s["cashflow"]["basis"] = "consolidated"
    return s


def _fields(ms: list[dict]) -> list[str]:
    return [m["field"] for m in ms]


# ── A1 SUMMARY ──────────────────────────────────────────────────────────────


def test_summarize_counts():
    recs = [
        _rec("1", cf="parsed", arith=True, basis="consolidated"),
        _rec("2", cf="none", arith=None, basis="unknown", ct="none", rows=0),
        _rec("3", cf="failed", arith=None, basis="unknown", ct="failed", rows=0),
        _rec("4", cf="parsed", arith=False, basis="non_consolidated", ct="not_found", rows=0,
             sp_items={**{k: "none" for k in _SP_KEYS}, "private_placement": "not_found"}),
        _rec("5", cf="not_found", arith=None, basis="unknown", sp="not_found",
             sp_items={k: "not_found" for k in _SP_KEYS}),
        {"ticker": "6", "error": "FileNotFoundError: x"},
    ]
    s = summarize(recs)
    assert s["total"] == 6
    assert s["cf_ok"] == 3          # 1 parsed、2 none、4 parsed（3 failed、5 not_found 不計；error 不計）
    assert s["ct_ok"] == 3          # 1 parsed、2 none、5 parsed（3 failed、4 not_found 不計；error 不計）
    assert s["sp_ok"] == 3          # 1、2、3 的 4 項都不是 not_found；4 有 1 項 not_found、5 全 not_found
    assert (s["basis_consolidated"], s["basis_non_consolidated"], s["basis_unknown"]) == (1, 1, 3)
    assert s["arith_not_true"] == 4  # 2、3、5 是 None，4 是 False；error 不計
    assert s["errors"] == 1


def test_summarize_sp_requires_four_items():
    """特別記載缺項目 key（不足 4 項）不算通過。"""
    assert summarize([_rec(sp_items={"affiliates": "none"})])["sp_ok"] == 0
    assert summarize([_rec()])["sp_ok"] == 1


def test_summary_line_contains_counts():
    recs = [_rec("1"), _rec("2", basis="non_consolidated", arith=False)]
    line = summary_line(summarize(recs))
    assert line.startswith("SUMMARY ")
    for frag in ("total=2", "cf_ok=2/2", "ct_ok=2/2", "sp_ok=2/2", "basis_consolidated=1",
                 "basis_non_consolidated=1", "basis_unknown=0", "arith_not_true=1"):
        assert frag in line
    assert "\n" not in line


# ── A2 每家輸出行 ───────────────────────────────────────────────────────────


def test_company_line_has_all_fields():
    items = {"affiliates": "see_mops", "private_placement": "none", "other_supplement": "disclosed",
             "material_events_36": "not_found"}
    line = company_line(_rec("3653", cf="parsed", arith=True, basis="non_consolidated", ct="parsed", rows=7,
                             sp_items=items))
    assert line.startswith("3653")
    for frag in ("cf=parsed", "arith_ok=True", "basis=non_consolidated", "ct=parsed", "rows=7", "sp=parsed",
                 "affiliates=see_mops", "private_placement=none", "other_supplement=disclosed",
                 "material_events_36=not_found"):
        assert frag in line
    err = company_line({"ticker": "9999", "error": "ValueError: x"})
    assert err.startswith("9999") and "ERROR" in err


# ── A3 金標比對 ─────────────────────────────────────────────────────────────


def test_gold_exact_match_has_no_mismatch():
    assert compare_gold("1111", _sections(), _gold()) == []


def test_gold_text_normalized_nfkc_and_whitespace():
    """文字欄：兩邊 NFKC＋去空白後相等即符合（全形數字、空白、CJK 相容字）。"""
    s = _sections()
    s["contracts"]["rows"][0]["content"] = "廠房興建"           # 金標「廠房 興建」：去空白後相等
    s["contracts"]["rows"][0]["period"] = "１１２.９.２５"       # 全形數字 NFKC 後相等
    s["cashflow"]["actual"]["remedy_invest"] = " 無 "
    assert compare_gold("1111", s, _gold()) == []


def test_gold_numbers_must_be_exactly_equal():
    s = _sections()
    s["cashflow"]["actual"]["cfo"] = 501
    s["cashflow"]["forecast"]["closing_cash"] = None
    ms = compare_gold("1111", s, _gold())
    assert _fields(ms) == ["cashflow.actual.cfo", "cashflow.forecast.closing_cash"]
    assert ms[0]["got"] == 501 and ms[0]["expected"] == 500 and ms[0]["known"] is False


def test_gold_reports_text_and_structure_mismatches():
    s = _sections()
    s["cashflow"]["actual_explanations"]["operating"] = "別的文字"
    s["contracts"]["rows"][0]["parties"] = ["甲公司"]
    s["special"]["items"]["affiliates"]["status"] = "disclosed"
    s["special"]["items"]["private_placement"]["text"] = "不同。"
    s["special"]["chapter_heading"] = None
    got = set(_fields(compare_gold("1111", s, _gold())))
    assert got == {"cashflow.actual_explanations.operating", "contracts.rows.0.parties",
                   "special.items.affiliates.status", "special.items.private_placement.text",
                   "special.chapter_heading"}


def test_gold_special_text_prefix_rule():
    """金標 text 是解析 text 的前綴 → 符合（解析 text 較長不算不符）；反過來解析 text 較短 → 不符。"""
    s = _sections()
    s["special"]["items"]["affiliates"]["text"] = "請參閱公開資訊觀測站，查閱路徑如下"
    assert compare_gold("1111", s, _gold()) == []
    s["special"]["items"]["affiliates"]["text"] = "請參閱"
    assert _fields(compare_gold("1111", s, _gold())) == ["special.items.affiliates.text"]
    s["special"]["items"]["affiliates"]["text"] = None  # 缺值不當作符合
    assert _fields(compare_gold("1111", s, _gold())) == ["special.items.affiliates.text"]


def test_gold_contract_row_count_mismatch():
    s = _sections()
    s["contracts"]["rows"] = []
    assert "contracts.rows.count" in _fields(compare_gold("1111", s, _gold()))


def test_gold_no_table_a_matches_all_null_gold():
    """金標表 A 全 null（無表 A）↔ 解析 actual=None 視為相符。"""
    g = _gold()
    g["cashflow"]["actual"] = {k: None for k in g["cashflow"]["actual"]}
    s = _sections(g)
    s["cashflow"]["actual"] = None
    assert compare_gold("1111", s, g) == []


@pytest.mark.parametrize("stmt,got,ok", [
    ("consolidated", "consolidated", True), ("consolidated", "non_consolidated", False),
    ("consolidated", "unknown", False), ("parent", "non_consolidated", True), ("parent", "consolidated", False),
    ("unstated", "non_consolidated", True), ("unstated", "consolidated", True),
])
def test_gold_basis_checked_against_statement_basis(stmt, got, ok):
    """金標 statement_basis_from_text 有表態（consolidated／parent）時，basis 須相符；unstated 不比對。"""
    g = _gold()
    g["cashflow"]["statement_basis_from_text"] = stmt
    s = _sections(g)
    s["cashflow"]["basis"] = got
    assert (compare_gold("1111", s, g) == []) is ok
    if not ok:  # testlint: allow — ok 分支已由上一行斷言；此行只補驗 not ok 時的不符欄位
        assert _fields(compare_gold("1111", s, g)) == ["cashflow.basis"]


# ── A4 已知不符 ─────────────────────────────────────────────────────────────


def test_known_mismatches_flagged_by_ticker_and_field_prefix():
    assert is_known("2412", "contracts.rows.0.nature") and is_known("2412", "contracts.status")
    assert is_known("2412", "cashflow.actual_explanations.operating")
    assert is_known("2412", "special.items.private_placement.text")
    assert is_known("2330", "special.items.affiliates.text") and is_known("2330", "special.pages")
    assert is_known("2603", "special.chapter_heading")
    # 不在已知清單
    assert not is_known("2412", "cashflow.actual.cfo")
    assert not is_known("2412", "special.items.affiliates.status")
    assert not is_known("2330", "special.items.affiliates.status")
    assert not is_known("2603", "special.pages")
    assert not is_known("1111", "contracts.status")
    assert not is_known("2412", "contractsX.status")  # 前綴須整段相符


def test_compare_gold_marks_known_flag():
    s = _sections()
    s["contracts"]["status"] = "failed"
    s["contracts"]["rows"] = []
    s["cashflow"]["actual"]["cfo"] = 1
    ms = compare_gold("2412", s, _gold())
    by = {m["field"]: m["known"] for m in ms}
    assert by["contracts.status"] is True and by["contracts.rows.count"] is True
    assert by["cashflow.actual.cfo"] is False
    assert gold_summary_line(ms, 10) == "GOLD tickers=10 mismatches=3 known=2 unexpected=1"
    assert all(m["known"] is False for m in compare_gold("1111", s, _gold()))


# ── 金標檔結構（producer 側：compare_gold 讀的欄位金標都有）─────────────────────


@pytest.mark.skipif(not GOLD_PATH.exists(), reason="金標 fixture 不存在")
def test_real_gold_file_has_fields_compare_gold_reads():
    gold = json.loads(Path(GOLD_PATH).read_text(encoding="utf-8"))
    assert len(gold) == 10
    for t, g in gold.items():
        # 以「空章節」比對不拋例外（金標欄位齊全），且必有不符（金標都有內容）
        ms = compare_gold(t, {"cashflow": {}, "contracts": {}, "special": {}}, g)
        assert ms, t
