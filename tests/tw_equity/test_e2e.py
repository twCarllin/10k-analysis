"""端到端整合測試（task item 5.2，Spec §5 DoD-1／DoD-2）。

fixture 注入全管線：真實 3653 年報 fixture 取代 PDF 讀取、LLM 走 dry-run mock。
只斷言跨模組串接後的可觀察結果（md／raw.json 內容）；各模組細節由各自測試檔擁有。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

import pytest  # noqa: E402

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.tw_pipeline import run_tw_equity_pipeline  # noqa: E402

_AR_FIXTURE = ROOT / "tests/fixtures/tw_equity/ar_3653_pages.json"


@pytest.fixture
def run_out(tmp_path, monkeypatch):
    import agent_runner

    (tmp_path / "tw_equity_inputs").mkdir()
    (tmp_path / "ar.pdf").write_bytes(b"%PDF-dummy")
    (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps({
        "ticker": "3653", "company_name": "健策精密工業股份有限公司",
        "fiscal_year": 2025, "annual_report_path": "ar.pdf",
        "consolidated_fs_path": None, "parent_fs_path": None,
    }), encoding="utf-8")
    doc = pdf_doc.from_json(json.loads(_AR_FIXTURE.read_text(encoding="utf-8")))
    monkeypatch.setattr(pdf_doc, "load_pdf", lambda path, **kw: doc)
    agent_runner.set_dry_run(True)
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=tmp_path)
    agent_runner.set_dry_run(False)
    (raw_path,) = md.parent.glob("*_raw.json")
    return md, json.loads(raw_path.read_text(encoding="utf-8"))


def test_outputs_md_and_raw_json_with_sections(run_out):
    md, raw = run_out
    text = md.read_text(encoding="utf-8")
    assert md.exists()
    for heading in ("## 1. ", "## 2. ", "## 3. ", "## 附錄 A", "## 附錄 B"):
        assert heading in text
    assert {"bundle", "skill_results", "anchors_summary"} <= set(raw)


def test_missing_tables_lists_fs_tables_and_t6(run_out):
    md, raw = run_out
    missing = raw["bundle"]["missing_tables"]
    assert {"T1", "T2", "T3", "T4", "T5", "T6"} <= set(missing)
    assert not {"T7a", "T7b", "T8_sales", "T8_purchase"} & set(missing)
    appendix_b = md.read_text(encoding="utf-8").split("## 附錄 B")[1]
    for name in ("T1", "T2", "T3", "T4", "T5", "T6"):
        assert f"- {name}" in appendix_b


def test_real_numbers_flow_into_raw_json_and_appendix_a(run_out):
    md, raw = run_out
    perf = {r["label"]: r for r in raw["bundle"]["fin_performance"]["rows"]}
    assert perf["營業收入"]["current"] == 20275577
    assert perf["營業收入"]["prior"] == 14278187
    assert perf["營業收入"]["diff_pct"] == 42.00
    pos = raw["bundle"]["fin_position"]["rows"]
    assert next(r for r in pos if "資產總" in r["label"])["diff_pct"] == 51.49

    sales = raw["bundle"]["customers_sales"]["years"]
    y114 = next(y for y in sales if "114" in y["label"])
    assert y114["entries"][0]["amount"] == 4627203
    assert y114["entries"][0]["pct"] == 22.82

    appendix_a = md.read_text(encoding="utf-8").split("## 附錄 A")[1].split("## 附錄 B")[0]
    for token in ("20,275,577", "14,278,187", "51.49", "4,627,203", "22.82"):
        assert token in appendix_a
