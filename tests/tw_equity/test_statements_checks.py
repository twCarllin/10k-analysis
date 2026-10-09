"""test_statements_checks.py — run_cross_checks 11 項勾稽（item 1.3，Spec §2.4）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity.statements import StatementRow, run_cross_checks

# Spec §2.4 表：name → (lhs keys, rhs keys)；順序即契約順序（單一出處）
SPEC = [
    ("bs_assets_eq_liab_equity", ["total_assets"], ["total_liabilities_and_equity"]),
    ("bs_assets_sum", ["total_current_assets", "total_noncurrent_assets"], ["total_assets"]),
    ("bs_liab_equity_sum", ["total_liabilities", "total_equity"], ["total_liabilities_and_equity"]),
    ("is_gross_profit", ["revenue", "cogs"], ["gross_profit"]),
    ("is_operating_income", ["gross_profit", "total_opex"], ["operating_income"]),
    ("is_pretax", ["operating_income", "nonoperating_total"], ["pretax_income"]),
    ("is_net_income", ["pretax_income", "income_tax"], ["net_income"]),
    ("cf_net_change", ["cfo", "cfi", "cff", "fx_effect"], ["net_change_in_cash"]),
    ("cf_ending", ["cash_beginning", "net_change_in_cash"], ["cash_ending"]),
    ("cf_ending_eq_bs_cash", ["cash_ending"], ["cash"]),
    ("cf_pretax_eq_is", ["pretax_income_cf"], ["pretax_income"]),
]


EXPENSE = {"cogs", "total_opex", "income_tax"}  # Spec §3 絕對值語義的減項


def _rows(vals: dict[str, tuple[float | None, float | None]]) -> list[StatementRow]:
    return [
        StatementRow("bs", None, k, k, None, c, p, None, None, 1, i)
        for i, (k, (c, p)) in enumerate(vals.items())
    ]


def _consistent(name: str) -> dict[str, tuple[float, float]]:
    """lhs 各項取 (10, 20)·序號，rhs 為其加總，保證相符。"""
    _, lk, rk = next(s for s in SPEC if s[0] == name)
    vals = {k: (10.0 * (i + 1), 20.0 * (i + 1)) for i, k in enumerate(lk)}
    # Spec §3：費用項（營業成本、營業費用、所得稅）在勾稽中為減項（絕對值語義）
    sgn = {k: -1 if k in EXPENSE else 1 for k in lk}
    vals[rk[0]] = (
        sum(sgn[k] * v[0] for k, v in vals.items() if k in sgn),
        sum(sgn[k] * v[1] for k, v in vals.items() if k in sgn),
    )
    return vals


def _get(checks, name, period):
    return next(c for c in checks if c.name == name and c.period == period)


def test_22_checks_in_spec_order() -> None:
    out = run_cross_checks([])
    assert [(c.name, c.period) for c in out] == [
        (n, p) for n, _, _ in SPEC for p in ("current", "prior")
    ]


@pytest.mark.parametrize("name", [s[0] for s in SPEC])
def test_pass_fail_none(name: str) -> None:
    _, lk, rk = next(s for s in SPEC if s[0] == name)
    ok = _consistent(name)
    c = _get(run_cross_checks(_rows(ok)), name, "current")
    assert c.passed is True
    assert c.lhs == c.rhs

    bad = dict(ok)
    rv = bad[rk[0]]
    bad[rk[0]] = (rv[0] + 100, rv[1])
    out = run_cross_checks(_rows(bad))
    assert _get(out, name, "current").passed is False
    assert _get(out, name, "prior").passed is True  # 期間獨立

    missing = {k: v for k, v in ok.items() if k != lk[0]}
    m = _get(run_cross_checks(_rows(missing)), name, "current")
    assert m.passed is None


def test_tolerance_boundary_and_partial_values() -> None:
    rows = _rows({"total_assets": (100, 90), "total_liabilities_and_equity": (100, 91)})
    out = run_cross_checks(rows)
    assert _get(out, "bs_assets_eq_liab_equity", "current").passed is True
    p = _get(out, "bs_assets_eq_liab_equity", "prior")
    assert (p.lhs, p.rhs, p.passed) == (90, 91, True)
    rows = _rows({"total_assets": (100, 90), "total_liabilities_and_equity": (100, 94)})
    assert _get(run_cross_checks(rows), "bs_assets_eq_liab_equity", "prior").passed is False


def test_gross_profit_example_and_missing_keeps_available_side() -> None:
    rows = _rows({"revenue": (100, None), "cogs": (-60, None), "gross_profit": (40, None)})
    out = run_cross_checks(rows)
    assert _get(out, "is_gross_profit", "current").passed is True
    assert _get(out, "is_gross_profit", "prior").passed is None
    out = run_cross_checks(_rows({"gross_profit": (40, 41)}))
    c = _get(out, "is_gross_profit", "current")
    assert (c.lhs, c.rhs, c.passed) == (None, 40, None)


def test_cf_net_change_and_ending_eq_bs_cash() -> None:
    rows = _rows({
        "cfo": (50, 5), "cfi": (-20, -2), "cff": (-10, -1), "fx_effect": (1, 0),
        "net_change_in_cash": (21, 2), "cash_ending": (500, 50), "cash": (500, 50),
    })
    out = run_cross_checks(rows)
    assert _get(out, "cf_net_change", "current").passed is True
    assert _get(out, "cf_ending_eq_bs_cash", "current").passed is True
