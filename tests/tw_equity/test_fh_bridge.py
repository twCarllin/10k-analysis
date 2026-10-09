"""test_fh_bridge.py — run 2026-10-09-tw-equity-fh-schema item 3.3：金控 net_income bridge。

契約表：
  B1: 合成 fh 帳本 current／prior 各 6 項 → components 6 個、Σ components delta + residual == target delta；
      top_drivers ≤3 且依 |delta| 降序；bridges 只有 1 組（net_income）
  B2: [邊界] 任一 component 的 prior 為 None → 該 component delta None、殘差含其餘
  B3: [邊界] 非保險金控（無 insurance_other_cost 列）→ 以 0 計、bridge 仍產出
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402

# key: (current, prior)；費用印負；income_tax 無括號標示 → 取 −|v|
_DATA = {
    "net_interest_income": (300, 200), "non_interest_income": (100, 120), "provision": (-20, -10),
    "insurance_other_cost": (-5, -8), "total_opex": (-150, -120), "income_tax": (-30, -25),
    "net_income": (195, 157),
}


def _ledger(data=None, drop=()) -> StatementLedger:
    data = data or _DATA
    rows = [StatementRow("is", None, "所得稅費用" if k == "income_tax" else k, k, None, c, p, None, None, 1, 0,
                         columns=[c, p]) for k, (c, p) in data.items() if k not in drop]
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": [], "is": ["115-01-01~115-06-30", "114-01-01~114-06-30"], "cf": []},
        basis="H1", periods={"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30"},
        schema="fh")


def _bridge(**kw):
    pack = compute_fh_bridges_pack(**kw)
    assert len(pack.bridges) == 1 and pack.bridges[0].target == "net_income"
    return pack.bridges[0]


def compute_fh_bridges_pack(**kw):
    return compute_metrics(_ledger(**kw), None, group="fh")


def test_bridge_sums_and_drivers():  # B1
    b = _bridge()
    assert len(b.components) == 6 and b.target_delta == 38
    assert sum(c.delta for c in b.components) + b.residual == pytest.approx(b.target_delta)
    assert b.residual == pytest.approx(0)
    assert len(b.top_drivers) <= 3
    ds = [abs(c.delta) for c in b.components]
    assert ds == sorted(ds, reverse=True)
    assert b.top_drivers == [c.key for c in b.components[:3]]


def test_component_prior_none():  # B2
    led = _ledger()
    led.rows = [r for r in led.rows if r.key != "total_opex"]
    led.rows.append(StatementRow("is", None, "total_opex", "total_opex", None, -150, None, None, None, 1, 0,
                                 columns=[-150]))
    b = compute_metrics(led, None, group="fh").bridges[0]
    opex = next(c for c in b.components if c.key == "total_opex")
    assert opex.delta is None
    known = sum(c.delta for c in b.components if c.delta is not None)
    assert b.residual == pytest.approx(b.target_delta - known)


def test_non_insurance_zero_cost():  # B3
    b = _bridge(drop=("insurance_other_cost",))
    ins = next(c for c in b.components if c.key == "insurance_other_cost")
    assert (ins.current, ins.prior, ins.delta) == (0.0, 0.0, 0.0)
