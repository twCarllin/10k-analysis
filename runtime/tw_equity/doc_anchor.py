"""doc_anchor.py — 年報 / 財報章節錨定層。

提供 PageRange dataclass、錨定字典常數（ANNUAL_REPORT_ANCHORS、FS_ANCHORS、
PARENT_FS_ANCHORS）與 find_sections 函式。

演算法概要：
1. 以 NFKC 正規化後的全頁文字偵測目錄頁（同頁命中 ≥3 個不同 key）。
2. toc_cutoff = 最小目錄頁頁碼（無目錄頁時為 0）。
3. 對每個 key，由前往後掃頁文字前 300 字（NFKC 正規化），
   第一個頁碼 > toc_cutoff 且含任一關鍵字的頁即為起頁。
4. 終頁 = 下一個「起頁大於本 key 起頁」的 key 起頁 − 1；
   最後一個 key 到文件末頁。
5. required 內任一 key 找不到 → raise AnchorError。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from runtime.tw_equity.pdf_doc import PdfDoc


# ── 例外 ────────────────────────────────────────────────────────────────────


class AnchorError(RuntimeError):
    """必填 key 找不到時拋出；訊息列出缺少與已找到的 key 及建議。"""


# ── PageRange ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageRange:
    start: int
    end: int  # 含兩端


# ── 錨定字典 ─────────────────────────────────────────────────────────────────

ANNUAL_REPORT_ANCHORS: dict[str, list[str]] = {
    "ar_letter":           ["致股東報告書"],
    "ar_governance":       ["公司治理報告"],   # 只作 ar_letter 的終止錨；段落文字仍取自 GOVERNANCE_HEADING_ANCHORS
    "ar_business":         ["一、業務內容"],
    "ar_market":           ["二、市場及產銷概況"],
    "ar_customers":        ["主要銷貨客戶", "曾占進(銷)貨總額", "主要進銷貨客戶"],
    "ar_mdna":             ["財務狀況及財務績效之檢討分析"],
    "ar_fin_position":     ["一、財務狀況"],
    "ar_fin_performance":  ["二、財務績效"],
    "ar_cashflow":         ["三、現金流量"],
    "ar_risk":             ["風險事項分析評估", "風險事項"],
    "ar_special":          ["特別記載事項"],
    "ar_production_sales": ["生產量值", "銷售量值", "產銷量值"],
}

FS_ANCHORS: dict[str, list[str]] = {
    "fs_audit_kam":           ["關鍵查核事項"],
    "fs_bs":                  ["資產負債表"],
    "fs_is":                  ["綜合損益表"],
    "fs_cf":                  ["現金流量表"],
    "fs_note_expense_nature": ["費用性質之額外資訊"],
    "fs_note_inventory":      ["存貨"],
    "fs_note_related":        ["關係人交易"],
    "fs_note_contingent":     ["或有負債", "未認列之合約承諾"],
    "fs_note_disclosure":     ["附註揭露事項"],
}

PARENT_FS_ANCHORS: dict[str, list[str]] = {
    "ps_is":          ["綜合損益表"],
    "ps_cogs_detail": ["營業成本明細表"],
    "ps_mfg_overhead":["製造費用明細表"],
    "ps_opex_detail": ["營業費用明細表"],
}


# ── 內部工具 ─────────────────────────────────────────────────────────────────


def _nfkc(s: str) -> str:
    """NFKC 正規化：解決 PDF 中常見的 CJK 相容表意文字問題。"""
    return unicodedata.normalize("NFKC", s)


def _hits_any(kws: list[str], text_norm: str) -> bool:
    """text_norm（已正規化）是否含任一 kws（各自正規化後）。"""
    return any(_nfkc(kw) in text_norm for kw in kws)


def _count_keys_in_text(anchors: dict[str, list[str]], text: str) -> int:
    """統計 anchors 中有多少個不同 key 的關鍵字出現在 text（NFKC 正規化後）。"""
    norm = _nfkc(text)
    return sum(1 for kws in anchors.values() if _hits_any(kws, norm))


# ── 主函式 ───────────────────────────────────────────────────────────────────


def find_sections(
    doc: PdfDoc,
    anchors: dict[str, list[str]],
    *,
    required: set[str],
    order: list[str],
) -> dict[str, PageRange | None]:
    """在 doc 中依 anchors 與 order 定位各章節的頁碼範圍。

    Args:
        doc: 已載入的 PdfDoc。
        anchors: key → 候選標題關鍵字清單（依優先序）。
        required: 必填 key 集合；任一找不到 → raise AnchorError。
        order: key 的掃描順序，也決定終頁計算時的序列。

    Returns:
        dict，key → PageRange（找到）或 None（未找到）。

    Raises:
        AnchorError: required 內有 key 找不到時。
    """
    sorted_pages = sorted(doc.pages, key=lambda p: p.number)

    # ── Step 1：偵測目錄頁（全頁文字命中 ≥3 個不同 key） ───────────────────
    toc_pages = [
        page.number
        for page in sorted_pages
        if _count_keys_in_text(anchors, page.text) >= 3
    ]
    toc_cutoff = min(toc_pages) if toc_pages else 0

    # ── Step 2：掃頁找起頁（頁文字前 300 字、NFKC 正規化、頁碼 > toc_cutoff） ─
    starts: dict[str, int] = {}
    for key in order:
        if key not in anchors:
            continue
        kws = anchors[key]
        for page in sorted_pages:
            if page.number <= toc_cutoff:
                continue
            if _hits_any(kws, _nfkc(page.text[:300])):
                starts[key] = page.number
                break

    # ── Step 3：計算終頁 ────────────────────────────────────────────────────
    last_page = sorted_pages[-1].number if sorted_pages else 0
    found_in_order = [(key, starts[key]) for key in order if key in starts]

    result: dict[str, PageRange | None] = {}
    for i, (key, start) in enumerate(found_in_order):
        end = last_page
        # 往後找第一個起頁 > 本 key 起頁的 key
        for j in range(i + 1, len(found_in_order)):
            _, next_start = found_in_order[j]
            if next_start > start:
                end = next_start - 1
                break
        result[key] = PageRange(start=start, end=end)

    # 未找到的 key 補 None
    for key in order:
        if key not in result:
            result[key] = None

    # ── Step 4：檢查 required ────────────────────────────────────────────────
    missing = [key for key in required if result.get(key) is None]
    if missing:
        found_keys = [key for key in order if result.get(key) is not None]
        missing_str = "、".join(missing)
        found_str = "、".join(found_keys) if found_keys else "（無）"
        raise AnchorError(
            f"必填 key 找不到：{missing_str}。"
            f"已找到：{found_str}。"
            f"建議：確認關鍵字與文件章名一致（PDF 可能使用 CJK 相容字元或空格）。"
        )

    return result


# ── 標題行錨定（1B-1，只讀 Page.lines）───────────────────────────────────────


@dataclass(frozen=True)
class HeadingAnchor:
    keywords: list[str]          # 依優先序
    enum: bool                   # True＝須有編號前綴；False＝整列（去空白後）等於關鍵字
    after: str | None = None     # 起頁須 ≥ 指定 key 的起頁
    tail: tuple[str, ...] = ()       # keywords 找不到時的備援：標題行（去空白、去尾冒號）以任一字串結尾即命中
    tail_after: str | None = None    # 備援起頁須 ≥ 指定 key 的起頁


_PREFIX = r"(?:[壹貳參肆伍陸柒捌玖拾]+、|[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[)）]|\d+\.)"
_PREFIX_RE = re.compile("^" + _PREFIX)
_PAGE_TAIL_RE = re.compile(r"\d+(?:[~～\-]\d+)?$")


def _norm(line: str) -> str:
    """NFKC 後刪除所有空白（處理「合 併 資 產 負 債 表」字距）。"""
    return re.sub(r"\s+", "", _nfkc(line))


def _is_heading(norm: str, anchor: HeadingAnchor) -> bool:
    for kw in anchor.keywords:
        k = _norm(kw)
        if anchor.enum:
            m = _PREFIX_RE.match(norm)
            if m and norm[m.end():].startswith(k) and not _PAGE_TAIL_RE.search(norm):
                return True
        else:
            if norm == k:
                return True
            m = _PREFIX_RE.match(norm)
            if m and norm[m.end():] == k:
                return True
    return False


def _page_hits(lines: list[str], anchors: dict[str, HeadingAnchor]) -> set[str]:
    norms = [_norm(l) for l in lines]
    return {
        key for key, a in anchors.items() if any(_is_heading(n, a) for n in norms)
    }


_LISTING_HEAD_RE = re.compile(r"^(?:[一二三四五六七八九十]+、|\d{2,3}(?![年月日\d])[\u4e00-\u9fff])")  # 「一、」或 2–3 位頁碼在前（1 位數常是表格序號）
_LISTING_MIN = 4
_LISTING_RATIO = 0.3
_TOC_LEADER_RE = re.compile(r"[-.·…─—_]{5,}\d{1,3}$")  # 引導線後接頁碼（單獨框線列不算）


def _is_toc_page(lines: list[str]) -> bool:
    """任一列為「引導線＋頁碼」；或 ≥4 列且 ≥30% 的列以「一、」／頁碼開頭（目錄／章節分隔頁）→ 視為目錄頁。
    標題斷行時 hits≥3 的目錄判定會漏；不用「列尾數字」判定，因表格列也以數字結尾。"""
    norms = [_norm(l) for l in lines]
    if any(_TOC_LEADER_RE.search(n) for n in norms):
        return True
    heads = sum(1 for n in norms if _LISTING_HEAD_RE.match(n))
    return heads >= _LISTING_MIN and heads >= _LISTING_RATIO * len(norms)


def _tail_start(pages: list, anchor: HeadingAnchor, toc_last: int, after_start: int | None) -> int | None:
    """備援：toc_last 之後（且 ≥ after_start）第一個有標題行以 anchor.tail 任一字串結尾的頁；目錄頁不算。"""
    floor = max(toc_last + 1, after_start or 0)
    kws = [_norm(k) for k in anchor.tail]
    for p in pages:
        if p.number < floor or _is_toc_page(p.lines):
            continue
        for n in (_norm(l).rstrip(":") for l in p.lines):
            if any(n.endswith(k) for k in kws):
                return p.number
    return None


def find_heading_sections(
    doc: PdfDoc,
    anchors: dict[str, HeadingAnchor],
    *,
    required: set[str],
) -> dict[str, PageRange | None]:
    """以標題行（Page.lines）錨定章節頁碼範圍；演算法見 Spec §2.2.1。

    Raises:
        AnchorError: required 內有 key 找不到時。
    """
    pages = sorted(doc.pages, key=lambda p: p.number)
    hits = {p.number: _page_hits(p.lines, anchors) for p in pages}
    toc_last = max((n for n, ks in hits.items() if len(ks) >= 3), default=0)

    start: dict[str, int | None] = {}

    def _resolve(key: str, seen: frozenset[str] = frozenset()) -> int | None:
        if key in start:
            return start[key]
        a = anchors[key]
        floor = toc_last
        if a.after and a.after in anchors and a.after not in seen:
            floor = max(floor, _resolve(a.after, seen | {key}) or 0)
        start[key] = next(
            (n for n in sorted(hits) if n > toc_last and n >= floor and key in hits[n]),
            None,
        )
        if start[key] is None and a.tail:
            start[key] = _tail_start(pages, a, toc_last, _resolve(a.tail_after, seen | {key})
                                     if a.tail_after in anchors and a.tail_after not in seen else None)
        return start[key]

    for key in anchors:
        _resolve(key)

    last_page = pages[-1].number if pages else 0
    starts_sorted = sorted({s for s in start.values() if s})
    result: dict[str, PageRange | None] = {}
    for key in anchors:
        s = start[key]
        if not s:
            result[key] = None
            continue
        larger = [x for x in starts_sorted if x > s]
        result[key] = PageRange(start=s, end=(larger[0] - 1) if larger else last_page)

    missing = [k for k in anchors if k in required and result[k] is None]
    missing += sorted(k for k in required if k not in anchors)
    if missing:
        found_keys = [k for k in anchors if result[k] is not None]
        raise AnchorError(
            f"必填 key 找不到：{'、'.join(missing)}。"
            f"已找到：{'、'.join(found_keys) if found_keys else '（無）'}。"
            f"建議：確認關鍵字與文件章名一致（PDF 可能使用 CJK 相容字元或空格）。"
        )
    return result


FS_HEADING_ANCHORS: dict[str, HeadingAnchor] = {
    "fs_audit_kam":           HeadingAnchor(["關鍵查核事項"], False),
    "fs_bs":                  HeadingAnchor(["合併資產負債表"], False),
    "fs_is":                  HeadingAnchor(["合併綜合損益表"], False),
    "fs_cf":                  HeadingAnchor(["合併現金流量表"], False),
    "fs_note_items":          HeadingAnchor(["重要會計項目之說明"], True),
    "fs_note_inventory":      HeadingAnchor(["存貨"], True, after="fs_note_items"),
    "fs_note_expense_nature": HeadingAnchor(["費用性質之額外資訊"], True, after="fs_note_items"),
    "fs_note_related":        HeadingAnchor(["關係人交易"], True),
    "fs_note_contingent":     HeadingAnchor(["重大或有負債及未認列之合約承諾"], True),
    "fs_note_disclosure":     HeadingAnchor(["附註揭露事項"], True),
}

GOVERNANCE_HEADING_ANCHORS: dict[str, HeadingAnchor] = {
    "ar_governance": HeadingAnchor(["公司治理報告"], True),
    "ar_pledge":     HeadingAnchor(["股權質押資訊"], True,
                                   tail=("質押變動情形", "質押情形"), tail_after="ar_governance"),
    "ar_top10":      HeadingAnchor(["持股比例占前十名之股東"], True),
    "ar_capital":    HeadingAnchor(["參、募資情形"], False),
    "ar_operations": HeadingAnchor(["肆、營運概況"], False),
}


# ── 年報標題行備援（1B-2，Spec §2.4）──────────────────────────────────────────

AR_HEADING_FALLBACK: dict[str, HeadingAnchor] = {
    "ar_market":          HeadingAnchor(["市場及產銷概況"], True),
    "ar_mdna":            HeadingAnchor(["財務狀況及財務績效之檢討分析"], True),
    "ar_fin_position":    HeadingAnchor(["財務狀況"], True, after="ar_mdna"),
    "ar_fin_performance": HeadingAnchor(["財務績效"], True, after="ar_mdna"),
}


# ── 金控年報章名補充（fh-schema 4.1，Spec §5；只增不改上面既有關鍵字）──────────────
# 與 ANNUAL_REPORT_ANCHORS 的差異：比對時去除所有空白、並額外嘗試「疊字還原」
# （2887 為「伍伍、、財財務務…」雙寫、2886 為「財 務狀況」字距）；僅在既有掃描
# 找不到（None）或只命中目錄續頁（含 ≥5 個點／連字號引導線）時才採用，
# 且只在 group=="fh" 時執行（分流依輸入檔 group，不依文件內容推測；Spec §1），
# 因此 group 非 fh（含 None）的結果與本 run 前完全相同。順序即解析順序（ar_fin_performance 須 ≥ ar_mdna 起頁）。
FH_ANNUAL_REPORT_ANCHORS: dict[str, list[str]] = {
    "ar_business":        ["4.1本公司營運概況", "肆、營運概況"],
    "ar_mdna":            ["財務狀況及財務績效檢討分析", "財務狀況及財務績效之檢討分析與風險管理"],
    "ar_fin_performance": ["5.2財務績效", "二、財務績效", "二、個體財務績效"],
}

_LEADER_RE = re.compile(r"[-.·…─—_]{5,}")
_DOUBLED_RE = re.compile(r"([\u4e00-\u9fff、，：])\1")


def _head_variants(text: str) -> list[str]:
    """頁首 300 字（NFKC）去空白後的比對字串；另附疊字還原版本。"""
    head = _nfkc(text[:300])
    flat = re.sub(r"\s+", "", head)
    return [flat, _DOUBLED_RE.sub(r"\1", flat)]


def _is_toc_like(text: str) -> bool:
    return bool(_LEADER_RE.search(_nfkc(text[:300])))


def _fh_starts(doc: PdfDoc, starts: dict[str, int]) -> None:
    """就地補／校正 starts：僅 None 或只命中目錄續頁的 key 才採金控章名關鍵字。"""
    pages = sorted(doc.pages, key=lambda p: p.number)
    by_no = {p.number: p for p in pages}
    toc_pages = [p.number for p in pages if _count_keys_in_text(ANNUAL_REPORT_ANCHORS, p.text) >= 3]
    toc_cutoff = min(toc_pages) if toc_pages else 0
    for key, kws in FH_ANNUAL_REPORT_ANCHORS.items():
        cur = starts.get(key)
        if cur is not None and not _is_toc_like(by_no[cur].text):
            continue
        floor = max(toc_cutoff + 1, starts.get("ar_mdna", 0) if key == "ar_fin_performance" else 0)
        norm_kws = [re.sub(r"\s+", "", _nfkc(k)) for k in kws]
        for p in pages:
            if p.number < floor or _is_toc_like(p.text):
                continue
            if any(k in v for v in _head_variants(p.text) for k in norm_kws):
                starts[key] = p.number
                break


# ── 主要進銷貨客戶標題行備援（D1）────────────────────────────────────────────
# 頁首 300 字找不到時才用：標題常在頁中段。須有編號前綴（「(四)」「2.」「4.2.4」「1、」），
# 起頁 ≥ ar_market（缺則 ar_business）且 < ar_mdna；結尾為頁碼者（目錄行）不算。
_CUST_PREFIX_RE = re.compile(r"^(?:[(][一二三四五六七八九十\d]+[)]|[一二三四五六七八九十]+、|\d+(?:\.\d+)*[.、]?)")
_CUST_HEAD_RE = re.compile(
    r"主要(?:進銷貨|銷貨)客戶|主要進貨廠商|主要供應商名單|主要客戶名單|[占佔](?:進\(銷\)|銷|進)貨(?:總額|淨額)百分之十以上"
)


def _customers_heading_start(pages: list, floor: int, ceil: int | None) -> int | None:
    if ceil is not None and ceil <= floor:  # ar_mdna 落在目錄頁等前段 → 不當上限
        ceil = None
    for p in pages:
        if p.number < floor or (ceil is not None and p.number >= ceil) or _is_toc_page(p.lines):
            continue
        for n in (_norm(l) for l in p.lines):
            m = _CUST_PREFIX_RE.match(n)
            if m and m.end() > 0 and _CUST_HEAD_RE.search(n[m.end():]) and not _PAGE_TAIL_RE.search(n):
                return p.number
    return None


# key 的起頁必須 ≥ 另一 key 的起頁：泛用關鍵字（「風險事項」）在前段章節被交叉引用時改往後找
_AR_START_AFTER: dict[str, str] = {"ar_risk": "ar_mdna"}


def find_annual_report_sections(
    doc: PdfDoc, *, required: set[str], group: str | None = None
) -> dict[str, PageRange | None]:
    """年報錨定：先走 find_sections（頁首 300 字），None 的 key 再以標題行備援。

    Raises:
        AnchorError: required 內有 key 仍找不到時。
    """
    order = list(ANNUAL_REPORT_ANCHORS)
    first = find_sections(doc, ANNUAL_REPORT_ANCHORS, required=set(), order=order)
    starts: dict[str, int] = {k: r.start for k, r in first.items() if r is not None}

    if group == "fh":
        _fh_starts(doc, starts)

    pages_sorted = sorted(doc.pages, key=lambda p: p.number)
    for key, after in _AR_START_AFTER.items():
        floor = starts.get(after)
        if floor is None or starts.get(key, floor) >= floor:
            continue
        hit = next((p.number for p in pages_sorted
                    if p.number >= floor and _hits_any(ANNUAL_REPORT_ANCHORS[key], _nfkc(p.text[:300]))), None)
        if hit is None:
            starts.pop(key, None)
        else:
            starts[key] = hit

    for key, anchor in AR_HEADING_FALLBACK.items():
        if first.get(key) is not None or key in starts:
            continue
        sub = {key: anchor}
        if anchor.after and anchor.after in AR_HEADING_FALLBACK:
            sub = {anchor.after: AR_HEADING_FALLBACK[anchor.after], key: anchor}
        got = find_heading_sections(doc, sub, required=set())
        if got[key] is not None:
            starts[key] = got[key].start

    if "ar_customers" not in starts:
        floor = starts.get("ar_market", starts.get("ar_business"))
        if floor is not None:
            hit = _customers_heading_start(pages_sorted, floor, starts.get("ar_mdna"))
            if hit is not None:
                starts["ar_customers"] = hit

    pages = sorted(doc.pages, key=lambda p: p.number)
    last_page = pages[-1].number if pages else 0
    found = [(k, starts[k]) for k in order if k in starts]
    result: dict[str, PageRange | None] = {k: None for k in order}
    for i, (key, s) in enumerate(found):
        end = last_page
        for _, nxt in found[i + 1:]:  # 規則同 find_sections：依 order 找第一個起頁較大者
            if nxt > s:
                end = nxt - 1
                break
        result[key] = PageRange(start=s, end=end)

    missing = [k for k in order if k in required and result[k] is None]
    missing += sorted(k for k in required if k not in result)
    if missing:
        found_keys = [k for k in order if result[k] is not None]
        raise AnchorError(
            f"必填 key 找不到：{'、'.join(missing)}。"
            f"已找到：{'、'.join(found_keys) if found_keys else '（無）'}。"
            f"建議：確認關鍵字與文件章名一致（PDF 可能使用 CJK 相容字元或空格）。"
        )
    return result
