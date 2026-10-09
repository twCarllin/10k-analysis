"""fs_acceptance.py — 台股財報三表解析驗收工具（Spec 2026-10-09-tw-equity-fs-generalize §5）。

CLI：./.venv/bin/python -m runtime.tw_equity.fs_acceptance [--out run/fs_acceptance.json]
讀 29 份驗收文件（28 檔 2026Q2 半年報＋3653 年度財報），每份跑
load_pdf → find_heading_sections(FS_HEADING_ANCHORS) → extract_statements。不打外部 API。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections
from runtime.tw_equity.statements import extract_statements

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPORT_DIR = _REPO_ROOT / "tw_report"

H1_TICKERS: tuple[str, ...] = (
    "1303", "2059", "2301", "2303", "2308", "2317", "2327", "2344", "2345", "2357",
    "2360", "2368", "2382", "2383", "2408", "2412", "2454", "3008", "3017", "3037",
    "3443", "3653", "4958", "5274", "6505", "6669", "7769", "8046",
)

ACCEPTANCE_FILES: tuple[str, ...] = tuple(
    f"{t}_2026Q2財報.pdf" for t in H1_TICKERS
) + ("3653_2025Q4合併財報.pdf",)


def _check_one(name: str, report_dir: Path) -> dict:
    path = report_dir / name
    if not path.exists():
        return {"file": name, "error": "missing"}
    try:
        doc = pdf_doc.load_pdf(path)
        anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
        led = extract_statements(doc, anchors)
    except Exception as e:  # 單檔失敗不中斷全量
        return {"file": name, "error": f"{type(e).__name__}: {e}"}
    if led is None:
        return {"file": name, "error": "no_statements"}
    d = led.to_dict()
    checks = d["checks"]
    return {
        "file": name,
        "checks_passed": sum(1 for c in checks if c["passed"] is True),
        "checks_failed": sum(1 for c in checks if c["passed"] is False),
        "checks_none": sum(1 for c in checks if c["passed"] is None),
        "failed_checks": [f"{c['name']}/{c['period']}" for c in checks if c["passed"] is not True],
        "n_unmapped": len(d["unmapped_labels"]),
        "unmapped_labels": d["unmapped_labels"],
        "parse_warnings": d["parse_warnings"],
        "column_periods": d["column_periods"],
        "unit": d["unit"],
    }


def _all_pass(rec: dict) -> bool:
    return (
        "error" not in rec
        and rec["checks_failed"] == 0
        and rec["checks_none"] == 0
        and rec["checks_passed"] > 0
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="台股財報三表解析驗收")
    ap.add_argument("--out", default="run/fs_acceptance.json")
    args = ap.parse_args(argv)
    result = {"files": [], "all_pass_files": 0, "total_files": len(ACCEPTANCE_FILES)}
    for name in ACCEPTANCE_FILES:
        rec = _check_one(name, _REPORT_DIR)
        result["files"].append(rec)
        if "error" in rec:
            print(f"{name}: ERROR {rec['error']}", flush=True)
        else:
            print(
                f"{name}: pass={rec['checks_passed']} fail={rec['checks_failed']} "
                f"none={rec['checks_none']} unmapped={rec['n_unmapped']}"
                + ("" if _all_pass(rec) else f" failed={','.join(rec['failed_checks'])}"),
                flush=True,
            )
    result["all_pass_files"] = sum(1 for r in result["files"] if _all_pass(r))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUMMARY all_pass_files={result['all_pass_files']} total_files={result['total_files']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
