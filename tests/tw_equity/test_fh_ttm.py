"""test_fh_ttm.py — run 2026-10-09-tw-equity-fh-schema item 4.4：金控 TTM（Spec §6.5）。

契約表：
  T1: consolidated：FY net_income=1000、H1 current 600、prior 500 → TTM 1100；values 的 key 集合＝FH_TTM_KEYS
  T2: parent_only：只有 net_income_parent 一 key、值＝FY＋H1c−H1p；scope=="parent_only"
  T3: ifrs17_break=True → comparability=="ifrs17_break" 且說明句含「IFRS 4」「IFRS 17」；False → comparability 非 ifrs17_break
  T4: [邊界] FY 缺 provision → 該 key TTM None、net_income TTM 仍算
  T5: [邊界] fy_income 年度與 H1 不符 → status=="unavailable"（沿既有 reason 碼 fy_year_mismatch）
  T6: [組合] parent_only × ifrs17_break=True → scope 與 comparability 同時存在
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity.fh_schema import FH_TTM_KEYS  # noqa: E402
from runtime.tw_equity.fy_income import FyIncome  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402

_H1 = {  # key: (current, prior)
    "net_interest_income": (300, 250), "non_interest_income": (100, 90), "net_revenue": (400, 340),
    "provision": (-20, -10), "total_opex": (-150, -120), "pretax_income": (230, 210),
    "income_tax": (-30, -25), "net_income": (600, 500), "net_income_parent": (580, 480),
}


def _ledger(ifrs17=False) -> StatementLedger:
    rows = [StatementRow("is", None, "所得稅費用" if k == "income_tax" else k, k, None, c, p, None, None, 1, 0,
                         columns=[c, p]) for k, (c, p) in _H1.items()]
    if ifrs17:
        rows.append(StatementRow("is", None, "保險服務結果", "insurance_service_result", None, 1, 1, None, None,
                                 1, 0, columns=[1, 1]))
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": [], "is": ["115-01-01~115-06-30", "114-01-01~114-06-30"], "cf": []},
        basis="H1", periods={"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30"},
        schema="fh")


def _fy(scope="consolidated", roc_year=114, drop=()) -> FyIncome:
    cur = {"net_interest_income": 600, "non_interest_income": 200, "net_revenue": 800, "provision": 30,
           "total_opex": 300, "pretax_income": 470, "income_tax": 60, "net_income": 1000, "net_income_parent": 950}
    if scope == "parent_only":
        cur = {"net_income_parent": 950}
    rows = [{"label": k, "key": k, "current": v, "prior": v} for k, v in cur.items() if k not in drop]
    return FyIncome(roc_year=roc_year, page=7, unit="仟元", scale=1.0, rows=rows, usable=True,
                    scope=scope, schema="fh")


def test_consolidated_ttm_formula_and_keys():  # T1
    ttm = compute_metrics(_ledger(), _fy(), group="fh").ttm
    assert ttm.status == "ok" and ttm.scope == "consolidated"
    assert ttm.values["net_income"]["ttm"] == 1100
    assert set(ttm.values) == set(FH_TTM_KEYS)
    json.dumps(ttm.to_dict())


def test_ttm_expense_signs_normalized_same_sign():  # T1 附：FY 印正號的費用與 H1 負號同號正規化後相加
    v = compute_metrics(_ledger(), _fy(), group="fh").ttm.values
    assert v["provision"]["ttm"] == -30 + -20 - -10       # FY +30 → −30
    assert v["total_opex"]["ttm"] == -300 + -150 - -120   # FY +300 → −300
    assert v["income_tax"]["ttm"] == -60 + -30 - -25      # 兩側同號（FY 無括號詞 → −|v|）


def test_parent_only_only_net_income_parent():  # T2
    ttm = compute_metrics(_ledger(), _fy("parent_only"), group="fh").ttm
    assert ttm.status == "ok" and ttm.scope == "parent_only"
    assert set(ttm.values) == {"net_income_parent"}
    assert ttm.values["net_income_parent"]["ttm"] == 950 + 580 - 480


def test_ifrs17_comparability():  # T3
    yes = compute_metrics(_ledger(ifrs17=True), _fy(), group="fh").ttm
    assert yes.comparability == "ifrs17_break"
    assert "IFRS 4" in yes.comparability_note and "IFRS 17" in yes.comparability_note
    no = compute_metrics(_ledger(ifrs17=False), _fy(), group="fh").ttm
    assert no.comparability != "ifrs17_break"


def test_fy_missing_provision_only_that_key_none():  # T4
    ttm = compute_metrics(_ledger(), _fy(drop=("provision",)), group="fh").ttm
    assert ttm.values["provision"]["ttm"] is None
    assert ttm.values["net_income"]["ttm"] == 1100


def test_fy_year_mismatch_unavailable():  # T5
    ttm = compute_metrics(_ledger(), _fy(roc_year=113), group="fh").ttm
    assert ttm.status == "unavailable" and ttm.reason == "fy_year_mismatch"


def test_parent_only_with_ifrs17_has_both_markers():  # T6
    ttm = compute_metrics(_ledger(ifrs17=True), _fy("parent_only"), group="fh").ttm
    assert ttm.scope == "parent_only" and ttm.comparability == "ifrs17_break"
