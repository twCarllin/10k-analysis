"""batch.py — tw-equity 批次 runner（工作包 F；run 2026-10-09-tw-equity-batch-runner）。

CLI：./.venv/bin/python -m runtime.tw_equity.batch [--tickers 3653,1303] [--out DIR]
每家只跑本地確定性步驟（load_pdf → 錨點 → extract_tables：三表帳本、指標／bridge、FY 損益／TTM），
不呼叫 LLM、不打外部 API。每家輸出固定 schema JSON，單家失敗不中斷其餘家。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import (
    FS_HEADING_ANCHORS,
    GOVERNANCE_HEADING_ANCHORS,
    find_annual_report_sections,
    find_heading_sections,
)
from runtime.tw_equity.inputs import load_inputs
from runtime.tw_equity.metrics import _ledger_value
from runtime.tw_equity.tables import extract_tables

SCHEMA_VERSION = 1
VALUE_KEYS = ("revenue", "gross_profit", "operating_income", "net_income", "cfo")


def _sha16(path: Path | None) -> str | None:
    if path is None:
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _empty_record(ticker: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "ticker": ticker, "company_name": None, "group": None,
        "fs_period": None, "status": "error", "error": None, "elapsed_seconds": None, "inputs": None,
        "basis": None, "assurance": None, "periods": None, "checks": None, "n_unmapped": None,
        "values": None, "metrics": None, "ttm": None, "fy_income_usable": None, "bridges": None,
    }


def _fill(rec: dict, bundle) -> None:
    led, mp, fy = bundle.statements, bundle.metrics, bundle.fy_income
    rec["fy_income_usable"] = None if fy is None else fy.usable
    if led is None:
        return
    checks = [c.to_dict() for c in led.checks]
    rec["basis"], rec["assurance"], rec["periods"] = led.basis, led.assurance, dict(led.periods)
    rec["checks"] = {
        "passed": sum(1 for c in checks if c["passed"] is True),
        "failed": sum(1 for c in checks if c["passed"] is False),
        "none": sum(1 for c in checks if c["passed"] is None),
        "not_passed": [f"{c['name']}/{c['period']}" for c in checks if c["passed"] is not True],
    }
    rec["n_unmapped"] = len(led.unmapped_labels)
    rec["values"] = {k: {p: _ledger_value(led, k, p) for p in ("current", "prior")} for k in VALUE_KEYS}
    if mp is None:
        return
    d = mp.to_dict()
    rec["metrics"] = d["index"]
    t = d["ttm_vs_fy"]
    rec["ttm"] = None if t is None else {"status": t["status"], "reason": t["reason"], "values": t["values"]}
    rec["bridges"] = [{"target": b["target"], "target_delta": b["target_delta"],
                       "top_drivers": b["top_drivers"]} for b in d["bridges"]]


def run_company(ticker: str, *, base_dir: Path | None = None) -> dict:
    """單家本地分析 → 固定 schema dict；任何例外 → status "error"（不拋出）。"""
    base = Path(".") if base_dir is None else base_dir
    rec = _empty_record(ticker)
    t0 = time.monotonic()
    try:
        raw = json.loads((base / "tw_equity_inputs" / f"{ticker}.json").read_text(encoding="utf-8"))
        rec["group"], rec["fs_period"] = raw.get("group"), raw.get("fs_period")
        inp = load_inputs(ticker, base_dir=base_dir)
        rec["company_name"] = inp.company_name
        ar_path, fs_path = inp.annual_report_path, inp.consolidated_fs_path
        rec["inputs"] = {"annual_report": {"path": str(ar_path), "sha256_16": _sha16(ar_path)},
                         "consolidated_fs": {"path": None if fs_path is None else str(fs_path),
                                             "sha256_16": _sha16(fs_path)}}
        ar = pdf_doc.load_pdf(ar_path)
        fs = pdf_doc.load_pdf(fs_path) if fs_path else None
        ar_anchors = find_annual_report_sections(ar, required=set())
        gov_anchors = find_heading_sections(ar, GOVERNANCE_HEADING_ANCHORS, required=set())
        fs_anchors = find_heading_sections(fs, FS_HEADING_ANCHORS, required=set()) if fs else None
        bundle = extract_tables(ar, ar_anchors, fs, fs_anchors, None, None,
                                roc_year=inp.roc_year, gov_anchors=gov_anchors)
        _fill(rec, bundle)
        rec["status"] = "ok"
    except Exception as e:  # 失敗隔離：單家任何例外只記錄
        rec["status"], rec["error"] = "error", f"{type(e).__name__}: {e}"
    rec["elapsed_seconds"] = round(time.monotonic() - t0, 3)
    return rec


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_batch(tickers: list[str], out_dir: Path, *, base_dir: Path | None = None) -> list[dict]:
    """逐家跑 run_company，寫 <out_dir>/<ticker>.json 與 manifest.json；回傳每家記錄。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"batch_id": out_dir.name, "git_head": _git_head(), "started_at": _now(),
                "finished_at": None, "companies": []}
    records = []
    for t in tickers:
        rec = run_company(t, base_dir=base_dir)
        records.append(rec)
        (out_dir / f"{t}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["companies"].append({k: rec[k] for k in ("ticker", "status", "error", "elapsed_seconds", "inputs")})
        print(f"{t}: {rec['status']} {rec['elapsed_seconds']}s" + (f" {rec['error']}" if rec["error"] else ""),
              flush=True)
    manifest["finished_at"] = _now()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tw-equity 批次 runner（本地，不打 API）")
    ap.add_argument("--tickers", help="逗號分隔；省略 → tw_equity_inputs/*.json 全部")
    ap.add_argument("--out", help="輸出目錄；預設 data/output/batch/<YYYYMMDD-HHMMSS>")
    args = ap.parse_args(argv)
    tickers = (args.tickers.split(",") if args.tickers
               else sorted(p.stem for p in Path("tw_equity_inputs").glob("*.json")))
    out = Path(args.out) if args.out else Path("data/output/batch") / datetime.now().strftime("%Y%m%d-%H%M%S")
    records = run_batch(tickers, out)
    from runtime.tw_equity.batch_summary import build_summary, write_summary
    write_summary(build_summary(records), out)
    n_err = sum(1 for r in records if r["status"] == "error")
    print(f"SUMMARY companies={len(records)} ok={len(records) - n_err} error={n_err} out={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
