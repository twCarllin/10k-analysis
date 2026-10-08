"""第 8 節（cross_year_compare）render 測試（契約：task item 5.1、Spec §2.7）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from runtime.tw_equity.inputs import TwEquityInputs  # noqa: E402
from runtime.tw_equity.report import save_tw_equity_report  # noqa: E402
from runtime.tw_equity.tables import TablesBundle  # noqa: E402

FX = json.loads((ROOT / "tests/fixtures/tw_equity/report_cross_year.json").read_text(encoding="utf-8"))
NO_RETURN = "（skill 未回傳）"
H7, H8, HA = "## 7. ", "## 8. 跨年比較", "## 附錄 A"


def _text(tmp_path, cyc) -> str:
    bundle = TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=[], unit_notes={},
    )
    inputs = TwEquityInputs(
        ticker="3653", company_name="健策", fiscal_year=2025,
        annual_report_path=Path("x.pdf"), consolidated_fs_path=None, parent_fs_path=None,
    )
    md = save_tw_equity_report(
        inputs=inputs, bundle=bundle, anchors_summary={}, skill_results={},
        eval_results={}, skipped_tasks=[], cross_year_compare=cyc, out_dir=tmp_path,
    )
    return md.read_text(encoding="utf-8")


def _s8(text: str) -> str:
    return text.split(H8)[1].split(HA)[0]


def test_full_prints_all_fields_and_position(tmp_path):
    text = _text(tmp_path, FX["full"])
    assert text.index(H7) < text.index(H8) < text.index(HA)
    s8 = _s8(text)
    for needle in ("CYFINDING營收成長一致", "CYFINDING2質押增加", "positive", "negative",
                   "CYREASON部分承諾兌現", "stable", "improving"):
        assert needle in s8
    assert NO_RETURN not in s8


def test_missing_cross_checks_prints_marker(tmp_path):
    s8 = _s8(_text(tmp_path, FX["missing_checks"]))
    assert NO_RETURN in s8
    assert "CYREASON部分承諾兌現" in s8


def test_error_prints_failure_and_other_sections_remain(tmp_path):
    text = _text(tmp_path, FX["error"])
    assert "失敗" in _s8(text) and "CYBOOM" in _s8(text)
    assert "## 1. 成本結構" in text and HA in text


def test_no_prior_prints_not_executed(tmp_path):
    s8 = _s8(_text(tmp_path, None))
    assert "本節未執行：未提供前一年度" in s8
    assert "未取得" not in s8
    assert NO_RETURN not in s8
