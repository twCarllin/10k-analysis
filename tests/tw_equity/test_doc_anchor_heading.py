"""test_doc_anchor_heading.py — find_heading_sections 合成 fixture 單元測試（item 1.3）。

合成資料區塊依據 Spec §2.2.1（演算法步驟 1–6）。
"""

from __future__ import annotations

import pytest

from runtime.tw_equity.doc_anchor import (
    AnchorError,
    HeadingAnchor,
    PageRange,
    find_heading_sections,
)
from runtime.tw_equity.pdf_doc import Page, PdfDoc


def _doc(pages: dict[int, list[str]]) -> PdfDoc:
    return PdfDoc(
        path="x.pdf",  # type: ignore[arg-type]
        pages=[Page(number=n, text="", tables=[], lines=ls) for n, ls in pages.items()],
    )


def _run(pages, anchors, required=frozenset()):
    return find_heading_sections(_doc(pages), anchors, required=set(required))


# Spec §2.2.1 步驟1／3（enum=False）、步驟5（終頁）
def test_spaced_heading_and_prefix_keyword_with_range_end():
    anchors = {
        "bs": HeadingAnchor(["合併資產負債表"], False),
        "is": HeadingAnchor(["合併綜合損益表"], False),
        "cf": HeadingAnchor(["合併現金流量表"], False),
    }
    pages = {
        1: ["封面"],
        2: ["合 併 資 產 負 債 表", "資料"],
        3: ["資料"],
        4: ["五、合併綜合損益表"],
        5: ["合併現金流量表"],
        6: ["尾"],
    }
    r = _run(pages, anchors, {"bs", "is", "cf"})
    assert r["bs"] == PageRange(2, 3)
    assert r["is"] == PageRange(4, 4)
    assert r["cf"] == PageRange(5, 6)  # 最後一個到文件末頁


# Spec §2.2.1 步驟3（enum=True、列尾頁碼排除）
def test_enum_hit_and_toc_row_with_trailing_page_not_hit():
    anchors = {"inv": HeadingAnchor(["存貨"], True)}
    pages = {
        1: ["六、存貨 12~13"],
        2: ["(五)存貨", "內文"],
    }
    r = _run(pages, anchors, {"inv"})
    assert r["inv"] == PageRange(2, 2)


# Spec §2.2.1 步驟4（目錄頁：同頁命中 ≥3 key）
def test_toc_page_with_three_keys_skipped_uses_later_heading():
    anchors = {
        "a": HeadingAnchor(["甲章"], False),
        "b": HeadingAnchor(["乙章"], False),
        "c": HeadingAnchor(["丙章"], False),
    }
    pages = {
        1: ["甲章", "乙章", "丙章"],  # 目錄頁（列等於關鍵字）
        2: ["甲章"],
        3: ["乙章"],
        4: ["丙章"],
    }
    r = _run(pages, anchors, {"a", "b", "c"})
    assert r["a"].start == 2
    assert r["b"].start == 3
    assert r["c"].start == 4


# Spec §2.2.1 `after`
def test_after_skips_same_name_heading_before_anchor_key():
    anchors = {
        "items": HeadingAnchor(["重要會計項目之說明"], True),
        "inv": HeadingAnchor(["存貨"], True, after="items"),
    }
    pages = {
        1: ["(十四)存貨"],       # 會計政策同名標題，早於 items
        2: ["六、重要會計項目之說明"],
        3: ["(五)存貨"],
    }
    r = _run(pages, anchors, {"inv"})
    assert r["inv"].start == 3
    assert r["items"].start == 2


# Spec §2.2.1 步驟6
def test_required_all_missing_raises_listing_keys():
    anchors = {
        "x": HeadingAnchor(["不存在甲"], False),
        "y": HeadingAnchor(["不存在乙"], False),
    }
    with pytest.raises(AnchorError) as ei:
        _run({1: ["無關"]}, anchors, {"x", "y"})
    assert "x" in str(ei.value) and "y" in str(ei.value)


def test_missing_non_required_is_none():
    anchors = {"x": HeadingAnchor(["不存在"], False)}
    assert _run({1: ["無關"]}, anchors)["x"] is None
