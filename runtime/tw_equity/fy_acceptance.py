"""fy_acceptance.py — FY 損益表解析驗收工具（Spec 2026-10-09-tw-equity-period-model §4）。

CLI：./.venv/bin/python -m runtime.tw_equity.fy_acceptance [--out run/fy_acceptance.json]
讀 30 份 2025 年報，每份跑 load_pdf → find_annual_report_sections → extract_fy_income(roc_year=114)；
並比對 3653 正確性錨（§0.3）。不打外部 API。exit code 以「可用數 ≥ 27」決定。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import find_annual_report_sections
from runtime.tw_equity.fy_income import FyIncome, extract_fy_income, normalize_sign

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPORT_DIR = _REPO_ROOT / "tw_report"
_DEFAULT_OUT = "run/fy_acceptance.json"
_DEFAULT_REPORT = "docs/research/2026-10-09_05_fy_income_acceptance.md"

ROC_YEAR = 114
MIN_USABLE = 27

_TICKERS: tuple[str, ...] = (
    "1303", "2059", "2301", "2303", "2308", "2317", "2327", "2330", "2344", "2345",
    "2357", "2360", "2368", "2382", "2383", "2408", "2454", "3008", "3017", "3037",
    "3443", "3711", "4958", "5274", "6505", "6669", "7769", "8046",
)

ACCEPTANCE_FILES: tuple[str, ...] = tuple(f"{t}_2025年報.pdf" for t in _TICKERS) + (
    "2025_2926_年報pdf.pdf",
    "2025_3653_健策年報.pdf",
)

ANCHOR_FILE = "2025_3653_健策年報.pdf"
ANCHOR_LEDGER_FILE = "3653_2025Q4合併財報.pdf"
ANCHOR_KEYS: tuple[str, ...] = (
    "revenue", "cogs", "gross_profit", "operating_income", "pretax_income", "income_tax", "net_income",
)


def anchor_compare(fy: FyIncome | None, ledger) -> dict:
    """3653 錨：FY 損益 114 年度 7 項 vs 帳本 current（皆經 normalize_sign），容差 0。

    回 {"all_equal": bool, "items": {key: {"fy", "ledger", "equal"}}}；任一邊缺值 → equal False。
    """
    items: dict[str, dict] = {}
    for key in ANCHOR_KEYS:
        fy_v = led_v = None
        if fy is not None:
            fy_v = fy.normalized(key, "current")
        if ledger is not None:
            lrow = next((r for r in ledger.rows if r.key == key and r.statement == "is"), None)
            if lrow is not None:
                crow = next((r for r in ledger.rows if r.key == "cogs" and r.statement == "is"), None)
                led_v = normalize_sign(
                    key, lrow.label, lrow.current, None if crow is None else crow.current
                )
        items[key] = {"fy": fy_v, "ledger": led_v, "equal": fy_v is not None and fy_v == led_v}
    return {"all_equal": all(i["equal"] for i in items.values()), "items": items}


def _record(name: str, fy: FyIncome | None, extra_warnings: list[str] | None = None) -> dict:
    if fy is None:
        return {
            "file": name, "page": None, "basis": None, "unit": None, "scale": None,
            "values": {}, "checks": [], "usable": False,
            "warnings": list(extra_warnings or []) + ["no_candidate_page"],
        }
    return {
        "file": name,
        "page": fy.page,
        "basis": fy.basis,
        "unit": fy.unit,
        "scale": fy.scale,
        "values": {r["key"]: {"current": r["current"], "prior": r["prior"]} for r in reversed(fy.rows)},
        "checks": fy.checks,
        "usable": fy.usable,
        "warnings": list(fy.warnings),
    }


def _extract_one(name: str, report_dir: Path) -> tuple[dict, FyIncome | None]:
    path = report_dir / name
    if not path.exists():
        return _record(name, None, [f"missing: {name}"]), None
    try:
        doc = pdf_doc.load_pdf(path)
        anchors = find_annual_report_sections(doc, required=set())
        fy = extract_fy_income(doc, anchors, roc_year=ROC_YEAR)
    except Exception as e:  # 單檔失敗不中斷全量
        return _record(name, None, [f"{type(e).__name__}: {e}"]), None
    return _record(name, fy), fy


def _anchor_3653(fy: FyIncome | None, report_dir: Path) -> dict:
    """載入 3653 財報帳本並與 fy 比對；財報 PDF 不存在或解析失敗 → all_equal False 並記 error。"""
    path = report_dir / ANCHOR_LEDGER_FILE
    if not path.exists():
        return {"all_equal": False, "items": {}, "error": f"missing: {ANCHOR_LEDGER_FILE}"}
    try:
        from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections
        from runtime.tw_equity.statements import extract_statements

        doc = pdf_doc.load_pdf(path)
        led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))
    except Exception as e:
        return {"all_equal": False, "items": {}, "error": f"{type(e).__name__}: {e}"}
    return anchor_compare(fy, led)


def _root_cause(rec: dict) -> tuple[str, str]:
    """未可用檔 → (根因一句, 建議工作包)。"""
    if rec["page"] is None:
        w = "；".join(rec["warnings"])
        if "missing" in w:
            return "年報 PDF 不存在", "補檔後重跑"
        return (
            "無候選頁（找不到含兩個年度表頭＋營收列＋2 個核心科目的頁）",
            "確認年報是否有 FY 損益比較表；若無則以帳本 FY 取代，若有則擴充 §2.2 候選條件",
        )
    if rec["scale"] is None:
        return f"單位無法辨識（{rec['unit']!r}）", "擴充單位換算表或單位偵測規則"
    if rec["basis"] == "parent":
        return "頁面為個體（母公司）報表", "改選合併表頁或擴充候選頁排序"
    failed = [c["name"] for c in rec["checks"] if c["passed"] is False]
    if failed:
        return f"勾稽失敗：{','.join(failed)}", "檢查該頁科目對照與括號／符號慣例，擴充 §2.4 別名或符號規則"
    missing = [k for k in ("revenue", "operating_income", "pretax_income", "net_income")
               if rec["values"].get(k, {}).get("current") is None]
    return f"本期缺必要科目：{','.join(missing)}", "擴充 §2.4 科目別名"


def render_report(result: dict) -> str:
    lines = [
        "# FY 損益表驗收報告（2026-10-09，period-model item 2.4）",
        "",
        f"可用 {result['usable_count']} / {result['total_files']}（門檻 ≥ {MIN_USABLE}）。",
        "",
        "## 3653 正確性錨",
        "",
        "| key | FY 解析 | 帳本 current | 相等 |",
        "|---|---|---|---|",
    ]
    anc = result["anchor_3653"]
    for k, it in anc["items"].items():
        lines.append(f"| {k} | {it['fy']} | {it['ledger']} | {'是' if it['equal'] else '否'} |")
    if anc.get("error"):
        lines.append(f"\n錨比對錯誤：{anc['error']}")
    lines += ["", "## 逐檔結果", "", "| 檔案 | 頁 | basis | unit | scale | usable | warnings |", "|---|---|---|---|---|---|---|"]
    for r in result["files"]:
        w = "；".join(r["warnings"]).replace("|", "/")
        lines.append(
            f"| {r['file']} | {r['page']} | {r['basis']} | {r['unit']} | {r['scale']} | "
            f"{'是' if r['usable'] else '否'} | {w} |"
        )
    bad = [r for r in result["files"] if not r["usable"]]
    lines += ["", "## 未可用檔根因與建議工作包", ""]
    if not bad:
        lines.append("無。")
    for r in bad:
        cause, pkg = _root_cause(r)
        lines.append(f"- {r['file']}：{cause}。建議：{pkg}。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="台股年報 FY 損益表解析驗收")
    ap.add_argument("--out", default=_DEFAULT_OUT)
    ap.add_argument("--report", default=_DEFAULT_REPORT, help="驗收報告 markdown 路徑")
    args = ap.parse_args(argv)

    files: list[dict] = []
    anchor_fy: FyIncome | None = None
    for name in ACCEPTANCE_FILES:
        rec, fy = _extract_one(name, _REPORT_DIR)
        files.append(rec)
        if name == ANCHOR_FILE:
            anchor_fy = fy
        print(
            f"{name}: usable={rec['usable']} page={rec['page']} basis={rec['basis']} scale={rec['scale']}"
            + ("" if rec["usable"] else f" warnings={'；'.join(rec['warnings'])}"),
            flush=True,
        )
    usable = sum(1 for r in files if r["usable"])
    result = {
        "files": files,
        "usable_count": usable,
        "total_files": len(ACCEPTANCE_FILES),
        "anchor_3653": _anchor_3653(anchor_fy, _REPORT_DIR),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rep = Path(args.report)
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(render_report(result), encoding="utf-8")
    print(
        f"SUMMARY usable={usable} total_files={result['total_files']} "
        f"anchor_3653_all_equal={result['anchor_3653']['all_equal']}"
    )
    return 0 if usable >= MIN_USABLE else 1


if __name__ == "__main__":
    sys.exit(main())
