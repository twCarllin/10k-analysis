"""工業／石化三表解析修正（run 2026-10-10-tw-equity-70-conform，Task 1：items 1.1–1.5）。

契約 row（task/2026-10-10-tw-equity-70-conform.md）：
  1.1: 別名表新增列不改既有別名的對應結果
  1.2: 列首裸中文數字（如 `七`）不得當純附註行處理（曾破壞 2317／2603／4958 的 cogs）
  1.3: (a) 兩列錯開表頭重排對工業與 fh 皆生效，fh 既有結果不變
  1.4: 6488 `net_defined_benefit_liabilities` 本期 = 1,255,650
  1.5: 單幣別報表的頁收集與欄位選取結果不變
行文字取自 2026Q2 財報 PDF 的原文列（tw_report/，以 pdfplumber 列通道抽出）。
逐家 22/0/0 的測試讀本地 PDF（OCR 只讀快取），PDF 不在則 skip。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc, statements, tables  # noqa: E402
from runtime.tw_equity.doc_anchor import (  # noqa: E402
    FS_HEADING_ANCHORS,
    PageRange,
    find_heading_sections,
)
from runtime.tw_equity.inputs import load_inputs  # noqa: E402
from runtime.tw_equity.statements import (  # noqa: E402
    SECTION_HEADERS,
    _columns,
    _split_line,
    _split_sides,
    detect_header,
    extract_statements,
    line_amounts,
    map_key,
    parse_statement_lines,
    statement_pages,
)


# 真實頁首的 5 列（公司名／表名／民國期間／單位／附記）。解析器對頁首 5 列內無金額的列另有處置，
# fixture 補上才能讓表頭列落在真實的列索引（idx）。
_PAGE_TOP = [
    "○○股份有限公司及子公司",
    "合併綜合損益表",
    "民國115年及114年1月1日至6月30日",
    "單位：新台幣仟元",
    "(除每股盈餘為新台幣元外)",
]


def _parse(texts: list[str], statement: str, schema: str = "industrial"):
    lines = [(1, i, t) for i, t in enumerate(_PAGE_TOP + texts)]
    rows, _, _ = parse_statement_lines(
        lines, statement, section_headers=SECTION_HEADERS[statement], schema=schema
    )
    return rows


def _by_key(rows, key):
    return next(r for r in rows if r.key == key)


def _doc(heads: dict[int, list[str]]) -> pdf_doc.PdfDoc:
    return pdf_doc.PdfDoc(
        path=Path("x.pdf"),
        pages=[pdf_doc.Page(number=n, text="", tables=[], lines=ls) for n, ls in heads.items()],
    )


# ── 1.1 別名與附註字元（I-1、I-7、I-10） ──────────────────────────────────────


@pytest.mark.parametrize("statement,label,key", [
    ("bs", "資產總額", "total_assets"),
    ("bs", "負債及權益總額", "total_liabilities_and_equity"),
    ("is", "稅前淨利(淨損)", "pretax_income"),
    ("is", "所得稅利益(費用)", "income_tax"),
    ("is", "營業費用", "total_opex"),
    ("cf", "本年度稅前淨利", "pretax_income_cf"),
    ("cf", "營業活動之淨現金(流出)流入", "cfo"),
    ("cf", "匯率變動影響數", "fx_effect"),
    ("cf", "現金及約當現金增加", "net_change_in_cash"),
    ("cf", "年初現金及約當現金餘額", "cash_beginning"),
    ("cf", "年底現金及約當現金餘額", "cash_ending"),
    ("cf", "合併資產負債表列示之現金及約當現金", "cash_per_bs_in_cf"),
])
def test_new_aliases_map_to_spec_keys(statement, label, key) -> None:
    assert map_key(statement, label, None) == key


@pytest.mark.parametrize("statement,label,key", [
    ("bs", "資產總計", "total_assets"),
    ("is", "稅前淨利", "pretax_income"),
    ("is", "營業費用合計", "total_opex"),
    ("cf", "期末現金及約當現金餘額", "cash_ending"),
    ("cf", "資產負債表帳列之現金及約當現金", "cash_per_bs_in_cf"),
    ("cf", "匯率變動對現金及約當現金影響數", "fx_effect"),
])
def test_existing_aliases_keep_mapping(statement, label, key) -> None:
    assert map_key(statement, label, None) == key


def test_note_with_nian_ten_char_is_stripped() -> None:
    label, note, code, amounts = _split_line("8200 所得稅費用 六(廿二) (3,261,283) (3,160,024)")
    assert (label, note, code) == ("所得稅費用", "六(廿二)", "8200")
    assert amounts == [-3261283, -3160024]
    assert map_key("is", label, None) == "income_tax"


def test_ai2_report_titles_without_consolidated_get_anchors() -> None:
    """3081 個別財報表名無「合併」：三表錨點非 None；合併財報的表名照舊命中。"""
    doc = _doc({
        4: ["聯亞光電工業股份有限公司", "資產負債表"],
        5: ["聯亞光電工業股份有限公司", "綜合損益表"],
        7: ["聯亞光電工業股份有限公司", "現金流量表"],
    })
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    assert (anchors["fs_bs"], anchors["fs_is"], anchors["fs_cf"]) == (
        PageRange(4, 4), PageRange(5, 6), PageRange(7, 7),
    )
    doc = _doc({4: ["統一企業股份有限公司", "合併資產負債表"]})
    assert find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())["fs_bs"] == PageRange(4, 4)


# ── 1.2 行組裝（I-2、I-3、I-4） ───────────────────────────────────────────────

_IS_HDR_2615 = [
    "115年4月至6月 114年4月至6月 115年1月至6月 114年1月至6月",
    "金　　額 ％ 金　　額 ％ 金　　額 ％ 金　　額 ％",
]


def test_lone_emdash_is_zero_marker_not_a_token() -> None:
    """2615：`—` 表 0／空。獨立 em-dash 轉 `-`（None），金額 token 數才對。"""
    assert line_amounts("518,000 — 40,000 — 9,094,079 2") == [518000, None, 40000, None, 9094079, 2]
    rows = _parse(_IS_HDR_2615 + [
        "6500 其他收益及費損淨額(附註六(二十四)) 105,683 — 241,786 1 180,063 — 397,451 1",
        "7010 其他收入 99,084 — 89,054 — 107,949 — 96,976 —",
    ], "is")
    other = _by_key(rows, "other_income")
    assert (other.current, other.prior) == (107949, 96976)
    gain = next(r for r in rows if r.code == "6500")
    assert (gain.current, gain.prior) == (180063, 397451)


def test_emdash_mutation_selfcheck(monkeypatch) -> None:
    """對照式：patch 前（生產碼）token 正確；把 em-dash 規則拆掉後，同一列欄位錯位。"""
    line = "99,084 — 89,054 — 107,949 — 96,976 —"
    assert line_amounts(line) == [99084, None, 89054, None, 107949, None, 96976, None]
    monkeypatch.setattr(tables, "_LONE_DASH_RE", __import__("re").compile(r"(?!)"))
    assert line_amounts(line) == [99084, 89054, 107949, 96976]


_IS_HDR_1216 = [
    "1 1 5 年4 月1 日 1 1 4 年4 月1 日 1 1 5 年1 月1 日 1 1 4 年1 月1 日",
    "至 6 月 3 0 日 至 6 月 3 0 日 至 6 月 3 0 日 至 6 月 3 0 日",
    "項目 附註 金 額 % 金 額 % 金 額 % 金 額 %",
]


def test_three_line_note_does_not_drop_cogs() -> None:
    """1216：營業成本附註斷成 3 行，中段純附註行 `(二十)(三十)` 不可截斷合併。"""
    rows = _parse(_IS_HDR_1216 + [
        "4000 營業收入 六(十一)(十二)",
        "(二十五)及七 $ 174,920,881 100 $ 169,572,497 100 $ 349,938,252 100 $ 338,837,523 100",
        "5000 營業成本 六(六)(十)(十三)",
        "(二十)(三十)",
        "(三十一)及七 ( 115,474,098 )( 66)( 112,251,934 )( 66)( 231,366,231)( 66)( 225,380,957 )( 67)",
        "5900 營業毛利 59,446,783 34 57,320,563 34 118,572,021 34 113,456,566 33",
    ], "is")
    cogs = _by_key(rows, "cogs")
    assert (cogs.current, cogs.prior) == (-231366231, -225380957)
    assert _by_key(rows, "gross_profit").current == 118572021


@pytest.mark.parametrize("head,first,cogs", [
    (
        ["5000 營業成本 六(九)(三十五)及",
         "七 (2,371,361,112) (94) (1,679,939,050) (94) (4,359,913,943) (94) (3,223,706,186) (94)"],
        "4000 營業收入 六(三十一)及七 $ 2,525,894,433 100 $ 1,793,468,046 100 $ 4,645,427,824 100 $ 3,437,783,609 100",
        (-4359913943, -3223706186),
    ),  # 2317
    (
        ["5000 營業成本 六(二十九)(三十)及",
         "七 ( 81,183,443 )( 77)( 67,790,903 )( 78)( 154,308,221)( 80)( 144,469,500 )( 74)"],
        "4000 營業收入 六(二十三)及七 $ 105,160,983 100 $ 86,483,997 100 $ 191,672,454 100 $ 196,454,558 100",
        (-154308221, -144469500),
    ),  # 2603
])
def test_leading_bare_cn_number_line_keeps_cogs(head, first, cogs) -> None:
    """契約 1.2：列首裸中文數字 `七` 不是純附註行，cogs 值與修改前相同。"""
    rows = _parse(_IS_HDR_1216 + [first] + head, "is")
    got = _by_key(rows, "cogs")
    assert (got.current, got.prior) == cogs


def test_4958_revenue_note_tail_line_keeps_cogs() -> None:
    rows = _parse(_IS_HDR_1216 + [
        "4000 營業收入 六(二十三)、七及",
        "十四 $ 48,430,657 100 $ 38,203,475 100 $ 89,158,843 100 $ 78,285,348 100",
        "5000 營業成本 六(六)及七 ( 37,244,554 )( 77)( 31,192,583)( 82)( 69,161,054 )( 78)( 65,389,426 )( 84)",
    ], "is")
    assert _by_key(rows, "revenue").current == 89158843
    assert _by_key(rows, "cogs").current == -69161054


def test_unlabeled_subtotal_with_code_only_rows_is_recognised() -> None:
    """2615：區段內有「代碼＋金額、科目名在他行」的列，無名小計的加總須把它算進去。"""
    rows = _parse([
        "115年6月30日 114年12月31日",
        "流動資產：",
        "1100 現金及約當現金 100,000 80,000",
        "1110 40,000 30,000",
        "140,000 110,000",
    ], "bs")
    total = _by_key(rows, "total_current_assets")
    assert (total.current, total.prior) == (140000, 110000)


# ── 1.3 表頭期間偵測（I-5 a–e） ───────────────────────────────────────────────

_Q2_H1 = [
    "115-04-01~115-06-30", "114-04-01~114-06-30", "115-01-01~115-06-30", "114-01-01~114-06-30",
]
_H1 = ["115-01-01~115-06-30", "114-01-01~114-06-30"]
_BS3 = ["115-06-30", "114-12-31", "114-06-30"]


@pytest.mark.parametrize("fh", [False, True])
def test_5a_two_line_staggered_header_reordered_for_industrial_and_fh(fh) -> None:
    """4904：114 年一列、115 年一列 → 資料欄序（本年在前）；工業與 fh 皆生效。"""
    h = detect_header([
        "114年4⽉1⽇⾄6⽉30⽇ 114年1⽉1⽇⾄6⽉30⽇",
        "115年4⽉1⽇⾄6⽉30⽇ (重編後) 115年1⽉1⽇⾄6⽉30⽇ (重編後)",
        "代碼 ⾦ 額 ％ ⾦ 額 ％ ⾦ 額 ％ ⾦ 額 ％",
    ], fh=fh)
    assert h.periods == _Q2_H1
    assert h.side_by_side is False


def test_5b_per_column_minguo_prefix_is_period_row() -> None:
    """6446：每欄帶「民國」的欄名列不當表題；含「及」的表題列仍跳過。"""
    h = detect_header([
        "藥華醫藥股份有限公司及子公司",
        "合併綜合損益表",
        "民國115年及民國114年1月1日至6月30日",
        "單位：除每股盈餘外，新臺幣千元",
        "民國115年4月1日 民國114年4月1日 民國115年1月1日 民國114年1月1日",
        "代碼 會計項目 附　　註 至6月30日 至6月30日 至6月30日 至6月30日",
        "金　　額 % 金　　額 % 金　　額 % 金　　額 %",
    ])
    assert h.periods == _Q2_H1
    assert h.side_by_side is False
    bs = detect_header([
        "民國115年6月30日、民國114年12月31日及民國114年6月30日",
        "資　　產 民國115年6月30日 民國114年12月31日 民國114年6月30日",
    ])
    assert bs.periods == _BS3


def test_5b_two_line_title_with_ranges_is_still_skipped() -> None:
    """3189 回歸：兩列表題（各含「至」、無「及」）不是欄名列，期間仍取下方欄頭。"""
    h = detect_header([
        "民國一一五年四月一日至六月三十日 年一一四年四月一日至六月三十日暨",
        "民國一一五年一月一日至六月三十日民國一一四年一月一日至六月三十日",
        "代碼 項 目 附註 一一五年第二季 一一四年第二季 一一五年上半年度 一一四年上半年度",
    ])
    assert h.periods == _Q2_H1


def test_5c_end_date_without_trailing_day_char() -> None:
    """2313（OCR）：迄日「至 6 月 30」少末尾「日」。"""
    h = detect_header([
        "項 目 115 年 1 月 1 日 至 6 月 30 114 年 1 月 1 日 至 6 月 30",
        "金 額 金 額",
    ])
    assert h.periods == _H1
    assert h.side_by_side is False


def test_5d_year_row_plus_half_year_row() -> None:
    """3034：`一一五年 一一四年 …` 一列、`上半年度 …` 另一列；並排 CF 左右各 2 欄。"""
    h = detect_header([
        "民國一一五年及一一四年一月一日至六月三十日",
        "單位：新台幣仟元",
        "一一五年 一一四年 一一五年 一一四年",
        "代 碼 項　　　目 上半年度 上半年度 代 碼 項　　　目 上半年度 上半年度",
        "金 額 金 額 金 額 金 額",
    ])
    assert h.periods == _H1
    assert h.side_by_side is True


def test_5e_side_by_side_bs_dates_on_two_lines() -> None:
    """8299：並排 BS 日期分兩列（`115.6.30 115.6.30 114.12.31 114.6.30`／`114.12.31 114.6.30`）。"""
    h = detect_header([
        "民國一一五年六月三十日、一一四年十二月三十一日及六月三十日 單位：新台幣千元",
        "115.6.30 115.6.30 114.12.31 114.6.30",
        "114.12.31 114.6.30",
        "資　　產 　負債及權益 金　　額 % 金　　額 % 金　　額 %",
        "金　　額 ％ 金　　額 ％ 金　　額 ％",
    ])
    assert h.periods == _BS3
    assert h.side_by_side is True


def test_5_single_row_header_unchanged() -> None:
    """既有單列表頭、已成對的並排頭結果不變（fh 與工業）。"""
    assert detect_header(["115.6.30 114.12.31 114.6.30"]).periods == _BS3
    h = detect_header(["資產 負債 115.6.30 114.12.31 114.6.30 115.6.30 114.12.31 114.6.30"])
    assert (h.periods, h.side_by_side) == (_BS3, True)


# ── 1.4 並排頁左右歸屬（I-6） ─────────────────────────────────────────────────

_BS_SIDE_HDR = [
    "115.6.30 114.12.31 114.6.30 115.6.30 114.12.31 114.6.30",
    "資　　產 金　　額 ％ 金　　額 ％ 金　　額 ％ 　負債及權益 金　　額 ％ 金　　額 ％ 金　　額 ％",
]


def test_6a_left_section_title_with_right_continuation_split() -> None:
    """6488／3081：左半區段標題與右半內容同列 → 標題歸左、其餘歸右。"""
    left, right = _split_sides(
        "非流動資產： 註六(十五)及八) 19,613 - 540,489 - 1,529,910 1", 6
    )
    assert left == "非流動資產:"
    assert right == "註六(十五)及八) 19,613 - 540,489 - 1,529,910 1"
    left, right = _split_sides("非流動資產： 　　 1,163,237 19 531,794 10 357,939 8", 6)
    assert (left, right.split()[0]) == ("非流動資產:", "1,163,237")
    # 兩側皆是區段標題的列照舊
    assert _split_sides("流動資產： 流動負債：", 6) == ("流動資產:", "流動負債:")


def test_6b_right_label_continuation_amounts_stay_on_right() -> None:
    """6488：右半科目換行，續行的金額列無代碼（`八)) 1,255,650 …`）→ 歸右半，不併入左半。"""
    rows = _parse(_BS_SIDE_HDR + [
        "1900 　其他非流動資產(附註六(十二)) 721,330 - 1,400,008 1 2,779,735 1 2670 　其他非流動負債(附註六(十七)) 2,365,226 1 2,331,342 1 2,213,492 1",
        "136,833,331 62 131,713,361 60 136,820,930 66 2640 　淨確定福利負債－非流動(附註六(十",
        "八)) 1,255,650 1 1,246,002 1 1,478,248 1",
        "58,206,879 26 70,939,034 33 69,868,879 34",
        "負債總計 122,499,929 56 125,047,759 58 121,480,383 59",
    ], "bs")
    ndb = _by_key(rows, "net_defined_benefit_liabilities")
    assert (ndb.current, ndb.prior) == (1255650, 1246002)


def test_6b_mutation_selfcheck(monkeypatch) -> None:
    """對照式：生產碼下 6b 的值正確；關掉對側歸屬後值偏離。"""
    lines = _BS_SIDE_HDR + [
        "136,833,331 62 131,713,361 60 136,820,930 66 2640 　淨確定福利負債－非流動(附註六(十",
        "八)) 1,255,650 1 1,246,002 1 1,478,248 1",
    ]

    def current():
        return [r.current for r in _parse(lines, "bs") if r.key == "net_defined_benefit_liabilities"]

    assert current() == [1255650]
    monkeypatch.setattr(statements, "_fragment_side", lambda streams, s_i, entry, hdrs: s_i)
    assert current() != [1255650]


def test_6c_section_title_with_unclosed_note_paren() -> None:
    """3081：區段標題附註斷行（`6000 營業費用(附註六(九)、(十)、(十三)、(十`）→ 仍是區段標題。"""
    rows = _parse([
        "115年4月至6月 114年4月至6月 115年1月至6月 114年1月至6月",
        "金　額 ％ 金　額 ％ 金　額 ％ 金　額 ％",
        "5900 營業毛利 701,611 57 239,659 43 1,196,844 56 386,672 38",
        "6000 營業費用(附註六(九)、(十)、(十三)、(十",
        "六)、七及十二)：",
        "6100 　推銷費用 16,539 1 12,066 2 29,088 1 23,693 2",
        "6200 　管理費用 63,047 5 31,930 6 106,806 5 54,901 6",
        "129,041 10 90,626 16 251,044 12 192,874 19",
    ], "is")
    assert _by_key(rows, "selling_expenses").section == "營業費用"
    assert _by_key(rows, "selling_expenses").current == 29088


def test_6c_mutation_selfcheck(monkeypatch) -> None:
    lines = [
        "115年4月至6月 114年4月至6月 115年1月至6月 114年1月至6月",
        "金　額 ％ 金　額 ％ 金　額 ％ 金　額 ％",
        "6000 營業費用(附註六(九)、(十)、(十三)、(十",
        "六)、七及十二)：",
        "6100 　推銷費用 16,539 1 12,066 2 29,088 1 23,693 2",
    ]
    assert _by_key(_parse(lines, "is"), "selling_expenses").section == "營業費用"
    monkeypatch.setattr(statements, "_DANGLING_NOTE_RE", __import__("re").compile(r"(?!)"))
    assert _by_key(_parse(lines, "is"), "selling_expenses").section != "營業費用"


# ── 1.5 雙幣別（I-8） ─────────────────────────────────────────────────────────


def test_statement_pages_stop_at_second_currency_copy() -> None:
    """3661：同名綜合損益表有新台幣與美金兩份 → 只收第一份（含其續頁）。"""
    doc = _doc({
        9: ["Alchip Technologies, Limited 及子公司", "合併綜合損益表", "民國115 年及114 年4 月1 日至6 月30 日", "單位：除每股盈餘為新台幣元", "外，餘係新台幣仟元"],
        10: ["（承前頁）", "115年4月1日至6月30日 114年4月1日至6月30日"],
        11: ["Alchip Technologies, Limited 及子公司", "合併綜合損益表", "民國115 年及114 年4 月1 日至6 月30 日", "單位：除每股盈餘為美金元", "外，餘係美金仟元"],
        12: ["（承前頁）", "115年4月1日至6月30日 114年4月1日至6月30日"],
    })
    assert statement_pages(doc, PageRange(9, 12), "綜合損益表") == [9, 10]


def test_statement_pages_single_currency_unchanged() -> None:
    doc = _doc({
        1: ["公司", "合併綜合損益表", "單位：新台幣仟元"],
        2: ["（承前頁）", "x"],
        3: ["公司", "合併綜合損益表", "單位：新台幣仟元"],
        4: ["公司", "合併權益變動表"],
    })
    assert statement_pages(doc, PageRange(1, 4), "綜合損益表") == [1, 2, 3]
    doc = _doc({1: ["公司", "合併現金流量表"], 2: ["(續)", "x"], 3: ["公司", "合併現金流量表"]})
    assert statement_pages(doc, PageRange(1, 3), "現金流量表") == [1, 2, 3]


_CF_USD_TWD = [
    "民國115 年及114 年1 月1 日至6 月30 日",
    "單位：新台幣仟元",
    "或美金仟元",
    "115年1月1日至6月30日 114年1月1日至6月30日",
    "代 碼 美 金 新 台 幣 美 金 新 台 幣",
    "營業活動之現金流量",
    "A10000 本期稅前淨利 $ 120,798 $ 3,818,952 $ 106,488 $ 3,392,626",
    "A20100 折舊及攤銷 46,112 1,457,799 48,801 1,554,740",
]


def test_dual_currency_columns_pick_twd() -> None:
    """3661：每期「美金 新台幣」兩欄 → 取新台幣欄（不是 `[0::2]` 的美金）。"""
    h = detect_header(_CF_USD_TWD)
    assert (h.periods, h.twd_pair) == (_H1, True)
    rows = _parse(_CF_USD_TWD, "cf")
    pretax = _by_key(rows, "pretax_income_cf")
    assert (pretax.current, pretax.prior) == (3818952, 3392626)
    dep = next(r for r in rows if r.code == "A20100")
    assert (dep.current, dep.prior) == (1457799, 1554740)


def test_single_currency_columns_unchanged() -> None:
    """契約 1.5：單幣別（表頭無「美金新台幣」）取欄與改前相同；IS 每欄「金額 %」成對仍取 `[0::2]`。"""
    h = detect_header(["115年1月1日 114年1月1日", "至6月30日 至6月30日", "項目 附註 金額 % 金額 %"])
    assert h.twd_pair is False
    assert _columns("is", 2, [10.0, 5.0, 20.0, 7.0]) == ([10.0, 20.0], [5.0, 7.0], 0)
    assert _columns("cf", 2, [1.0, 2.0, 3.0, 4.0]) == ([1.0, 3.0], None, 0)
    assert _columns("cf", 2, [1.0, 2.0, 3.0, 4.0], twd_pair=True) == ([2.0, 4.0], None, 0)


# ── 逐家勾稽（本地 PDF，OCR 只讀快取；PDF 不在則 skip） ───────────────────────


def _cache_only_ocr(path, pages):
    raise RuntimeError("ocr_cache_miss")


def _ledger(ticker: str):
    inp = load_inputs(ticker, base_dir=ROOT)
    pdf = Path(inp.consolidated_fs_path)
    if not pdf.exists():
        pytest.skip(f"{pdf} 不在本機")
    try:
        doc = pdf_doc.load_pdf(pdf, ocr=_cache_only_ocr)
    except RuntimeError:
        doc = pdf_doc.load_pdf(pdf)
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    return extract_statements(doc, anchors, group=inp.group)


_TARGETS = [
    "1216", "1326", "2615", "3034", "3045", "3481", "6274", "6488",
    "2313", "3081", "3189", "8299", "3661", "4904", "6446", "6770",
]
_LEDGERS: dict = {}


def _led(ticker: str):
    if ticker not in _LEDGERS:
        _LEDGERS[ticker] = _ledger(ticker)
    return _LEDGERS[ticker]


@pytest.mark.parametrize("ticker", _TARGETS)
def test_target_company_checks_all_pass(ticker) -> None:
    c = _led(ticker).checks
    assert (sum(x.passed is True for x in c), sum(x.passed is False for x in c),
            sum(x.passed is None for x in c)) == (22, 0, 0), [x.name for x in c if x.passed is not True]


@pytest.mark.parametrize("ticker", ["6446", "2313"])
def test_h1_basis_for_ocr_and_minguo_prefix_reports(ticker) -> None:
    assert _led(ticker).basis == "H1"


def test_3081_individual_report_has_ledger() -> None:
    led = _led("3081")
    assert led is not None and led.checks


def test_6488_net_defined_benefit_liabilities() -> None:
    rows = [r for r in _led("6488").rows if r.statement == "bs" and r.key == "net_defined_benefit_liabilities"]
    assert [r.current for r in rows] == [1255650]


def test_3661_operating_income_is_twd_not_usd() -> None:
    row = next(r for r in _led("3661").rows if r.statement == "is" and r.key == "operating_income")
    assert row.current is not None and row.current != 95345
    assert row.current > 1_000_000  # 新台幣仟元（美金仟元為 95,345 量級）


@pytest.mark.parametrize("ticker,cogs", [
    ("2317", (-4359913943, -3223706186)),
    ("2603", (-154308221, -144469500)),
    ("4958", (-69161054, -65389426)),
])
def test_regression_cogs_unchanged_vs_before(ticker, cogs) -> None:
    row = next(r for r in _led(ticker).rows if r.statement == "is" and r.key == "cogs")
    assert (row.current, row.prior) == cogs
