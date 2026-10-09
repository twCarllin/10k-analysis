"""qa.py — tw-equity 會計問答（工作包 G1：FCF 事實包＋模板答案＋數字核對；task/2026-10-09-tw-equity-qa-fcf.md）。

CLI：./.venv/bin/python -m runtime.tw_equity.qa --ticker 2317 --ask "本季影響 FCF 最多的是什麼？" [--json]
只讀本地財報 PDF 與 OCR 快取，不打外部 API。FCF＝cfo＋capex（同 metrics 的 fcf）。
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


# ── 數字核對 ─────────────────────────────────────────────────────────────────

_NUM_UNIT_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(億|%|仟元|千元|百萬元)")
_UNIT_SCALE = {"億": _YI, "仟元": 1, "千元": 1, "百萬元": 1_000}


def _fact_amounts(facts: dict[str, Any]) -> tuple[list[float], list[float]]:
    """→ (金額集合（仟元）, 比例集合（小數）)。"""
    amounts: list[float] = []
    shares: list[float] = []
    items = [facts["fcf"], *facts["level1"], *facts["level2"], *facts["inflows"], *facts["outflows"]]
    for it in items:
        amounts += [v for k in ("current", "prior", "delta") if (v := it.get(k)) is not None]
        if it.get("share") is not None:
            shares.append(it["share"])
    amounts += [facts["cfo_delta"], facts["residual"], *facts["group_deltas"].values()]
    return amounts, shares


def verify_numbers(text: str, facts: dict[str, Any]) -> list[str]:
    """答案中帶單位（億／%／仟元／千元／百萬元）的數字，比對事實包；容差＝該數字小數位的半個單位。回傳對不上的原文。"""
    if not facts.get("answerable"):
        return [m.group(0) for m in _NUM_UNIT_RE.finditer(text)]
    amounts, shares = _fact_amounts(facts)
    bad: list[str] = []
    for m in _NUM_UNIT_RE.finditer(text):
        raw, unit = m.group(1), m.group(2)
        x = float(raw.replace(",", ""))
        dec = len(raw.split(".")[1]) if "." in raw else 0
        tol = 0.5 * 10 ** -dec + 1e-9
        if unit == "%":
            ok = any(abs(abs(x) - abs(s * 100)) <= tol for s in shares)
        else:
            scale = _UNIT_SCALE[unit]
            ok = any(abs(abs(x) - abs(a / scale)) <= tol for a in amounts)
        if not ok:
            bad.append(m.group(0))
    return bad


# ── CLI ──────────────────────────────────────────────────────────────────────

_FCF_Q_RE = re.compile(r"FCF|自由現金流", re.IGNORECASE)


class _OcrCacheMiss(Exception):
    pass


def _cache_only_ocr(path, pages):
    raise _OcrCacheMiss(f"pages={pages}")


def load_ledger(fs_path: Path) -> StatementLedger | None:
    """財報 PDF → 帳本；有圖片頁或亂碼頁時改用 OCR 快取（未命中則沿用原文）。不打 API。"""
    doc = pdf_doc.load_pdf(fs_path)
    if doc.image_pages or doc.garbled_pages:
        try:
            doc = pdf_doc.load_pdf(fs_path, ocr=_cache_only_ocr)
        except _OcrCacheMiss:
            pass
    return extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))


def answer(ticker: str, question: str, *, base_dir: Path | None = None) -> tuple[str, dict[str, Any] | None]:
    """→ (答案文字, 事實包或 None)。"""
    base = Path(".") if base_dir is None else base_dir
    raw = json.loads((base / "tw_equity_inputs" / f"{ticker}.json").read_text(encoding="utf-8"))
    company = f"{ticker} {raw.get('company_name', '')}".strip()
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
    ap = argparse.ArgumentParser(description="tw-equity 會計問答（G1：FCF）")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--ask", required=True)
    ap.add_argument("--json", action="store_true", help="另輸出事實包 JSON")
    args = ap.parse_args(argv)
    text, facts = answer(args.ticker, args.ask)
    print(text)
    if facts is not None:
        bad = verify_numbers(text, facts)
        if bad:
            print(f"\n[數字核對] 對不上：{', '.join(bad)}")
        if args.json:
            print(json.dumps(facts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
