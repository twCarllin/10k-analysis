"""test_fh_metrics.py — run 2026-10-09-tw-equity-fh-schema item 3.1：compute_metrics(group="fh") 10 項金控指標。

契約表：
  M1: total_equity=100,total_assets=1000 → equity_to_assets current==10.0；pack 指標 key 集合恰為 10 項（無工業 key、無 None 佔位）
  M2: roe＝net_income÷total_equity（期末，不平均）；roa＝net_income÷total_assets
  M3: credit_cost＝−provision÷loans_net（sign-fix Spec §2 C）：provision 印負（提存）為正、印正（迴轉）為負
  M4: [邊界] net_revenue 為 0 或缺列 → cost_income_ratio／nii_share／fee_share 為 None，其他指標不受影響
  M5: [組合] group=="fh" × fy_income=None → 指標照算、ttm 為 None 或 unavailable、不拋例外
  M6: group=None／非 fh → 輸出與 industrial_metrics_snapshot.json 逐值相同
  M7: 其餘公式（cost_income_ratio、nii_share、fee_share、pretax_margin、loan_to_deposit、liquid_to_assets）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/tw_equity"))

from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402

FH_KEYS = {"equity_to_assets", "credit_cost", "cost_income_ratio", "roa", "roe", "nii_share", "fee_share",
           "pretax_margin", "loan_to_deposit", "liquid_to_assets"}

_VALUES = {
    "total_equity": ("bs", 100), "total_assets": ("bs", 1000), "loans_net": ("bs", 500), "deposits": ("bs", 800),
    "cash": ("bs", 30), "due_from_central_bank": ("bs", 70),
    "provision": ("is", -5), "net_revenue": ("is", 200), "net_interest_income": ("is", 120),
    "fee_income_net": ("is", 40), "pretax_income": ("is", 50), "net_income": ("is", 40), "total_opex": ("is", -100),
}


def _ledger(overrides=None, drop=()) -> StatementLedger:
    vals = {**{k: v for k, v in _VALUES.items() if k not in drop}}
    for k, v in (overrides or {}).items():
        vals[k] = (_VALUES[k][0], v)
    rows = [StatementRow(st, None, k, k, None, v, v, None, None, 1, 0, columns=[v, v, v] if st == "bs" else [v, v])
            for k, (st, v) in vals.items()]
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": ["115-06-30", "114-12-31", "114-06-30"],
                        "is": ["115-01-01~115-06-30", "114-01-01~114-06-30"], "cf": []},
        basis="H1", periods={"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                             "bs_current": "115-06-30", "bs_prior_same": "114-06-30",
                             "bs_prior_fy_end": "114-12-31"},
        days={"current": 181, "prior": 181}, schema="fh")


def _cur(pack, key):
    return pack.get(key, "current")


def test_equity_to_assets_and_key_set():  # M1
    pack = compute_metrics(_ledger(), None, group="fh")
    assert _cur(pack, "equity_to_assets") == pytest.approx(10.0)
    assert {m.key for m in pack.metrics} == FH_KEYS
    assert len(pack.metrics) == 2 * len(FH_KEYS)  # 兩期各一，無工業佔位


def test_roe_roa_use_period_end_values():  # M2
    pack = compute_metrics(_ledger(), None, group="fh")
    assert _cur(pack, "roe") == pytest.approx(40 / 100 * 100)
    assert _cur(pack, "roa") == pytest.approx(40 / 1000 * 100)


@pytest.mark.parametrize("provision,expected", [(-5, 1.0), (5, -1.0)])
def test_credit_cost_sign_provision(provision, expected):  # M3；依據 Spec sign-fix §2 C：−provision／loans_net，提存為正、迴轉為負
    pack = compute_metrics(_ledger({"provision": provision}), None, group="fh")
    assert _cur(pack, "credit_cost") == pytest.approx(expected)


@pytest.mark.parametrize("case", ["zero", "missing"])
def test_net_revenue_zero_or_missing(case):  # M4
    led = _ledger({"net_revenue": 0}) if case == "zero" else _ledger(drop=("net_revenue",))
    pack = compute_metrics(led, None, group="fh")
    for k in ("cost_income_ratio", "nii_share", "fee_share", "pretax_margin"):
        assert _cur(pack, k) is None
    for k in ("equity_to_assets", "credit_cost", "roa", "roe", "loan_to_deposit", "liquid_to_assets"):
        assert _cur(pack, k) is not None


def test_fy_income_none_no_ttm_no_raise():  # M5
    pack = compute_metrics(_ledger(), None, group="fh")
    assert pack.ttm is None or pack.ttm.status == "unavailable"
    assert _cur(pack, "roe") is not None
    json.dumps(pack.to_dict())


def test_other_formulas():  # M7
    pack = compute_metrics(_ledger(), None, group="fh")
    assert _cur(pack, "cost_income_ratio") == pytest.approx(50.0)
    assert _cur(pack, "nii_share") == pytest.approx(60.0)
    assert _cur(pack, "fee_share") == pytest.approx(20.0)
    assert _cur(pack, "pretax_margin") == pytest.approx(25.0)
    assert _cur(pack, "loan_to_deposit") == pytest.approx(62.5)
    assert _cur(pack, "liquid_to_assets") == pytest.approx(10.0)


@pytest.mark.parametrize("group", [None, "industrial"])
def test_non_fh_group_matches_snapshot(group):  # M6
    from make_industrial_metrics_snapshot import FIX, ledgers
    snap = json.loads((FIX / "industrial_metrics_snapshot.json").read_text(encoding="utf-8"))
    for name, led in ledgers().items():
        got = json.loads(json.dumps(compute_metrics(led, None, group=group).to_dict(), sort_keys=True))
        assert got == snap[name], name
