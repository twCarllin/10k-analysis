"""qa.py — tw-equity 會計問答（G1：FCF 事實包＋模板答案＋數字核對；G2：主題事實包（FCF＋指標＋bridge）＋LLM 問答；
G3a：萬元／兆／pp 單位、方向詞核對、毛利 bridge 與毛利率拆解；
task/2026-10-09-tw-equity-qa-fcf.md、task/2026-10-09-tw-equity-qa-llm.md、task/2026-10-10-tw-equity-qa-g3a.md）。

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
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections
from runtime.tw_equity.metrics import _build_bridge, _label_of, _value, compute_metrics
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


def render_fcf_answer(facts: dict[str, Any], *, company: str = "", source: str = "") -> str:
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
             f"{_updown(f['delta'])} {_yi(abs(f['delta']))} 億元。影響最大的是{top1['label']}"
             f"（變動 {_yi(top1['delta'])} 億元，占 FCF 變動 {_pct(top1['share'])}%）"
             + f"。CFO 變動中影響最大的分組是{lead_g}（{_yi(gd[lead_g])} 億元）"
             + (f"，其中最大的是「{lead['label']}」（變動 {_yi(lead['delta'])} 億元，p.{lead['page']}）" if lead and len(in_g) > 1 else "")
             + (f"；方向相反、最大的抵銷項是「{offset['label']}」（變動 {_yi(offset['delta'])} 億元，"
                f"p.{offset['page']}）" if offset else "") + "。",
             "", "一、變動歸因（本期 − 去年同期，億元）"]
    for i, x in enumerate(l1, 1):
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


def _bridge_topic(ledger: StatementLedger, b) -> dict[str, Any]:
    return {"kind": "bridge", "name": b.name, "current": b.target_current, "prior": b.target_prior,
            "delta": b.target_delta, "residual": b.residual, "page": _row_page(ledger, b.target),
            "components": [{"key": c.key, "label": c.name, "current": c.current, "prior": c.prior,
                            "delta": c.delta, "share": c.share, "page": _row_page(ledger, c.key)}
                           for c in b.components]}


GROSS_KEYS = ("revenue", "cogs", "gross_profit")


def _gross_topics(ledger: StatementLedger, mp) -> dict[str, dict[str, Any]]:
    """G3a：毛利金額 bridge（營收＋成本）與毛利率拆解（營收效果＋成本效果，百分點）；三者兩期皆有值才加。"""
    def get(key: str, which: str) -> float | None:
        return _value(ledger, mp, key, "current" if which == "cur" else "prior")

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


def topic_pack(ledger: StatementLedger | None, group: str | None = None) -> dict[str, Any]:
    """主題事實包：fcf_analysis（G1 事實包；金控不提供）＋ 指標 key ＋ bridge:<target>。ledger None → 不可答。"""
    if ledger is None:
        return {"answerable": False, "reason": "財報三表解析失敗（無帳本）"}
    mp = compute_metrics(ledger, group=group)
    topics: dict[str, dict[str, Any]] = {}
    if group != "fh":
        f = fcf_facts(ledger)
        if f["answerable"]:
            topics[FCF_TOPIC] = {"kind": "fcf", "name": "自由現金流變動歸因與本期構成", "facts": f}
    metric_names = {m.key: m.name for m in mp.metrics}
    metric_units = {m.key: m.unit for m in mp.metrics}
    for key in dict.fromkeys(m.key for m in mp.metrics):
        cur, pri = (next(m for m in mp.metrics if m.key == key and m.period == p) for p in ("current", "prior"))
        topics[key] = {
            "kind": "metric", "name": cur.name, "formula": cur.formula, "unit": cur.unit,
            "current": cur.value, "prior": pri.value, "delta": _delta(cur.value, pri.value),
            "inputs": [{"key": k, "label": "期間天數" if k == "days" else _row_label(ledger, k, metric_names.get(k, k)),
                        "unit": "天" if k == "days" else metric_units.get(k, "仟元"),
                        "current": cur.inputs.get(k), "prior": pri.inputs.get(k), "page": _row_page(ledger, k)}
                       for k in cur.inputs]}
    for b in mp.bridges:
        topics[f"bridge:{b.target}"] = _bridge_topic(ledger, b)
    if group != "fh":
        topics.update(_gross_topics(ledger, mp))
    return {"answerable": True, "unit": ledger.unit, "basis": ledger.basis, "assurance": ledger.assurance,
            "periods": dict(ledger.periods), "ifrs17_break": bool(mp.ifrs17_break), "topics": topics}


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


def _render_metric(t: dict[str, Any]) -> list[str]:
    u = t["unit"]
    ins = "、".join(f"{i['label']} {fmt_value(i['current'], i['unit'])}{_page(i['page'])}"
                   for i in t["inputs"])
    return [f"■ {t['name']}：本期 {fmt_value(t['current'], u)}，去年同期 {fmt_value(t['prior'], u)}，"
            f"變動 {fmt_delta(t['delta'], u)}",
            f"  公式：{t['formula']}；本期輸入：{ins or '—'}"]


def _render_bridge(t: dict[str, Any]) -> list[str]:
    lines = [f"■ {t['name']}：本期 {fmt_value(t['current'], '仟元')}，去年同期 {fmt_value(t['prior'], '仟元')}，"
             f"變動 {fmt_value(t['delta'], '仟元')}{_page(t['page'])}"]
    comps = [c for c in t["components"] if c["delta"] is not None][:5]
    lines += [f"  - {c['label']}：變動 {fmt_value(c['delta'], '仟元')}，占 {_pct(c['share'])}%{_page(c['page'])}"
              for c in comps]
    lines.append(f"  殘差 {fmt_value(t['residual'], '仟元')}（未歸入組成項的差額）")
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
    if not pack.get("answerable"):
        return f"{company} 無法回答：{pack.get('reason')}"
    known = [k for k in topics if k in pack["topics"]]
    if known == [FCF_TOPIC]:
        return render_fcf_answer(pack["topics"][FCF_TOPIC]["facts"], company=company, source=source)
    lines = [f"【{company}】"]
    for k in known:
        t = pack["topics"][k]
        lines += [""] + (_fcf_sections(t["facts"], company, source)
                         if t["kind"] == "fcf" else _render_metric(t) if t["kind"] == "metric"
                         else _render_margin(t) if t["kind"] == "margin_bridge" else _render_bridge(t))
    per = pack["periods"]
    lines += ["", "期間與限制",
              f"  - 本期 {_period_text(per.get('flow_current'))}（資產負債表 {per.get('bs_current') or '—'}），"
              f"去年同期 {_period_text(per.get('flow_prior'))}。",
              "  - 半年報只有 1–6 月累計數，沒有單季數；比率為上半年數或期末數，未年化。"
              if pack["basis"] == "H1" else f"  - 期間口徑：{pack['basis']}。",
              f"  - 財報類型：{_ASSURANCE.get(pack['assurance'] or '', '未標示')}。",
              *(["  - 保險子公司適用 IFRS 17，去年同期為重編數，本期與去年同期的損益比較可能不一致。"]
                if pack.get("ifrs17_break") else []),
              "", f"出處：{source or '財報 PDF'}"]
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

_FCF_Q_RE = re.compile(r"FCF|自由現金流", re.IGNORECASE)


class _OcrCacheMiss(Exception):
    pass


def _cache_only_ocr(path, pages):
    raise _OcrCacheMiss(f"pages={pages}")


def load_ledger(fs_path: Path, group: str | None = None) -> StatementLedger | None:
    """財報 PDF → 帳本（group=="fh" 走金控 schema）；有圖片頁或亂碼頁時改用 OCR 快取（未命中則沿用原文）。不打 API。"""
    doc = pdf_doc.load_pdf(fs_path)
    if doc.image_pages or doc.garbled_pages:
        try:
            doc = pdf_doc.load_pdf(fs_path, ocr=_cache_only_ocr)
        except _OcrCacheMiss:
            pass
    return extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()), group=group)


def answer(ticker: str, question: str, *, base_dir: Path | None = None,
           use_llm: bool = False, llm: Any = None) -> tuple[str, dict[str, Any] | None]:
    """→ (答案文字, 事實包或 None)。use_llm=False：G1 FCF 模板；True：G2 主題事實包＋LLM（qa_llm）。"""
    base = Path(".") if base_dir is None else base_dir
    raw = json.loads((base / "tw_equity_inputs" / f"{ticker}.json").read_text(encoding="utf-8"))
    company = f"{ticker} {raw.get('company_name', '')}".strip()
    if use_llm:
        fs_rel = raw.get("consolidated_fs_path")
        if not fs_rel:
            return f"{company} 無財報 PDF（consolidated_fs_path 未設定）。", None
        group = raw.get("group")
        pack = topic_pack(load_ledger(base / fs_rel, group=group), group)
        if not pack["answerable"]:
            return f"{company} 無法回答：{pack['reason']}", None
        from runtime.tw_equity.qa_llm import answer_llm  # qa_llm 引用本模組，函式內 import 避開循環
        text, _meta = answer_llm(pack, question, company=company, source=fs_rel, llm=llm)
        return text, pack
    if not _FCF_Q_RE.search(question):
        return "G1 只支援 FCF 問題（問題需含「FCF」或「自由現金流」）。", None
    if raw.get("group") == "fh":
        return (f"{company} 為金控，FCF（營業現金流＋資本支出）不適用於金融業："
                "放款與存款變動都列在營業活動，數字不代表可自由運用的現金。"), None
    fs_rel = raw.get("consolidated_fs_path")
    if not fs_rel:
        return f"{company} 無財報 PDF（consolidated_fs_path 未設定）。", None
    facts = fcf_facts(load_ledger(base / fs_rel))
    return render_fcf_answer(facts, company=company, source=fs_rel), facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tw-equity 會計問答（G1：FCF 模板；G2：--llm）")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--ask", required=True)
    ap.add_argument("--json", action="store_true", help="另輸出事實包 JSON")
    ap.add_argument("--llm", action="store_true", help="以 LLM（config.json provider）對應問題並寫答案；程式核對數字")
    args = ap.parse_args(argv)
    text, facts = answer(args.ticker, args.ask, use_llm=args.llm)
    print(text)
    if facts is not None:
        if not args.llm:
            bad = verify_numbers(text, facts)
            if bad:
                print(f"\n[數字核對] 對不上：{', '.join(bad)}")
        if args.json:
            print(json.dumps(facts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
