"""report.py — 台股財報 pipeline 報告輸出（md＋pdf＋raw.json）。

契約：Spec §2.8。skill 結果缺 key 時印「（skill 未回傳）」，不用 `.get(k, {})` 吞成空白。
"""

from __future__ import annotations

import json
import re
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


def _not_executed(task_id: str) -> list[str]:
    return [f"本節未執行：輸入資料不足（{task_id}）"]


_NARRATIVE_STATUS = {"consistent": "一致", "inconsistent": "不一致", "unverifiable": "無法驗證"}


def _render_kam_analysis(skill_results: dict, skipped_tasks: list[str]) -> list[str]:
    if "tw_kam_analysis" in skipped_tasks:
        return _not_executed("tw_kam_analysis")
    res, fallback = _skill_guard(skill_results, "tw_kam_analysis")
    if fallback:
        return fallback
    L = _insufficient_line(res)
    L += ["**關鍵查核事項**"]
    ms = _list_of(res, "matters")
    L += _bullets(ms if isinstance(ms, str) else [
        f"- {_val(i, 'matter')}（{_val(i, 'risk_area')}）：{_val(i, 'why_key')}；查核回應：{_val(i, 'audit_response')}"
        for i in ms])
    L += ["", "**與財報數字的連結**"]
    lk = _list_of(res, "linkage_to_numbers")
    L += _bullets(lk if isinstance(lk, str) else [
        f"- {_val(i, 'matter')}［{_val(i, 'table_ref')}］：{_val(i, 'observation')}" for i in lk])
    L += ["", "**重點觀察**"]
    obs = _list_of(res, "key_observations")
    L += _bullets(obs if isinstance(obs, str) else [f"- {_t(o)}" for o in obs])
    return L


def _render_business_analysis(skill_results: dict, skipped_tasks: list[str]) -> list[str]:
    if "tw_business_analysis" in skipped_tasks:
        return _not_executed("tw_business_analysis")
    res, fallback = _skill_guard(skill_results, "tw_business_analysis")
    if fallback:
        return fallback
    L = _insufficient_line(res)
    L.append(f"- 業務概述：{_val(res, 'business_summary')}")
    L += ["", "**主要產品**"]
    pr = _list_of(res, "products")
    L += _bullets(pr if isinstance(pr, str) else [
        f"- {_val(i, 'name')}：{_val(i, 'note')}" for i in pr])
    L += ["", "**管理層計畫**"]
    mp = _list_of(res, "management_plans")
    L += _bullets(mp if isinstance(mp, str) else [
        f"- {_val(i, 'plan')}（期間：{_val(i, 'horizon')}；可量化：{_val(i, 'measurable')}）" for i in mp])
    L += ["", "**敘述與數字對照**"]
    nv = _list_of(res, "narrative_vs_numbers")
    L += _bullets(nv if isinstance(nv, str) else [
        f"- {_val(i, 'claim')}［{_val(i, 'table_ref')}］："
        f"{_NARRATIVE_STATUS.get(_get(i, 'status'), _val(i, 'status'))}；{_val(i, 'note')}" for i in nv])
    L += ["", "**重點觀察**"]
    obs = _list_of(res, "key_observations")
    L += _bullets(obs if isinstance(obs, str) else [f"- {_t(o)}" for o in obs])
    return L


def _conc(d: Any, label: str) -> str:
    if d is _NO_RETURN:
        return f"- {label}：{_NO_RETURN}"
    return (f"- {label}：前一大 {_val(d, 'top1_pct')}%，前三大 {_val(d, 'top3_pct')}%，"
            f"趨勢 {_val(d, 'direction')}；{_val(d, 'note')}")


def _render_customer_supplier(skill_results: dict, skipped_tasks: list[str]) -> list[str]:
    if "tw_customer_supplier" in skipped_tasks:
        return _not_executed("tw_customer_supplier")
    res, fallback = _skill_guard(skill_results, "tw_customer_supplier")
    if fallback:
        return fallback
    L = _insufficient_line(res)
    L += ["**集中度**"]
    L.append(_conc(_get(res, "customer_concentration"), "客戶"))
    L.append(_conc(_get(res, "supplier_concentration"), "供應商"))
    L += ["", "**關係人往來對象**"]
    rc = _list_of(res, "related_counterparties")
    L += _bullets(rc if isinstance(rc, str) else [
        f"- {_val(i, 'name')}（{_val(i, 'kind')}）：{_val(i, 'relation')}" for i in rc])
    L += ["", "**議價力**"]
    bp = _get(res, "bargaining_power")
    if bp is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- 對客戶：{_val(bp, 'vs_customers')}；對供應商：{_val(bp, 'vs_suppliers')}")
        L.append(f"- {_val(bp, 'rationale')}")
    L += ["", "**重點觀察**"]
    obs = _list_of(res, "key_observations")
    L += _bullets(obs if isinstance(obs, str) else [f"- {_t(o)}" for o in obs])
    return L


def _render_governance_flags(skill_results: dict, skipped_tasks: list[str]) -> list[str]:
    if "tw_governance_flags" in skipped_tasks:
        return _not_executed("tw_governance_flags")
    res, fallback = _skill_guard(skill_results, "tw_governance_flags")
    if fallback:
        return fallback
    L = _insufficient_line(res)
    L += ["**質押**"]
    pl = _get(res, "pledge")
    if pl is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- 狀態：{_val(pl, 'status')}；最高質押比率 {_val(pl, 'max_pledge_pct')}%；"
                 f"警示：{_val(pl, 'flag')}")
        L.append(f"- {_val(pl, 'note')}")
    L += ["", "**股權結構**"]
    ow = _get(res, "ownership")
    if ow is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- {_val(ow, 'structure_note')}［{_val(ow, 'flag')}］")
        L.append(f"- 親屬關係：{_val(ow, 'family_relations_note')}")
    L += ["", "**董事會**"]
    bd = _get(res, "board")
    if bd is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- {_val(bd, 'independence_note')}［{_val(bd, 'flag')}］")
    L += ["", "**背書保證**"]
    gu = _get(res, "guarantees")
    if gu is _NO_RETURN:
        L.append(f"- {_NO_RETURN}")
    else:
        L.append(f"- {_val(gu, 'note')}［{_val(gu, 'flag')}］")
    L += ["", "**資本運作**"]
    ca = _list_of(res, "capital_actions")
    L += _bullets(ca if isinstance(ca, str) else [
        f"- {_val(i, 'item')}：{_val(i, 'note')}" for i in ca])
    L += ["", "**重點觀察**"]
    obs = _list_of(res, "key_observations")
    L += _bullets(obs if isinstance(obs, str) else [f"- {_t(o)}" for o in obs])
    return L


# ── 附錄 A：解析表 ────────────────────────────────────────────────────────────


def _render_cross_year_compare(cross_year_compare: dict | None) -> list[str]:
    if cross_year_compare is None:
        return ["本節未執行：未提供前一年度"]
    if not isinstance(cross_year_compare, dict):
        return [_NO_RETURN]
    if "error" in cross_year_compare:
        return [f"本節 skill 失敗：{_t(cross_year_compare['error'])}"]
    res = cross_year_compare
    L = _insufficient_line(res)
    L += ["**跨面向檢核**"]
    cc = _list_of(res, "cross_checks")
    if isinstance(cc, str):
        L += _bullets(cc)
    else:
        for i in cc:
            dims = _get(i, "dimensions")
            dims_s = "、".join(_t(d) for d in dims) if isinstance(dims, list) else _NO_RETURN
            L.append(f"- ［{dims_s}］{_val(i, 'finding')}；意涵：{_val(i, 'implication')}；"
                     f"方向：{_val(i, 'direction')}")
        if not cc:
            L.append("- （無）")
    L += ["", f"管理層可信度：{_val(res, 'mgmt_credibility')}（{_val(res, 'mgmt_credibility_reason')}）",
          f"品質趨勢：{_val(res, 'quality_trend')}",
          f"整體方向：{_val(res, 'overall_direction')}"]
    return L


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


def _guarantees_loans(tbl) -> list[str]:
    L = [f"資金貸與狀態：{_t(tbl.loans_status)}", f"背書保證狀態：{_t(tbl.guarantees_status)}"]
    if tbl.max_pct_of_net_worth is not None:
        L.append(f"最高占淨值比率：{_num(tbl.max_pct_of_net_worth)}%")
    if tbl.guarantees:
        L += [""] + _md_table(
            ["編號", "背書保證者", "被背書保證對象", "關係", "單項限額", "本期最高餘額", "期末餘額",
             "實際動支", "擔保金額", "占淨值%", "累計限額", "母對子", "子對母", "對大陸"],
            [[g.no, g.guarantor, g.guaranteed, g.relation_code, g.single_limit, g.max_balance,
              g.ending_balance, g.drawn, g.collateral, g.pct_of_net_worth, g.max_limit,
              g.parent_to_sub, g.sub_to_parent, g.to_china] for g in tbl.guarantees])
    return L


def _pledges(tbl) -> list[str]:
    L = [f"狀態：{_t(tbl.status)}"]
    if tbl.max_pledge_pct is not None:
        L.append(f"最高質押比率：{_num(tbl.max_pledge_pct)}%")
    if tbl.rows:
        L += [""] + _md_table(
            ["姓名", "事由", "日期", "質權人", "關係", "股數", "持股%", "質押%", "金額"],
            [[r.name, r.reason, r.date, r.counterparty, r.relation, r.shares, r.holding_pct,
              r.pledge_pct, r.amount] for r in tbl.rows])
    return L


def _top_shareholders(tbl) -> list[str]:
    L = _md_table(
        ["姓名", "代表人列", "持股數", "持股%", "配偶股數", "配偶%", "代名股數", "代名%"],
        [[r.name, "是" if r.is_representative else "否", r.shares, r.pct, r.spouse_shares,
          r.spouse_pct, r.nominee_shares, r.nominee_pct] for r in tbl.rows])
    if tbl.relation_notes:
        L += [""] + [f"- {_t(n)}" for n in tbl.relation_notes]
    return L


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
        ("T9 背書保證／資金貸與", bundle.guarantees_loans, _guarantees_loans),
        ("T10 股權質押", bundle.pledges, _pledges),
        ("T10 前十大股東", bundle.top_shareholders, _top_shareholders),
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


def _pages(pages: list[int] | None) -> str:
    return "、".join(f"p{n}" for n in pages) if pages else "無"


def _page_status(label: str, garbled: list[int] | None, ocr: list[int] | None,
                 ocr_checks: list[dict] | None) -> list[str]:
    L = [f"**{label}**", "",
         f"- 亂碼頁：{_pages(garbled)}",
         f"- 已 OCR 頁：{_pages(ocr)}"]
    failed = [c for c in (ocr_checks or []) if not c["passed"]]
    if failed:
        L += ["", "OCR 數字未通過檢查", ""]
        L += _md_table(["檢查", "表", "項目", "說明"],
                       [[c["check"], c["table"], c["label"], c["detail"]] for c in failed])
    return L


def _appendix_b(bundle: TablesBundle, anchors_summary: dict, skipped_tasks: list[str],
                garbled_pages: list[int] | None = None, ocr_pages: list[int] | None = None,
                ocr_checks: list[dict] | None = None, prior: dict | None = None) -> list[str]:
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
    L += ["", "### 亂碼頁與 OCR 頁", ""]
    L += _page_status("當年度", garbled_pages, ocr_pages, ocr_checks)
    if prior is not None:
        L += ["", "### 前一年度", ""]
        L += _page_status("前一年度頁面", prior["garbled_pages"], prior["ocr_pages"],
                          prior.get("ocr_checks"))
        L += ["", "**前一年度錨定頁碼**", ""]
        pa = prior["anchors_summary"]
        L += _md_table(["anchor key", "頁碼範圍"],
                       [[k, _fmt_anchor(v)] for k, v in pa.items()]) if pa else ["（無錨定資訊）"]
        L += ["", "**前一年度缺表清單**", ""]
        L += [f"- {_t(m)}" for m in prior["bundle"].missing_tables] or ["- （無）"]
        if prior["skipped_tasks"]:
            L += ["", "**前一年度跳過的任務**", ""] + [f"- {_t(s)}" for s in prior["skipped_tasks"]]
    return L


_NOT_OBTAINED = "未取得"


def _year_sort_key(label: str) -> tuple[int, str]:
    m = re.match(r"\s*(\d+)", str(label))
    return (int(m.group(1)) if m else 10**9, str(label))


def _appendix_c(cross_year: dict | None) -> list[str]:
    if cross_year is None:
        return ["本附錄未執行：未提供前一年度"]
    if not isinstance(cross_year, dict):
        return [_NO_RETURN]
    L = ["### 財務績效表序列", ""]
    series = _list_of(cross_year, "fin_performance_series")
    if isinstance(series, str):
        L.append(series)
    elif not series:
        L.append(_NOT_OBTAINED)
    else:
        years = sorted({y for r in series for y in r["values"]}, key=_year_sort_key)
        L += _md_table(["項目", *years],
                       [[r["label"], *[r["values"].get(y) for y in years]] for r in series])
    L += ["", "### 重疊年度數字檢查", ""]
    ov = _list_of(cross_year, "overlap_checks")
    if isinstance(ov, str):
        L.append(ov)
    elif not ov:
        L.append(_NOT_OBTAINED)
    else:
        bad = [o for o in ov if not o["match"]]
        if not bad:
            L.append("兩份文件重疊年度數字一致")
        else:
            L += _md_table(["表", "項目", "年度", "當年度文件", "前一年度文件"],
                           [[o["table"], o["label"], o["year"], o["current_doc"], o["prior_doc"]]
                            for o in bad])
    L += ["", "### 客戶集中度序列", ""]
    conc = _get(cross_year, "customer_concentration_series")
    if not isinstance(conc, dict):
        L.append(_NO_RETURN)
    else:
        for key in ("T8_sales", "T8_purchase"):
            L += [f"**{key}**", ""]
            rows = _list_of(conc, key)
            if isinstance(rows, str):
                L.append(rows)
            elif not rows:
                L.append(_NOT_OBTAINED)
            else:
                L += _md_table(["年度", "top1_pct"], [[r["label"], _val(r, "top1_pct")] for r in rows])
            L.append("")
        L.pop()
    L += ["", "### 前十大股東變動", ""]
    sh = _list_of(cross_year, "top_shareholders_change")
    if isinstance(sh, str):
        L.append(sh)
    elif not sh:
        L.append(_NOT_OBTAINED)
    else:
        L += _md_table(["股東", "當年度持股%", "前一年度持股%", "變動", "狀態"],
                       [[r["name"], r["current_pct"], r["prior_pct"], r["delta_pct"], r["status"]]
                        for r in sh])
    L += ["", "### 質押變動", ""]
    pc = _get(cross_year, "pledge_change")
    if not isinstance(pc, dict):
        L.append(_NO_RETURN)
    elif not pc:
        L.append(_NOT_OBTAINED)
    else:
        L += _md_table(["", "狀態", "最高質押比例%"],
                       [["當年度", _val(pc, "current_status"), _val(pc, "current_max_pct")],
                        ["前一年度", _val(pc, "prior_status"), _val(pc, "prior_max_pct")]])
    return L


_APPENDIX_D_UNMAPPED_MAX = 30
_CHECK_MARK = {True: "✅", False: "❌", None: "—"}


def _appendix_d(bundle: TablesBundle) -> list[str]:
    st = bundle.statements
    if st is None:
        return ["無合併財報或三表未解析"]
    d = st.to_dict()
    rc = d["row_counts"]
    L = [f"單位：{_t(d['unit']) or _NOT_OBTAINED}；期間：{_t(d['period_current'])} vs "
         f"{_t(d['period_prior'])}；列數：BS {rc['bs']}／IS {rc['is']}／CF {rc['cf']}；"
         f"未對照科目：{len(d['unmapped_labels'])}", ""]
    L += _md_table(["項目", "期間", "左值", "右值", "結果"],
                   [[c["name"], c["period"], c["lhs"], c["rhs"], _CHECK_MARK[c["passed"]]]
                    for c in d["checks"]])
    L += ["", "### 未對照科目", ""]
    un = d["unmapped_labels"]
    if not un:
        L.append("無")
    else:
        L.append("、".join(_t(u) for u in un[:_APPENDIX_D_UNMAPPED_MAX])
                 + ("…" if len(un) > _APPENDIX_D_UNMAPPED_MAX else ""))
    return L


def _appendix_e(bundle: TablesBundle) -> list[str]:
    mp = bundle.metrics
    if mp is None:
        return ["無帳本，未計算指標"]
    d = mp.to_dict()
    cur, pri = _t(d["period_current"]), _t(d["period_prior"])
    days = d["days"]
    L = ["### 指標", "", f"期間：本期 {cur}、上期 {pri}；金額單位仟元，比率 %，天數天，倍數 x", "",
         f"期間模型：基準 {_t(d['basis'])}；本期 {_t(d['periods'].get('flow_current'))}、"
         f"上期 {_t(d['periods'].get('flow_prior'))}；天數 {_num(days.get('current'))}／{_num(days.get('prior'))}；"
         f"確信等級 {_t(d['assurance'])}", ""]
    idx = d["index"]
    seen: list[tuple[str, str, str, str]] = []
    for m in d["metrics"]:
        if m["period"] == "current":
            seen.append((m["key"], m["name"], m["formula"], m["unit"]))
    L += _md_table(["指標", "公式", "本期", "上期", "單位"],
                   [[f"{name}（{key}）", formula, idx[key]["current"], idx[key]["prior"], unit]
                    for key, name, formula, unit in seen])
    L += ["", "### 變動歸因（bridge）", ""]
    for b in d["bridges"]:
        L += [f"#### {_t(b['name'])}（{b['target']}）：本期 {_num(b['target_current'])}、上期 "
              f"{_num(b['target_prior'])}、Δ {_num(b['target_delta'])}；主要驅動：{_t('、'.join(b['top_drivers'])) or _NA}", ""]
        rows = [[f"{_t(c['name'])}（{c['key']}）", c["current"], c["prior"], c["delta"],
                 None if c["share"] is None else c["share"] * 100] for c in b["components"]]
        rows.append(["殘差", None, None, b["residual"], None])
        L += _md_table(["組成項", "本期", "上期", "Δ", "占比%"], rows) + [""]
    L += _ttm_section(d["ttm_vs_fy"], bundle.fy_income_error)
    return L


def _ttm_section(t: dict | None, fy_error: str | None = None) -> list[str]:
    """「### TTM vs FY」小節；ttm 為 None（FY 帳本）且無解析錯誤時不輸出；FY 損益表解析失敗時加一行警示。"""
    if t is None and fy_error is None:
        return []
    L = ["### TTM vs FY", ""]
    if fy_error is not None:
        L += [f"⚠️ FY 損益表解析失敗：{_t(fy_error)}", ""]
    if t is None:
        return L
    if t["status"] != "ok":
        return L + [f"TTM 不可用：{_t(t['reason'])}"]
    L += [f"TTM 期間迄 {_t(t['period_ttm'])}；FY {_t(t['period_fy'])}（年報第 {_num(t['source_page'])} 頁）；"
          f"確信等級 {_t(t['assurance'])}；金額單位仟元", "", "#### TTM 損益組成", ""]
    L += _md_table(["科目", "FY", "H1 本期", "H1 上期", "TTM"],
                   [[k + ("（歸母代用）" if v.get("basis") == "parent" else ""),
                     v["fy"], v["h1_current"], v["h1_prior"], v["ttm"]] for k, v in t["values"].items()])
    idx = t["index"]
    seen = [(m["key"], m["name"], m["unit"]) for m in t["metrics"] if m["period"] == "ttm"]
    L += ["", "#### TTM 指標", ""]
    L += _md_table(["指標", "TTM", "FY", "單位"],
                   [[f"{name}（{key}）", idx[key]["ttm"], idx[key]["fy"], unit] for key, name, unit in seen])
    for b in t["bridges"]:
        L += ["", f"#### TTM {_t(b['name'])}（{b['target']}）：TTM {_num(b['target_current'])}、FY "
              f"{_num(b['target_prior'])}、Δ {_num(b['target_delta'])}；主要驅動：{_t('、'.join(b['top_drivers'])) or _NA}", ""]
        rows = [[f"{_t(c['name'])}（{c['key']}）", c["current"], c["prior"], c["delta"],
                 None if c["share"] is None else c["share"] * 100] for c in b["components"]]
        rows.append(["殘差", None, None, b["residual"], None])
        L += _md_table(["組成項", "TTM", "FY", "Δ", "占比%"], rows)
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
    cross_year_compare: dict | None = None,
    cross_year: dict | None = None,
    garbled_pages: list[int] | None = None,
    ocr_pages: list[int] | None = None,
    ocr_checks: list[dict] | None = None,
    prior: dict | None = None,
    out_dir: Path | None = None,
) -> Path:
    """輸出 md／pdf／raw.json 到 out_dir（預設 data/output/<ticker>/），回傳 md 路徑。

    prior：前一年度結果（無前一年度時為 None）。必備 key：
    bundle（TablesBundle）、anchors_summary（dict）、skill_results（dict）、
    skipped_tasks（list[str]）、garbled_pages（list[int]）、ocr_pages（list[int]）；
    選填 key：ocr_checks（list[dict]）。
    """
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
        "## 4. 關鍵查核事項", "", *_render_kam_analysis(skill_results, skipped_tasks), "",
        "## 5. 業務與管理層敘述", "", *_render_business_analysis(skill_results, skipped_tasks), "",
        "## 6. 客戶與供應商", "", *_render_customer_supplier(skill_results, skipped_tasks), "",
        "## 7. 公司治理警訊", "", *_render_governance_flags(skill_results, skipped_tasks), "",
        "## 8. 跨年比較", "", *_render_cross_year_compare(cross_year_compare), "",
        "## 附錄 A：解析表原始數字", "", *_appendix_a(bundle),
        "## 附錄 B：錨定與缺表", "", *_appendix_b(bundle, anchors_summary, skipped_tasks,
                                                garbled_pages, ocr_pages, ocr_checks, prior), "",
        "## 附錄 C：跨年表格比對", "", *_appendix_c(cross_year), "",
        "## 附錄 D：合併財報三表勾稽", "", *_appendix_d(bundle), "",
        "## 附錄 E：關鍵指標與變動歸因", "", *_appendix_e(bundle), "",
    ]
    md_text = "\n".join(lines)

    md_path = out_dir / f"{stem}_tw_report.md"
    md_path.write_text(md_text, encoding="utf-8")

    raw = {
        "bundle": bundle.to_dict(),
        "skill_results": skill_results,
        "eval_results": eval_results,
        "anchors_summary": anchors_summary,
        "garbled_pages": garbled_pages,
        "ocr_pages": ocr_pages,
        "ocr_checks": ocr_checks,
        "prior": None if prior is None else {
            "bundle": prior["bundle"].to_dict(),
            "anchors_summary": prior["anchors_summary"],
            "skill_results": prior["skill_results"],
            "skipped_tasks": prior["skipped_tasks"],
            "garbled_pages": prior["garbled_pages"],
            "ocr_pages": prior["ocr_pages"],
            "ocr_checks": prior.get("ocr_checks"),
        },
        "cross_year": cross_year,
        "cross_year_compare": cross_year_compare,
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
