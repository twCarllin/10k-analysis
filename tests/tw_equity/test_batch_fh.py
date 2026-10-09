"""batch.py 金控記錄測試（run 2026-10-09-tw-equity-fh-schema，item 5.1；Spec §8.1）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.tw_equity import batch

REPO = Path(__file__).resolve().parents[2]
OLD_VALUE_KEYS = ("revenue", "gross_profit", "operating_income", "net_income", "cfo")
FH_VALUE_KEYS = ("net_interest_income", "non_interest_income", "net_revenue", "provision", "total_opex",
                 "pretax_income", "net_income", "net_income_parent", "total_assets", "total_equity",
                 "loans_net", "deposits")


def _write_input(base: Path, ticker: str, group: str) -> None:
    (base / "tw_report").mkdir(exist_ok=True)
    (base / "tw_report" / f"{ticker}_ar.pdf").write_bytes(b"ar")
    (base / "tw_report" / f"{ticker}_fs.pdf").write_bytes(b"fs")
    (base / "tw_equity_inputs").mkdir(exist_ok=True)
    (base / "tw_equity_inputs" / f"{ticker}.json").write_text(json.dumps({
        "ticker": ticker, "company_name": f"公司{ticker}", "fiscal_year": 2025, "group": group,
        "annual_report_path": f"tw_report/{ticker}_ar.pdf",
        "consolidated_fs_path": f"tw_report/{ticker}_fs.pdf", "fs_period": "2026H1",
    }), encoding="utf-8")


@pytest.fixture
def fake_pipeline(monkeypatch):
    """系統邊界替身：PDF 載入／錨點／extract_tables（回空 bundle；ticker 含 "bad" 者拋例外）。"""
    monkeypatch.setattr(batch.pdf_doc, "load_pdf", lambda p: SimpleNamespace(path=p))
    monkeypatch.setattr(batch, "find_annual_report_sections", lambda doc, required, **k: {})
    monkeypatch.setattr(batch, "find_heading_sections", lambda doc, anchors, required: {})

    def fake_extract(ar, *a, **k):
        if "bad" in str(ar.path):
            raise ValueError("boom")
        return SimpleNamespace(statements=None, metrics=None, fy_income=None, fh_notes=None, fh_notes_error=None)

    monkeypatch.setattr(batch, "extract_tables", fake_extract)


def test_fh_failure_keeps_schema_and_empty_fh_fields(tmp_path, fake_pipeline):
    _write_input(tmp_path, "badfh", "fh")
    rec = batch.run_company("badfh", base_dir=tmp_path)
    assert rec["status"] == "error" and rec["error"] == "ValueError: boom"
    assert rec["schema"] == "fh"
    assert rec["values"] is None and rec["metrics"] is None and rec["ttm"] is None and rec["bridges"] is None
    assert rec["fh_notes"] is None and rec["ifrs17_break"] is None


def test_mixed_batch_each_follows_own_schema_in_order(tmp_path, fake_pipeline):
    _write_input(tmp_path, "ind", "industrial")
    _write_input(tmp_path, "fhco", "fh")
    recs = batch.run_batch(["ind", "fhco"], tmp_path / "out", base_dir=tmp_path)
    assert [r["ticker"] for r in recs] == ["ind", "fhco"]
    assert [r["schema"] for r in recs] == ["industrial", "fh"]
    assert recs[0]["ifrs17_break"] is None
    assert "fh_notes" not in recs[0]


@pytest.mark.skipif(not (REPO / "tw_report" / "2881_2026Q2財報.pdf").exists(), reason="需本地 tw_report")
def test_real_2881_fh_record():
    rec = batch.run_company("2881", base_dir=REPO)
    assert rec["status"] == "ok", rec["error"]
    assert rec["schema_version"] == 2 and rec["schema"] == "fh"
    assert isinstance(rec["ifrs17_break"], bool)
    assert set(rec["values"]) == set(FH_VALUE_KEYS)
    assert rec["values"]["net_income"]["current"] is not None
    assert rec["values"]["non_interest_income"]["current"] is not None
    assert len(rec["metrics"]) == 13
    assert rec["metrics"]["group_car"]["source"]["current"]["page"] is not None
    assert rec["ttm"]["scope"] in ("consolidated", "parent_only") and "comparability" in rec["ttm"]
    assert rec["bridges"][0]["target"] == "net_income"
    assert "unavailable" in rec["fh_notes"]


@pytest.mark.skipif(not (REPO / "tw_report" / "3653_2025Q4合併財報.pdf").exists(), reason="需本地 tw_report")
def test_real_industrial_record_marks():
    rec = batch.run_company("3653", base_dir=REPO)
    assert rec["status"] == "ok", rec["error"]
    assert rec["schema"] == "industrial" and rec["ifrs17_break"] is None
    assert set(rec["values"]) == set(OLD_VALUE_KEYS)
