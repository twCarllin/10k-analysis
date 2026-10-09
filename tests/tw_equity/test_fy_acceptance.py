"""fy_acceptance CLI（Spec 2026-10-09-tw-equity-period-model §4；item 2.4）。

以 PyMuPDF 在 tmp_path 產生極小的合成年報 PDF（單頁 FY 損益比較表，文字由 pdf_doc 實際讀回），
驗證 CLI 的輸出檔、缺檔處理與 exit code。不依賴 tw_report/。
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz

from runtime.tw_equity import fy_acceptance as fa

_TABLE = [
    "二、財務績效",
    "單位：新台幣仟元",
    "項目 114 年度 113 年度",
    "營業收入 1,000 900",
    "營業成本 600 500",
    "營業毛利 400 400",
    "營業費用 100 100",
    "營業利益 300 300",
    "稅前淨利 320 310",
    "所得稅費用 20 10",
    "本期淨利 300 300",
]


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    pg = doc.new_page()
    y = 60
    for line in _TABLE:
        pg.insert_text((50, y), line, fontname="china-t", fontsize=11)
        y += 20
    doc.save(str(path))


def _run(tmp_path, monkeypatch, n_present: int):
    pdf_dir = tmp_path / "tw_report"
    pdf_dir.mkdir()
    for name in fa.ACCEPTANCE_FILES[:n_present]:
        _make_pdf(pdf_dir / name)
    monkeypatch.setattr(fa, "_REPORT_DIR", pdf_dir)
    out, rep = tmp_path / "out" / "fy.json", tmp_path / "docs" / "report.md"
    code = fa.main(["--out", str(out), "--report", str(rep)])
    return code, json.loads(out.read_text(encoding="utf-8")), rep


def test_acceptance_files_count():
    assert len(fa.ACCEPTANCE_FILES) == 30
    assert "2025_2926_年報pdf.pdf" in fa.ACCEPTANCE_FILES
    assert "2025_3653_健策年報.pdf" in fa.ACCEPTANCE_FILES


def test_out_json_has_30_records_and_exit_zero_when_enough_usable(tmp_path, monkeypatch):
    code, result, rep = _run(tmp_path, monkeypatch, n_present=28)
    assert len(result["files"]) == 30
    rec = result["files"][0]
    assert rec["usable"] is True and rec["page"] == 1 and rec["scale"] == 1
    for k in ("file", "basis", "unit", "values", "checks", "warnings"):
        assert k in rec
    assert rec["values"]["revenue"]["current"] == 1000
    assert result["usable_count"] == 28
    assert code == 0
    assert rep.exists()


def test_missing_pdf_does_not_abort_and_marks_unusable(tmp_path, monkeypatch):
    code, result, _ = _run(tmp_path, monkeypatch, n_present=28)
    missing = result["files"][28]
    assert missing["file"] == fa.ACCEPTANCE_FILES[28]
    assert missing["usable"] is False
    assert any(fa.ACCEPTANCE_FILES[28] in w for w in missing["warnings"])
    assert len(result["files"]) == 30


def test_exit_code_nonzero_below_threshold(tmp_path, monkeypatch):
    code, result, _ = _run(tmp_path, monkeypatch, n_present=26)
    assert result["usable_count"] == 26
    assert code != 0


def test_report_lists_unusable_with_cause(tmp_path, monkeypatch):
    _, _, rep = _run(tmp_path, monkeypatch, n_present=26)
    text = rep.read_text(encoding="utf-8")
    assert fa.ACCEPTANCE_FILES[27] in text
    assert "建議" in text
