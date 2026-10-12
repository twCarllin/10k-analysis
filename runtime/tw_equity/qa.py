"""qa.py — tw-equity 會計問答（G1：FCF 事實包＋模板答案＋數字核對；G2：主題事實包（FCF＋指標＋bridge）＋LLM 問答；
G3a：萬元／兆／pp 單位、方向詞核對、毛利 bridge 與毛利率拆解；G3b：TTM（ttm:*）與金控附註指標，--llm 時一併讀年報；
task/2026-10-09-tw-equity-qa-fcf.md、task/2026-10-09-tw-equity-qa-llm.md、task/2026-10-10-tw-equity-qa-g3a.md、
task/2026-10-10-tw-equity-qa-g3b.md）。

CLI：./.venv/bin/python -m runtime.tw_equity.qa --ticker 2317 --ask "本季影響 FCF 最多的是什麼？" [--json] [--llm]
只讀本地財報 PDF 與 OCR 快取；加 --llm 才呼叫 Azure（qa_llm.py）。FCF＝cfo＋capex（同 metrics 的 fcf）。
金額單位：帳本為新台幣仟元；答案換算為億元（1 億＝100,000 仟元）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.ar_sections import (
    SPECIAL_KEYS, STATUS_NONE, STATUS_PARSED, apply_cashflow_basis, parse_cashflow, parse_contracts, parse_special)
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_annual_report_sections, find_heading_sections
from runtime.tw_equity.inputs import uses_fh_schema
from runtime.tw_equity.metrics import BRIDGE_SPECS, TtmView, _build_bridge, _label_of, _value, compute_metrics
from runtime.tw_equity.statements import StatementLedger, StatementRow, extract_statements

_YI = 100_000  # 仟元 → 億元

# 營業活動各列的篩選：cfo 列之前、非投資／籌資區段（並排頁右半）、非小計列
_SUBTOTAL_RE = re.compile(r"營運產生|合計|小計|總額|淨現金|淨變動數$")
_OTHER_SECTION_RE = re.compile(r"投資活動|籌資活動")
_WC_START_RE = re.compile(r"資產/?(?:及)?負債")
_WC_HEADER_PREFIX_RE = re.compile(r"^與營業活動相關之資產/?(?:及)?負債(?:淨)?變動數")
_CASH_ITEM_RE = re.compile(r"^(?:收取|支付|退還|繳納)")

GROUPS = ("稅前淨利", "非現金調整", "營運資金變動", "利息股利與所得稅")


def _yi(v: float | None) -> str:
    return "—" if v is None else f"{v / _YI:,.2f}"


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}"


def _share(delta: float | None, total: float | None) -> float | None:
    return None if delta is None or not total else delta / total


def _delta(cur: float | None, pri: float | None) -> float | None:
    return None if cur is None or pri is None else cur - pri


def _item(label: str, cur: float | None, pri: float | None, page: int, **extra: Any) -> dict[str, Any]:
    return {"label": label, "current": cur, "prior": pri, "delta": _delta(cur, pri), "page": page, **extra}


def _operating_rows(cf: list[StatementRow], cfo_idx: int) -> list[StatementRow]:
    return [r for r in cf[:cfo_idx]
            if (r.current is not None or r.prior is not None)
            and not _SUBTOTAL_RE.search(r.label)
            and not _OTHER_SECTION_RE.search(r.section or "")]


def _grouped(rows: list[StatementRow]) -> list[tuple[StatementRow, str, str]]:
    """→ (row, 顯示 label, 分組)。營運資金區段自第一個「資產/負債」或 change_* 列起算（2330 區段標題黏在首列 label）。"""
    out: list[tuple[StatementRow, str, str]] = []
    in_wc = False
    for r in rows:
        label = _WC_HEADER_PREFIX_RE.sub("", r.label) or r.label
        if _WC_START_RE.search(r.section or "") or _WC_START_RE.search(r.label) or (r.key or "").startswith("change_"):
            in_wc = True
        if r.key == "pretax_income_cf" or (not in_wc and "稅前" in label):
            group = "稅前淨利"
        elif _CASH_ITEM_RE.match(label):
            group = "利息股利與所得稅"
        elif in_wc:
            group = "營運資金變動"
        else:
            group = "非現金調整"
        out.append((r, label, group))
    return out


def fcf_facts(ledger: StatementLedger | None) -> dict[str, Any]:
    """FCF 事實包：兩層變動歸因＋本期構成；每個數字帶頁碼。cfo／capex 缺 → {"answerable": False, "reason": …}。"""
    if ledger is None:
        return {"answerable": False, "reason": "財報三表解析失敗（無帳本）"}
    cf = sorted((r for r in ledger.rows if r.statement == "cf"), key=lambda r: (r.page, r.line_idx))
    cfo_idx = next((i for i, r in enumerate(cf) if r.key == "cfo"), None)
    capex = next((r for r in cf if r.key == "capex"), None)
    if cfo_idx is None or capex is None:
        missing = [n for n, ok in (("營業活動之淨現金流", cfo_idx is not None), ("取得不動產、廠房及設備", capex is not None)) if not ok]
        return {"answerable": False, "reason": f"現金流量表缺：{'、'.join(missing)}"}
    cfo = cf[cfo_idx]
    if None in (cfo.current, cfo.prior, capex.current, capex.prior):
        return {"answerable": False, "reason": "營業現金流或資本支出缺本期／去年同期金額"}

    fcf_cur, fcf_pri = cfo.current + capex.current, cfo.prior + capex.prior
    fcf_delta = fcf_cur - fcf_pri
    level1 = sorted(
        [_item("營業活動之淨現金流（CFO）", cfo.current, cfo.prior, cfo.page, key="cfo"),
         _item("資本支出（取得不動產、廠房及設備）", capex.current, capex.prior, capex.page, key="capex")],
        key=lambda x: -abs(x["delta"]))
    for x in level1:
        x["share"] = _share(x["delta"], fcf_delta)

    cfo_delta = cfo.current - cfo.prior
    level2: list[dict[str, Any]] = []
    for r, label, group in _grouped(_operating_rows(cf, cfo_idx)):  # 單側空值＝報表印「-」＝0
        it = _item(label, r.current or 0.0, r.prior or 0.0, r.page, group=group)
        it["share"] = _share(it["delta"], cfo_delta)
        level2.append(it)
    known = [x for x in level2 if x["delta"] is not None]
    groups = {g: sum(x["delta"] for x in known if x["group"] == g) for g in GROUPS}
    level2.sort(key=lambda x: (x["delta"] is None, -abs(x["delta"] or 0)))

    comp = [x for x in level2 if x["current"]] + [{"label": "資本支出（取得不動產、廠房及設備）",
                                                  "current": capex.current, "page": capex.page}]
    periods = ledger.column_periods.get("cf") or []
    cc, pc = ledger.current_col.get("cf"), ledger.prior_col.get("cf")
    return {
        "answerable": True,
        "unit": ledger.unit,
        "basis": ledger.basis,
        "assurance": ledger.assurance,
        "period_current": periods[cc] if cc is not None and cc < len(periods) else None,
        "period_prior": periods[pc] if pc is not None and pc < len(periods) else None,
        "cf_pages": sorted({r.page for r in cf}),
        "fcf": {"current": fcf_cur, "prior": fcf_pri, "delta": fcf_delta},
        "level1": level1,
        "cfo_delta": cfo_delta,
        "level2": level2,
        "group_deltas": groups,
        "residual": cfo_delta - sum(x["delta"] for x in known),
        "inflows": sorted((x for x in comp if x["current"] > 0), key=lambda x: -x["current"])[:3],
        "outflows": sorted((x for x in comp if x["current"] < 0), key=lambda x: x["current"])[:3],
    }


# ── 模板答案 ─────────────────────────────────────────────────────────────────

_ASSURANCE = {"reviewed": "會計師核閱（非查核）", "audited": "會計師查核"}


def _period_text(label: str | None) -> str:
    m = re.match(r"(\d+)-(\d+)-(\d+)~(\d+)-(\d+)-(\d+)$", label or "")
    if not m:
        return label or "（期間不明）"
    y1, m1, d1, y2, m2, d2 = (int(g) for g in m.groups())
    return f"民國 {y1}/{m1}/{d1}–{y2}/{m2}/{d2}"


def _updown(v: float) -> str:
    return "增加" if v >= 0 else "減少"


def _capex_text(x: dict[str, Any], target: str = "FCF", keys: tuple[str, ...] = ("capex",)) -> str | None:
    """資本支出（兩期皆負）→「本期支出 X、去年同期支出 Y，支出增加（減少）Z 億，使 FCF 減少（增加）Z 億」；否則 None。
    bridge 答案傳 target＝bridge 名稱去掉「變動」、keys 加無形資產（cf-bridge Spec §2.2）；FCF 答案用預設值。"""
    cur, pri = x.get("current"), x.get("prior")
    if x.get("key") not in keys or cur is None or pri is None or cur > 0 or pri > 0:
        return None
    d = abs(cur) - abs(pri)
    sp = " " if target.isascii() else ""  # 英文縮寫（FCF）前後留空白，中文目標不留
    if d == 0:
        return f"本期支出 {_yi(abs(cur))}、去年同期支出 {_yi(abs(pri))}，支出不變，對{sp}{target}{sp}無影響"
    up = d > 0
    return (f"本期支出 {_yi(abs(cur))}、去年同期支出 {_yi(abs(pri))}，支出{'增加' if up else '減少'} {_yi(abs(d))} 億，"
            f"使{sp}{target}{sp}{'減少' if up else '增加'} {_yi(abs(d))} 億")


def render_fcf_answer(facts: dict[str, Any], *, company: str = "", source: str = "",
                      period_notes: list[str] | None = None) -> str:
    if not facts.get("answerable"):
        return f"{company} 無法回答 FCF 問題：{facts.get('reason')}"
    f, l1 = facts["fcf"], facts["level1"]
    top1 = l1[0]
    l2 = [x for x in facts["level2"] if x["delta"] is not None]
    gd = facts["group_deltas"]
    lead_g = max(gd, key=lambda g: abs(gd[g]))
    in_g = [x for x in l2 if x["group"] == lead_g]
    lead = in_g[0] if in_g else None
    offset = next((x for x in l2 if x["delta"] * gd[lead_g] < 0), None)
    cur_p, pri_p = _period_text(facts["period_current"]), _period_text(facts["period_prior"])
    lines = [f"【{company}】自由現金流（FCF）", "",
             f"結論：本期（{cur_p}）FCF 為 {_yi(f['current'])} 億元，較去年同期（{pri_p}）"
             f"{_updown(f['delta'])} {_yi(abs(f['delta']))} 億元。影響最大的是"
             + (f"資本支出（{_capex_text(top1)}，占 FCF 變動 {_pct(top1['share'])}%）" if _capex_text(top1) else
                f"{top1['label']}（變動 {_yi(top1['delta'])} 億元，占 FCF 變動 {_pct(top1['share'])}%）")
             + f"。CFO 變動中影響最大的分組是{lead_g}（{_yi(gd[lead_g])} 億元）"
             + (f"，其中最大的是「{lead['label']}」（變動 {_yi(lead['delta'])} 億元，p.{lead['page']}）" if lead and len(in_g) > 1 else "")
             + (f"；方向相反、最大的抵銷項是「{offset['label']}」（變動 {_yi(offset['delta'])} 億元，"
                f"p.{offset['page']}）" if offset else "") + "。",
             "", "一、變動歸因（本期 − 去年同期，億元）"]
    for i, x in enumerate(l1, 1):
        if _capex_text(x):
            lines.append(f"  {i}. 資本支出：{_capex_text(x)}（p.{x['page']}）")
            continue
        lines.append(f"  {i}. {x['label']}：本期 {_yi(x['current'])}，去年同期 {_yi(x['prior'])}，"
                     f"變動 {_yi(x['delta'])}，占 FCF 變動 {_pct(x['share'])}%（p.{x['page']}）")
    lines.append(f"  CFO 變動 {_yi(facts['cfo_delta'])} 億元的前 5 項：")
    for x in l2[:5]:
        lines.append(f"    - {x['label']}（{x['group']}）：本期 {_yi(x['current'])}，去年同期 {_yi(x['prior'])}，"
                     f"變動 {_yi(x['delta'])}，占 CFO 變動 {_pct(x['share'])}%（p.{x['page']}）")
    lines.append("  CFO 變動分組小計：" + "；".join(
        f"{g} {_yi(v)}" for g, v in facts["group_deltas"].items()))
    lines += ["", "二、本期構成（FCF＝CFO＋資本支出，億元）", "  最大流入："]
    lines += [f"    - {x['label']} {_yi(x['current'])}（p.{x['page']}）" for x in facts["inflows"]]
    lines.append("  最大流出：")
    lines += [f"    - {x['label']} {_yi(x['current'])}（p.{x['page']}）" for x in facts["outflows"]]
    lines += ["", "三、期間與限制",
              "  - 半年報的現金流量表只有 1–6 月累計數，沒有單季數；「本季」「今年」都以上半年累計回答。"
              if facts["basis"] == "H1" else f"  - 期間口徑：{facts['basis']}。",
              *([f"  - 本期 {cur_p}，去年同期 {pri_p}。"] if period_notes else []),
              *[f"  - {n}" for n in period_notes or []],
              f"  - 財報類型：{_ASSURANCE.get(facts['assurance'] or '', '未標示')}。",
              "  - FCF＝營業活動之淨現金流＋取得不動產、廠房及設備（負值）；未含無形資產、使用權資產與租賃本金。",
              f"  - CFO 歸因殘差 {_yi(facts['residual'])} 億元（未歸入任何列的差額）。",
              "", f"四、出處：{source or '財報 PDF'}，現金流量表 p.{', p.'.join(str(p) for p in facts['cf_pages'])}"]
    return "\n".join(lines)


# ── 主題事實包（G2） ─────────────────────────────────────────────────────────

FCF_TOPIC = "fcf_analysis"


def _row_page(ledger: StatementLedger, key: str) -> int | None:
    return next((r.page for r in ledger.rows if r.key == key), None)


def _row_label(ledger: StatementLedger, key: str, fallback: str) -> str:
    return next((r.label for r in ledger.rows if r.key == key), fallback)


def _bridge_topic(ledger: StatementLedger, b, ttm: TtmView | None = None) -> dict[str, Any]:
    """ttm 給定 → TTM vs FY 的 bridge（頁碼不適用，TTM 值的出處見 ttm:values）。"""
    page = (lambda k: None) if ttm else (lambda k: _row_page(ledger, k))
    t = {"kind": "bridge", "name": b.name, "current": b.target_current, "prior": b.target_prior,
         "delta": b.target_delta, "residual": b.residual, "page": page(b.target),
         "components": [{"key": c.key, "label": c.name, "current": c.current, "prior": c.prior,
                         "delta": c.delta, "share": c.share,
                         "page": None if ttm else (getattr(c, "page", None) or page(c.key)),
                         **({"synthetic": True} if c.synthetic else {})}
                        for c in b.components]}
    if ttm:
        t.update(compare="ttm_vs_fy", period_ttm=ttm.period_ttm, period_fy=ttm.period_fy)
    return t


def _metric_topics(ledger: StatementLedger, metrics: list, periods: tuple[str, str] = ("current", "prior"),
                   ttm: TtmView | None = None) -> dict[str, dict[str, Any]]:
    """指標主題（每個 key 一個）；ttm 給定 → TTM vs FY（key 加 ttm: 前綴，TTM 值為 None 的不加）。"""
    names = {m.key: m.name for m in metrics}
    units = {m.key: m.unit for m in metrics}
    out: dict[str, dict[str, Any]] = {}
    for key in dict.fromkeys(m.key for m in metrics):
        cur, pri = (next(m for m in metrics if m.key == key and m.period == p) for p in periods)
        if ttm and cur.value is None:
            continue
        t = {
            "kind": "metric", "name": cur.name, "formula": cur.formula, "unit": cur.unit,
            "current": cur.value, "prior": pri.value, "delta": _delta(cur.value, pri.value),
            "inputs": [{"key": k, "label": "期間天數" if k == "days" else _row_label(ledger, k, names.get(k, k)),
                        "unit": "天" if k == "days" else units.get(k, "仟元"),
                        "current": cur.inputs.get(k), "prior": pri.inputs.get(k),
                        "page": None if ttm and k in ttm.values else _row_page(ledger, k)}
                       for k in cur.inputs]}
        if cur.source is not None:  # 金控附註指標（G3b）：出處在財報附註，無帳本輸入
            t["source"] = {"current": cur.source, "prior": pri.source}
        if ttm:
            t.update(compare="ttm_vs_fy", period_ttm=ttm.period_ttm, period_fy=ttm.period_fy)
        out[f"ttm:{key}" if ttm else key] = t
    return out


def _ttm_topics(ledger: StatementLedger, ttm: TtmView) -> dict[str, dict[str, Any]]:
    """G3b：ttm:values（TTM＝FY＋H1 本期−H1 去年同期）＋ ttm:<指標> ＋ ttm:bridge:<target>（工業）。"""
    rows = []
    for k, v in ttm.values.items():
        src = "net_income_parent" if v.get("basis") == "parent" else k
        rows.append({"key": k, "label": _row_label(ledger, src, k), "fy": v["fy"], "h1_current": v["h1_current"],
                     "h1_prior": v["h1_prior"], "ttm": v["ttm"], "page": _row_page(ledger, src),
                     "basis": v.get("basis")})
    out = {"ttm:values": {
        "kind": "ttm_values", "name": "近四季（TTM）損益", "formula": "TTM＝FY＋H1 本期−H1 去年同期",
        "period_ttm": ttm.period_ttm, "period_fy": ttm.period_fy, "fy_page": ttm.source_page,
        "scope": ttm.scope, "comparability_note": ttm.comparability_note, "rows": rows}}
    out.update(_metric_topics(ledger, ttm.metrics, ("ttm", "fy"), ttm))
    for b in ttm.bridges:
        out[f"ttm:bridge:{b.target}"] = _bridge_topic(ledger, b, ttm)
    return out


GROSS_KEYS = ("revenue", "cogs", "gross_profit")


def _gross_topics(ledger: StatementLedger, mp) -> dict[str, dict[str, Any]]:
    """G3a：毛利金額 bridge（營收＋成本）與毛利率拆解（營收效果＋成本效果，百分點）；三者兩期皆有值才加。"""
    def get(key: str, which: str) -> float | None:
        return _value(ledger, mp, key, "current" if which == "cur" else "prior")  # cogs 已正規化成 −|v|

    v = {k: (get(k, "cur"), get(k, "pri")) for k in GROSS_KEYS}
    if any(x is None for pair in v.values() for x in pair):
        return {}
    out = {"bridge:gross_profit": _bridge_topic(ledger, _build_bridge(
        "gross_profit", "毛利變動", ("revenue", "cogs"), get, lambda k: _label_of(ledger, k)))}
    (r1, r0), (c1, c0) = v["revenue"], (abs(v["cogs"][0]), abs(v["cogs"][1]))  # type: ignore[arg-type]
    if not r1 or not r0:
        return out
    gm1, gm0 = (r1 - c1) / r1 * 100, (r0 - c0) / r0 * 100
    d = gm1 - gm0
    effects = (("revenue_effect", "營收變動效果", (c0 / r0 - c0 / r1) * 100),
               ("cost_effect", "成本變動效果", (c0 - c1) / r1 * 100))
    out["bridge:gross_margin"] = {
        "kind": "margin_bridge", "name": "毛利率變動拆解", "unit": "%",
        "formula": "毛利率＝（營業收入 − |營業成本|）／營業收入 × 100",
        "current": gm1, "prior": gm0, "delta": d,
        "components": [{"key": k, "label": lb, "value": x, "share": x / d if d else None} for k, lb, x in effects],
        "inputs": [{"key": k, "label": _row_label(ledger, k, k), "unit": "仟元", "current": v[k][0],
                    "prior": v[k][1], "page": _row_page(ledger, k)} for k in ("revenue", "cogs")]}
    return out


_TTM_REASONS = {
    "ledger_is_fy": "財報已是年度數，不需 TTM", "ledger_not_h1": "財報不是半年報",
    "fy_income_missing": "年報找不到 FY 損益比較表", "fy_income_unusable": "年報 FY 損益表勾稽未通過",
    "fy_year_mismatch": "年報年度與半年報去年同期年度不符", "unit_mismatch": "年報與財報金額單位不同",
}


AR_CASHFLOW_TOPIC, AR_CONTRACTS_TOPIC, AR_SPECIAL_TOPIC = "ar:cashflow", "ar:contracts", "ar:special"
AR_TOPICS = (AR_CASHFLOW_TOPIC, AR_CONTRACTS_TOPIC, AR_SPECIAL_TOPIC)
_AR_KEY_TOPIC = {"cashflow": AR_CASHFLOW_TOPIC, "contracts": AR_CONTRACTS_TOPIC, "special": AR_SPECIAL_TOPIC}
_AR_KEY_LABEL = {"cashflow": "年報現金流量", "contracts": "年報重要契約", "special": "年報特別記載事項"}
SPECIAL_TEXT_MAX = 800  # 特別記載 4 個子項問答都只給前 800 字（使用者裁示 Q3；主 flow 2026-10-12 擴及全部子項：2412 關係企業原文 15,304 字）
AR_CF_FIELDS = (("opening_cash", "期初現金"), ("cfo", "營業活動淨現金流量"), ("cfi", "投資活動淨現金流量"),
                ("cff", "籌資活動淨現金流量"), ("cfi_cff", "投資及籌資活動合計淨現金流量"),
                ("outflow", "全年現金流出量"), ("fx", "匯率變動影響"), ("closing_cash", "現金剩餘數額（期末）"))
AR_SPECIAL_LABELS = {
    "affiliates": "關係企業相關資料", "private_placement": "私募有價證券辦理情形",
    "other_supplement": "其他必要補充說明事項",
    "material_events_36": "證券交易法第三十六條第三項第二款所定對股東權益或證券價格有重大影響之事項"}


def _cf_table_view(t: dict[str, Any] | None) -> dict[str, Any] | None:
    """表 A／表 B（CashflowTable.to_dict，仟元原值；缺值保持 None）＋ yi＝億元字串（缺值 None）。"""
    if t is None:
        return None
    return {**t, "yi": {f: None if t.get(f) is None else fmt_value(t[f], "仟元") for f, _ in AR_CF_FIELDS}}


def _ar_cashflow_topic(d: dict[str, Any]) -> dict[str, Any]:
    """d＝CashflowSection.to_dict()（producer：ar_sections.py CashflowSection.to_dict）。"""
    return {"kind": "ar_cashflow", "name": "年報現金流量（表 A 實際數、表 B 預估數）", "status": d["status"],
            "pages": d["pages"], "basis": d["basis"], "basis_note": d["basis_note"], "arith_ok": d["arith_ok"],
            "unit_text": d["unit_text"], "actual": _cf_table_view(d["actual"]),
            "actual_explanations": d["actual_explanations"], "forecast": _cf_table_view(d["forecast"]),
            "forecast_explanations": d["forecast_explanations"]}


def _ar_contracts_topic(d: dict[str, Any]) -> dict[str, Any]:
    """d＝ContractsSection.to_dict()。"""
    return {"kind": "ar_contracts", "name": "年報重要契約", "status": d["status"], "pages": d["pages"],
            "rows": d["rows"], "none_entities": d["none_entities"]}


def _ar_special_topic(d: dict[str, Any]) -> dict[str, Any]:
    """d＝SpecialSection.to_dict()；各子項 text 只留前 SPECIAL_TEXT_MAX 字並標 truncated。"""
    items: dict[str, dict[str, Any]] = {}
    for k, it in d["items"].items():
        text = it["text"]
        cut = text is not None and len(text) > SPECIAL_TEXT_MAX
        items[k] = {"status": it["status"], "page": it["page"],
                    "text": text[:SPECIAL_TEXT_MAX] if cut else text, "truncated": bool(cut),
                    "full_length": None if text is None else len(text)}
    return {"kind": "ar_special", "name": "年報特別記載事項", "status": d["status"], "pages": d["pages"],
            "items": items}


_AR_BUILDERS = {"cashflow": _ar_cashflow_topic, "contracts": _ar_contracts_topic, "special": _ar_special_topic}


def load_ar_sections(ar: Any, ledger: StatementLedger | None) -> tuple[dict[str, Any] | None, str | None]:
    """年報 PdfDoc → ({"cashflow": CashflowSection（已判口徑）, "contracts", "special"}, None)；
    任一解析例外 → (None, "<類型>: <訊息>")（同 tables.extract_tables：三章節全部不可用）。口徑用當次問答選用的帳本。"""
    try:
        return {"cashflow": apply_cashflow_basis(parse_cashflow(ar), ledger), "contracts": parse_contracts(ar),
                "special": parse_special(ar)}, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _ar_status(ar_sections: dict[str, Any] | None, error: str | None) -> dict[str, dict[str, Any]]:
    if ar_sections is None:
        failed = error is not None
        reason = f"年報讀取或解析失敗：{error}" if failed else "沒有可用的年報（annual_report_path 未設定）"
        return {k: {"status": "failed" if failed else "not_found", "reason": reason} for k in _AR_BUILDERS}
    return {k: {"status": ar_sections[k].status, "reason": ar_sections[k].reason} for k in _AR_BUILDERS}


def topic_pack(ledger: StatementLedger | None, group: str | None = None, *, fy_income: Any = None,
               notes: Any = None, ttm_error: str | None = None, ar_sections: dict[str, Any] | None = None,
               ar_sections_error: str | None = None) -> dict[str, Any]:
    """主題事實包：fcf_analysis（G1 事實包；金控不提供）＋ 指標 key ＋ bridge:<target>；
    fy_income（年報 FY 損益表）給定且 TTM 可用 → 另加 ttm:*；notes（金控附註）給定 → 附註三指標。ledger None → 不可答。
    ar_sections（load_ar_sections 的結果）給定 → 章節 status 為 parsed／none 者加 ar:cashflow／ar:contracts／ar:special；
    failed／not_found 不加主題。pack["ar_sections_status"] 一律記每章節 status＋reason。"""
    if ledger is None:
        return {"answerable": False, "reason": "財報三表解析失敗（無帳本）"}
    mp = compute_metrics(ledger, fy_income, group="fh" if uses_fh_schema(group) else group, notes=notes)
    topics: dict[str, dict[str, Any]] = {}
    if not uses_fh_schema(group):
        f = fcf_facts(ledger)
        if f["answerable"]:
            topics[FCF_TOPIC] = {"kind": "fcf", "name": "自由現金流變動歸因與本期構成", "facts": f}
    topics.update(_metric_topics(ledger, mp.metrics))
    for b in mp.bridges:
        topics[f"bridge:{b.target}"] = _bridge_topic(ledger, b)
    if not uses_fh_schema(group):
        topics.update(_gross_topics(ledger, mp))
    ttm = mp.ttm
    if ttm is not None and ttm.status == "ok":
        topics.update(_ttm_topics(ledger, ttm))
        ttm_status, ttm_reason = "ok", ""
    else:
        ttm_status = "unavailable"
        code = "ledger_is_fy" if ttm is None else ttm.reason
        ttm_reason = f"年報讀取失敗：{ttm_error}" if ttm_error else f"{_TTM_REASONS.get(code, code)}（{code}）"
    for key, build in _AR_BUILDERS.items():
        sec = (ar_sections or {}).get(key)
        if sec is not None and sec.status in (STATUS_PARSED, STATUS_NONE):
            topics[_AR_KEY_TOPIC[key]] = build(sec.to_dict())
    return {"answerable": True, "unit": ledger.unit, "basis": ledger.basis, "assurance": ledger.assurance,
            "periods": dict(ledger.periods), "ifrs17_break": bool(mp.ifrs17_break),
            "ar_sections_status": _ar_status(ar_sections, ar_sections_error),
            "ttm_status": ttm_status, "ttm_reason": ttm_reason,
            "ttm_period": None if ttm is None else ttm.period_ttm, "fy_period": None if ttm is None else ttm.period_fy,
            "topics": topics}


# ── 數字核對 ─────────────────────────────────────────────────────────────────

_NUM_UNIT_PAT = r"(-?\d[\d,]*(?:\.\d+)?)\s*(億|%|％|百分點|仟元|千元|百萬元|萬元|兆元?|天|倍|pp(?![A-Za-z])|x(?![A-Za-z]))"
_NUM_UNIT_RE = re.compile(_NUM_UNIT_PAT)
_UNIT_SCALE = {"億": _YI, "仟元": 1, "千元": 1, "百萬元": 1_000, "萬元": 10, "兆": 1_000_000_000, "兆元": 1_000_000_000}
_UNIT_KIND = {"%": "pct", "％": "pct", "百分點": "pct", "pp": "pct", "天": "day", "倍": "x", "x": "x"}  # 其餘＝金額（amt，仟元）
_METRIC_KIND = {"仟元": "amt", "%": "pct", "天": "day", "x": "x"}

# 方向詞（G3a）：詞後略過空白與「了／約／達」，緊接數字＋單位才檢查；接「至／到／為」（期末水準）不檢查
_POS_WORDS = ("增加", "上升", "提高", "成長", "增長", "擴大", "回升")
_NEG_WORDS = ("減少", "下降", "降低", "衰退", "縮小", "下滑", "減")
_DIR_RE = re.compile("(" + "|".join(sorted(_POS_WORDS + _NEG_WORDS, key=len, reverse=True)) + ")[\\s了約達]*"
                     + _NUM_UNIT_PAT)

Levels = dict[str, list[float]]
Delta = tuple[str, float, set[int]]  # (單位類別, 變動值, 可接受的方向 {+1／-1})


def _vals(*vs: float | None) -> list[float]:
    return [v for v in vs if v is not None]


def _sgn(v: float) -> set[int]:
    return {1} if v > 0 else {-1} if v < 0 else {1, -1}


def _dir(kind: str, cur: float | None, pri: float | None, delta: float | None,
         component: bool = False) -> list[Delta]:
    """變動值與可接受方向。組成項兩期皆負（成本、流出）→ delta 或絕對值變化任一方向皆可（使用者 2026-10-10 裁示）。"""
    if delta is None:
        return []
    signs = _sgn(delta)
    if component and cur is not None and pri is not None and cur < 0 and pri < 0:
        signs |= _sgn(abs(cur) - abs(pri))
    return [(kind, delta, signs)]


def _new_levels() -> Levels:
    return {"amt": [], "pct": [], "day": [], "x": []}


def _fact_values(facts: dict[str, Any]) -> tuple[Levels, list[Delta]]:
    """FCF 事實包 → (非變動值, 變動值)；金額單位仟元、比例為百分數。"""
    levels, deltas = _new_levels(), []
    f = facts["fcf"]
    levels["amt"] += _vals(f["current"], f["prior"])
    deltas += _dir("amt", f["current"], f["prior"], f["delta"])
    for it in [*facts["level1"], *facts["level2"], *facts["inflows"], *facts["outflows"]]:
        levels["amt"] += _vals(it.get("current"), it.get("prior"))
        deltas += _dir("amt", it.get("current"), it.get("prior"), it.get("delta"), component=True)
        if it.get("share") is not None:
            levels["pct"].append(it["share"] * 100)
    deltas += _dir("amt", None, None, facts["cfo_delta"])
    for v in facts["group_deltas"].values():
        deltas += _dir("amt", None, None, v)
    levels["amt"] += _vals(facts["residual"])
    return levels, deltas


def _input_values(inputs: list[dict[str, Any]], levels: Levels, deltas: list[Delta]) -> None:
    for i in inputs:
        kind = _METRIC_KIND.get(i["unit"], "amt")
        levels[kind] += _vals(i["current"], i["prior"])
        deltas += _dir(kind, i["current"], i["prior"], _delta(i["current"], i["prior"]), component=True)


def _text_values(texts: list[str | None], levels: Levels) -> None:
    """年報原文中帶單位的數字 → 可用數字（換算成該單位類別的基準值；金額為仟元）。"""
    for text in texts:
        for m in _NUM_UNIT_RE.finditer(text or ""):
            x, _, kind, scale = _parse(m.group(1), m.group(2))
            levels[kind].append(x * scale)


def _topic_values(t: dict[str, Any]) -> tuple[Levels, list[Delta]]:
    """主題 → (非變動值, 變動值)；單位類別 amt＝仟元、pct＝百分數、day＝天、x＝倍。"""
    if t["kind"] == "fcf":
        return _fact_values(t["facts"])
    levels, deltas = _new_levels(), []
    if t["kind"] == "metric":
        kind = _METRIC_KIND.get(t["unit"])
        if kind:
            levels[kind] += _vals(t["current"], t["prior"])
            deltas += _dir(kind, t["current"], t["prior"], t["delta"])
        _input_values(t["inputs"], levels, deltas)
    elif t["kind"] == "margin_bridge":
        levels["pct"] += _vals(t["current"], t["prior"])
        deltas += _dir("pct", t["current"], t["prior"], t["delta"])
        for c in t["components"]:
            deltas += _dir("pct", None, None, c["value"])
            levels["pct"] += _vals(None if c["share"] is None else c["share"] * 100)
        _input_values(t["inputs"], levels, deltas)
    elif t["kind"] == "ttm_values":  # 變動值＝TTM−FY（＝H1 本期−H1 去年同期）
        for r in t["rows"]:
            levels["amt"] += _vals(r["fy"], r["h1_current"], r["h1_prior"], r["ttm"])
            deltas += _dir("amt", r["ttm"], r["fy"], _delta(r["ttm"], r["fy"]), component=True)
    elif t["kind"] == "ar_cashflow":  # 表 A／表 B 各欄＋說明原文中的金額（年報原文可照抄）
        for tbl in (t["actual"], t["forecast"]):
            if tbl is not None:
                levels["amt"] += _vals(*(tbl.get(f) for f, _ in AR_CF_FIELDS))
        _text_values([*t["actual_explanations"].values(), *t["forecast_explanations"].values()], levels)
    elif t["kind"] == "ar_contracts":  # 契約金額、日期原文不核對來源欄位；原文出現的帶單位數字視為可引用
        _text_values([str(v) for r in t["rows"] for k, v in r.items() if k not in ("page", "parties")]
                     + [p for r in t["rows"] for p in r["parties"]], levels)
    elif t["kind"] == "ar_special":
        _text_values([it["text"] for it in t["items"].values()], levels)
    else:
        levels["amt"] += _vals(t["current"], t["prior"], t["residual"])
        deltas += _dir("amt", t["current"], t["prior"], t["delta"])
        for c in t["components"]:
            levels["amt"] += _vals(c["current"], c["prior"])
            deltas += _dir("amt", c["current"], c["prior"], c["delta"], component=True)
            levels["pct"] += _vals(None if c["share"] is None else c["share"] * 100)
    return levels, deltas


def _allowed(levels: Levels, deltas: list[Delta]) -> Levels:
    out = {k: list(v) for k, v in levels.items()}
    for kind, v, _ in deltas:
        out[kind].append(v)
    return out


def _parse(raw: str, unit: str) -> tuple[float, float, str, float]:
    """→ (數值, 容差（該數字小數位的半個單位）, 單位類別, 換算倍數)。"""
    dec = len(raw.split(".")[1]) if "." in raw else 0
    return (float(raw.replace(",", "")), 0.5 * 10 ** -dec + 1e-9, _UNIT_KIND.get(unit, "amt"), _UNIT_SCALE.get(unit, 1))


def _hit(x: float, tol: float, scale: float, v: float) -> bool:
    return abs(abs(x) - abs(v / scale)) <= tol


def _unmatched(text: str, allowed: Levels) -> list[str]:
    """答案中帶單位的數字，比對允許值（取絕對值）；容差＝該數字小數位的半個單位。回傳對不上的原文。"""
    bad: list[str] = []
    for m in _NUM_UNIT_RE.finditer(text):
        x, tol, kind, scale = _parse(m.group(1), m.group(2))
        if not any(_hit(x, tol, scale, a) for a in allowed.get(kind, [])):
            bad.append(m.group(0))
    return bad


def _wrong_direction(text: str, levels: Levels, deltas: list[Delta]) -> list[str]:
    """方向詞＋緊接數字：數字對到的變動值全部與方向詞反向、且不等於任何非變動值 → 回傳原文（方向與帳本不符）。"""
    bad: list[str] = []
    for m in _DIR_RE.finditer(text):
        word = m.group(1)
        x, tol, kind, scale = _parse(m.group(2), m.group(3))
        want = 1 if word in _POS_WORDS else -1
        hits = [signs for k, v, signs in deltas if k == kind and _hit(x, tol, scale, v)]
        if not hits or any(want in signs for signs in hits):
            continue
        if any(_hit(x, tol, scale, a) for a in levels.get(kind, [])):
            continue
        bad.append(f"{m.group(0)}（方向與帳本不符）")
    return bad


def _check_text(text: str, levels: Levels, deltas: list[Delta]) -> list[str]:
    return _unmatched(text, _allowed(levels, deltas)) + _wrong_direction(text, levels, deltas)


def verify_numbers(text: str, facts: dict[str, Any]) -> list[str]:
    """答案中帶單位的數字比對 FCF 事實包（G1）＋方向詞核對（G3a）；回傳對不上的原文。"""
    if not facts.get("answerable"):
        return [m.group(0) for m in _NUM_UNIT_RE.finditer(text)]
    return _check_text(text, *_fact_values(facts))


def verify_topics(text: str, pack: dict[str, Any], topics: list[str]) -> list[str]:
    """答案中帶單位的數字只准來自 topics 所列主題＋方向詞核對（G3a）；不存在的主題不提供允許值。回傳對不上的原文。"""
    levels, deltas = _new_levels(), []
    for key in topics:
        t = (pack.get("topics") or {}).get(key)
        if t is not None:
            lv, dl = _topic_values(t)
            for k, v in lv.items():
                levels[k] += v
            deltas += dl
    return _check_text(text, levels, deltas)


# ── 主題模板答案（G2；也是 LLM 未通過核對時的退回答案） ─────────────────────

def fmt_value(v: float | None, unit: str) -> str:
    if v is None:
        return "—"
    if unit == "仟元":
        return f"{_yi(v)} 億元"
    if unit == "%":
        return f"{v:.2f}%"
    if unit == "天":
        return f"{v:.1f} 天"
    if unit == "x":
        return f"{v:.2f} 倍"
    return f"{v:,.2f}"


def fmt_delta(v: float | None, unit: str) -> str:
    return fmt_value(v, unit).replace("%", " 百分點") if unit == "%" else fmt_value(v, unit)


def _page(p: int | None) -> str:
    return "" if p is None else f"，p.{p}"


def _labels(t: dict[str, Any]) -> tuple[str, str]:
    """→ (本期稱呼, 比較期稱呼)；TTM 主題為「近四季（TTM，迄 X）」對「FY Y 年度」。"""
    if t.get("compare") == "ttm_vs_fy":
        return f"近四季（TTM，迄 {t.get('period_ttm') or '—'}）", f"FY {t.get('period_fy') or '—'} 年度"
    return "本期", "去年同期"


def _source_text(src: dict[str, Any] | None) -> str:
    if not src:
        return "—"
    if src.get("page") is None:
        return f"未取得（{src.get('reason') or '未揭露'}）"
    return (f"財報附註 p.{src['page']}（期間 {src.get('period') or '—'}、{src.get('entity') or '—'}"
            + ("；非最新期" if src.get("stale") else "") + "）")


def _render_metric(t: dict[str, Any]) -> list[str]:
    u = t["unit"]
    a, b = _labels(t)
    head = (f"■ {t['name']}：{a} {fmt_value(t['current'], u)}，{b} {fmt_value(t['prior'], u)}，"
            f"變動 {fmt_delta(t['delta'], u)}")
    if "source" in t:
        return [head, f"  出處：{a} {_source_text(t['source']['current'])}；{b} {_source_text(t['source']['prior'])}"]
    ins = "、".join(f"{i['label']} {fmt_value(i['current'], i['unit'])}{_page(i['page'])}"
                   for i in t["inputs"])
    return [head, f"  公式：{t['formula']}；{a}輸入：{ins or '—'}"]


def _render_ttm_values(t: dict[str, Any]) -> list[str]:
    lines = [f"■ {t['name']}（迄 {t['period_ttm'] or '—'}）：{t['formula']}；FY {t['period_fy']} 年度數出自年報"
             f"{_page(t['fy_page'])}，H1 數出自財報"]
    for r in t["rows"]:
        if r["ttm"] is None:
            continue
        note = "（歸屬母公司淨利）" if r.get("basis") == "parent" else ""
        lines.append(f"  - {r['label']}{note}：TTM {fmt_value(r['ttm'], '仟元')}＝FY {fmt_value(r['fy'], '仟元')}"
                     f"＋本期 {fmt_value(r['h1_current'], '仟元')}−去年同期 {fmt_value(r['h1_prior'], '仟元')}"
                     f"{_page(r['page'])}；較 FY 變動 {fmt_value(_delta(r['ttm'], r['fy']), '仟元')}")
    if t.get("scope") == "parent_only":
        lines.append("  年報只有個體損益表，TTM 只算歸屬母公司淨利。")
    if t.get("comparability_note"):
        lines.append(f"  可比性：{t['comparability_note']}。")
    return lines


def ar_basis_hint(t: dict[str, Any]) -> str | None:
    """年報現金流量口徑提示：basis 不是 consolidated（含未判定）→ 提示句；consolidated → None。"""
    b = t.get("basis")
    if b == "consolidated":
        return None
    note = f"（{t['basis_note']}）" if t.get("basis_note") else ""
    head = "年報此節的數字不是合併數字" if b == "non_consolidated" else "年報此節的數字無法確認是否為合併數字"
    return f"{head}{note}，不可與財報合併現金流量表的數字混在同一句比較。"


def ar_arith_hint(t: dict[str, Any]) -> str | None:
    """表 A 驗算提示：arith_ok 不是 True（含 None＝無法驗算）→ 提示句；True → None。"""
    return None if t.get("arith_ok") is True else "此表期初＋各項流量與期末不平（或無法驗算）。"


def _pages_text(pages: list[int]) -> str:
    return "p." + "、".join(str(p) for p in pages) if pages else "頁碼不明"


def _ar_table_lines(title: str, tbl: dict[str, Any] | None, explanations: dict[str, str | None]) -> list[str]:
    if tbl is None:
        return [f"  {title}：年報未列此表。"]
    if tbl.get("applicable") is False:
        return [f"  {title}：年報寫「不適用」。"]
    listed = [f"{lab} {tbl['yi'][f]}" for f, lab in AR_CF_FIELDS if tbl.get(f) is not None]
    missing = [lab for f, lab in AR_CF_FIELDS if tbl.get(f) is None]
    pg = "" if tbl.get("page") is None else f"（p.{tbl['page']}）"
    body = "、".join(listed) if listed else "年報未列任何金額"
    lines = [f"  {title}{pg}：{body}" + (f"；年報未列：{'、'.join(missing)}" if listed and missing else "")]
    if tbl.get("remedy_invest") is not None or tbl.get("remedy_finance") is not None:
        lines.append(f"    現金不足額之補救措施／投資計畫：{tbl.get('remedy_invest') or '年報未列'}；"
                     f"理財計畫：{tbl.get('remedy_finance') or '年報未列'}")
    for k, lab in (("operating", "營業活動"), ("investing", "投資活動"), ("financing", "籌資活動")):
        if explanations.get(k):
            lines.append(f"    {lab}說明（年報原文）：{explanations[k]}")
    return lines


def _render_ar_cashflow(t: dict[str, Any]) -> list[str]:
    lines = [f"■ 年報現金流量（檢討分析章現金流量節，{_pages_text(t['pages'])}）"]
    if t["status"] == STATUS_NONE:
        return lines + ["  年報此節寫「無」或「不適用」，沒有現金流量分析表。"]
    hint = ar_basis_hint(t)
    if hint:
        lines.append(f"  注意：{hint}")
    arith = ar_arith_hint(t)
    if arith and t["actual"] is not None:
        lines.append(f"  注意：表 A {arith}")
    lines += _ar_table_lines("表 A（實際數）", t["actual"], t["actual_explanations"])
    lines += _ar_table_lines("表 B（預估數：公司預計未來一年的數字，不是實際數）", t["forecast"], t["forecast_explanations"])
    return lines


def _render_ar_contracts(t: dict[str, Any]) -> list[str]:
    lines = [f"■ 年報重要契約（{_pages_text(t['pages'])}）"]
    if t["status"] == STATUS_NONE or not t["rows"]:
        lines.append("  年報此節寫「無」，沒有列出重要契約。")
    else:
        lines.append(f"  共 {len(t['rows'])} 筆：")
    for r in t["rows"]:
        ent = f"［{r['entity']}］" if r.get("entity") else ""
        lines.append(f"  - {ent}{r['nature'] or '—'}（p.{r['page']}）：當事人 {'、'.join(r['parties']) or '—'}；"
                     f"期間 {r['period'] or '—'}；內容 {r['content'] or '—'}；限制條款 {r['restrictions'] or '—'}")
    if t["none_entities"]:
        lines.append(f"  年報寫「無」的子公司：{'、'.join(t['none_entities'])}。")
    return lines


def _render_ar_special(t: dict[str, Any]) -> list[str]:
    lines = [f"■ 年報特別記載事項（{_pages_text(t['pages'])}）"]
    for k in SPECIAL_KEYS:
        it, lab = t["items"][k], AR_SPECIAL_LABELS[k]
        if it["status"] == "not_found" or it["page"] is None:
            lines.append(f"  - {lab}：年報找不到此項。")
            continue
        state = {"none": "年報寫「無」或「不適用」", "see_mops": "年報只列公開資訊觀測站連結"}.get(it["status"], "年報有揭露")
        lines.append(f"  - {lab}（p.{it['page']}）：{state}")
        if it["text"]:
            lines.append(f"    {it['text']}")
        if it["truncated"]:
            lines.append(f"    （原文共 {it['full_length']} 字，此處只列前 {SPECIAL_TEXT_MAX} 字，其餘省略；全文見年報 p.{it['page']}）")
    return lines


def _render_ar(t: dict[str, Any]) -> list[str]:
    return (_render_ar_cashflow(t) if t["kind"] == "ar_cashflow"
            else _render_ar_contracts(t) if t["kind"] == "ar_contracts" else _render_ar_special(t))


def render_ar_answer(pack: dict[str, Any], keys: list[str], *, company: str = "", source: str = "") -> str:
    """年報章節模板答案（不打 API）。keys＝章節名（cashflow／contracts／special）；章節不可答 → 「年報此節無法解析（原因）」。"""
    lines = [f"【{company}】"]
    for key in keys:
        t = pack["topics"].get(_AR_KEY_TOPIC[key])
        if t is not None:
            lines += [""] + _render_ar(t)
            continue
        st = (pack.get("ar_sections_status") or {}).get(key) or {}
        lines += ["", f"■ {_AR_KEY_LABEL[key]}：年報此節無法解析（{st.get('reason') or '找不到章節'}）。"]
    return "\n".join(lines + ["", f"出處：{source or '年報 PDF'}"])


_COST_KEYS = ("cogs", "selling_expenses", "admin_expenses", "rd_expenses", "total_opex", "other_opex_residual",
              "finance_costs", "income_tax")


def _cost_text(c: dict[str, Any], target: str) -> str | None:
    """費用類組成項（Task 1 正規化成負數）→「費用增加（減少）Z 億，使〈目標〉減少（增加）Z 億」；
    所得稅為利益（任一期為正值）→「所得稅利益增加（減少）Z 億，使〈目標〉增加（減少）Z 億」；其他 → None。"""
    cur, pri, d = c.get("current"), c.get("prior"), c.get("delta")
    if c["key"] not in _COST_KEYS or cur is None or pri is None or d is None:
        return None
    z = _yi(abs(d))
    if c["key"] == "income_tax" and (cur > 0 or pri > 0):
        w = "增加" if d >= 0 else "減少"
        return f"所得稅利益{w} {z} 億，使{target}{w} {z} 億"
    if cur > 0 or pri > 0 or abs(cur) == abs(pri):  # 兩期同額 → 退回「變動 0.00 億元」，不寫「費用減少 0.00 億」
        return None
    up = abs(cur) > abs(pri)  # 費用金額變大
    return f"費用{'增加' if up else '減少'} {z} 億，使{target}{'減少' if up else '增加'} {z} 億"


_CF_BRIDGE_NAMES = frozenset(s.name for s in BRIDGE_SPECS if s.target in ("fcf", "cfo", "cfi", "cff", "net_change_in_cash"))


def _render_bridge(t: dict[str, Any]) -> list[str]:
    a, b = _labels(t)
    target = t["name"].removesuffix("變動")
    effect = "對現金的影響" if t["name"] in _CF_BRIDGE_NAMES else "變動"  # 現金流量表項目是帶號的現金影響數
    lines = [f"■ {t['name']}：{a} {fmt_value(t['current'], '仟元')}，{b} {fmt_value(t['prior'], '仟元')}，"
             f"變動 {fmt_value(t['delta'], '仟元')}{_page(t['page'])}"]
    comps = [c for c in t["components"] if c["delta"] is not None][:5]
    for c in comps:
        body = (_cost_text(c, target) or _capex_text(c, target, ("capex", "intangible_purchase"))
                or f"{effect} {fmt_value(c['delta'], '仟元')}")
        lines.append(f"  - {c['label']}：{body}，占 {_pct(c['share'])}%{_page(c['page'])}")
    if t["residual"] is not None and abs(t["residual"]) >= 500:  # 四捨五入到 0.01 億仍非 0
        lines.append(f"  未歸類項目 {_yi(abs(t['residual']))} 億（未歸入組成項的差額）")
    return lines


def _render_margin(t: dict[str, Any]) -> list[str]:
    ins = "、".join(f"{i['label']} 本期 {fmt_value(i['current'], '仟元')}、去年同期 {fmt_value(i['prior'], '仟元')}"
                   f"{_page(i['page'])}" for i in t["inputs"])
    return [f"■ {t['name']}：本期 {fmt_value(t['current'], '%')}，去年同期 {fmt_value(t['prior'], '%')}，"
            f"變動 {fmt_delta(t['delta'], '%')}",
            *[f"  - {c['label']}：{fmt_delta(c['value'], '%')}，占 {_pct(c['share'])}%" for c in t["components"]],
            f"  輸入：{ins}",
            f"  拆解方式：{t['formula']}。營收變動效果＝成本維持去年同期金額、只換入本期營收的毛利率變動；"
            "成本變動效果＝再換入本期成本的毛利率變動；兩者合計＝毛利率變動。此毛利率未含未實現銷貨損益等調整，"
            "可能與財報營業毛利算出的毛利率略有差異。"]


def _fcf_sections(facts: dict[str, Any], company: str, source: str) -> list[str]:
    """與其他主題並用時只取 FCF 答案的結論與一、二節（期間與出處由 render_topics_answer 統一列）。"""
    lines = render_fcf_answer(facts, company=company, source=source).splitlines()[2:]
    return lines[:next((i for i, ln in enumerate(lines) if ln.startswith("三、")), len(lines))]


def render_topics_answer(pack: dict[str, Any], topics: list[str], *, company: str = "", source: str = "") -> str:
    notes = pack.get("period_notes") or []
    if not pack.get("answerable"):
        return f"{company} 無法回答：{pack.get('reason')}"
    known = [k for k in topics if k in pack["topics"]]
    if known and all(k in AR_TOPICS for k in known):
        return render_ar_answer(pack, [k for k, v in _AR_KEY_TOPIC.items() if v in known], company=company, source=source)
    if known == [FCF_TOPIC]:
        return render_fcf_answer(pack["topics"][FCF_TOPIC]["facts"], company=company, source=source,
                                 period_notes=notes)
    lines = [f"【{company}】"]
    for k in known:
        t = pack["topics"][k]
        lines += [""] + (_fcf_sections(t["facts"], company, source)
                         if t["kind"] == "fcf" else _render_metric(t) if t["kind"] == "metric"
                         else _render_margin(t) if t["kind"] == "margin_bridge"
                         else _render_ttm_values(t) if t["kind"] == "ttm_values"
                         else _render_ar(t) if t["kind"].startswith("ar_") else _render_bridge(t))
    per = pack["periods"]
    lines += ["", "期間與限制",
              f"  - 本期 {_period_text(per.get('flow_current'))}（資產負債表 {per.get('bs_current') or '—'}），"
              f"去年同期 {_period_text(per.get('flow_prior'))}。",
              "  - 半年報只有 1–6 月累計數，沒有單季數；比率為上半年數或期末數，未年化。"
              if pack["basis"] == "H1" else f"  - 期間口徑：{pack['basis']}。",
              *[f"  - {n}" for n in notes],
              f"  - 財報類型：{_ASSURANCE.get(pack['assurance'] or '', '未標示')}。",
              *(["  - 保險子公司適用 IFRS 17，去年同期為重編數，本期與去年同期的損益比較可能不一致。"]
                if pack.get("ifrs17_break") else []),
              *(["  - 近四季（TTM）＝年報 FY 年度數＋半年報本期−半年報去年同期；FY 為查核數、H1 為核閱數。"]
                if any(k.startswith("ttm:") for k in known) else []),
              "", f"出處：{source or '財報 PDF'}"]
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

_FCF_Q_RE = re.compile(r"FCF|自由現金流", re.IGNORECASE)
# 年報章節問題分流（模板路徑）：用詞取窄；FCF 問題先走 FCF 路徑；「契約負債」等會計科目不算重要契約
_AR_ROUTES = (
    ("cashflow", re.compile(r"現金流動性|未來一年.{0,6}現金(?:流動性|狀況|流量|餘額)|現金流量預估|預估現金|現金剩餘(?!.{0,4}股)|現金不足")),
    ("contracts", re.compile(r"重要契約|契約(?!負債|資產|成本|收入)")),
    ("special", re.compile(r"特別記載|私募(?!基金)|關係企業(?!交易)|第三十六條|第36條|對股東權益或證券價格有重大影響|重大影響之?事項")),
)


def route_ar_sections(question: str) -> list[str]:
    """問題用詞 → 要答的年報章節（cashflow／contracts／special，依此序；都不符 → []）。"""
    return [key for key, rx in _AR_ROUTES if rx.search(question)]


_QUARTER_RE = re.compile(r"第[一二三四]季|Q[1-4]|單季|季度", re.IGNORECASE)  # 單季用詞（答案加「沒有單季財報」說明）
_HALF_RE = re.compile(r"半年|上半|下半|H1|H2|第[一二三四]季|Q[1-4]|季度|單季", re.IGNORECASE)  # 年度內子期間（半年、單季）→ 不選全年帳本


def _fy_term_re(fy_year: int) -> re.Pattern[str]:
    """年度用詞：完整的西元年、民國年＋「年」、全年、整年、年度（前面不是「半」「上」「下」「今」「本」）。"""
    return re.compile(rf"(?<!\d){fy_year}(?!\d)|(?<!\d){fy_year - 1911}\s*年|全年|整年|(?<![半上下今本])年度")


def select_period(question: str, has_fy: bool, period_arg: str = "auto", fy_year: int = 2025) -> tuple[str, bool]:
    """問答選期間 → ("fy" | "h1", 是否要加「沒有全年財報」說明)。
    period_arg＝fy／h1 直接指定（fy 但沒有全年財報 → h1＋說明）；auto：問題含年度用詞（且不含半年用詞）才選全年。
    「去年」「今年」「半年度」「上半年度」不算年度用詞。"""
    if period_arg == "h1":
        return "h1", False
    wants_fy = period_arg == "fy" or (bool(_fy_term_re(fy_year).search(question)) and not _HALF_RE.search(question))
    if not wants_fy:
        return "h1", False
    return ("fy", False) if has_fy else ("h1", True)


def _year_of(label: str | None, default: int | None) -> int | None:
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", label or "")
    return int(m.group(1)) if m else default


def _period_choice(raw: dict[str, Any], question: str, period_arg: str,
                   base: Path | None = None) -> tuple[str, list[str]]:
    """→ ("fy"|"h1", 期間說明句)。fy＝全年財報（不做 TTM）；說明句寫在答案的「期間與限制」。
    全年財報欄位有值但檔案不在 → 視為沒有全年財報（與 inputs.load_inputs 一致）。"""
    fy_year = _year_of(raw.get("fy_fs_period"), raw.get("fiscal_year")) or 2025
    fy_rel = raw.get("fy_consolidated_fs_path")
    has_fy = bool(fy_rel) and ((base or Path(".")) / fy_rel).exists()
    period, missing = select_period(question, has_fy, period_arg, fy_year)
    if missing:
        h1_year = _year_of(raw.get("fs_period"), None)
        return period, [f"沒有 {fy_year} 全年財報，以下為 {h1_year} 上半年" if h1_year
                        else f"沒有 {fy_year} 全年財報，以下為上半年"]
    if period == "fy":
        return period, [f"本答案使用 {fy_year} 全年財報（{raw.get('fy_fs_period') or 'FY'}），"
                        "全年數不做近四季（TTM）換算。"]
    if _QUARTER_RE.search(question):  # 問單季（第一～四季、Q1～Q4、單季）：只有半年累計數，說明清楚
        h1_year = _year_of(raw.get("fs_period"), None)
        return period, [f"沒有單季財報，以下為 {h1_year} 上半年累計數" if h1_year else "沒有單季財報，以下為上半年累計數"]
    return period, []


class _OcrCacheMiss(Exception):
    pass


def _cache_only_ocr(path, pages):
    raise _OcrCacheMiss(f"pages={pages}")


def _load_doc(path: Path) -> pdf_doc.PdfDoc:
    """有圖片頁或亂碼頁時改用 OCR 快取（未命中則沿用原文）。不打 API。"""
    doc = pdf_doc.load_pdf(path)
    if doc.image_pages or doc.garbled_pages:
        try:
            doc = pdf_doc.load_pdf(path, ocr=_cache_only_ocr)
        except _OcrCacheMiss:
            pass
    return doc


def load_ledger(fs_path: Path, group: str | None = None) -> StatementLedger | None:
    """財報 PDF → 帳本（group=="fh" 走金控 schema）。"""
    doc = _load_doc(fs_path)
    return extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()), group=group)


def load_fy_income(ar_path: Path, roc_year: int, group: str | None = None, *,
                   ar: pdf_doc.PdfDoc | None = None) -> tuple[Any, str | None]:
    """年報 PDF → (FyIncome 或 None, 錯誤)；任何例外 → (None, "<類型>: <訊息>")（G3b：問答照常、無 TTM 主題）。
    ar 給定（呼叫端已讀過年報）→ 重用，不重讀檔。"""
    from runtime.tw_equity.fy_income import extract_fy_income
    try:
        ar = ar if ar is not None else _load_doc(ar_path)
        anchors = find_annual_report_sections(ar, required=set(), **({"group": "fh"} if uses_fh_schema(group) else {}))
        return extract_fy_income(ar, anchors, roc_year=roc_year, group="fh" if uses_fh_schema(group) else group), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def load_fh_notes(fs_path: Path, ledger: StatementLedger | None) -> Any:
    """金控財報附註（集團資本適足率、逾放比、覆蓋率）；bs_current 取法同 tables.extract_tables；例外 → 附註抽取失敗。"""
    from runtime.tw_equity.fh_notes import CarResult, FhNotes, extract_fh_notes
    bs_cur = None
    if ledger is not None:
        ci = ledger.current_col.get("bs")
        cols = ledger.column_periods.get("bs") or []
        bs_cur = cols[ci] if ci is not None and ci < len(cols) else None
    try:
        return extract_fh_notes(_load_doc(fs_path), bs_current_period=bs_cur)
    except Exception:
        return FhNotes(group_car=CarResult(value=None, reason="附註抽取失敗"), npl=None)


def build_pack(base: Path, raw: dict[str, Any], question: str = "", period_arg: str = "auto") -> tuple[dict[str, Any], str]:
    """--llm 與年報章節模板路徑的事實包：財報帳本＋年報（FY 損益表 TTM、三章節）＋金控附註 → (pack, 出處)。
    期間依 select_period 選（全年財報或半年報）；全年帳本 basis 不是 H1，不做 TTM。
    有 annual_report_path 時一律讀年報（只讀快取）解析三章節，全年帳本也讀；年報只讀一次，TTM 與三章節共用。"""
    period, notes = _period_choice(raw, question, period_arg, base)
    fs_rel = raw["fy_consolidated_fs_path"] if period == "fy" else raw["consolidated_fs_path"]
    ar_rel, group = raw.get("annual_report_path"), raw.get("group")
    ledger = load_ledger(base / fs_rel, group=group)
    ar_doc, ar_sections, ar_sec_err = None, None, None  # 年報只讀一次：TTM 與三章節共用同一份 PdfDoc
    if ledger is not None and ar_rel:
        try:
            ar_doc = _load_doc(base / ar_rel)
        except Exception as e:
            ar_sec_err = f"{type(e).__name__}: {e}"
        if ar_doc is not None:
            ar_sections, ar_sec_err = load_ar_sections(ar_doc, ledger)
    fy, err = None, None
    if ledger is not None and ledger.basis == "H1":  # 年度帳本不需 TTM，不讀年報
        if not ar_rel or not raw.get("fiscal_year"):
            err = "annual_report_path 或 fiscal_year 未設定"
        else:
            fy, err = load_fy_income(base / ar_rel, int(raw["fiscal_year"]) - 1911, group, ar=ar_doc)
    fh_notes = load_fh_notes(base / fs_rel, ledger) if uses_fh_schema(group) else None
    pack = topic_pack(ledger, group, fy_income=fy, notes=fh_notes, ttm_error=err,
                      ar_sections=ar_sections, ar_sections_error=ar_sec_err)
    if notes:
        pack["period_notes"] = notes
    used_ar = pack.get("ttm_status") == "ok" or any(k in pack.get("topics", {}) for k in AR_TOPICS)
    return pack, fs_rel + (f"；年報 {ar_rel}" if ar_rel and used_ar else "")


def answer(ticker: str, question: str, *, base_dir: Path | None = None,
           use_llm: bool = False, llm: Any = None, period: str = "auto") -> tuple[str, dict[str, Any] | None]:
    """→ (答案文字, 事實包或 None)。use_llm=False：G1 FCF 模板；True：G2 主題事實包＋LLM（qa_llm）。"""
    base = Path(".") if base_dir is None else base_dir
    raw = json.loads((base / "tw_equity_inputs" / f"{ticker}.json").read_text(encoding="utf-8"))
    company = f"{ticker} {raw.get('company_name', '')}".strip()
    if use_llm:
        fs_rel = raw.get("consolidated_fs_path")
        if not fs_rel:
            return f"{company} 無財報 PDF（consolidated_fs_path 未設定）。", None
        pack, source = build_pack(base, raw, question, period)
        if not pack["answerable"]:
            return f"{company} 無法回答：{pack['reason']}", None
        from runtime.tw_equity.qa_llm import answer_llm  # qa_llm 引用本模組，函式內 import 避開循環
        text, _meta = answer_llm(pack, question, company=company, source=source, llm=llm)
        return text, pack
    if not _FCF_Q_RE.search(question):
        keys = route_ar_sections(question)
        if not keys:
            return ("G1 只支援 FCF 問題（問題需含「FCF」或「自由現金流」）。"
                    "年報章節問題需含「重要契約」「特別記載」「現金流動性」等用詞。"), None
        if not raw.get("consolidated_fs_path"):
            return f"{company} 無財報 PDF（consolidated_fs_path 未設定）。", None
        pack, source = build_pack(base, raw, question, period)
        if not pack["answerable"]:
            return f"{company} 無法回答：{pack['reason']}", None
        text = render_ar_answer(pack, keys, company=company, source=source)
        return text + "\n（模板答案只回答年報章節；問題中的其他部分請單獨提問或加 --llm）", pack
    if uses_fh_schema(raw.get("group")):
        return (f"{company} 為金控，FCF（營業現金流＋資本支出）不適用於金融業："
                "放款與存款變動都列在營業活動，數字不代表可自由運用的現金。"), None
    fs_rel = raw.get("consolidated_fs_path")
    if not fs_rel:
        return f"{company} 無財報 PDF（consolidated_fs_path 未設定）。", None
    chosen, notes = _period_choice(raw, question, period, base)
    if chosen == "fy":
        fs_rel = raw["fy_consolidated_fs_path"]
    facts = fcf_facts(load_ledger(base / fs_rel))
    return render_fcf_answer(facts, company=company, source=fs_rel, period_notes=notes), facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tw-equity 會計問答（G1：FCF 模板；G2：--llm）")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--ask", required=True)
    ap.add_argument("--json", action="store_true", help="另輸出事實包 JSON")
    ap.add_argument("--llm", action="store_true", help="以 LLM（config.json provider）對應問題並寫答案；程式核對數字")
    ap.add_argument("--period", choices=("auto", "h1", "fy"), default="auto",
                    help="期間：auto 依問題用詞（年度用詞且有全年財報 → fy，否則 h1）；h1 半年報；fy 全年財報")
    args = ap.parse_args(argv)
    text, facts = answer(args.ticker, args.ask, use_llm=args.llm, period=args.period)
    print(text)
    if facts is not None:
        if not args.llm:
            bad = (verify_topics(text, facts, [k for k in AR_TOPICS if k in facts["topics"]])
                   if "topics" in facts else verify_numbers(text, facts))
            if bad:
                print(f"\n[數字核對] 對不上：{', '.join(bad)}")
        if args.json:
            print(json.dumps(facts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
