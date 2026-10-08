"""report.py — 台股財報 pipeline 報告輸出（md＋pdf＋raw.json）。

契約：Spec §2.8。skill 結果缺 key 時印「（skill 未回傳）」，不用 `.get(k, {})` 吞成空白。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.tw_equity.inputs import TwEquityInputs
from runtime.tw_equity.tables import TablesBundle

_NO_RETURN = "（skill 未回傳）"
_NO_TABLE = "未取得"
_NO_ANCHOR = "未錨定"
_NO_COVERAGE = "無法計算（缺個體／合併營業成本）"
_NA = "—"


# ── 文字／格式工具 ────────────────────────────────────────────────────────────


def _t(x: Any) -> str:
    """文字過 tone_filter；None → 「—」。"""
    from report_writer import tone_filter

    if x is None:
        return _NA
    return tone_filter(str(x))


def _c(x: Any) -> str:
    """表格 cell：過 tone_filter 後再 escape。"""
    from report_writer import _escape_md_cell

    return _escape_md_cell(_t(x))


def _num(v: Any) -> str:
    if v is None:
        return _NA
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{int(v):,}" if float(v) == int(v) else f"{v:,.2f}"
    return _t(v)


def _md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(_c(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_c(x) if isinstance(x, str) else _c(_num(x)) for x in r) + " |")
    return out


def _get(d: Any, key: str) -> Any:
    """讀欄位；缺 key（或 d 非 dict）回傳哨兵字串，不吞成空白。"""
    if isinstance(d, dict) and key in d:
        return d[key]
    return _NO_RETURN


def _val(d: Any, key: str) -> str:
    v = _get(d, key)
    if v is _NO_RETURN:
        return _NO_RETURN
    return _num(v) if not isinstance(v, str) else _t(v)


def _list_of(d: Any, key: str) -> list | str:
    """回傳 list；缺 key／型別不符回傳哨兵字串。"""
    v = _get(d, key)
    return v if isinstance(v, list) else _NO_RETURN


def _bullets(lines_or_msg: list[str] | str) -> list[str]:
    if isinstance(lines_or_msg, str):
        return [f"- {lines_or_msg}"]
    return lines_or_msg or ["- （無）"]


# ── skill 節 render ───────────────────────────────────────────────────────────


def _skill_guard(skill_results: dict, name: str) -> tuple[dict | None, list[str] | None]:
    """回傳 (result, None)；或 (None, 降級行)。"""
    if name not in skill_results or not isinstance(skill_results[name], dict):
        return None, [_NO_RETURN]
    res = skill_results[name]
    if "error" in res:
        return None, [f"本節 skill 失敗：{_t(res['error'])}"]
    return res, None


def _insufficient_line(res: dict) -> list[str]:
    if "insufficient_data" not in res:
        return [f"資料充足性：{_NO_RETURN}"]
    return ["> 資料不足，以下內容僅供參考。"] if res["insufficient_data"] else []


def _render_cost_structure(skill_results: dict) -> list[str]:
    res, fallback = _skill_guard(skill_results, "tw_cost_structure")
    if fallback:
        return fallback
    L = _insufficient_line(res)
    L.append(f"- 涵蓋基礎：{_val(res, 'coverage_basis')}")
    L.append(f"- 涵蓋說明：{_val(res, 'coverage_note')}")
    L += ["", "**成本組成**"]
    items = _list_of(res, "cost_composition")
    L += _bullets(items if isinstance(items, str) else [
        f"- {_val(i, 'item')}：占比 {_val(i, 'share_pct')}%，YoY {_val(i, 'yoy_pct')}%；{_val(i, 'note')}"
        for i in items])
    L += ["", "**費用性質**"]
    items = _list_of(res, "expense_nature")
    L += _bullets(items if isinstance(items, str) else [
        f"- {_val(i, 'item')}：占營收 {_val(i, 'pct_of_revenue')}%；{_val(i, 'note')}" for i in items])
    L += ["", "**存貨**"]
    inv = _get(res, "inventory")
    if inv is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- 結構：{_val(inv, 'structure_note')}")
        L.append(f"- 跌價：{_val(inv, 'writedown_note')}")
    L += ["", "**單位經濟**"]
    items = _list_of(res, "unit_economics")
    L += _bullets(items if isinstance(items, str) else [
        f"- {_val(i, 'product')}：單價 {_val(i, 'implied_asp')}，單位成本 {_val(i, 'implied_unit_cost')}；{_val(i, 'note')}"
        for i in items])
    L += ["", "**營業槓桿**"]
    ol = _get(res, "operating_leverage")
    if ol is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- 營收 YoY {_val(ol, 'revenue_yoy_pct')}%，營業利益 YoY {_val(ol, 'operating_income_yoy_pct')}%")
        L.append(f"- {_val(ol, 'summary')}")
    L += ["", "**重點觀察**"]
    obs = _list_of(res, "key_observations")
    L += _bullets(obs if isinstance(obs, str) else [f"- {_t(o)}" for o in obs])
    return L


def _render_financial_analysis(skill_results: dict) -> list[str]:
    res, fallback = _skill_guard(skill_results, "tw_financial_analysis")
    if fallback:
        return fallback
    L = _insufficient_line(res)
    L.append(f"- 整體體質：{_val(res, 'overall_health')}")
    L.append(f"- 理由：{_val(res, 'overall_health_rationale')}")
    L += ["", "**資產負債表**"]
    bs = _get(res, "balance_sheet")
    if bs is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- {_val(bs, 'summary')}")
        ch = _list_of(bs, "notable_changes")
        L += _bullets(ch if isinstance(ch, str) else [
            f"- {_val(i, 'item')}：{_val(i, 'diff_pct')}%；{_val(i, 'note')}" for i in ch])
    L += ["", "**損益表**"]
    inc = _get(res, "income_statement")
    if inc is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- {_val(inc, 'summary')}")
        mg = _list_of(inc, "margins")
        L += _bullets(mg if isinstance(mg, str) else [
            f"- {_val(i, 'metric')}：本期 {_val(i, 'current_pct')}%，前期 {_val(i, 'prior_pct')}%" for i in mg])
    L += ["", "**管理層說明**"]
    me = _get(res, "management_explanation")
    if me is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- 與數字一致：{_val(me, 'consistent')}")
        L.append(f"- {_val(me, 'summary')}")
        un = _list_of(me, "unexplained_changes")
        L += _bullets(un if isinstance(un, str) else [
            f"- 未解釋變動：{_val(i, 'item')}（{_val(i, 'diff_pct')}%）" for i in un])
    return L


def _render_footnotes_quality(skill_results: dict) -> list[str]:
    res, fallback = _skill_guard(skill_results, "tw_footnotes_quality")
    if fallback:
        return fallback
    L = _insufficient_line(res)
    L += ["**關係人交易**"]
    rp = _list_of(res, "related_party")
    L += _bullets(rp if isinstance(rp, str) else [
        f"- {_val(i, 'counterparty')}（{_val(i, 'nature')}）：{_val(i, 'amount_note')}［{_val(i, 'flag')}］"
        for i in rp])
    L += ["", "**或有事項**"]
    ct = _list_of(res, "contingencies")
    L += _bullets(ct if isinstance(ct, str) else [
        f"- {_val(i, 'item')}：{_val(i, 'note')}" for i in ct])
    L += ["", "**背書保證與資金貸與**"]
    gl = _get(res, "guarantees_and_loans")
    if gl is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- {_val(gl, 'summary')}［{_val(gl, 'flag')}］")
    L += ["", "**關鍵查核事項**"]
    kam = _list_of(res, "kam")
    L += _bullets(kam if isinstance(kam, str) else [
        f"- {_val(i, 'matter')}：{_val(i, 'risk_pointed')}" for i in kam])
    L += ["", "**重點觀察**"]
    obs = _list_of(res, "key_observations")
    L += _bullets(obs if isinstance(obs, str) else [f"- {_t(o)}" for o in obs])
    return L


# ── 附錄 A：解析表 ────────────────────────────────────────────────────────────


def _two_year(tbl) -> list[str]:
    rows = [[r.label, r.current, r.prior, r.diff, r.diff_pct] for r in tbl.rows]
    return [f"單位：{_t(tbl.unit)}", ""] + _md_table(
        ["項目", tbl.current_label, tbl.prior_label, "差異", "差異%"], rows)


def _customers(tbl) -> list[str]:
    L = [f"單位：{_t(tbl.unit)}"]
    for y in tbl.years:
        L += ["", f"{_t(y.label)}（合計 {_num(y.total)}；其他 {_num(y.others_pct)}%）"]
        L += _md_table(["排名", "名稱", "金額", "比率%", "關係"],
                       [[e.rank, e.name, e.amount, e.pct, e.relation] for e in y.entries])
    return L


def _expense_nature(tbl) -> list[str]:
    headers = ["項目"] + [f"{p} {k}" for p in tbl.periods for k in ("銷貨成本", "營業費用", "合計")]
    rows = []
    for r in tbl.rows:
        row: list[Any] = [r.label]
        for i in range(len(tbl.periods)):
            row += [r.cost_of_sales[i], r.opex[i], r.total[i]]
        rows.append(row)
    return [f"單位：{_t(tbl.unit)}", ""] + _md_table(headers, rows)


def _inventory(tbl) -> list[str]:
    headers = ["項目"] + [f"{p} {k}" for p in tbl.periods for k in ("成本", "備抵跌價", "淨額")]
    rows = []
    for r in tbl.rows:
        row: list[Any] = [r.label]
        for i in range(len(tbl.periods)):
            row += [r.cost[i], r.allowance[i], r.net[i]]
        rows.append(row)
    L = [f"單位：{_t(tbl.unit)}", ""] + _md_table(headers, rows)
    if tbl.writedown is not None:
        L += ["", "存貨跌價損失（回升利益）：" + "、".join(_num(v) for v in tbl.writedown)]
    return L


def _cost_detail(tbl) -> list[str]:
    rows = [[r.label, *r.values] for r in tbl.rows]
    return [f"單位：{_t(tbl.unit)}", ""] + _md_table(["項目", *tbl.periods], rows)


def _appendix_a(bundle: TablesBundle) -> list[str]:
    specs = [
        ("T7a 財務狀況比較表", bundle.fin_position, _two_year),
        ("T7b 財務績效比較表", bundle.fin_performance, _two_year),
        ("T8 主要銷貨客戶", bundle.customers_sales, _customers),
        ("T8 主要進貨客戶", bundle.customers_purchase, _customers),
        ("T4 費用性質", bundle.expense_nature, _expense_nature),
        ("T5 存貨附註", bundle.inventory, _inventory),
        ("T1 營業成本明細", bundle.cost_detail_cogs, _cost_detail),
        ("T2 製造費用明細", bundle.cost_detail_mfg, _cost_detail),
        ("T3 營業費用明細", bundle.cost_detail_opex, _cost_detail),
    ]
    L: list[str] = []
    for title, tbl, fn in specs:
        L += [f"### {title}", ""]
        L += [_NO_TABLE] if tbl is None else fn(tbl)
        L.append("")
    return L


# ── 附錄 B：錨定與缺表 ────────────────────────────────────────────────────────


def _fmt_anchor(v: Any) -> str:
    if v is None:
        return _NO_ANCHOR
    if hasattr(v, "start") and hasattr(v, "end"):
        s, e = v.start, v.end
    elif isinstance(v, dict) and "start" in v and "end" in v:
        s, e = v["start"], v["end"]
    elif isinstance(v, (list, tuple)) and len(v) == 2:
        s, e = v
    else:
        return _t(v)
    return f"p{s}" if s == e else f"p{s}–{e}"


def _appendix_b(bundle: TablesBundle, anchors_summary: dict, skipped_tasks: list[str]) -> list[str]:
    L = ["### 錨定頁碼", ""]
    L += _md_table(["anchor key", "頁碼範圍"],
                   [[k, _fmt_anchor(v)] for k, v in anchors_summary.items()]) if anchors_summary else ["（無錨定資訊）"]
    L += ["", "### 缺表清單", ""]
    L += [f"- {_t(m)}" for m in bundle.missing_tables] or ["- （無）"]
    L += ["", "### 母公司成本涵蓋率", ""]
    cov = bundle.parent_cost_coverage
    L.append(_NO_COVERAGE if cov is None else f"parent_cost_coverage = {cov:.4f}")
    if skipped_tasks:
        L += ["", "### 跳過的任務", ""] + [f"- {_t(s)}" for s in skipped_tasks]
    return L


# ── 主函式 ────────────────────────────────────────────────────────────────────


def save_tw_equity_report(
    *,
    inputs: TwEquityInputs,
    bundle: TablesBundle,
    anchors_summary: dict,
    skill_results: dict,
    eval_results: dict,
    skipped_tasks: list[str],
    out_dir: Path | None = None,
) -> Path:
    """輸出 md／pdf／raw.json 到 out_dir（預設 data/output/<ticker>/），回傳 md 路徑。"""
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M")
    out_dir = Path(out_dir) if out_dir is not None else Path("data/output") / inputs.ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{inputs.ticker}_{ts}"

    lines: list[str] = [
        f"# {_t(inputs.company_name)}（{inputs.ticker}）{inputs.fiscal_year} 年度財報分析",
        "",
        f"產生時間：{now.strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 1. 成本結構", "", *_render_cost_structure(skill_results), "",
        "## 2. 財務分析", "", *_render_financial_analysis(skill_results), "",
        "## 3. 附註品質", "", *_render_footnotes_quality(skill_results), "",
        "## 附錄 A：解析表原始數字", "", *_appendix_a(bundle),
        "## 附錄 B：錨定與缺表", "", *_appendix_b(bundle, anchors_summary, skipped_tasks), "",
    ]
    md_text = "\n".join(lines)

    md_path = out_dir / f"{stem}_tw_report.md"
    md_path.write_text(md_text, encoding="utf-8")

    raw = {
        "bundle": bundle.to_dict(),
        "skill_results": skill_results,
        "eval_results": eval_results,
        "anchors_summary": anchors_summary,
    }
    (out_dir / f"{stem}_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    import markdown
    from report_writer import _build_pdf_css
    from weasyprint import HTML

    html = markdown.markdown(md_text, extensions=["tables"])
    doc = (f"<html><head><meta charset='utf-8'><style>{_build_pdf_css()}</style></head>"
           f"<body>{html}</body></html>")
    HTML(string=doc).write_pdf(str(out_dir / f"{stem}_tw_report.pdf"))
    return md_path
