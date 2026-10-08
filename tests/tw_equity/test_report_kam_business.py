"""第 4／5 節（tw_kam_analysis／tw_business_analysis）render 測試（契約：task item 5.1、Spec §3.1／§3.2）。"""

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

FIXTURE = json.loads(
    (ROOT / "tests/fixtures/tw_equity/report_skill_results.json").read_text(encoding="utf-8")
)
FULL = FIXTURE["full"]
PARTIAL = FIXTURE["partial"]
NO_RETURN = "（skill 未回傳）"
H4, H5 = "## 4. 關鍵查核事項", "## 5. 業務與管理層敘述"


def _bundle() -> TablesBundle:
    return TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=[], unit_notes={},
    )


def _text(tmp_path, skill_results, skipped=None) -> str:
    inputs = TwEquityInputs(
        ticker="3653", company_name="健策", fiscal_year=2025,
        annual_report_path=Path("x.pdf"), consolidated_fs_path=None, parent_fs_path=None,
    )
    md = save_tw_equity_report(
        inputs=inputs, bundle=_bundle(), anchors_summary={}, skill_results=skill_results,
        eval_results={}, skipped_tasks=skipped or [], out_dir=tmp_path,
    )
    return md.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    return text.split(start)[1].split(end)[0]


def test_kam_full_renders_matters_and_linkage(tmp_path):
    text = _text(tmp_path, FULL)
    assert text.index("## 3. 附註品質") < text.index(H4) < text.index(H5) < text.index("## 附錄 A")
    sec = _section(text, H4, H5)
    for m in ("KAMMATTER", "KAMWHY", "KAMRESP", "KAMLINK", "T5 inventory.writedown", "KAMOBS"):
        assert m in sec
    assert NO_RETURN not in sec


def test_kam_missing_matters_prints_marker(tmp_path):
    sec = _section(_text(tmp_path, PARTIAL), H4, H5)
    assert NO_RETURN in sec


def test_business_full_renders_status_in_chinese(tmp_path):
    sec = _section(_text(tmp_path, FULL), H5, "## 附錄 A")
    for m in ("BIZSUM", "BIZPROD", "BIZPLAN", "BIZCLAIM1", "BIZNOTE1", "BIZOBS"):
        assert m in sec
    assert "一致" in sec and "不一致" in sec and "無法驗證" in sec
    for raw in ("consistent", "inconsistent", "unverifiable"):
        assert raw not in sec
    assert NO_RETURN not in sec


def test_business_missing_key_prints_marker(tmp_path):
    sec = _section(_text(tmp_path, PARTIAL), H5, "## 附錄 A")
    assert "PARTBIZ" in sec
    assert NO_RETURN in sec


def test_skipped_task_prints_not_executed(tmp_path):
    text = _text(tmp_path, FULL, skipped=["tw_kam_analysis"])
    assert "本節未執行：輸入資料不足（tw_kam_analysis）" in _section(text, H4, H5)
    assert "KAMMATTER" not in text
    assert "BIZSUM" in _section(text, H5, "## 附錄 A")
