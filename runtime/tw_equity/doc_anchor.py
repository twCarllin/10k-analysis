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
