"""報告附錄 E（run 2026-10-09-tw-equity-metrics-t1 item 2.2）。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from runtime.tw_equity.inputs import TwEquityInputs
from runtime.tw_equity.metrics import compute_metrics
from runtime.tw_equity.report import save_tw_equity_report
from runtime.tw_equity.statements import StatementLedger, StatementRow
from runtime.tw_equity.tables import TablesBundle

_KL = {k: (None, None) for k in ["營業收入", "營業成本", "營業毛利", "營業費用", "營業利益", "本期淨利"]}


def _bundle(metrics):
    return TablesBundle(None, None, None, None, None, None, None, None, None, None,
                        dict(_KL), dict(_KL), None, [], {}, metrics=metrics)


def _ledger():
    rows = [StatementRow("cf", None, k, k, None, c, p, None, None, 1, i) for i, (k, (c, p)) in
            enumerate({"cfo": (300, 100), "capex": (-50, -20), "revenue": (1000, 800)}.items())]
    return StatementLedger("仟元", "114", "113", rows, [], [])


def _run(tmp_path, bundle):
    inputs = TwEquityInputs(ticker="3653", company_name="健策", fiscal_year=2025,
                            annual_report_path=tmp_path / "ar.pdf", consolidated_fs_path=None, parent_fs_path=None)
    md = save_tw_equity_report(inputs=inputs, bundle=bundle, anchors_summary={}, skill_results={},
                               eval_results={}, skipped_tasks=[], out_dir=tmp_path)
    raw = json.loads(next(tmp_path.glob("*_raw.json")).read_text(encoding="utf-8"))
    return md.read_text(encoding="utf-8"), raw


def test_appendix_e_with_metrics(tmp_path):
    text, raw = _run(tmp_path, _bundle(compute_metrics(_ledger())))
    sec = text[text.index("## 附錄 E"):]
    assert "自由現金流（fcf）" in sec and "cfo + capex" in sec
    table = sec[sec.index("### 指標"):sec.index("### 變動歸因")]
    assert len([l for l in table.splitlines() if l.startswith("| ") and "（" in l]) == 30
    assert len(re.findall(r"^#### ", sec, flags=re.M)) == 8
    assert "| 殘差 |" in sec
    assert "| 毛利率（gross_margin） | gross_profit / revenue * 100 | — | — | % |" in sec  # None → —
    assert raw["bundle"]["metrics"]["index"]["fcf"]["current"] == 250


def test_appendix_e_without_metrics(tmp_path):
    text, raw = _run(tmp_path, _bundle(None))
    assert "未計算指標" in text[text.index("## 附錄 E"):]
    assert raw["bundle"]["metrics"] is None
    assert text.index("## 附錄 D") < text.index("## 附錄 E")
