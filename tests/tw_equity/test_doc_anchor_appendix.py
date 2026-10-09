"""test_doc_anchor_appendix.py — 年報附表錨點備援（run 2026-10-09-tw-equity-anchor-ocr，Task 1）。

1.1 ar_customers 標題行備援；1.2 ar_pledge 標題行結尾備援；共用目錄頁判定 _is_toc_page。
"""

from __future__ import annotations

from runtime.tw_equity.doc_anchor import (
    GOVERNANCE_HEADING_ANCHORS,
    _is_toc_page,
    find_annual_report_sections,
    find_heading_sections,
)
from runtime.tw_equity.pdf_doc import Page, PdfDoc

_PROSE = "本公司持續拓展市場並維持與上下游廠商之良好合作關係，以下說明最近二年度之相關資料內容與變動原因。"


def _doc(pages: dict[int, tuple[str, list[str]]]) -> PdfDoc:
    return PdfDoc(
        path="x.pdf",  # type: ignore[arg-type]
        pages=[Page(number=n, text=t, tables=[], lines=ls) for n, (t, ls) in pages.items()],
    )


def _ar_pages(p4_lines: list[str], p2_lines: list[str] | None = None, p4_text: str = "營運說明") -> dict:
    return {
        1: ("目錄 一、業務內容 二、市場及產銷概況 財務狀況及財務績效之檢討分析", ["目錄"]),
        2: ("一、業務內容\n" + _PROSE, p2_lines or [_PROSE]),
        3: ("二、市場及產銷概況\n" + _PROSE, [_PROSE]),
        4: (p4_text, p4_lines),
        5: ("財務狀況及財務績效之檢討分析", ["財務狀況及財務績效之檢討分析"]),
    }


# ── 1.1 ar_customers ────────────────────────────────────────────────────────


def test_customers_mid_page_heading_hits():
    r = find_annual_report_sections(_doc(_ar_pages([_PROSE, "(四)最近二年度主要進銷貨客戶名單", _PROSE])), required=set())
    assert r["ar_customers"] is not None and r["ar_customers"].start == 4


def test_customers_statutory_ten_percent_heading_hits():
    lines = [_PROSE, "1.最近二年度任一年度中曾佔進貨總額百分之十以上之進貨廠商名單"]
    r = find_annual_report_sections(_doc(_ar_pages(lines)), required=set())
    assert r["ar_customers"].start == 4


def test_customers_toc_line_with_page_number_not_hit():
    r = find_annual_report_sections(_doc(_ar_pages([_PROSE, "2.主要銷貨客戶資料 12"])), required=set())
    assert r["ar_customers"] is None


def test_customers_cross_reference_before_market_not_hit():
    pages = _ar_pages([_PROSE], p2_lines=[_PROSE, "2.最近二年度主要銷貨客戶資料請見後述"])
    r = find_annual_report_sections(_doc(pages), required=set())
    assert r["ar_customers"] is None


def test_customers_heading_without_enum_prefix_not_hit():
    r = find_annual_report_sections(_doc(_ar_pages([_PROSE, "本公司進貨廠商及主要銷貨客戶尚屬分散"])), required=set())
    assert r["ar_customers"] is None


def test_customers_head_300_hit_unchanged():
    # 頁首 300 字已命中 → 備援不執行（取頁首掃描結果 p4，與改前相同）
    pages = _ar_pages([_PROSE], p4_text="主要銷貨客戶\n" + _PROSE)
    pages[5] = ("其他", ["(四)最近二年度主要進銷貨客戶名單"])
    pages[6] = ("財務狀況及財務績效之檢討分析", ["財務狀況及財務績效之檢討分析"])
    r = find_annual_report_sections(_doc(pages), required=set())
    assert r["ar_customers"].start == 4


# ── 1.2 ar_pledge ───────────────────────────────────────────────────────────

_TOC_LINES = ["五、更換會計師資訊", "六、董事長資訊", "七、董事、經理人及持股比例超過百分之十之股東股權移轉及股權質押變動情形",
              "八、持股比例占前十名之股東"]
_PLEDGE_PAGE = ["七、最近年度及截至年報刊印日止,董事、經理人及持股比例超過百分之十之股東股權移轉",
                "及股權質押變動情形", "1.董事、經理人及大股東股權變動情形", "職稱 姓名 持有股數 質押股數",
                "董事長 王大明 0 0", "董事 李小華 1,000 0", _PROSE]


def _gov(pages: dict[int, list[str]]):
    return find_heading_sections(_doc({n: ("", ls) for n, ls in pages.items()}), GOVERNANCE_HEADING_ANCHORS,
                                 required=set())


def test_pledge_split_statutory_heading_hits():
    r = _gov({1: _TOC_LINES, 2: ["貳、公司治理報告", _PROSE], 3: _PLEDGE_PAGE, 4: ["八、持股比例占前十名之股東", _PROSE]})
    assert r["ar_pledge"].start == 3


def test_pledge_primary_keyword_takes_precedence():
    r = _gov({1: _TOC_LINES, 2: ["貳、公司治理報告"], 3: _PLEDGE_PAGE, 4: ["(三)股權質押資訊:", _PROSE]})
    assert r["ar_pledge"].start == 4


def test_pledge_toc_and_listing_pages_not_hit():
    # 章節分隔頁（短標題清單）與「引導線＋頁碼」目錄行都不算
    r = _gov({1: ["目錄", "股權移轉及股權質押變動情形......63"], 2: ["貳、公司治理報告"], 3: _TOC_LINES, 4: [_PROSE]})
    assert r["ar_pledge"] is None


def test_pledge_before_governance_not_hit():
    r = _gov({1: ["簡介", "及股權質押變動情形", _PROSE], 2: ["貳、公司治理報告", _PROSE], 3: [_PROSE]})
    assert r["ar_pledge"] is None


def test_pledge_trailing_colon_hits():
    r = _gov({1: ["貳、公司治理報告"], 2: ["(一)董事、經理人及持股10%以上大股東之股權變動及質押情形:", _PROSE]})
    assert r["ar_pledge"].start == 2


# ── _is_toc_page ────────────────────────────────────────────────────────────


def test_table_border_and_number_rows_not_toc():
    assert not _is_toc_page(["1──────", "董事長 王大明 0", "董事 李小華 12", "董事 陳一 3", "董事 林二 45", _PROSE])


def test_page_number_first_listing_is_toc():
    assert _is_toc_page(["公司治理報告", "10董事及經理人資訊", "22公司治理運作情形", "53簽證會計師公費", "57募資情形"])


def test_content_page_with_some_enum_headings_not_toc():
    lines = ["四、簽證會計師公費資訊", "五、更換會計師資訊", "六、董事長資訊", "七、股權移轉"] + [_PROSE] * 12
    assert not _is_toc_page(lines)
