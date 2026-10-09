"""驗收工具 fs_acceptance（fs-generalize item 2.2，Spec §5）。

契約 row：
  F1: 以假 load_pdf／extract_statements → 輸出 JSON 有 29 個 file 項與 all_pass_files／total_files
  F2: 缺檔 → 該項 error=="missing" 且其他項照跑
  F3: [邊界] 模組常數清單不含 2330、3711 與 7 家金控
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import fs_acceptance  # noqa: E402

_HOLDINGS = {"2881", "2882", "2884", "2885", "2886", "2887", "2891"}


class _FakeLedger:
    def to_dict(self) -> dict:
        checks = [{"name": f"c{i}", "period": "current", "passed": True} for i in range(21)]
        checks.append({"name": "bad", "period": "prior", "passed": False})
        return {
            "checks": checks,
            "unmapped_labels": ["x"],
            "parse_warnings": [],
            "column_periods": {"bs": [], "is": [], "cf": []},
            "unit": "新台幣千元",
        }


def _setup(monkeypatch, tmp_path: Path, missing: str | None = None) -> Path:
    report_dir = tmp_path / "tw_report"
    report_dir.mkdir()
    for name in fs_acceptance.ACCEPTANCE_FILES:
        if name != missing:
            (report_dir / name).write_bytes(b"%PDF")
    monkeypatch.setattr(fs_acceptance, "_REPORT_DIR", report_dir)
    monkeypatch.setattr(fs_acceptance.pdf_doc, "load_pdf", lambda path: SimpleNamespace(pages=[]))
    monkeypatch.setattr(fs_acceptance, "find_heading_sections", lambda doc, anchors, required=None: {})
    monkeypatch.setattr(fs_acceptance, "extract_statements", lambda doc, anchors: _FakeLedger())
    return tmp_path / "out.json"


def test_output_has_29_files_and_summary(monkeypatch, tmp_path) -> None:
    out = _setup(monkeypatch, tmp_path)
    assert fs_acceptance.main(["--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert len(result["files"]) == 29
    assert result["total_files"] == 29
    assert isinstance(result["all_pass_files"], int)
    f = result["files"][0]
    assert {"file", "checks_passed", "checks_failed", "failed_checks", "n_unmapped"} <= set(f)


def test_missing_file_recorded_and_others_run(monkeypatch, tmp_path) -> None:
    missing = fs_acceptance.ACCEPTANCE_FILES[3]
    out = _setup(monkeypatch, tmp_path, missing=missing)
    fs_acceptance.main(["--out", str(out)])
    files = json.loads(out.read_text(encoding="utf-8"))["files"]
    by_name = {f["file"]: f for f in files}
    assert by_name[missing]["error"] == "missing"
    assert all("error" not in f for n, f in by_name.items() if n != missing)


def test_constant_list_excludes_2330_3711_and_holdings() -> None:
    tickers = {n.split("_")[0] for n in fs_acceptance.ACCEPTANCE_FILES}
    assert not tickers & ({"2330", "3711"} | _HOLDINGS)
    assert len(fs_acceptance.ACCEPTANCE_FILES) == 29


def test_ocr_cache_flag_adds_ocr_files_and_never_calls_api(monkeypatch, tmp_path) -> None:
    """D2b item 1.3：--ocr-cache 另驗 2330／3711；OCR 函式只拒絕（快取未命中 → ocr_cache_miss）。"""
    out = _setup(monkeypatch, tmp_path)
    for name in fs_acceptance.OCR_FILES:
        (tmp_path / "tw_report" / name).write_bytes(b"%PDF")
    seen: list = []

    def fake_load(path, ocr=None):
        seen.append(ocr)
        if ocr is not None and path.name.startswith("3711"):
            ocr(path, [4])  # 模擬快取未命中：load_pdf 呼叫 OCR
        return SimpleNamespace(pages=[])

    monkeypatch.setattr(fs_acceptance.pdf_doc, "load_pdf", fake_load)
    fs_acceptance.main(["--out", str(out), "--ocr-cache"])
    result = json.loads(out.read_text(encoding="utf-8"))
    by_name = {f["file"]: f for f in result["files"]}
    assert result["total_files"] == 31
    assert by_name["3711_2026Q2財報.pdf"]["error"] == "ocr_cache_miss"
    assert "error" not in by_name["2330_2026Q2財報.pdf"]
    assert seen.count(fs_acceptance._cache_only_ocr) == 2 and seen.count(None) == 29
