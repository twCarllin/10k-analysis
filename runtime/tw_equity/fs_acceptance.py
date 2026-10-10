"""fs_acceptance.py — 台股財報三表解析驗收工具（Spec 2026-10-09-tw-equity-fs-generalize §5）。

CLI：./.venv/bin/python -m runtime.tw_equity.fs_acceptance [--out run/fs_acceptance.json]
讀 29 份驗收文件（28 檔 2026Q2 半年報＋3653 年度財報），每份跑
load_pdf → find_heading_sections(FS_HEADING_ANCHORS) → extract_statements。不打外部 API。
`--ocr-cache`：另驗 OCR_FILES（三表為圖片頁），OCR 只讀既有 .ocr.json 快取；未命中記 error `ocr_cache_miss`。
`--all70`：70 家驗收（Spec 2026-10-10-tw-equity-70-conform §1）。依 tw_equity_inputs/*.json 的 group 產清單
（工業／石化 22 項、金控／銀行 18 項）；OCR 只讀快取、未命中改不做 OCR 載入（不打 API）；
例外只有 ACCEPTANCE_EXCEPTIONS 兩筆（ticker＋check 鍵）。輸出每家結果與 SUMMARY 行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections
from runtime.tw_equity.inputs import load_inputs, uses_fh_schema
from runtime.tw_equity.statements import SINGLE_STEP_NA, SINGLE_STEP_WARNING, extract_statements

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

OCR_FILES: tuple[str, ...] = ("2330_2026Q2財報.pdf", "3711_2026Q2財報.pdf")


# 70 家驗收：每家應有的勾稽項數；例外＝(ticker, "<check 名>/<period>")，停業單位損益未納入勾稽（Spec §5 Q3），僅此 2 筆
EXPECTED_CHECKS = {"industrial": 22, "fh": 18}
ACCEPTANCE_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset({
    ("2449", "is_net_income/prior"),
    ("2890", "is_net_income/current"),
})


# 已知限制（使用者 2026-10-10 裁示，Spec 2026-10-10-tw-equity-top100-conform §4）：不修，輸出標示，不計入符合數
KNOWN_LIMITATIONS: frozenset[str] = frozenset({"6223", "1101", "3529"})


class OcrCacheMiss(Exception):
    pass


def _cache_only_ocr(path, pages):
    """load_pdf 快取未命中才會呼叫 OCR → 一律拒絕，保證不打 API。"""
    raise OcrCacheMiss(f"pages={pages}")


def _check_one(name: str, report_dir: Path, *, ocr_cache: bool = False) -> dict:
    path = report_dir / name
    if not path.exists():
        return {"file": name, "error": "missing"}
    try:
        doc = pdf_doc.load_pdf(path, ocr=_cache_only_ocr) if ocr_cache else pdf_doc.load_pdf(path)
    except OcrCacheMiss:
        return {"file": name, "error": "ocr_cache_miss"}
    except Exception as e:  # 單檔失敗不中斷全量
        return {"file": name, "error": f"{type(e).__name__}: {e}"}
    try:
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


def acceptance_tickers(base_dir: Path) -> list[tuple[str, str | None]]:
    """tw_equity_inputs/*.json → [(ticker, group)]，依代號排序。"""
    return [(p.stem, load_inputs(p.stem, base_dir=base_dir).group)
            for p in sorted((base_dir / "tw_equity_inputs").glob("*.json"))]


def check_company(ticker: str, group: str | None, base_dir: Path) -> dict:
    """單家驗收：財報 OCR 只讀快取（ocr_scanned 政策同 batch），未命中改不做 OCR 載入；扣除例外後 failed／none 須為 0。"""
    expected = EXPECTED_CHECKS["fh" if uses_fh_schema(group) else "industrial"]
    rec: dict = {"ticker": ticker, "group": group, "expected": expected}
    try:
        inp = load_inputs(ticker, base_dir=base_dir)
        if inp.consolidated_fs_path is None:
            return {**rec, "error": "no_fs_path"}
        try:
            doc = pdf_doc.load_pdf(inp.consolidated_fs_path, ocr=_cache_only_ocr, ocr_scanned=True)
        except OcrCacheMiss:
            doc = pdf_doc.load_pdf(inp.consolidated_fs_path)
        led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()), group=group)
    except Exception as e:  # 單家失敗不中斷全量
        return {**rec, "error": f"{type(e).__name__}: {e}"}
    if led is None:
        return {**rec, "error": "no_statements"}
    return {**rec, **evaluate_checks(ticker, group, led.checks, led.parse_warnings)}


# 單步式損益表（parse_warnings 帶 SINGLE_STEP_WARNING）：這兩項勾稽算「不適用」，不算失敗（Spec 2026-10-10-tw-equity-top100-conform §3.1 I-12）
SINGLE_STEP_NA_CHECKS = SINGLE_STEP_NA


def evaluate_checks(ticker: str, group: str | None, checks: list, parse_warnings: list[str] | tuple = ()) -> dict:
    """勾稽結果 → 驗收判定：項數須等於該 group 的期望數；扣除 ACCEPTANCE_EXCEPTIONS（ticker＋check 鍵）與單步式不適用項後無任何未通過。"""
    expected = EXPECTED_CHECKS["fh" if uses_fh_schema(group) else "industrial"]
    single_step = SINGLE_STEP_WARNING in parse_warnings
    na = [f"{c.name}/{c.period}" for c in checks
          if single_step and c.name in SINGLE_STEP_NA_CHECKS and c.passed is None]
    bad = [f"{c.name}/{c.period}" for c in checks if c.passed is not True and f"{c.name}/{c.period}" not in na]
    excepted = [k for k in bad if (ticker, k) in ACCEPTANCE_EXCEPTIONS]
    rest = [k for k in bad if k not in excepted]
    return {"total": len(checks), "passed": sum(1 for c in checks if c.passed is True),
            "excepted": excepted, "not_applicable": na, "not_passed": rest,
            "conform": len(checks) == expected and not rest}


def _all_pass(rec: dict) -> bool:
    return (
        "error" not in rec
        and rec["checks_failed"] == 0
        and rec["checks_none"] == 0
        and rec["checks_passed"] > 0
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="台股財報三表解析驗收")
    ap.add_argument("--out", default=None, help="結果 JSON；預設 run/fs_acceptance.json（--all70：run/conform_acceptance.json）")
    ap.add_argument("--ocr-cache", action="store_true", help="另驗 OCR_FILES（只讀 OCR 快取，不打 API）")
    ap.add_argument("--all70", action="store_true", help="70 家驗收（依 tw_equity_inputs 的 group；不打 API）")
    args = ap.parse_args(argv)
    if args.all70:
        return _main_all70(Path(args.out or "run/conform_acceptance.json"))
    jobs = [(n, False) for n in ACCEPTANCE_FILES] + ([(n, True) for n in OCR_FILES] if args.ocr_cache else [])
    result = {"files": [], "all_pass_files": 0, "total_files": len(jobs)}
    for name, ocr_cache in jobs:
        rec = _check_one(name, _REPORT_DIR, ocr_cache=ocr_cache)
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
    out = Path(args.out or "run/fs_acceptance.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUMMARY all_pass_files={result['all_pass_files']} total_files={result['total_files']}")
    return 0


def _main_all70(out: Path) -> int:
    recs = []
    for ticker, group in acceptance_tickers(_REPO_ROOT):
        rec = {**check_company(ticker, group, _REPO_ROOT), "known_limitation": ticker in KNOWN_LIMITATIONS}
        recs.append(rec)
        if "error" in rec:
            print(f"{ticker} [{group}]: ERROR {rec['error']}" + (" known_limitation" if ticker in KNOWN_LIMITATIONS else ""), flush=True)
        else:
            print(f"{ticker} [{group}]: {'OK' if rec['conform'] else 'FAIL'} {rec['passed']}/{rec['total']}"
                  + (" known_limitation" if ticker in KNOWN_LIMITATIONS else "")
                  + (f" excepted={','.join(rec['excepted'])}" if rec["excepted"] else "")
                  + (f" failed={','.join(rec['not_passed'])}" if rec["not_passed"] else ""), flush=True)
    n_known = sum(1 for r in recs if r["ticker"] in KNOWN_LIMITATIONS)
    n_ok = sum(1 for r in recs if r.get("conform") and r["ticker"] not in KNOWN_LIMITATIONS)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUMMARY conform={n_ok}/{len(recs)} known_limitations={n_known} exceptions={sum(len(r.get('excepted', [])) for r in recs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
