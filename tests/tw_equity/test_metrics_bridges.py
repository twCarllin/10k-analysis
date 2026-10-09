"""metrics.py bridge 歸因（run 2026-10-09-tw-equity-metrics-t1 item 1.2）。"""
import pytest

from runtime.tw_equity.metrics import BRIDGE_SPECS, compute_metrics
from runtime.tw_equity.statements import StatementLedger, StatementRow


def _ledger(rows: dict[str, tuple], labels: dict[str, str] | None = None) -> StatementLedger:
    labels = labels or {}
    out = [StatementRow("cf", None, labels.get(k, k), k, None, cur, pri, None, None, 1, i)
           for i, (k, (cur, pri)) in enumerate(rows.items())]
    return StatementLedger("仟元", "114", "113", out, [], [])


def _bridge(pack, target):
    return next(b for b in pack.bridges if b.target == target)


def test_registry_has_8_bridges_in_order():
    assert [b.target for b in BRIDGE_SPECS] == [
        "fcf", "cfo", "net_income", "operating_income", "net_change_in_cash", "cfi", "cff", "total_assets"]
    assert len(BRIDGE_SPECS[1].components) == 28


def test_fcf_bridge_order_share_residual_and_label():
    pack = compute_metrics(_ledger({"cfo": (300, 100), "capex": (-50, -20)},
                                   labels={"cfo": "營業活動之淨現金流入"}))
    b = _bridge(pack, "fcf")
    assert (b.target_current, b.target_prior, b.target_delta) == (250, 80, 170)
    assert [c.key for c in b.components] == ["cfo", "capex"]
    assert b.components[0].delta == 200 and b.components[0].share == pytest.approx(200 / 170)
    assert b.components[0].name == "營業活動之淨現金流入"
    assert b.components[1].delta == -30
    assert b.residual == 0 and b.top_drivers == ["cfo", "capex"]


def test_missing_component_row_is_none_last_and_excluded_from_sum():
    pack = compute_metrics(_ledger({"net_change_in_cash": (100, 0), "cfo": (60, 0), "cfi": (-10, 0), "cff": (40, 0)}))
    b = _bridge(pack, "net_change_in_cash")
    assert [c.key for c in b.components] == ["cfo", "cff", "cfi", "fx_effect"]  # fx_effect 無列 → None 殿後
    assert b.components[-1].delta is None and b.components[-1].share is None
    assert b.top_drivers == ["cfo", "cff", "cfi"]
    assert b.residual == 10  # 100 − (60 − 10 + 40)
    assert b.target_delta == pytest.approx(sum(c.delta for c in b.components if c.delta is not None) + b.residual, abs=1e-6)


def test_dash_component_counts_as_zero():
    pack = compute_metrics(_ledger({"net_change_in_cash": (100, 0), "cfo": (60, 0), "cfi": (-10, 0),
                                    "cff": (40, 0), "fx_effect": (10, None)}))
    b = _bridge(pack, "net_change_in_cash")
    fx = next(c for c in b.components if c.key == "fx_effect")
    assert fx.prior == 0.0 and fx.delta == 10
    assert b.residual == 0


def test_target_missing_period_gives_none_everywhere():
    pack = compute_metrics(_ledger({"cfo": (300, 100), "capex": (-50, -20), "net_income": (10, 10)}))
    b = _bridge(pack, "cfi")  # cfi 無列
    assert b.target_delta is None and b.residual is None
    assert all(c.share is None for c in b.components)
    assert b.top_drivers == ["capex"]  # top_drivers 只看 component delta（Spec §1.1），不隨 target None 清空


def test_top_drivers_capped_at_3_sorted_by_abs_delta():
    pack = compute_metrics(_ledger({"net_income": (0, 0), "revenue": (5, 0), "cogs": (-50, 0),
                                    "rd_expenses": (-20, 0), "income_tax": (-1, 0)}))
    b = _bridge(pack, "net_income")
    assert b.top_drivers == ["cogs", "rd_expenses", "revenue"]
    assert b.residual == 66  # 0 − (5 − 50 − 20 − 1)
