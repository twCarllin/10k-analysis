"""附錄 B 增補（亂碼／OCR 頁、前一年度）與 raw.json 新欄測試（契約：task item 5.3、Spec §2.7）。"""

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

FX = json.loads((ROOT / "tests/fixtures/tw_equity/report_cross_year.json").read_text(encoding="utf-8"))["appendix_b_prior"]
SIX = {"bundle", "anchors_summary", "skill_results", "skipped_tasks", "garbled_pages", "ocr_pages"}


def _bundle(missing=()) -> TablesBundle:
    return TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=list(missing), unit_notes={},
    )


def _run(tmp_path, **kw):
    inputs = TwEquityInputs(
        ticker="3653", company_name="健策", fiscal_year=2025,
        annual_report_path=Path("x.pdf"), consolidated_fs_path=None, parent_fs_path=None,
    )
    md = save_tw_equity_report(
        inputs=inputs, bundle=_bundle(), anchors_summary={}, skill_results={},
        eval_results={}, skipped_tasks=[], out_dir=tmp_path, **kw)
    (raw_path,) = md.parent.glob("*_raw.json")
    return md.read_text(encoding="utf-8"), json.loads(raw_path.read_text(encoding="utf-8"))


def _prior(key, missing=("PRIORMISS_T4",)):
    return {**FX[key], "bundle": _bundle(missing)}


def _b(text: str) -> str:
    return text.split("## 附錄 B")[1].split("## 附錄 C")[0]


def test_prior_garbled_pages_and_missing_tables(tmp_path):
    text, _ = _run(tmp_path, prior=_prior("prior_garbled_ocr"), garbled_pages=[3], ocr_pages=[])
    b = _b(text)
    assert "p51" in b and "p79" in b
    assert "PRIORMISS_T4" in b
    assert "ar_governance" in b


def test_ocr_pages_shown_and_failed_checks_listed(tmp_path):
    text, _ = _run(tmp_path, prior=_prior("prior_ocr"), garbled_pages=[], ocr_pages=[])
    b = _b(text)
    assert "已 OCR 頁：p51、p79" in b
    assert "OCR 數字未通過檢查" in b and "OCRBADCHECK" in b
    assert "OCRGOODCHECK" not in b


def test_raw_json_has_prior_and_cross_keys(tmp_path):
    cy, cyc = {"years": {"current": 114, "prior": 113}}, {"quality_trend": "stable"}
    _, raw = _run(tmp_path, prior=_prior("prior_garbled_ocr"), cross_year=cy, cross_year_compare=cyc)
    assert SIX <= set(raw["prior"])
    assert raw["prior"]["garbled_pages"] == [51, 79]
    assert raw["prior"]["bundle"]["missing_tables"] == ["PRIORMISS_T4"]
    assert raw["cross_year"] == cy and raw["cross_year_compare"] == cyc


def test_no_prior_raw_none_and_no_prior_section_but_current_garbled_listed(tmp_path):
    text, raw = _run(tmp_path, garbled_pages=[12, 13], ocr_pages=[])
    assert raw["prior"] is None and raw["cross_year"] is None and raw["cross_year_compare"] is None
    b = _b(text)
    assert "前一年度" not in b
    assert "p12" in b and "p13" in b
