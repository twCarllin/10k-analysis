"""metrics.py 指標登錄表與 compute_metrics（run 2026-10-09-tw-equity-metrics-t1 item 1.1）。"""
import json

import pytest

from runtime.tw_equity.metrics import METRIC_SPECS, compute_metrics
from runtime.tw_equity.statements import StatementLedger, StatementRow


def _ledger(**kv) -> StatementLedger:
    """kv：key → (current, prior) 或單值（prior=None 視為「-」）。statement 依 key 粗分，測試不依賴。"""
    rows = []
    for i, (k, v) in enumerate(kv.items()):
        cur, pri = v if isinstance(v, tuple) else (v, None)
        rows.append(StatementRow("bs", None, k, k, None, cur, pri, None, None, 1, i))
    return StatementLedger(unit="仟元", period_current="114", period_prior="113", rows=rows,
                           checks=[], unmapped_labels=[])


def test_registry_has_30_specs_in_fixed_order():
    assert len(METRIC_SPECS) == 30
    assert [s.key for s in METRIC_SPECS][:3] == ["fcf", "fcf_margin", "gross_margin"]
    assert METRIC_SPECS[-1].key == "working_capital"
    assert {s.unit for s in METRIC_SPECS} <= {"仟元", "%", "天", "x", "元"}


def test_fcf_and_margin_with_inputs_recorded():
    pack = compute_metrics(_ledger(cfo=(100, 80), capex=(-30, -10), revenue=(1000, 900)))
    assert pack.get("fcf") == 70
    assert pack.get("fcf", "prior") == 70
    assert pack.get("fcf_margin") == pytest.approx(7.0)
    m = next(m for m in pack.metrics if m.key == "fcf" and m.period == "current")
    assert m.inputs == {"cfo": 100, "capex": -30}
    assert m.formula == "cfo + capex" and m.unit == "仟元"


def test_metrics_list_is_60_in_spec_x_period_order():
    pack = compute_metrics(_ledger(cfo=(1, 1)))
    assert len(pack.metrics) == 60
    assert [(m.key, m.period) for m in pack.metrics[:4]] == [
        ("fcf", "current"), ("fcf", "prior"), ("fcf_margin", "current"), ("fcf_margin", "prior")]


def test_zero_denominator_gives_none():
    pack = compute_metrics(_ledger(gross_profit=(10, 10), revenue=(0, 100)))
    assert pack.get("gross_margin") is None
    assert pack.get("gross_margin", "prior") == pytest.approx(10.0)


def test_missing_row_gives_none_but_dash_is_zero():
    pack = compute_metrics(_ledger(net_income=(50, 40), equity_parent=(500, 400)))
    assert pack.get("roe") is None  # 帳本無 net_income_parent 列
    pack2 = compute_metrics(_ledger(net_income_parent=(50, None), equity_parent=(500, 400)))
    assert pack2.get("roe") == pytest.approx(10.0)
    assert pack2.get("roe", "prior") == 0.0  # 上期「-」視為 0


def test_interest_bearing_debt_optional_inputs():
    assert compute_metrics(_ledger(lease_liabilities_current=(40, 30))).get("interest_bearing_debt") == 40
    assert compute_metrics(_ledger(cash=(1, 1))).get("interest_bearing_debt") is None
    pack = compute_metrics(_ledger(short_term_borrowings=(10, 0), bonds_payable=(5, 5), cash=(3, 3)))
    assert pack.get("interest_bearing_debt") == 15
    assert pack.get("net_debt") == 12  # 衍生指標引用先前指標


def test_days_and_ccc():
    pack = compute_metrics(_ledger(accounts_receivable=(100, 100), accounts_receivable_related=(0, 0),
                                   revenue=(365, 365), inventories=(50, 50), cogs=(-365, -365),
                                   accounts_payable=(20, 20)))
    assert pack.get("dso") == pytest.approx(100)
    assert pack.get("dio") == pytest.approx(50)
    assert pack.get("dpo") == pytest.approx(20)
    assert pack.get("ccc") == pytest.approx(130)


def test_abs_based_ratios():
    pack = compute_metrics(_ledger(capex=(-30, -30), depreciation=(10, 10), revenue=(100, 100),
                                   income_tax=(-20, -20), pretax_income=(100, 100), finance_costs=(-5, -5),
                                   operating_income=(50, 50), dividends_paid=(-40, -40), net_income_parent=(80, 80)))
    assert pack.get("capex_to_depreciation") == pytest.approx(3.0)
    assert pack.get("capex_to_revenue") == pytest.approx(30.0)
    assert pack.get("effective_tax_rate") == pytest.approx(20.0)
    assert pack.get("interest_coverage") == pytest.approx(10.0)
    assert pack.get("dividend_payout") == pytest.approx(50.0)


def test_none_ledger_and_to_dict():
    assert compute_metrics(None) is None
    pack = compute_metrics(_ledger(cfo=(100, 80), capex=(-30, -10)))
    d = pack.to_dict()
    json.dumps(d)
    assert d["index"]["fcf"] == {"current": 70, "prior": 70}
    assert d["period_current"] == "114" and len(d["metrics"]) == 60 and len(d["bridges"]) == 8
