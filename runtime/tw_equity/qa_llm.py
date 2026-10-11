"""qa_llm.py — tw-equity 會計問答 G2：LLM 對應主題＋寫答案，程式核對數字（task/2026-10-09-tw-equity-qa-llm.md）。

流程：呼叫 LLM → 主題都存在且 verify_topics 無錯 → 輸出；否則帶 retry_hint 重呼叫 1 次 → 仍失敗改用模板答案。
預設 LLM 走 runtime.agent_runner.run_agent（config.json 的 provider，目前 Azure）；測試以假 llm 注入。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from runtime.tw_equity.qa import (
    FCF_TOPIC, _FCF_Q_RE, _pct, fmt_delta, fmt_value, render_topics_answer, verify_topics,
)

Llm = Callable[[dict[str, Any]], dict[str, Any]]
SKILL = "tw_accounting_qa"


def _azure_llm(inputs: dict[str, Any]) -> dict[str, Any]:
    from runtime.agent_runner import run_agent  # 延遲 import：載入即讀 config.json 建 client
    return run_agent("analyst_agent", SKILL, inputs, task_label="tw_accounting_qa")


# ── 給 LLM 的事實包（金額已換算億元字串、比例已 ×100） ─────────────────────

def _amt(v: float | None) -> str:
    return fmt_value(v, "仟元")


def _share(v: float | None) -> str:
    return "—" if v is None else f"{_pct(v)}%"


def _fcf_view(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "fcf": {k: _amt(f["fcf"][k]) for k in ("current", "prior", "delta")},
        "level1_fcf_delta_attribution": [
            {"label": x["label"], "current": _amt(x["current"]), "prior": _amt(x["prior"]),
             "delta": _amt(x["delta"]), "share_of_fcf_delta": _share(x["share"]), "page": x["page"]}
            for x in f["level1"]],
        "cfo_delta": _amt(f["cfo_delta"]),
        "level2_cfo_delta_attribution_top10": [
            {"label": x["label"], "group": x["group"], "current": _amt(x["current"]), "prior": _amt(x["prior"]),
             "delta": _amt(x["delta"]), "share_of_cfo_delta": _share(x["share"]), "page": x["page"]}
            for x in f["level2"] if x["delta"] is not None][:10],
        "cfo_delta_by_group": {g: _amt(v) for g, v in f["group_deltas"].items()},
        "largest_inflows": [{"label": x["label"], "current": _amt(x["current"]), "page": x["page"]}
                            for x in f["inflows"]],
        "largest_outflows": [{"label": x["label"], "current": _amt(x["current"]), "page": x["page"]}
                             for x in f["outflows"]],
        "cfo_residual": _amt(f["residual"]),
        "definition": "FCF＝營業活動之淨現金流＋取得不動產、廠房及設備（負值）",
        "cf_pages": f["cf_pages"],
    }


def _compare(t: dict[str, Any]) -> dict[str, Any]:
    """TTM 主題（G3b）：current＝近四季 TTM、prior＝FY 年度。"""
    if t.get("compare") != "ttm_vs_fy":
        return {}
    return {"compare": f"current＝近四季 TTM（迄 {t.get('period_ttm')}），prior＝FY {t.get('period_fy')} 年度"}


def _topic_view(t: dict[str, Any]) -> dict[str, Any]:
    if t["kind"] == "fcf":
        return _fcf_view(t["facts"])
    if t["kind"] == "metric":
        u = t["unit"]
        v = {"name": t["name"], "formula": t["formula"], "current": fmt_value(t["current"], u),
             "prior": fmt_value(t["prior"], u), "delta": fmt_delta(t["delta"], u), **_compare(t),
             "inputs": [{"label": i["label"], "current": fmt_value(i["current"], i["unit"]),
                         "prior": fmt_value(i["prior"], i["unit"]), "page": i["page"]}
                        for i in t["inputs"]]}
        if "source" in t:
            v["source"] = t["source"]
        return v
    if t["kind"] == "ttm_values":
        return {"name": t["name"], "formula": t["formula"], "period_ttm": t["period_ttm"],
                "period_fy": t["period_fy"], "fy_page": t["fy_page"], "scope": t["scope"],
                "comparability_note": t["comparability_note"],
                "rows": [{"label": r["label"] + ("（歸屬母公司淨利）" if r.get("basis") == "parent" else ""),
                          "ttm": _amt(r["ttm"]), "fy": _amt(r["fy"]), "h1_current": _amt(r["h1_current"]),
                          "h1_prior": _amt(r["h1_prior"]),
                          "ttm_minus_fy": _amt(None if r["ttm"] is None or r["fy"] is None else r["ttm"] - r["fy"]),
                          "page": r["page"]} for r in t["rows"] if r["ttm"] is not None]}
    if t["kind"] == "margin_bridge":
        return {"name": t["name"], "formula": t["formula"], "current": fmt_value(t["current"], "%"),
                "prior": fmt_value(t["prior"], "%"), "delta": fmt_delta(t["delta"], "%"),
                "components": [{"label": c["label"], "delta": fmt_delta(c["value"], "%"),
                                "share_of_delta": _share(c["share"])} for c in t["components"]],
                "inputs": [{"label": i["label"], "current": _amt(i["current"]), "prior": _amt(i["prior"]),
                            "page": i["page"]} for i in t["inputs"]]}
    return {"name": t["name"], "current": _amt(t["current"]), "prior": _amt(t["prior"]),
            "delta": _amt(t["delta"]), **_compare(t), "page": t["page"], "residual": _amt(t["residual"]),
            "components": [{"label": c["label"], "current": _amt(c["current"]), "prior": _amt(c["prior"]),
                            "delta": _amt(c["delta"]), "share_of_delta": _share(c["share"]), "page": c["page"]}
                           for c in t["components"] if c["delta"] is not None]}


def llm_inputs(pack: dict[str, Any], question: str, company: str) -> dict[str, Any]:
    catalog = [{"key": k, "name": t["name"]} for k, t in pack["topics"].items()]
    facts = {"context": {"periods": pack["periods"], "basis": pack["basis"], "assurance": pack["assurance"],
                         "ifrs17_break": pack.get("ifrs17_break", False), "amount_unit": "億元",
                         "ttm_status": pack.get("ttm_status"), "ttm_reason": pack.get("ttm_reason"),
                         "ttm_period": pack.get("ttm_period"), "fy_period": pack.get("fy_period"),
                         **({"period_notes": pack["period_notes"]} if pack.get("period_notes") else {})},
             "topics": {k: _topic_view(t) for k, t in pack["topics"].items()}}
    return {"question": question, "company": company,
            "topics_catalog": json.dumps(catalog, ensure_ascii=False),
            "facts_json": json.dumps(facts, ensure_ascii=False)}


# ── 檢查、重試、退回 ─────────────────────────────────────────────────────────

def _check(out: Any, pack: dict[str, Any]) -> tuple[list[str], list[str] | None]:
    """→ (問題清單, 合法 topics 或 None)。問題清單為空＝通過。"""
    if not isinstance(out, dict) or "error" in out:
        return [f"輸出不是合法 JSON（{(out or {}).get('error', '格式不符') if isinstance(out, dict) else '格式不符'}）"], None
    topics, answer, supported = out.get("topics"), out.get("answer"), out.get("supported")
    if not isinstance(answer, str) or not answer.strip() or not isinstance(topics, list) or not isinstance(supported, bool):
        return ["輸出欄位不符（需 supported:bool、topics:list、answer:str）"], None
    if not supported:
        bad = verify_topics(answer, pack, [])
        return ([f"supported=false 時答案不可含數字：{', '.join(bad)}"] if bad else []), []
    if not all(isinstance(t, str) for t in topics):
        return ["topics 元素必須是字串"], None
    unknown = [t for t in topics if t not in pack["topics"]]
    if unknown:
        return [f"主題不存在：{', '.join(map(str, unknown))}"], None
    if not topics:
        return ["supported=true 但 topics 為空"], None
    bad = verify_topics(answer, pack, topics)
    return ([f"以下數字不在所選主題的事實包內：{', '.join(bad)}"] if bad else []), topics


def answer_llm(pack: dict[str, Any], question: str, *, company: str = "", source: str = "",
               llm: Llm | None = None) -> tuple[str, dict[str, Any]]:
    """→ (答案文字（含來源尾行）, meta)。meta：source（llm／template／none）、topics、attempts、problems。"""
    call = llm or _azure_llm
    inputs = llm_inputs(pack, question, company)
    problems: list[str] = []
    last_topics: list[str] | None = None
    for attempt in (1, 2):
        if problems:
            inputs["retry_hint"] = ("上次輸出未通過檢查：" + "；".join(problems)
                                    + "。數字只能照抄 facts_json 中所選主題的字串，不可自行計算或換算。")
        try:
            out = call(inputs)
        except Exception as e:  # LLM 失敗不中斷 CLI，視同未通過
            out = {"error": f"{type(e).__name__}: {e}"}
        problems, topics = _check(out, pack)
        if topics:
            last_topics = topics
        if not problems:
            tag = "；主題：" + "、".join(topics) if topics else "（問題超出可回答範圍）"
            return (f"{out['answer'].strip()}\n\n［來源］LLM 答案，數字核對通過{tag}",
                    {"source": "llm", "topics": topics, "attempts": attempt, "problems": []})
    if not last_topics and _FCF_Q_RE.search(question) and FCF_TOPIC in pack["topics"]:
        last_topics = [FCF_TOPIC]
    reason = "；".join(problems)
    if last_topics:
        text = render_topics_answer(pack, last_topics, company=company, source=source)
        return (f"{text}\n\n［來源］模板答案（LLM 答案 2 次未通過檢查：{reason}）",
                {"source": "template", "topics": last_topics, "attempts": 2, "problems": problems})
    return (f"{company} 無法回答：LLM 未能把問題對應到事實包主題（{reason}）。",
            {"source": "none", "topics": [], "attempts": 2, "problems": problems})
