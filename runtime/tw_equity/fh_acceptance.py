"""fh_acceptance.py — 金控（fh）驗收工具（Spec 2026-10-09-tw-equity-fh-schema §9、§0.3）。

CLI：./.venv/bin/python -m runtime.tw_equity.fh_acceptance [--tickers 2881,2886]
對 6 家金控讀 H1 財報與年報（本地快取／PDF，不打外部 API、無 OCR、無 LLM），逐家輸出：
勾稽通過數／總數與未過項、n_unmapped、附註值 vs 期望、年報錨點起頁、FY scope／usable、TTM 狀態、
ifrs17_break、bridge 殘差；末行 `PASS n/N`。exit code：全部通過且無未知代號 → 0，否則 1。

分層：collect_company（讀 PDF → 純資料 facts）／judge_company（facts → 判定，逐條對映 §0.3）／render／main。
`PASS n/N` 的 N ＝ 合法（6 家名單內）代號數；未知代號另輸出錯誤行且使 exit code 非 0，不計入 N。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from runtime.tw_equity.fh_schema import FH_CHECK_SPECS

_REPO_ROOT = Path(__file__).resolve().parents[2]

TICKERS: tuple[str, ...] = ("2881", "2882", "2885", "2886", "2887", "2891")

# §0.3：金控 bridge 殘差絕對值上限（仟元；使用者 2026-10-09 裁示，無例外）
BRIDGE_RESIDUAL_LIMIT = 2.0
# §0.3／§4.2：附註比對的期間
NPL_PERIOD = "115-06-30"
ANCHOR_KEYS: tuple[str, ...] = ("ar_business", "ar_mdna", "ar_fin_performance")  # §0.3／§5

# §6.4／§6.5：FY 損益 scope 與 TTM scope 期望
EXPECTED_SCOPE: dict[str, str] = {
    "2881": "consolidated", "2885": "consolidated", "2886": "consolidated",
    "2882": "parent_only", "2887": "parent_only", "2891": "parent_only",
}
# §4.1：集團 CAR 期望（值, 期間）；2887 未揭露 → (None, None)
EXPECTED_CAR: dict[str, tuple[float | None, str | None]] = {
    "2881": (139.13, "114-06-30"), "2882": (120.22, "114-06-30"),
    "2885": (130.70, "114-06-30"), "2886": (133.83, "114-06-30"),
    "2887": (None, None), "2891": (125.07, "114-12-31"),
}
# §4.2：115-06-30 主值（npl_ratio, coverage_ratio）
EXPECTED_NPL: dict[str, tuple[float, float]] = {
    "2881": (0.11, 1112.78), "2882": (0.14, 1100.45), "2885": (0.11, 1091.36),
    "2886": (0.20, 813.14), "2887": (0.13, 922.63), "2891": (0.54, 280.47),
}
EXPECTED_TTM_STATUS = "ok"  # §6.5


# ── 蒐集（讀 PDF；唯一碰檔案處） ─────────────────────────────────────────────

def facts_from_bundle(ticker: str, bundle: Any, ar_anchors: dict) -> dict:
    """把 extract_tables 的 bundle（或同形物件：statements／fy_income／fh_notes／metrics）與年報錨點轉為純資料 facts。"""
    led, fy, notes, pack = bundle.statements, bundle.fy_income, bundle.fh_notes, bundle.metrics
    facts: dict[str, Any] = {"ticker": ticker, "error": None}
    facts["checks"] = [{"name": c.name, "period": c.period, "lhs": c.lhs, "rhs": c.rhs, "passed": c.passed}
                       for c in (led.checks if led else [])]
    facts["n_unmapped"] = len(led.unmapped_labels) if led else None
    if notes is None:
        facts["car"] = {"value": None, "period": None}
        facts["npl"] = None
    else:
        car = notes.group_car
        facts["car"] = {"value": car.value, "period": car.period}
        row = next((p for p in ((notes.npl or {}).get("periods") or []) if p.get("period") == NPL_PERIOD), None)
        facts["npl"] = None if row is None else {
            "period": row["period"], "npl_ratio": row.get("npl_ratio"),
            "coverage_ratio": row.get("coverage_ratio"), "entity": row.get("entity")}
    facts["notes_error"] = getattr(bundle, "fh_notes_error", None)
    facts["anchors"] = {k: (None if ar_anchors.get(k) is None else ar_anchors[k].start) for k in ANCHOR_KEYS}
    facts["fy"] = None if fy is None else {"scope": fy.scope, "usable": fy.usable, "page": fy.page}
    ttm = pack.ttm if pack else None
    facts["ttm"] = None if ttm is None else {"status": ttm.status, "scope": ttm.scope, "reason": ttm.reason,
                                              "comparability": ttm.comparability}
    facts["ifrs17_break"] = None if pack is None else pack.ifrs17_break
    bridge = next((b for b in (pack.bridges if pack else []) if b.target == "net_income"), None)
    facts["bridge_residual"] = None if bridge is None else bridge.residual
    return facts


def collect_company(ticker: str, base_dir: Path = _REPO_ROOT) -> dict:
    """讀該家輸入檔、H1 財報與年報（本地快取／PDF），回 facts。缺檔 raise FileNotFoundError（訊息含檔名）。"""
    from runtime.tw_equity import pdf_doc
    from runtime.tw_equity.doc_anchor import (
        FS_HEADING_ANCHORS, GOVERNANCE_HEADING_ANCHORS, find_annual_report_sections, find_heading_sections)
    from runtime.tw_equity.inputs import load_inputs
    from runtime.tw_equity.tables import extract_tables

    inputs = load_inputs(ticker, base_dir=base_dir)
    if inputs.group != "fh":
        raise ValueError(f"輸入檔 group 非 fh：{inputs.group!r}")
    if inputs.consolidated_fs_path is None:
        raise FileNotFoundError(f"{ticker} 輸入檔未指定 H1 財報（consolidated_fs_path）")
    ar = pdf_doc.load_pdf(inputs.annual_report_path)
    fs = pdf_doc.load_pdf(inputs.consolidated_fs_path)
    ar_anchors = find_annual_report_sections(ar, required=set(), group="fh")
    gov = find_heading_sections(ar, GOVERNANCE_HEADING_ANCHORS, required=set())
    fs_anchors = find_heading_sections(fs, FS_HEADING_ANCHORS, required=set())
    bundle = extract_tables(ar, ar_anchors, fs, fs_anchors, None, None,
                            roc_year=inputs.roc_year, gov_anchors=gov, group="fh")
    return facts_from_bundle(ticker, bundle, ar_anchors)


# ── 判定（純函式；§0.3 逐條） ───────────────────────────────────────────────

def _fail(item: str, detail: str, cause: str) -> dict:
    return {"item": item, "detail": detail, "cause": cause}


def _equal(a: float | None, b: float | None) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-9)


def judge_company(ticker: str, facts: dict) -> dict:
    """facts → {"ticker","ok","failures":[{item,detail,cause}],"facts"}；每項不符都列一筆 failure。"""
    if facts.get("error"):
        return {"ticker": ticker, "ok": False, "facts": facts,
                "failures": [_fail("執行", facts["error"], "資料載入或解析失敗")]}
    fails: list[dict] = []

    # §0.3-1：H1 勾稽全 passed=True
    checks = facts["checks"]
    expected = {(name, p) for name, _l, _r in FH_CHECK_SPECS for p in ("current", "prior")}
    if not checks:
        fails.append(_fail("勾稽", "無勾稽結果", "三表帳本缺失，無法勾稽"))
    elif len(checks) != len(expected):
        got = {(c["name"], c["period"]) for c in checks}
        missing = sorted(f"{n}/{p}" for n, p in expected - got)
        fails.append(_fail("勾稽筆數", f"{len(checks)} ≠ 期望 {len(expected)}",
                           f"勾稽筆數不符（§0.3 每項×current／prior），缺：{'、'.join(missing) or '（重複項）'}"))
    for c in checks:
        if c["passed"] is True:
            continue
        label = f"勾稽:{c['name']}/{c['period']}"
        if c["passed"] is None:
            fails.append(_fail(label, f"lhs={c['lhs']} rhs={c['rhs']}", "輸入列缺值，無法勾稽（科目對照或解析缺列）"))
        else:
            diff = c["lhs"] - c["rhs"]
            fails.append(_fail(label, f"lhs={c['lhs']} rhs={c['rhs']} 差={diff}", f"兩側差額 {diff} 仟元超出容許誤差"))

    # §0.3-3：年報三錨點非 None
    for k in ANCHOR_KEYS:
        if not _anchor_found(facts["anchors"].get(k)):
            fails.append(_fail(f"錨點:{k}", "None", "年報章名／關鍵字未命中，錨點缺失"))

    # §0.3-4：FY usable＋scope；TTM 狀態
    fy = facts["fy"]
    if fy is None:
        fails.append(_fail("FY", "無 FY 損益結果", "年報找不到 FY 損益比較表（候選頁缺失）"))
    else:
        if fy["scope"] != EXPECTED_SCOPE[ticker]:
            fails.append(_fail("FY scope", f"{fy['scope']} ≠ 期望 {EXPECTED_SCOPE[ticker]}", "FY 表選用範圍（合併／個體）與 §6.4 期望不符"))
        if fy["usable"] is not True:
            fails.append(_fail("FY usable", str(fy["usable"]), "FY 損益關鍵科目缺值或單位無法辨識（§6.4）"))
    ttm = facts["ttm"]
    if ttm is None or ttm["status"] != EXPECTED_TTM_STATUS:
        why = "無 TTM 結果" if ttm is None else f"status={ttm['status']} reason={ttm['reason']}"
        fails.append(_fail("TTM", why, "TTM 前提不成立（§6.5 期望 ok）"))
    elif ttm["scope"] != EXPECTED_SCOPE[ticker]:
        fails.append(_fail("TTM scope", f"{ttm['scope']} ≠ 期望 {EXPECTED_SCOPE[ticker]}", "TTM scope 與 §6.5 期望不符"))

    # §0.3-5：附註逐值相等
    exp_v, exp_p = EXPECTED_CAR[ticker]
    car = facts["car"]
    if not (_equal(car["value"], exp_v) and car["period"] == exp_p):
        fails.append(_fail("附註 group_car", f"{car['value']}@{car['period']} ≠ 期望 {exp_v}@{exp_p}", "集團 CAR 值或期間與 §4.1 期望不符"))
    exp_npl, exp_cov = EXPECTED_NPL[ticker]
    npl = facts["npl"]
    if npl is None:
        fails.append(_fail("附註 npl", f"無 {NPL_PERIOD} 期", f"逾放比／覆蓋率 {NPL_PERIOD} 未抽到（§4.2）"))
    else:
        if not _equal(npl["npl_ratio"], exp_npl):
            fails.append(_fail("附註 npl_ratio", f"{npl['npl_ratio']} ≠ 期望 {exp_npl}", "逾放比與 §4.2 期望不符"))
        if not _equal(npl["coverage_ratio"], exp_cov):
            fails.append(_fail("附註 coverage_ratio", f"{npl['coverage_ratio']} ≠ 期望 {exp_cov}", "覆蓋率與 §4.2 期望不符"))

    # §0.3-6：bridge 殘差 ≤ 2 仟元
    res = facts["bridge_residual"]
    if res is None:
        fails.append(_fail("bridge 殘差", "None", "bridge 缺失或殘差無法計算"))
    elif not (abs(res) <= BRIDGE_RESIDUAL_LIMIT):  # NaN 亦判 FAIL
        fails.append(_fail("bridge 殘差", f"{res}", f"殘差絕對值 {abs(res)} 仟元超過上限 {BRIDGE_RESIDUAL_LIMIT}"))

    return {"ticker": ticker, "ok": not fails, "failures": fails, "facts": facts}


def _anchor_found(start: int | None) -> bool:
    """驗收判定的單一錨點判準：起頁非 None 即視為錨點命中。"""
    return start is not None


# ── 輸出與 CLI ─────────────────────────────────────────────────────────────

def render_company(v: dict) -> str:
    f = v["facts"]
    lines = [f"[{v['ticker']}] {'PASS' if v['ok'] else 'FAIL'}"]
    if f.get("error"):
        lines.append(f"  錯誤：{f['error']}")
    else:
        checks = f["checks"]
        ok_n = sum(1 for c in checks if c["passed"] is True)
        lines.append(f"  勾稽：{ok_n}/{len(checks)} 通過")
        lines.append(f"  n_unmapped：{f['n_unmapped']}")
        exp_v, exp_p = EXPECTED_CAR[v["ticker"]]
        lines.append(f"  附註 group_car：{f['car']['value']}@{f['car']['period']}（期望 {exp_v}@{exp_p}）")
        npl = f["npl"] or {}
        e_n, e_c = EXPECTED_NPL[v["ticker"]]
        lines.append(f"  附註 npl_ratio：{npl.get('npl_ratio')}（期望 {e_n}）；coverage_ratio：{npl.get('coverage_ratio')}（期望 {e_c}）")
        lines.append("  錨點起頁：" + "、".join(f"{k}={f['anchors'].get(k)}" for k in ANCHOR_KEYS))
        fy = f["fy"] or {}
        lines.append(f"  FY：scope={fy.get('scope')} usable={fy.get('usable')} page={fy.get('page')}")
        ttm = f["ttm"] or {}
        lines.append(f"  TTM：status={ttm.get('status')} scope={ttm.get('scope')} comparability={ttm.get('comparability')}")
        lines.append(f"  ifrs17_break：{f['ifrs17_break']}")
        lines.append(f"  bridge 殘差：{f['bridge_residual']}（上限 ±{BRIDGE_RESIDUAL_LIMIT}）")
    for x in v["failures"]:
        lines.append(f"  FAIL 家別={v['ticker']} 項目={x['item']} 明細={x['detail']} 根因={x['cause']}")
    return "\n".join(lines)


def run_tickers(tickers: list[str], collect: Callable[[str], dict]) -> list[dict]:
    """逐家蒐集＋判定；單家例外（含缺檔）轉為該家 FAIL，不中斷。"""
    out = []
    for t in tickers:
        try:
            facts = collect(t)
        except FileNotFoundError as e:
            facts = {"ticker": t, "error": f"缺檔：{e}"}
        except Exception as e:  # 單家失敗不中斷其他家
            facts = {"ticker": t, "error": f"{type(e).__name__}: {e}"}
        out.append(judge_company(t, facts))
    return out


def main(argv: list[str] | None = None, *, collect: Callable[[str], dict] | None = None) -> int:
    ap = argparse.ArgumentParser(description="台股金控（fh）驗收")
    ap.add_argument("--tickers", default=",".join(TICKERS), help="逗號分隔代號；預設 6 家")
    args = ap.parse_args(argv)
    requested = list(dict.fromkeys(t.strip() for t in args.tickers.split(",") if t.strip()))
    unknown = [t for t in requested if t not in TICKERS]
    valid = [t for t in requested if t in TICKERS]
    for t in unknown:
        print(f"ERROR 未知代號 {t}（合法：{','.join(TICKERS)}）", flush=True)
    verdicts = run_tickers(valid, collect or collect_company)
    for v in verdicts:
        print(render_company(v), flush=True)
    n_ok = sum(1 for v in verdicts if v["ok"])
    print(f"PASS {n_ok}/{len(verdicts)}", flush=True)
    return 0 if verdicts and n_ok == len(verdicts) and not unknown else 1


if __name__ == "__main__":
    sys.exit(main())
