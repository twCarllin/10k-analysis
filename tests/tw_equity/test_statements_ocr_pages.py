"""OCR 頁表別內容辨認＋別名補齊（D2b；task/2026-10-09-tw-equity-ocr-fs-anchor.md）。

契約 row：
  U1: OCR 頁有 1xxx 代碼列 ≥3、無表名 → 歸 bs
  U2: OCR 頁有 4xxx–8xxx 代碼列 ≥3 → 歸 is
  U3: OCR 頁無代碼但含「營業活動之現金流量」 → 歸 cf
  U4: OCR 權益變動表頁（A1／B1 短碼） → 不歸任何表
  U5: 表名比對已命中 → 不走內容辨認
  U6: 文件無 ocr_pages → 結果與改前相同（無表名頁不入選）
  C1: IS 營業費用區段「合計」 → total_opex
  C2: 「負債合計」 → total_liabilities
行文字取自 2330／3711 2026Q2 財報 OCR 快取（Mistral）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.pdf_doc import Page, PdfDoc  # noqa: E402
from runtime.tw_equity.statements import (  # noqa: E402
    _is_skip,
    _norm_label,
    extract_statements,
    map_key,
    ocr_statement_pages,
)

_BS = [  # 2330 p4：無表名
    "單位：新台幣仟元",
    "代 碼 資 產 115年6月30日 114年12月31日 114年6月30日",
    "金 額 % 金 額 % 金 額 %",
    "流動資產",
    "1100 現金及約當現金（附註六） $ 3,134,218,213 33 $ 2,767,856,402 35 $ 2,364,524,340 34",
    "1110 透過損益按公允價值衡量之金融資產（附註七） 226,375 - 100,200 - 1,765,904 -",
    "1170 應收票據及帳款淨額（附註十一） 435,762,477 5 279,051,553 3 233,407,179 3",
    "1310 存貨（附註十二） 385,524,542 4 288,109,485 4 304,193,716 4",
]
_IS = [  # 3711 p6：表名讀錯成「合併現金損益表」
    "日月光投資控股股份有限公司及子公司",
    "合併現金損益表",
    "單位：新台幣千元，惟每",
    "代 碼 115年4月1日至6月30日 114年4月1日至6月30日 115年1月1日至6月30日 114年1月1日至6月30日",
    "4000 營業收入（附註四十） $ 191,063,522 100 $ 150,750,323 100 $ 364,725,674 100 $ 298,903,585 100",
    "5000 營業成本（附註十一及二五） 150,913,465 79 125,062,803 83 289,757,480 79 248,323,329 83",
    "5900 營業毛利 40,150,057 21 25,687,520 17 74,968,194 21 50,580,256 17",
]
_EQ = [  # 3711 p8：權益變動表
    "單位：新台幣千元",
    "A1 114年1月1日餘額 4,415,201 $ 44,152,505 $ 148,872,716",
    "B1 法定盈餘金額 - - - 3,259,174 - (3,259,174)",
    "B5 普通股現金股利 - - - - - (23,420,372)",
    "C7 採用權益法認列關聯企業之變動數 - - 21,603",
]
_CF = [  # 2330 p8：表名讀成「台灣資產負債表」、無代碼
    "台灣積體電器股份有限公司及子公司",
    "台灣資產負債表",
    "單位：新台幣仟元",
    "115年1月1日 至6月30日 114年1月1日 至6月30日",
    "營業活動之現金流量：",
    "稅前淨利 $ 1,550,229,773 $ 923,930,616",
    "折舊費用 359,541,458 359,012,194",
]


def _page(n: int, lines: list[str]) -> Page:
    return Page(number=n, text="\n".join(lines), tables=[], lines=lines)


def _doc(ocr: bool) -> PdfDoc:
    pages = [_page(1, ["封面"]), _page(2, _BS), _page(3, _IS), _page(4, _EQ), _page(5, _CF)]
    return PdfDoc(path=Path("x.pdf"), pages=pages, ocr_pages=[2, 3, 4, 5] if ocr else [])


def test_u1_u2_u3_u4_classify_by_content() -> None:
    doc = _doc(ocr=True)
    assert ocr_statement_pages(doc, "bs") == [2]
    assert ocr_statement_pages(doc, "is") == [3]
    assert ocr_statement_pages(doc, "cf") == [5]
    assert 4 not in ocr_statement_pages(doc, "bs") + ocr_statement_pages(doc, "is") + ocr_statement_pages(doc, "cf")


def test_extract_uses_ocr_fallback_when_no_title_anchor() -> None:
    led = extract_statements(_doc(ocr=True), {})
    assert led is not None
    by_st = {st: {r.page for r in led.rows if r.statement == st} for st in ("bs", "is", "cf")}
    assert by_st == {"bs": {2}, "is": {3}, "cf": {5}}
    cash = next(r for r in led.rows if r.key == "cash")
    assert cash.current == 3134218213.0


def test_u5_title_anchor_hit_skips_content_fallback() -> None:
    doc = _doc(ocr=True)
    doc.pages.append(_page(6, ["合併資產負債表", *_BS[1:]]))
    led = extract_statements(doc, {"fs_bs": PageRange(6, 6)})
    assert {r.page for r in led.rows if r.statement == "bs"} == {6}


def test_u6_no_ocr_pages_no_fallback() -> None:
    assert extract_statements(_doc(ocr=False), {}) is None


def test_c1_opex_section_total() -> None:
    assert map_key("is", "合計", "營業費用") == "total_opex"
    assert map_key("is", "合計", "營業外收入及支出") == "nonoperating_total"


def test_c2_and_net_change_aliases() -> None:
    assert map_key("bs", "負債合計", "非流動負債") == "total_liabilities"
    assert map_key("cf", "本期現金及約當現金淨增加數", None) == "net_change_in_cash"
    assert map_key("cf", "現金及約當現金淨減少", None) == "net_change_in_cash"
    assert map_key("is", "其他營業收益及費損淨額", "營業費用") == "other_operating_net"


def test_footer_signature_rows_skipped() -> None:
    for s in ("會計主管:", "會計主管:郭宏銘", "經理人:"):
        assert _is_skip(_norm_label(s))
