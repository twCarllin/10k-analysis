"""batch.py 批次 runner 測試（run 2026-10-09-tw-equity-batch-runner，Task 1.1）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.tw_equity import batch

REPO = Path(__file__).resolve().parents[2]
TOP_KEYS = {
    "schema_version", "ticker", "company_name", "group", "fs_period", "status", "error",
    "elapsed_seconds", "inputs", "basis", "assurance", "periods", "checks", "n_unmapped",
    "values", "metrics", "ttm", "fy_income_usable", "bridges",
}


def _write_input(base: Path, ticker: str, *, fs: bool = True) -> None:
    (base / "tw_report").mkdir(exist_ok=True)
    (base / "tw_report" / f"{ticker}_ar.pdf").write_bytes(b"ar")
    if fs:
        (base / "tw_report" / f"{ticker}_fs.pdf").write_bytes(b"fs")
    (base / "tw_equity_inputs").mkdir(exist_ok=True)
    (base / "tw_equity_inputs" / f"{ticker}.json").write_text(json.dumps({
        "ticker": ticker, "company_name": f"公司{ticker}", "fiscal_year": 2025, "group": "industrial",
        "annual_report_path": f"tw_report/{ticker}_ar.pdf",
        "consolidated_fs_path": f"tw_report/{ticker}_fs.pdf" if fs else None,
        "fs_period": "2026H1" if fs else None,
    }), encoding="utf-8")


@pytest.fixture
def fake_pipeline(monkeypatch):
    """替換 PDF 載入／錨點／extract_tables；ticker "bad" 的年報讓 extract_tables 拋 ValueError("boom")。"""
    monkeypatch.setattr(batch.pdf_doc, "load_pdf", lambda p: SimpleNamespace(path=p))
    monkeypatch.setattr(batch, "find_annual_report_sections", lambda doc, required: {})
    monkeypatch.setattr(batch, "find_heading_sections", lambda doc, anchors, required: {})

    def fake_extract(ar, *a, **k):
        if "bad" in str(ar.path):
            raise ValueError("boom")
        return SimpleNamespace(statements=None, metrics=None, fy_income=None)

    monkeypatch.setattr(batch, "extract_tables", fake_extract)


def test_run_batch_isolates_failure(tmp_path, fake_pipeline):
    _write_input(tmp_path, "good")
    _write_input(tmp_path, "bad")
    out = tmp_path / "out"
    recs = batch.run_batch(["good", "bad"], out, base_dir=tmp_path)
    assert [r["status"] for r in recs] == ["ok", "error"]
    assert recs[1]["error"] == "ValueError: boom"
    assert (out / "good.json").exists() and (out / "bad.json").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [c["ticker"] for c in manifest["companies"]] == ["good", "bad"]
    assert manifest["companies"][1]["error"] == "ValueError: boom"
    assert manifest["finished_at"] is not None
    assert json.loads((out / "bad.json").read_text(encoding="utf-8"))["status"] == "error"


def test_record_keys_fixed(tmp_path, fake_pipeline):
    _write_input(tmp_path, "good")
    rec = batch.run_company("good", base_dir=tmp_path)
    assert set(rec) == TOP_KEYS
    assert rec["schema_version"] == 1
    assert rec["inputs"]["annual_report"]["sha256_16"] is not None
    assert set(batch.run_company("nope", base_dir=tmp_path)) == TOP_KEYS


def test_missing_input_is_error(tmp_path, fake_pipeline):
    rec = batch.run_company("nope", base_dir=tmp_path)
    assert rec["status"] == "error"
    assert rec["error"].startswith("FileNotFoundError")


def test_no_consolidated_fs_is_ok_with_none_fields(tmp_path, fake_pipeline):
    _write_input(tmp_path, "nofs", fs=False)
    rec = batch.run_company("nofs", base_dir=tmp_path)
    assert rec["status"] == "ok"
    assert rec["checks"] is None and rec["values"] is None and rec["metrics"] is None
    assert rec["inputs"]["consolidated_fs"] == {"path": None, "sha256_16": None}


@pytest.mark.skipif(not (REPO / "tw_report" / "3653_2025Q4合併財報.pdf").exists(), reason="需本地 tw_report")
def test_real_3653_fills_ledger_fields():
    rec = batch.run_company("3653", base_dir=REPO)
    assert rec["status"] == "ok", rec["error"]
    assert rec["checks"]["passed"] == 22 and rec["checks"]["failed"] == 0
    assert rec["values"]["revenue"]["current"] > 0
    assert rec["metrics"]["fcf"]["current"] is not None
    assert rec["bridges"] and {"target", "target_delta", "top_drivers"} <= set(rec["bridges"][0])
