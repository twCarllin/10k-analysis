"""金控勾稽 run_cross_checks(schema="fh")（fh-schema Spec §2.4；task 1.3）。

契約 row（合成帳本）：
  C1: key 備齊且平衡 → 9 項 × current／prior 全 passed=True
  C2: interest_expense 印 -100 或 100 → 同樣 passed
  C3: 缺 insurance_other_cost 列 → is_pretax 仍可判定（以 0 計）
  C4: 缺必要列（net_revenue）→ 依賴它的項目 passed=None（不代 0）
  C5: [邊界] 無 non_interest_income 合計列、F4 各項加總相符 → is_net_revenue passed 且 parse_warnings 含代用句
  C6: [邊界] 同上但差 3 仟元 → passed=False
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity.fh_schema import FH_CHECK_SPECS  # noqa: E402
from runtime.tw_equity.statements import StatementRow, run_cross_checks  # noqa: E402

_STMT = {"total_assets": "bs", "total_liabilities_and_equity": "bs", "total_liabilities": "bs",
         "total_equity": "bs", "cfo": "cf", "cfi": "cf", "cff": "cf", "fx_effect": "cf",
         "net_change_in_cash": "cf", "cash_beginning": "cf", "cash_ending": "cf", "pretax_income_cf": "cf"}

# current 值；prior 取 current + 1 以區分兩期
_BASE: dict[str, float] = {
    "total_assets": 1000, "total_liabilities_and_equity": 1000,
    "total_liabilities": 900, "total_equity": 100,
    "interest_income": 500, "interest_expense": -200, "net_interest_income": 300,
    "non_interest_income": 150, "net_revenue": 450,
    "provision": -20, "insurance_other_cost": -10, "total_opex": -120, "pretax_income": 300,
    "income_tax": -50, "net_income": 250,
    "cfo": 40, "cfi": -30, "cff": 20, "fx_effect": 5, "net_change_in_cash": 35,
    "cash_beginning": 100, "cash_ending": 135, "pretax_income_cf": 300,
}


def _rows(values: dict[str, float], labels: dict[str, str] | None = None) -> list[StatementRow]:
    out = []
    for i, (k, v) in enumerate(values.items()):
        out.append(StatementRow(
            statement=_STMT.get(k, "is"), section=None, label=(labels or {}).get(k, k), key=k,
            note=None, current=v, prior=v + 1 if k not in ("total_assets", "total_liabilities_and_equity") else v,
            current_pct=None, prior_pct=None, page=1, line_idx=i,
        ))
    return out


def _prior_balanced(values: dict[str, float]) -> list[StatementRow]:
    """prior 欄與 current 同值（避免 +1 破壞平衡）。"""
    rows = _rows(values)
    for r in rows:
        r.prior = r.current
    return rows


def _by(checks, name, period="current"):
    return next(c for c in checks if c.name == name and c.period == period)


def test_all_keys_balanced_all_nine_checks_pass() -> None:
    checks = run_cross_checks(_prior_balanced(_BASE), schema="fh")
    assert len(checks) == 2 * len(FH_CHECK_SPECS) == 18
    assert [c.name for c in checks[::2]] == [n for n, _, _ in FH_CHECK_SPECS]
    assert all(c.passed is True for c in checks)


def test_interest_expense_sign_agnostic() -> None:
    for v in (-200, 200):
        checks = run_cross_checks(_prior_balanced({**_BASE, "interest_expense": v}), schema="fh")
        assert _by(checks, "is_net_interest").passed is True
        assert _by(checks, "is_net_interest", "prior").passed is True


def test_missing_insurance_other_cost_counts_as_zero() -> None:
    vals = {k: v for k, v in _BASE.items() if k != "insurance_other_cost"}
    vals["pretax_income"] = 450 - 20 - 120  # 310
    c = _by(run_cross_checks(_prior_balanced(vals), schema="fh"), "is_pretax")
    assert c.passed is True


def test_missing_required_row_gives_none_not_zero() -> None:
    vals = {k: v for k, v in _BASE.items() if k != "net_revenue"}
    checks = run_cross_checks(_prior_balanced(vals), schema="fh")
    for name in ("is_net_revenue", "is_pretax"):
        for period in ("current", "prior"):
            assert _by(checks, name, period).passed is None
    assert _by(checks, "is_net_interest").passed is True  # 不依賴 net_revenue 者不受影響


def _no_total(delta: float = 0):
    vals = {k: v for k, v in _BASE.items() if k != "non_interest_income"}
    vals["fee_income_net"] = 100
    vals["fx_gain"] = 60
    vals["impairment_loss"] = -10 + delta  # 加總 150 + delta
    return vals


def test_missing_non_interest_total_uses_components_and_warns() -> None:
    warnings: list[str] = []
    checks = run_cross_checks(_prior_balanced(_no_total()), schema="fh", warnings=warnings)
    assert _by(checks, "is_net_revenue").passed is True
    assert _by(checks, "is_net_revenue", "prior").passed is True
    assert any("利息以外淨收益" in w for w in warnings)


def test_components_off_by_three_fails() -> None:
    checks = run_cross_checks(_prior_balanced(_no_total(3)), schema="fh", warnings=[])
    assert _by(checks, "is_net_revenue").passed is False


# ── item 1.6：insurance_other_cost 依報表原號相加（不取絕對值；Spec §2.4 修訂） ──────────

def test_insurance_other_cost_positive_net_recovery_added() -> None:
    vals = {**_BASE, "insurance_other_cost": 10, "pretax_income": 450 - 20 + 10 - 120}  # 320
    checks = run_cross_checks(_prior_balanced(vals), schema="fh")
    assert _by(checks, "is_pretax").passed is True
    assert _by(checks, "is_pretax", "prior").passed is True


def test_insurance_other_cost_positive_not_treated_as_cost() -> None:
    vals = {**_BASE, "insurance_other_cost": 10}  # pretax 仍 300（把 +10 當成本）→ 不平
    assert _by(run_cross_checks(_prior_balanced(vals), schema="fh"), "is_pretax").passed is False
