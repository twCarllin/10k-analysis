"""附錄 C（跨年表格比對）render 測試（契約：task item 5.2、Spec §2.7）。"""

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

FX = json.loads((ROOT / "tests/fixtures/tw_equity/report_cross_year.json").read_text(encoding="utf-8"))["appendix_c"]
HC = "## 附錄 C：跨年表格比對"


def _text(tmp_path, cy) -> str:
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
        eval_results={}, skipped_tasks=[], cross_year=cy, out_dir=tmp_path,
    )
    return md.read_text(encoding="utf-8")


def _c(text: str) -> str:
    return text.split(HC)[1]


def test_full_series_ascending_and_overlap_ok(tmp_path):
    text = _text(tmp_path, FX["full"])
    assert text.index("## 附錄 B") < text.index(HC)
    c = _c(text)
    assert c.index("12,062,664") < c.index("14,278,187") < c.index("20,275,577")
    assert "兩份文件重疊年度數字一致" in c
    for needle in ("15.37", "APPCSHOLDER甲", "rows", "17.99"):
        assert needle in c
    assert "未取得" not in c


def test_mismatch_lists_only_false(tmp_path):
    c = _c(_text(tmp_path, FX["mismatch"]))
    assert "APPCMISMATCH毛利" in c
    assert "兩份文件重疊年度數字一致" not in c


def test_empty_sales_series_prints_not_obtained_once_others_normal(tmp_path):
    c = _c(_text(tmp_path, FX["empty_sales"]))
    assert c.count("未取得") == 1
    assert "8.5" in c and "APPCSHOLDER甲" in c


def test_no_prior_prints_not_executed(tmp_path):
    c = _c(_text(tmp_path, None))
    assert "本附錄未執行：未提供前一年度" in c
    assert "未取得" not in c


def test_empty_shareholders_and_mismatch_coexist(tmp_path):
    c = _c(_text(tmp_path, FX["combo"]))
    assert "APPCMISMATCH毛利" in c
    assert c.count("未取得") == 1
    assert "APPCSHOLDER甲" not in c
