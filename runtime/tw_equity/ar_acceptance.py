"""ar_acceptance.py — 年報三章節（現金流量、重要契約、特別記載事項）解析驗收工具
（Spec 2026-10-12-tw-equity-ar-sections §2.5）。

CLI：./.venv/bin/python -m runtime.tw_equity.ar_acceptance [--all101] [--gold] [--out <json>]
- `--all101`：對 `tw_equity_inputs/` 全部公司，讀年報快取、跑 parse_cashflow／parse_contracts／parse_special；
  口徑判定用半年報（`consolidated_fs_path`）帳本。每家輸出 3 章節 status、cashflow 的 arith_ok 與 basis、契約列數、
  特別記載 4 項 status；最後一行 `SUMMARY`。結果寫入 JSON（預設 run/ar_acceptance.json）。
- `--gold`：比對 tests/fixtures/tw_equity/ar_sections_gold_expected.json（數字完全相等；文字 NFKC＋去空白；
  特別記載子項 text 以金標為前綴）。Spec §2.6 的已知不符標示 known，不計入未預期不符。
- 只讀快取：PDF 文字層走 load_pdf 快取；圖片頁／亂碼頁的 OCR 只讀既有快取，未命中沿用原文（不打 OCR／API）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.ar_sections import (
    BASIS_CONSOLIDATED,
    BASIS_NON_CONSOLIDATED,
    BASIS_UNKNOWN,
    STATUS_NONE,
    STATUS_NOT_FOUND,
    STATUS_PARSED,
    apply_cashflow_basis,
    parse_cashflow,
    parse_contracts,
    parse_special,
)
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections
from runtime.tw_equity.fs_acceptance import OcrCacheMiss, _cache_only_ocr
from runtime.tw_equity.inputs import load_inputs
from runtime.tw_equity.statements import extract_statements

_REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = _REPO_ROOT / "tests" / "fixtures" / "tw_equity" / "ar_sections_gold_expected.json"

_NUM_FIELDS = ("opening_cash", "cfo", "cfi", "cff", "cfi_cff", "outflow", "fx", "closing_cash")
_TXT_FIELDS = ("remedy_invest", "remedy_finance")
_EXPL_KEYS = ("operating", "investing", "financing")

# Spec §2.6 已知不符：ticker → 欄位路徑前綴（欄位路徑以 "." 分段；前綴須整段相符）
KNOWN_MISMATCHES: dict[str, tuple[str, ...]] = {
    "2412": ("cashflow.actual_explanations", "cashflow.forecast_explanations", "contracts",
             "special.items.private_placement", "special.items.other_supplement",
             "special.items.material_events_36"),
    "2330": ("special.pages", "special.chapter_heading", "special.items.affiliates.text"),
    "2603": ("special.chapter_heading",),
}

# 金標 statement_basis_from_text → 期望的 basis（unstated → 金標未表態，不比對）
_GOLD_BASIS = {"consolidated": BASIS_CONSOLIDATED, "parent": BASIS_NON_CONSOLIDATED}


# ── 單家解析 ────────────────────────────────────────────────────────────────


def _load_ar(path: Path):
    """年報：先讀文字層快取；有圖片頁或亂碼頁時改用 OCR 快取（未命中沿用原文）。不打 OCR／API。"""
    doc = pdf_doc.load_pdf(path)
    if doc.image_pages or doc.garbled_pages:
        try:
            doc = pdf_doc.load_pdf(path, ocr=_cache_only_ocr)
        except OcrCacheMiss:
            pass
    return doc


def _load_ledger(inp) -> tuple[Any, str | None]:
    """半年報合併財報帳本（同 fs_acceptance 的只讀快取規則）→ (帳本或 None, 錯誤說明或 None)。"""
    if inp.consolidated_fs_path is None:
        return None, "no_fs_path"
    path = inp.consolidated_fs_path
    try:
        try:
            doc = pdf_doc.load_pdf(path, ocr=_cache_only_ocr, ocr_scanned=True)
        except OcrCacheMiss:
            doc = pdf_doc.load_pdf(path)
        led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()),
                                 group=inp.group)
    except Exception as e:  # 帳本失敗不中斷：口徑判 unknown
        return None, f"{type(e).__name__}: {e}"
    return led, (None if led is not None else "no_statements")


def analyze_company(ticker: str, base_dir: Path) -> dict:
    """單家：年報三章節＋口徑判定。回傳 rec；整家失敗 → rec["error"]。完整章節 dict 在 rec["sections"]。"""
    rec: dict = {"ticker": ticker}
    try:
        inp = load_inputs(ticker, base_dir=base_dir)
        rec["group"] = inp.group
        ar = _load_ar(inp.annual_report_path)
        led, led_err = _load_ledger(inp)
    except Exception as e:
        return {**rec, "error": f"{type(e).__name__}: {e}"}
    if led_err:
        rec["ledger_error"] = led_err
    sections: dict[str, dict] = {}
    for key, fn in (("cashflow", parse_cashflow), ("contracts", parse_contracts), ("special", parse_special)):
        try:
            sec = fn(ar)
            if key == "cashflow":
                apply_cashflow_basis(sec, led)
            sections[key] = sec.to_dict()
        except Exception as e:  # 單一章節例外只記該章節
            sections[key] = {"status": "error", "reason": f"{type(e).__name__}: {e}"}
    rec["sections"] = sections
    cf, ct, sp = sections["cashflow"], sections["contracts"], sections["special"]
    rec["cf"] = {"status": cf["status"], "arith_ok": cf.get("arith_ok"), "basis": cf.get("basis"),
                 "basis_note": cf.get("basis_note")}
    rec["ct"] = {"status": ct["status"], "rows": len(ct.get("rows", []))}
    rec["sp"] = {"status": sp["status"],
                 "items": {k: v["status"] for k, v in sp.get("items", {}).items()}}
    return rec


# ── SUMMARY ─────────────────────────────────────────────────────────────────


def _sp_all_found(rec: dict) -> bool:
    items = (rec.get("sp") or {}).get("items") or {}
    return len(items) == 4 and all(s != STATUS_NOT_FOUND for s in items.values())


def summarize(recs: list[dict]) -> dict:
    """驗收統計。error 的家（無 cf／ct／sp）不計入任何通過數與 basis 類別，另計 errors。"""
    with_cf = [r for r in recs if "cf" in r]

    def basis_n(b: str) -> int:
        return sum(1 for r in with_cf if r["cf"].get("basis") == b)

    return {
        "total": len(recs),
        "cf_ok": sum(1 for r in with_cf if r["cf"]["status"] in (STATUS_PARSED, STATUS_NONE)),
        "ct_ok": sum(1 for r in recs if "ct" in r and r["ct"]["status"] in (STATUS_PARSED, STATUS_NONE)),
        "sp_ok": sum(1 for r in recs if "sp" in r and _sp_all_found(r)),
        "basis_consolidated": basis_n(BASIS_CONSOLIDATED),
        "basis_non_consolidated": basis_n(BASIS_NON_CONSOLIDATED),
        "basis_unknown": basis_n(BASIS_UNKNOWN),
        "arith_not_true": sum(1 for r in with_cf if r["cf"].get("arith_ok") is not True),
        "errors": sum(1 for r in recs if "error" in r),
    }


def summary_line(s: dict) -> str:
    return (f"SUMMARY total={s['total']} cf_ok={s['cf_ok']}/{s['total']} ct_ok={s['ct_ok']}/{s['total']} "
            f"sp_ok={s['sp_ok']}/{s['total']} basis_consolidated={s['basis_consolidated']} "
            f"basis_non_consolidated={s['basis_non_consolidated']} basis_unknown={s['basis_unknown']} "
            f"arith_not_true={s['arith_not_true']} errors={s['errors']}")


def company_line(rec: dict) -> str:
    if "error" in rec:
        return f"{rec['ticker']}: ERROR {rec['error']}"
    items = " ".join(f"{k}={v}" for k, v in rec["sp"]["items"].items())
    return (f"{rec['ticker']} [{rec.get('group')}]: cf={rec['cf']['status']} arith_ok={rec['cf']['arith_ok']} "
            f"basis={rec['cf']['basis']} | ct={rec['ct']['status']} rows={rec['ct']['rows']} | "
            f"sp={rec['sp']['status']} {items}")


# ── 金標比對 ────────────────────────────────────────────────────────────────


def _n(s: str | None) -> str | None:
    return None if s is None else re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def is_known(ticker: str, field: str) -> bool:
    """欄位路徑是否落在該家的 Spec §2.6 已知不符前綴下（整段相符）。"""
    return any(field == p or field.startswith(p + ".") for p in KNOWN_MISMATCHES.get(ticker, ()))


def compare_gold(ticker: str, sections: dict, gold: dict) -> list[dict]:
    """單家章節 dict（`to_dict()` 結果）對金標 → 不符清單 [{ticker, field, got, expected, known}]。"""
    out: list[dict] = []

    def chk(field: str, ok: bool, got: Any, exp: Any) -> None:
        if not ok:
            out.append({"ticker": ticker, "field": field, "got": got, "expected": exp,
                        "known": is_known(ticker, field)})

    def txt(field: str, got: str | None, exp: str | None) -> None:
        chk(field, _n(got) == _n(exp), got, exp)

    cf, gcf = sections.get("cashflow") or {}, gold["cashflow"]
    chk("cashflow.status", cf.get("status") == gcf["status"], cf.get("status"), gcf["status"])
    chk("cashflow.pages", cf.get("pages") == gcf["pages"], cf.get("pages"), gcf["pages"])
    txt("cashflow.basis_label", cf.get("basis_label"), gcf["basis_label"])
    for tbl in ("actual", "forecast"):
        got, g = cf.get(tbl) or {}, gcf[tbl]
        chk(f"cashflow.{tbl}.page", got.get("page") == g["page"], got.get("page"), g["page"])
        for f in _NUM_FIELDS:
            chk(f"cashflow.{tbl}.{f}", got.get(f) == g[f], got.get(f), g[f])
        for f in _TXT_FIELDS:
            txt(f"cashflow.{tbl}.{f}", got.get(f), g[f])
        if "applicable" in g:
            chk(f"cashflow.{tbl}.applicable", got.get("applicable") == g["applicable"],
                got.get("applicable"), g["applicable"])
    for key in ("actual_explanations", "forecast_explanations"):
        got = cf.get(key) or {}
        for k in _EXPL_KEYS:
            txt(f"cashflow.{key}.{k}", got.get(k), gcf[key][k])
    exp_basis = _GOLD_BASIS.get(gcf.get("statement_basis_from_text"))
    if exp_basis is not None:
        chk("cashflow.basis", cf.get("basis") == exp_basis, cf.get("basis"), exp_basis)

    ct, gct = sections.get("contracts") or {}, gold["contracts"]
    chk("contracts.status", ct.get("status") == gct["status"], ct.get("status"), gct["status"])
    chk("contracts.pages", ct.get("pages") == gct["pages"], ct.get("pages"), gct["pages"])
    rows, grows = ct.get("rows") or [], gct["rows"]
    chk("contracts.rows.count", len(rows) == len(grows), len(rows), len(grows))
    for i, (r, g) in enumerate(zip(rows, grows)):
        chk(f"contracts.rows.{i}.page", r.get("page") == g["page"], r.get("page"), g["page"])
        chk(f"contracts.rows.{i}.entity", (r.get("entity") is None) == (g["entity"] is None),
            r.get("entity"), g["entity"])
        for f in ("nature", "period", "content", "restrictions"):
            txt(f"contracts.rows.{i}.{f}", r.get(f), g[f])
        chk(f"contracts.rows.{i}.parties", [_n(x) for x in r.get("parties", [])] == [_n(x) for x in g["parties"]],
            r.get("parties"), g["parties"])

    sp, gsp = sections.get("special") or {}, gold["special"]
    chk("special.status", sp.get("status") == gsp["status"], sp.get("status"), gsp["status"])
    chk("special.pages", sp.get("pages") == gsp["pages"], sp.get("pages"), gsp["pages"])
    txt("special.chapter_heading", sp.get("chapter_heading"), gsp["chapter_heading"])
    items = sp.get("items") or {}
    chk("special.items.keys", list(items) == list(gsp["items"]), list(items), list(gsp["items"]))
    for k, g in gsp["items"].items():
        it = items.get(k) or {}
        chk(f"special.items.{k}.status", it.get("status") == g["status"], it.get("status"), g["status"])
        chk(f"special.items.{k}.page", it.get("page") == g["page"], it.get("page"), g["page"])
        got_t, exp_t = _n(it.get("text")), _n(g["text"])
        chk(f"special.items.{k}.text", got_t is not None and exp_t is not None and got_t.startswith(exp_t),
            it.get("text"), g["text"])
    return out


def gold_summary_line(mismatches: list[dict], n_tickers: int) -> str:
    known = sum(1 for m in mismatches if m["known"])
    return f"GOLD tickers={n_tickers} mismatches={len(mismatches)} known={known} unexpected={len(mismatches) - known}"


# ── CLI ─────────────────────────────────────────────────────────────────────


def _all_tickers(base_dir: Path) -> list[str]:
    return [p.stem for p in sorted((base_dir / "tw_equity_inputs").glob("*.json"))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="年報三章節解析驗收（只讀快取，不打 OCR／API）")
    ap.add_argument("--all101", action="store_true", help="tw_equity_inputs/ 全部公司驗收")
    ap.add_argument("--gold", action="store_true", help="比對金標 10 家")
    ap.add_argument("--out", default=None, help="結果 JSON；預設 run/ar_acceptance.json（只跑 --gold：run/ar_acceptance_gold.json）")
    args = ap.parse_args(argv)
    if not (args.all101 or args.gold):
        ap.error("需指定 --all101 或 --gold")
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8")) if args.gold else {}
    tickers = _all_tickers(_REPO_ROOT) if args.all101 else list(gold)
    recs = []
    for t in tickers:
        rec = analyze_company(t, _REPO_ROOT)
        recs.append(rec)
        print(company_line(rec), flush=True)
    result: dict = {"companies": recs}
    mismatches: list[dict] = []
    if args.gold:
        for rec in recs:
            if rec["ticker"] in gold and "sections" in rec:
                mismatches += compare_gold(rec["ticker"], rec["sections"], gold[rec["ticker"]])
            elif rec["ticker"] in gold:
                mismatches.append({"ticker": rec["ticker"], "field": "*", "got": rec.get("error"),
                                   "expected": "金標", "known": False})
        for m in mismatches:
            print(f"GOLD_MISMATCH {m['ticker']} {m['field']} {'known' if m['known'] else 'UNEXPECTED'} "
                  f"got={m['got']!r} expected={m['expected']!r}", flush=True)
        result["gold_mismatches"] = mismatches
        print(gold_summary_line(mismatches, len(gold)), flush=True)
    result["summary"] = summarize(recs)
    out = Path(args.out or ("run/ar_acceptance.json" if args.all101 else "run/ar_acceptance_gold.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.all101:
        print(summary_line(result["summary"]))
    return 1 if any(not m["known"] for m in mismatches) else 0


if __name__ == "__main__":
    sys.exit(main())
