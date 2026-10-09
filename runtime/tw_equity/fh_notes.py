"""fh_notes.py — 金控附註抽取（Spec 2026-10-09-tw-equity-fh-schema §4）。

純規則，不用 LLM。目前實作：集團資本適足率（§4.1）、單一銀行逾放比／覆蓋率（§4.2，item 2.2）、不可得清單（§4.3）。
`npl` 形狀：{"entity": 主值銀行名|None（單一銀行無小節標題）, "periods": [{entity, period, npl_ratio, coverage_ratio, total_loans, page}…（新→舊）],
"entities": [{entity, periods}…]（全部銀行含主值）}；頁面無 `放款業務合計` 列 → None。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from runtime.tw_equity.pdf_doc import PdfDoc

UNDISCLOSED_REASON = "未揭露（延後補正）"

_CAR_LABELS = ("集團資本適足比率", "集團資本適足率")
_TRAILING_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*%?\s*$")
# 表頭日期列：整列只有日期（民國 114.6.30／114年6月30日，容許空白、「民國」前綴）
_DATE_HEADER_RE = re.compile(r"^(?:民國)?(\d{2,3})(?:年|\.)(\d{1,2})(?:月|\.)(\d{1,2})日?$")

# F7／§4.3：H1 報告無數字表的項目
_UNAVAILABLE: tuple[tuple[str, str], ...] = (
    ("銀行 BIS 資本適足率", "H1 報告僅出現在敘述文字，無數字表"),
    ("銀行第一類資本比率", "H1 報告僅出現在敘述文字，無數字表"),
    ("銀行普通股權益比率", "H1 報告僅出現在敘述文字，無數字表"),
    ("保險 RBC", "H1 報告僅出現在敘述文字，無數字表"),
    ("法定存放比率", "H1 報告皆無揭露"),
)


@dataclass
class CarResult:
    value: float | None
    period: str | None = None   # 民國 "114-06-30"
    page: int | None = None
    stale: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "period": self.period, "page": self.page,
                "stale": self.stale, "reason": self.reason}


@dataclass
class FhNotes:
    group_car: CarResult
    npl: dict[str, Any] | None = None
    unavailable: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"group_car": self.group_car.to_dict(), "npl": self.npl,
                "unavailable": [dict(u) for u in self.unavailable]}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _page_lines(page) -> list[str]:
    # lines（PyMuPDF）對橫向／直排亂碼頁較穩；無 lines 才退回 text
    return list(page.lines) if page.lines else page.text.splitlines()


def _header_period(line: str) -> str | None:
    m = _DATE_HEADER_RE.match(_norm(line))
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):03d}-{int(mo):02d}-{int(d):02d}"


def _car_candidates(fs: PdfDoc) -> list[tuple[str | None, int, float]]:
    out: list[tuple[str | None, int, float]] = []
    for page in fs.pages:
        period: str | None = None
        for line in _page_lines(page):
            p = _header_period(line)
            if p:
                period = p
                continue
            n = _norm(line)
            if not n.startswith(_CAR_LABELS):
                continue
            m = _TRAILING_NUM_RE.search(line.strip())
            if m:
                out.append((period, page.number, float(m.group(1).replace(",", ""))))
    return out


_DATE_IN_HEADER_RE = re.compile(r"(\d{2,3})(?:年|\.)(\d{1,2})(?:月|\.)(\d{1,2})日?")
# 銀行小節標題，如「(1) 台新銀行」「(8) 臺灣新光商銀」（整列只有編號＋銀行名）
_ENTITY_RE = re.compile(r"^[（(]\d+[)）](\S*(?:銀行|商銀))$")
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NPL_LABEL = "放款業務合計"
_LABEL_RE = re.compile(r"\s*".join(_NPL_LABEL))
_QUALITY = "資產品質"


def _header_periods(line: str) -> list[str]:
    """表頭日期列（可有「年／月」前綴字）→ 依序的民國日期；非表頭回 []。"""
    n = _norm(line).replace("民國", "")
    n = re.sub(r"^(?:年月|項目)", "", n)
    dates = _DATE_IN_HEADER_RE.findall(n)
    if not dates or _DATE_IN_HEADER_RE.sub("", n):
        return []
    return [f"{int(y):03d}-{int(m):02d}-{int(d):02d}" for y, m, d in dates]


_HEADING_START_LINES = 5   # 非資產品質頁上，銀行小節標題須在頁首此列數內（小節起始頁）才更新 entity
# 已知限制：銀行小節若在非資產品質頁的第 6 列之後才開始，標題會被忽略，下一頁的資產品質表會歸到前一家銀行（同期取先出現者，新銀行資料被略過）


def _npl_entries(fs: PdfDoc) -> list[dict[str, Any]]:
    by_no = {p.number: p for p in fs.pages}
    out: list[dict[str, Any]] = []
    entity: str | None = None
    for page in fs.pages:
        prev = by_no.get(page.number - 1)
        # 資產品質小節標題可能在上一頁（表跨頁時，如 2881 p291、2886 p115）
        quality = any(_QUALITY in _norm(" ".join(_page_lines(pg) or [pg.text])) for pg in (page, prev) if pg)
        headers: list[str] = []
        for idx, line in enumerate(_page_lines(page)):   # 標題更新與資料列判定按行序同一迴圈
            m = _ENTITY_RE.match(_norm(line))
            if m and (quality or idx < _HEADING_START_LINES):
                entity = m.group(1)
                continue
            if not quality:
                continue
            hp = _header_periods(line)
            if hp:
                headers = hp
                continue
            if not _norm(line).startswith(_NPL_LABEL):
                continue
            nums = [float(x.replace(",", "")) for x in _NUM_RE.findall(_LABEL_RE.sub("", line, count=1))]
            chunks = [nums[0:5], nums[5:10]] if len(nums) >= 10 else [nums[0:5]] if len(nums) >= 5 else []
            for period, c in zip(headers, chunks):
                out.append({"entity": entity, "period": period, "npl_ratio": c[2], "coverage_ratio": c[4],
                            "total_loans": c[1], "page": page.number})
    return out


def _npl_block(fs: PdfDoc) -> dict[str, Any] | None:
    """每家銀行一筆（出現序）；主值＝最新期放款總額最大者，相等取先出現者。"""
    banks: dict[str | None, dict[str, dict[str, Any]]] = {}
    for e in _npl_entries(fs):
        banks.setdefault(e["entity"], {}).setdefault(e["period"], e)   # 同期多頁取先出現
    if not banks:
        return None
    entities = [{"entity": k, "periods": [v[p] for p in sorted(v, reverse=True)]} for k, v in banks.items()]
    latest = max(e["periods"][0]["period"] for e in entities)

    def loans(e: dict[str, Any]) -> float:
        top = e["periods"][0]
        return top["total_loans"] if top["period"] == latest else -1.0

    main = max(entities, key=loans)   # max 對相等值回傳先出現者
    return {"entity": main["entity"], "periods": main["periods"], "entities": entities}


def extract_fh_notes(fs: PdfDoc, *, bs_current_period: str | None = None) -> FhNotes:
    cands = [c for c in _car_candidates(fs) if c[0] is not None]
    if cands:
        period, page, value = max(cands, key=lambda c: c[0])
        stale = bs_current_period is not None and period < bs_current_period
        car = CarResult(value=value, period=period, page=page, stale=stale)
    else:
        car = CarResult(value=None, reason=UNDISCLOSED_REASON)
    return FhNotes(group_car=car, npl=_npl_block(fs),
                   unavailable=[{"item": i, "reason": r} for i, r in _UNAVAILABLE])
