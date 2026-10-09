"""勾稽正負號正規化（fs-generalize item 2.1，Spec §3）。

契約 row：
  S1: revenue=1000, cogs=600（正）, gross_profit=400 → is_gross_profit True
  S2: cogs=-600 同樣 True
  S3: cogs=600, gross_profit=1600 → False
  S4: 2059 fixture IS 勾稽 is_gross_profit current／prior True
  S5: [邊界] 3653 年度 fixture 22 項全 True
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, PageRange, find_heading_sections  # noqa: E402
from runtime.tw_equity.statements import StatementRow, extract_statements, run_cross_checks  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"


def _gp_check(cogs: float, gross_profit: float):
    vals = {"revenue": 1000.0, "cogs": cogs, "gross_profit": gross_profit}
    rows = [
        StatementRow("is", None, k, k, None, v, v, None, None, 1, i)
        for i, (k, v) in enumerate(vals.items())
    ]
    return next(c for c in run_cross_checks(rows) if c.name == "is_gross_profit" and c.period == "current")


def test_positive_cogs_passes() -> None:
    assert _gp_check(600.0, 400.0).passed is True


def test_negative_cogs_passes() -> None:
    assert _gp_check(-600.0, 400.0).passed is True


def test_wrong_gross_profit_fails() -> None:
    assert _gp_check(600.0, 1600.0).passed is False


def test_2059_fixture_gross_profit_check_passes() -> None:
    entry = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))["2059"]
    doc = pdf_doc.from_json(entry["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
    led = extract_statements(doc, anchors)
    gp = [c for c in led.checks if c.name == "is_gross_profit"]
    assert [c.period for c in gp] == ["current", "prior"]
    assert all(c.passed is True for c in gp)


def test_3653_annual_all_22_checks_pass() -> None:
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))
    assert len(led.checks) == 22 and all(c.passed is True for c in led.checks)


# ── Task 3（Spec §8.1、§8.3.4）：所得稅符號、同日現金、毛利／營業利益候選、現金調節 ──────

import pytest  # noqa: E402


def _rows_of(items: list[tuple]) -> list[StatementRow]:
    """items：(statement, key, label, current, prior[, columns])。"""
    out = []
    for i, it in enumerate(items):
        st, key, label, cur, pri = it[:5]
        r = StatementRow(st, None, label, key, None, cur, pri, None, None, 1, i)
        r.columns = list(it[5]) if len(it) > 5 else [cur, pri]
        out.append(r)
    return out


def _check(rows, name, period="current", column_periods=None):
    return next(c for c in run_cross_checks(rows, column_periods) if c.name == name and c.period == period)


def _net(tax_label: str, tax: float, net: float):
    rows = _rows_of([
        ("is", "pretax_income", "稅前淨利", 100.0, 100.0),
        ("is", "income_tax", tax_label, tax, tax),
        ("is", "net_income", "本期淨利", net, net),
    ])
    return _check(rows, "is_net_income").passed


@pytest.mark.parametrize("label,tax,net,expected", [
    ("所得稅費用", -20.0, 80.0, True),
    ("所得稅費用", -20.0, 120.0, False),
    ("所得稅費用", 20.0, 80.0, True),
    ("所得稅(費用)利益", -20.0, 80.0, True),
    ("所得稅(費用)利益", -20.0, 120.0, False),
    ("所得稅(費用)利益", 20.0, 120.0, True),
    ("所得稅費用(利益)", 20.0, 80.0, True),
    ("所得稅費用(利益)", -20.0, 120.0, True),
])
def test_income_tax_sign_follows_label(label, tax, net, expected) -> None:
    assert _net(label, tax, net) is expected


def test_cf_ending_eq_bs_cash_prior_uses_same_day_bs_column() -> None:
    rows = _rows_of([
        ("bs", "cash", "現金及約當現金", 500.0, 400.0, [500.0, 400.0, 300.0]),
        ("cf", "cash_ending", "期末現金及約當現金餘額", 500.0, 300.0),
    ])
    cp = {
        "bs": ["115-06-30", "114-12-31", "114-06-30"],
        "cf": ["115-01-01~115-06-30", "114-01-01~114-06-30"],
    }
    assert _check(rows, "cf_ending_eq_bs_cash", "prior", cp).passed is True
    assert _check(rows, "cf_ending_eq_bs_cash", "prior", None).passed is False  # 無期間資訊 → 原 prior 欄


def test_gross_profit_and_operating_income_use_net_gross_and_other_operating() -> None:
    rows = _rows_of([
        ("is", "revenue", "銷貨", 90.0, 90.0),
        ("is", "revenue_total", "營業收入合計", 100.0, 100.0),
        ("is", "cogs", "營業成本", -60.0, -60.0),
        ("is", "gross_profit", "營業毛利", 40.0, 40.0),
        ("is", "gross_profit_net", "營業毛利淨額", 38.0, 38.0),
        ("is", "total_opex", "營業費用合計", -10.0, -10.0),
        ("is", "other_operating_net", "其他收益及費損淨額", 2.0, 2.0),
        ("is", "operating_income", "營業利益", 30.0, 30.0),
    ])
    assert _check(rows, "is_gross_profit").passed is True       # revenue_total − |cogs| = gross_profit
    assert _check(rows, "is_operating_income").passed is True   # 38 − 10 + 2 = 30


def test_operating_income_multiple_rows_last_wins() -> None:
    rows = _rows_of([
        ("is", "gross_profit", "營業毛利", 40.0, 40.0),
        ("is", "total_opex", "營業費用合計", -10.0, -10.0),
        ("is", "operating_income", "營業淨利", 30.0, 30.0),
        ("is", "other_operating_net", "其他收益及費損淨額", 5.0, 5.0),
        ("is", "operating_income", "營業利益", 35.0, 35.0),
    ])
    assert _check(rows, "is_operating_income").passed is True


def test_cash_reconciliation_row_preferred_for_cf_ending_check() -> None:
    base = [("bs", "cash", "現金及約當現金", 93096071.0, 0.0)]
    with_recon = _rows_of(base + [
        ("cf", "cash_ending", "期末現金及約當現金餘額", 93972534.0, 0.0),
        ("cf", "cash_per_bs_in_cf", "資產負債表帳列之現金及約當現金", 93096071.0, 0.0),
    ])
    assert _check(with_recon, "cf_ending_eq_bs_cash").passed is True
    without = _rows_of(base + [("cf", "cash_ending", "期末現金及約當現金餘額", 93972534.0, 0.0)])
    assert _check(without, "cf_ending_eq_bs_cash").passed is False


def test_duplicate_cash_ending_in_reconciliation_does_not_override_first() -> None:
    rows = _rows_of([
        ("bs", "cash", "現金及約當現金", 100.0, 0.0),
        ("cf", "cash_ending", "期末現金及約當現金餘額", 100.0, 0.0),
        ("cf", "cash_ending", "期末現金及約當現金餘額", 999.0, 0.0),
    ])
    assert _check(rows, "cf_ending_eq_bs_cash").passed is True
