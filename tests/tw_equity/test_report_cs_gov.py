"""第 6／7 節（tw_customer_supplier／tw_governance_flags）render 測試（契約：task item 5.2、Spec §3.3／§3.4）。"""

from __future__ import annotations

import json
import re
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
H6, H7, HA = "## 6. 客戶與供應商", "## 7. 公司治理警訊", "## 附錄 A"


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


def test_customer_supplier_full(tmp_path):
    text = _text(tmp_path, FULL)
    assert text.index("## 5. 業務與管理層敘述") < text.index(H6) < text.index(H7) < text.index(HA)
    sec = _section(text, H6, H7)
    for m in ("CUSTNOTE", "SUPPNOTE", "CPNAME", "BARGAINWHY", "CSOBS", "48"):
        assert m in sec
    assert NO_RETURN not in sec


def test_customer_supplier_missing_prints_marker(tmp_path):
    sec = _section(_text(tmp_path, PARTIAL), H6, H7)
    assert "PARTCUST" in sec
    assert NO_RETURN in sec


def test_governance_full(tmp_path):
    sec = _section(_text(tmp_path, FULL), H7, HA)
    for m in ("PLEDGENOTE", "watch", "CAPITEM", "CAPNOTE", "OWNSTRUCT", "BOARDNOTE", "GUARNOTE", "GOVOBS"):
        assert m in sec
    assert NO_RETURN not in sec


def test_governance_missing_prints_marker(tmp_path):
    sec = _section(_text(tmp_path, PARTIAL), H7, HA)
    assert "PARTPLEDGE" in sec and "PARTBOARD" in sec
    assert NO_RETURN in sec


def test_governance_skipped_prints_not_executed(tmp_path):
    text = _text(tmp_path, FULL, skipped=["tw_governance_flags"])
    assert "本節未執行：輸入資料不足（tw_governance_flags）" in _section(text, H7, HA)
    assert "PLEDGENOTE" not in text
    assert "CUSTNOTE" in _section(text, H6, H7)


def test_eight_main_sections_and_three_appendices(tmp_path):
    heads = re.findall(r"^## (.+)$", _text(tmp_path, FULL), flags=re.M)
    assert len([h for h in heads if re.match(r"\d+\. ", h)]) == 8
    assert len([h for h in heads if h.startswith("附錄")]) == 5  # A–E
