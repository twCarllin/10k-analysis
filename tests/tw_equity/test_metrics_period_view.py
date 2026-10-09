"""metrics 主視圖走 value_at、天數用實際天數（period-model item 1.3，Spec §3.1）。

契約 row：
  M1: H1 帳本 revenue (600,500)、AR BS [300,200,250]、days 181 → dso current = 300*181/600
  M2: gross_margin prior 取 flow_prior；current_ratio prior 取 bs_prior_same（114-06-30 欄；本檔欄序下為欄 2）
  M3: total_assets bridge prior 取 bs_prior_fy_end（114-12-31 欄；本檔欄序下為欄 1），target 與 components 皆如此
  M4: FY 帳本 dso 用 365
  M5: [邊界] days None 且 column_periods["is"] 非空 → dso/dio/dpo None，其他指標不受影響
  M6: column_periods 皆空的舊帳本 → 天數用 365
  M7: to_dict() 含 basis/days/assurance/periods 且可 json.dumps
"""
from __future__ import annotations

import json

import pytest

from runtime.tw_equity.metrics import compute_metrics
from runtime.tw_equity.statements import StatementLedger, StatementRow


def _row(st, key, cur, pri, columns):
    return StatementRow(st, None, key, key, None, cur, pri, None, None, 1, 0, columns=columns)


_BS_COLS = ["115-06-30", "114-12-31", "114-06-30"]
_PERIODS = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
            "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": "114-12-31"}


def _h1(days=None, **kw) -> StatementLedger:
    # BS 欄序 [115-06-30, 114-12-31, 114-06-30]：欄 1＝fy_end、欄 2＝prior_same（值依 columns 位置）
    rows = [
        _row("is", "revenue", 600, 500, [600, 500]),
        _row("is", "gross_profit", 300, 100, [300, 100]),
        _row("bs", "accounts_receivable", 300, 200, [300, 200, 250]),
        _row("bs", "accounts_receivable_related", 0, 0, [0, 0, 0]),
        _row("bs", "total_current_assets", 400, 0, [400, 111, 200]),
        _row("bs", "total_current_liabilities", 200, 0, [200, 111, 100]),
        _row("bs", "cash", 50, 0, [50, 30, 40]),
        _row("bs", "total_assets", 1000, 0, [1000, 900, 800]),
    ]
    base = dict(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": _BS_COLS, "is": ["115-01-01~115-06-30", "114-01-01~114-06-30"], "cf": []},
        basis="H1", periods=dict(_PERIODS), days=days or {"current": 181, "prior": 181},
    )
    base.update(kw)
    return StatementLedger(**base)


def test_dso_uses_actual_days() -> None:
    pack = compute_metrics(_h1())
    assert pack.get("dso") == pytest.approx(300 * 181 / 600)
    dso = next(m for m in pack.metrics if m.key == "dso")
    assert "* days" in dso.formula


def test_prior_views_use_matching_columns() -> None:
    pack = compute_metrics(_h1())
    assert pack.get("gross_margin", "prior") == pytest.approx(100 / 500 * 100)
    assert pack.get("current_ratio") == pytest.approx(200.0)
    assert pack.get("current_ratio", "prior") == pytest.approx(200 / 100 * 100)  # bs_prior_same＝欄 2


def test_total_assets_bridge_prior_uses_fy_end() -> None:
    pack = compute_metrics(_h1())
    b = next(b for b in pack.bridges if b.target == "total_assets")
    assert (b.target_current, b.target_prior) == (1000, 900)  # bs_prior_fy_end＝欄 1
    cash = next(c for c in b.components if c.key == "cash")
    assert (cash.current, cash.prior) == (50, 30)


def test_fy_ledger_uses_365() -> None:
    led = _h1(days={"current": 365, "prior": 365}, basis="FY")
    assert compute_metrics(led).get("dso") == pytest.approx(300 * 365 / 600)


def test_days_none_with_is_periods_gives_none_but_others_intact() -> None:
    pack = compute_metrics(_h1(days={"current": None, "prior": None}))
    for k in ("dso", "dio", "dpo"):
        assert pack.get(k) is None
    assert pack.get("gross_margin") == pytest.approx(50.0)


def test_legacy_ledger_without_column_periods_uses_365() -> None:
    rows = [_row("is", "revenue", 365, 365, []), _row("bs", "accounts_receivable", 100, 100, []),
            _row("bs", "accounts_receivable_related", 0, 0, [])]
    led = StatementLedger(unit="仟元", period_current="114", period_prior="113", rows=rows, checks=[],
                          unmapped_labels=[])
    pack = compute_metrics(led)
    assert pack.get("dso") == pytest.approx(100)


def test_to_dict_has_period_keys_and_is_json_serializable() -> None:
    d = compute_metrics(_h1(assurance="reviewed")).to_dict()
    json.dumps(d)
    assert d["basis"] == "H1"
    assert d["days"] == {"current": 181, "prior": 181}
    assert d["assurance"] == "reviewed"
    assert d["periods"]["bs_prior_fy_end"] == "114-12-31"
