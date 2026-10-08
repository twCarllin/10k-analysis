"""e2e：dry-run 全管線帶 fs 時輸出含 statements 與附錄 D（task item 2.3，Spec §6）。"""

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

_FIX = ROOT / "tests/fixtures/tw_equity"


def _run(tmp_path, monkeypatch, with_fs):
    import agent_runner

    (tmp_path / "tw_equity_inputs").mkdir()
    (tmp_path / "ar.pdf").write_bytes(b"%PDF-dummy")
    (tmp_path / "fs.pdf").write_bytes(b"%PDF-dummy")
    (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps({
        "ticker": "3653", "company_name": "健策精密工業股份有限公司",
        "fiscal_year": 2025, "annual_report_path": "ar.pdf",
        "consolidated_fs_path": "fs.pdf" if with_fs else None, "parent_fs_path": None,
    }), encoding="utf-8")
    docs = {
        "ar.pdf": pdf_doc.from_json(json.loads((_FIX / "ar_3653_pages.json").read_text(encoding="utf-8"))),
        "fs.pdf": pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8"))),
    }
    monkeypatch.setattr(pdf_doc, "load_pdf", lambda path, **kw: docs[Path(path).name])
    agent_runner.set_dry_run(True)
    try:
        md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=tmp_path)
    finally:
        agent_runner.set_dry_run(False)
    (raw_path,) = md.parent.glob("*_raw.json")
    return md.read_text(encoding="utf-8"), json.loads(raw_path.read_text(encoding="utf-8"))


def test_dry_run_with_fs_has_statements_and_appendix_d(tmp_path, monkeypatch):
    text, raw = _run(tmp_path, monkeypatch, True)
    st = raw["bundle"]["statements"]
    assert st is not None and all(st["row_counts"][k] > 0 for k in ("bs", "is", "cf"))
    assert "## 附錄 D" in text


def test_dry_run_without_fs_statements_null(tmp_path, monkeypatch):
    text, raw = _run(tmp_path, monkeypatch, False)
    assert raw["bundle"]["statements"] is None
    assert "三表未解析" in text.split("## 附錄 D")[1]
