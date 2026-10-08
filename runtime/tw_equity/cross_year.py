"""cross_year.py — 兩年度 TablesBundle 的確定性跨年比對（Spec §2.5，無 LLM）。

years／fin_performance_series／overlap_checks（4.1）；
customer_concentration_series／top_shareholders_change／pledge_change（4.2）。
"""

from __future__ import annotations

import re

from runtime.tw_equity.pdf_doc import PdfDoc
from runtime.tw_equity.tables import TablesBundle, TwoYearTable


def _year_key(label: str) -> tuple[int, str]:
    m = re.match(r"\s*(\d+)", label)
    return (int(m.group(1)) if m else 0, label)


def _row_map(table: TwoYearTable) -> dict[str, dict[str, float | None]]:
    """label → {年度標籤: 值}；同 label 取第一列。"""
    out: dict[str, dict[str, float | None]] = {}
    for r in table.rows:
        if r.label in out:
            continue
        out[r.label] = {table.current_label: r.current, table.prior_label: r.prior}
    return out


def _series(current: TwoYearTable, prior: TwoYearTable) -> list[dict]:
    cur, pri = _row_map(current), _row_map(prior)
    labels = list(cur) + [k for k in pri if k not in cur]
    out = []
    for label in labels:
        values: dict[str, float | None] = {}
        for src in (pri.get(label, {}), cur.get(label, {})):  # 當年度文件後蓋 → 優先
            for year, v in src.items():
                if v is not None:
                    values[year] = v
        out.append({"label": label,
                    "values": {y: values[y] for y in sorted(values, key=_year_key)}})
    return out


def _overlaps(name: str, current: TwoYearTable, prior: TwoYearTable) -> list[dict]:
    cur, pri = _row_map(current), _row_map(prior)
    out = []
    for label, cvals in cur.items():
        if label not in pri:
            continue
        for year in sorted(set(cvals) & set(pri[label]), key=_year_key):
            c, p = cvals[year], pri[label][year]
            if c is None or p is None:
                continue
            out.append({"table": name, "label": label, "year": year,
                        "current_doc": c, "prior_doc": p,
                        "match": abs(c - p) <= 1})
    return out


def _concentration_series(current: TablesBundle, prior: TablesBundle) -> dict:
    cur, pri = current.to_dict()["concentration"], prior.to_dict()["concentration"]
    out: dict = {}
    for key in ("T8_sales", "T8_purchase"):
        merged = {e["label"]: e for e in pri.get(key, [])}
        merged.update({e["label"]: e for e in cur.get(key, [])})  # 當年度為準
        out[key] = [merged[k] for k in sorted(merged, key=_year_key)]
    return out


def _holders(bundle: TablesBundle) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for r in bundle.top_shareholders.rows:
        if r.is_representative:
            continue
        out.setdefault(re.sub(r"\s+", "", r.name), r.pct)
    return out


def _top_shareholders_change(current: TablesBundle, prior: TablesBundle) -> list[dict]:
    """任一邊 top_shareholders 為 None → []（無法比較，不誤報 new／exited）。"""
    if current.top_shareholders is None or prior.top_shareholders is None:
        return []
    cur, pri = _holders(current), _holders(prior)
    out = []
    for name in list(cur) + [n for n in pri if n not in cur]:
        c, p = cur.get(name), pri.get(name)
        status = "both" if name in cur and name in pri else ("new" if name in cur else "exited")
        delta = round(c - p, 2) if status == "both" and c is not None and p is not None else None
        out.append({"name": name, "current_pct": c, "prior_pct": p,
                    "delta_pct": delta, "status": status})
    return out


def _pledge_side(bundle: TablesBundle) -> tuple[str, float | None]:
    if bundle.pledges is None:
        return "unknown", None
    return bundle.pledges.status, bundle.pledges.max_pledge_pct


def build_cross_year(current: TablesBundle, prior: TablesBundle, *,
                     current_roc: int, prior_roc: int) -> dict:
    result: dict = {
        "years": {"current": current_roc, "prior": prior_roc},
        "fin_performance_series": [],
        "overlap_checks": [],
        "customer_concentration_series": {"T8_sales": [], "T8_purchase": []},
        "top_shareholders_change": [],
        "pledge_change": {},
    }
    cs, cm = _pledge_side(current)
    ps, pm = _pledge_side(prior)
    result["pledge_change"] = {"current_status": cs, "prior_status": ps,
                               "current_max_pct": cm, "prior_max_pct": pm}
    result["customer_concentration_series"] = _concentration_series(current, prior)
    result["top_shareholders_change"] = _top_shareholders_change(current, prior)
    if current.fin_performance is not None and prior.fin_performance is not None:
        result["fin_performance_series"] = _series(
            current.fin_performance, prior.fin_performance)
        result["overlap_checks"] += _overlaps(
            "T7b", current.fin_performance, prior.fin_performance)
    if current.fin_position is not None and prior.fin_position is not None:
        result["overlap_checks"] += _overlaps(
            "T7a", current.fin_position, prior.fin_position)
    return result


def _hits(anchors: dict, key: str, ocr_set: set[int]) -> bool:
    rng = anchors.get(key)
    return rng is not None and any(rng.start <= n <= rng.end for n in ocr_set)


def ocr_checks(doc: PdfDoc, bundle: TablesBundle, anchors: dict) -> list[dict]:
    """OCR 取代頁所產生之表的數字檢查（Spec §2.3b）。

    anchors 為年報錨點與治理錨點合併的 dict：`ar_fin_position` 範圍與
    doc.ocr_pages 有交集才查 T7a；`ar_top10` 範圍有交集才查前十大股東。
    doc.ocr_pages 空 → []。
    """
    if not doc.ocr_pages:
        return []
    ocr_set = set(doc.ocr_pages)
    out: list[dict] = []

    t7a = bundle.fin_position
    if t7a is not None and _hits(anchors, "ar_fin_position", ocr_set):
        for r in t7a.rows:
            if None in (r.current, r.prior, r.diff):
                continue
            gap = abs(r.current - r.prior - r.diff)
            out.append({"check": "t7a_diff", "table": "T7a", "label": r.label,
                        "detail": f"|current−prior−diff|={gap}", "passed": gap <= 1})

    top = bundle.top_shareholders
    if top is not None and _hits(anchors, "ar_top10", ocr_set):
        total = round(sum(r.pct for r in top.rows
                          if not r.is_representative and r.pct is not None), 2)
        out.append({"check": "top10_pct_sum", "table": "T10_top10",
                    "label": "非代表人列持股比例合計",
                    "detail": f"合計={total}（上限 100）", "passed": total <= 100})
    return out
