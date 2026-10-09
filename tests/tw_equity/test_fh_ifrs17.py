"""test_fh_ifrs17.py — run 2026-10-09-tw-equity-fh-schema item 3.4：IFRS 17 斷點旗標。

契約表：
  F1: 帳本含 insurance_service_result 列（label「保險服務結果」）→ ifrs17_break True、evidence.label＝該列原文、rule 固定
  F2: 無此列（合成銀行型金控）→ False、evidence None
  F3: [邊界] 該列存在但兩期值皆 None → 仍 True（判準是「列存在」）
  F4: group=None 的 pack.to_dict() 無 ifrs17 鍵（與工業快照鍵集合相同）；fh 的 to_dict 有兩鍵
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/tw_equity"))

from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402


def _ledger(with_row: bool, values=(10, 8)) -> StatementLedger:
    rows = [StatementRow("bs", None, "total_assets", "total_assets", None, 1000, 900, None, None, 1, 0,
                         columns=[1000, 900, 800]),
            StatementRow("is", None, "net_income", "net_income", None, 5, 4, None, None, 1, 0, columns=[5, 4])]
    if with_row:
        rows.append(StatementRow("is", None, "保險服務結果", "insurance_service_result", None,
                                 values[0], values[1], None, None, 1, 0, columns=list(values)))
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": ["115-06-30", "114-12-31", "114-06-30"],
                        "is": ["115-01-01~115-06-30", "114-01-01~114-06-30"], "cf": []},
        basis="H1", periods={"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                             "bs_current": "115-06-30", "bs_prior_same": "114-06-30",
                             "bs_prior_fy_end": "114-12-31"}, schema="fh")


def test_row_present_true_with_label():  # F1
    p = compute_metrics(_ledger(True), None, group="fh")
    assert p.ifrs17_break is True
    assert p.ifrs17_evidence == {"rule": "is_has_insurance_service_result", "label": "保險服務結果"}


def test_row_absent_false():  # F2
    p = compute_metrics(_ledger(False), None, group="fh")
    assert p.ifrs17_break is False and p.ifrs17_evidence is None


def test_row_present_values_none_still_true():  # F3
    p = compute_metrics(_ledger(True, values=(None, None)), None, group="fh")
    assert p.ifrs17_break is True and p.ifrs17_evidence["label"] == "保險服務結果"


def test_to_dict_keys_fh_only():  # F4
    fh = compute_metrics(_ledger(True), None, group="fh").to_dict()
    assert fh["ifrs17_break"] is True and fh["ifrs17_evidence"]["label"] == "保險服務結果"
    assert not compute_metrics(_ledger(False), None, group="fh").to_dict()["ifrs17_evidence"]
    from make_industrial_metrics_snapshot import FIX, ledgers
    snap = json.loads((FIX / "industrial_metrics_snapshot.json").read_text(encoding="utf-8"))
    for name, led in ledgers().items():
        d = compute_metrics(led, None).to_dict()
        assert set(d) == set(snap[name]) and "ifrs17_break" not in d
