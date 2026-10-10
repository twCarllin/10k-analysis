"""工業公司三表解析修正（run 2026-10-10-tw-equity-top100-conform，Task 1：items 1.1–1.5）。

契約 row（task/2026-10-10-tw-equity-top100-conform.md）：
  1.1: 條件式別名（`繼續營業單位本期淨利(損)` → net_income）只在同表沒有本期淨利列時生效。
  1.2: 民國年的表頭解析結果不變。
  1.3: 沒有冒號的「營業成本」不可當區段標題。`ecl_operating` 只有位置在 total_opex 之後、operating_income 之前時才計入。
  1.4: `_reclaim_right_amounts` 只在左半是**非空**的附註殘片時觸發。
  1.5: 只有同表同時有收入合計與支出合計、而且沒有毛利與營業利益列時，才判為單步式。
fixture 的行文字取自 2026Q2 財報 PDF 的原文列（tw_report/，pdfplumber 列通道）。
逐家 22/0/0 的測試讀本地 PDF（OCR 只讀快取），PDF 不在則 skip。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import fs_acceptance, pdf_doc, statements  # noqa: E402
from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.inputs import load_inputs  # noqa: E402
from runtime.tw_equity.statements import (  # noqa: E402
    SECTION_HEADERS,
    SINGLE_STEP_WARNING,
    CrossCheck,
    _is_header,
    _split_line,
    detect_header,
    map_key,
    parse_statement_lines,
    run_cross_checks,
    statement_pages,
)

_PAGE_TOP = [
    "○○股份有限公司及子公司",
    "合併綜合損益表",
    "民國115年及114年1月1日至6月30日",
    "單位：新台幣仟元",
    "(除每股盈餘為新台幣元外)",
]
_IS_HDR = [
    "115年4月至6月 114年4月至6月 115年1月至6月 114年1月至6月",
    "金　額 % 金　額 % 金　額 % 金　額 %",
]


def _parse(texts: list[str], statement: str = "is", top: list[str] | None = None):
    top = _PAGE_TOP + _IS_HDR if top is None else top
    lines = [(1, i, t) for i, t in enumerate(top + texts)]
    rows, _, _ = parse_statement_lines(lines, statement, section_headers=SECTION_HEADERS[statement])
    return rows


def _by_key(rows, key):
    return next(r for r in rows if r.key == key)


def _check(checks, name):
    return [c for c in checks if c.name == name]


# ── 1.1 別名與營業成本合計（I-11、I-14） ──────────────────────────────────────


@pytest.mark.parametrize("statement,label,key", [
    ("cf", "籌資活動之淨現金流(出)入", "cff"),
    ("cf", "籌資活動之現金流出", "cff"),
    ("cf", "匯率變動對現金之影響", "fx_effect"),
    ("cf", "本期現金及約當現金(減少)數", "net_change_in_cash"),
    ("cf", "本期現金及約當現金增(減)數", "net_change_in_cash"),
    ("cf", "本期現金及約當現金淨增加(減少)", "net_change_in_cash"),
    ("cf", "繼續營業單位稅前淨利(損)", "pretax_income_cf"),
    ("cf", "本期稅前淨(損)利", "pretax_income_cf"),
    ("is", "營業外收入及支出淨額", "nonoperating_total"),
    ("bs", "現金", "cash"),
    ("is", "營業成本合計", "cogs_total"),
    ("is", "收入合計", "income_total"),
    ("is", "支出合計", "expense_total"),
    ("is", "預期信用減損損失", "ecl_operating"),
])
def test_new_aliases_map_to_keys(statement, label, key) -> None:
    assert map_key(statement, label, None) == key


def test_conditional_net_income_alias_only_when_no_net_income_row() -> None:
    """契約 1.1：同表沒有本期淨利列 → `繼續營業單位本期淨利(損)` 是 net_income；有本期淨利列 → 維持對不到 key。"""
    cont = "6900 繼續營業單位本期淨利(損) 8,000 8 7,000 7 16,000 8 14,000 7"
    rows = _parse([cont])
    assert _by_key(rows, "net_income").current == 16000
    rows = _parse([cont, "8200 本期淨利 8,000 8 7,000 7 16,000 8 14,000 7"])
    assert [r.label for r in rows if r.key == "net_income"] == ["本期淨利"]
    assert next(r for r in rows if r.label.startswith("繼續營業單位")).key is None


_COGS_ROWS = [
    "4000 營業收入 $ 1,000,000 100 $ 900,000 100 $ 2,000,000 100 $ 1,800,000 100",
    "5110 銷貨成本 (600,000) (60) (540,000) (60) (1,200,000) (60) (1,080,000) (60)",
    "5120 工程成本 (100,000) (10) (90,000) (10) (200,000) (10) (180,000) (10)",
    "5000 營業成本合計 (700,000) (70) (630,000) (70) (1,400,000) (70) (1,260,000) (70)",
    "5900 營業毛利 300,000 30 270,000 30 600,000 30 540,000 30",
]


def test_cogs_total_takes_precedence_over_cogs(monkeypatch) -> None:
    """對照式：生產碼 → 毛利勾稽取營業成本合計而通過；拆掉 cogs_total 候選 → 取組成項 銷貨成本 而不通過。"""
    rows = _parse(_COGS_ROWS)
    assert _by_key(rows, "cogs_total").current == -1400000
    gp = _check(run_cross_checks(rows), "is_gross_profit")
    assert [c.passed for c in gp] == [True, True]
    monkeypatch.setitem(statements._KEY_CANDIDATES, ("is_gross_profit", "cogs"), ("cogs",))
    gp = _check(run_cross_checks(rows), "is_gross_profit")
    assert [c.passed for c in gp] == [False, False]


# ── 1.2 西元年表頭（I-13） ────────────────────────────────────────────────────

_ROC_PERIODS = ["115-06-30", "114-12-31", "114-06-30"]


@pytest.mark.parametrize("lines", [
    ["中租控股股份有限公司及子公司", "合併資產負債表", "2026年6月30日 2025年12月31日 2025年6月30日", "單位：新台幣千元"],
    ["中租控股股份有限公司及子公司", "合併資產負債表", "2026.6.30 2025.12.31 2025.6.30", "單位：新台幣千元"],
    ["中租控股股份有限公司及子公司", "合併資產負債表",
     "二○二六年六月三十日、二○二五年十二月三十一日及六月三十日 單位：新台幣千元",
     "2026.6.30 2025.12.31 2025.6.30"],
    ["Silergy Corp.及子公司", "合併資產負債表", "西元2026 年6 月30 日暨西元2025 年12 月31 日及6 月30 日",
     "單位：新台幣仟元", "2026年6月30日 2025年12月31日 2025年6月30日"],
], ids=["年月日", "點分", "中文西元表題", "西元表題"])
def test_western_year_header_forms_yield_roc_periods(lines) -> None:
    assert detect_header(lines).periods == _ROC_PERIODS


def test_western_year_titles_are_skipped_not_taken_as_periods() -> None:
    h = detect_header([
        "中租控股股份有限公司及子公司", "合併綜合損益表",
        "二○二六年及二○二五年四月一日至六月三十日及二○二六年及二○二五年一月一日至六月三十日", "單位：新台幣千元",
        "2026年4月至6月 2025年4月至6月 2026年1月至6月 2025年1月至6月",
    ])
    assert len(h.periods) == 4 and 2 in h.skip_idx
    assert h.periods[2] == "115-01-01~115-06-30"


def test_5871_side_by_side_bs_header_and_cf_two_columns() -> None:
    bs = detect_header([
        "中租控股股份有限公司及子公司", "合併資產負債表",
        "二○二六年六月三十日、二○二五年十二月三十一日及六月三十日 單位：新台幣千元",
        "2026.6.30 2025.12.31 2025.6.30 2026.6.30 2025.12.31 2025.6.30",
        "資　　產 金　　額 % 金　　額 % 金　　額 % 　負債及權益 金　　額 % 金　　額 % 金　　額 %",
    ])
    assert bs.side_by_side is True and bs.periods == _ROC_PERIODS
    cf = detect_header([
        "中租控股股份有限公司及子公司", "合併現金流量表", "二○二六年及二○二五年一月一日至六月三十日",
        "單位：新台幣千元", "2026年1月至6月 2025年1月至6月",
    ])
    assert cf.periods == ["115-01-01~115-06-30", "114-01-01~114-06-30"]


def test_roc_header_result_unchanged() -> None:
    """契約 1.2：民國年表頭的解析結果不變（含欄名帶「民國」與中文數字年）。"""
    assert detect_header(["x", "y", "民國115年6月30日 民國114年12月31日 民國114年6月30日"]).periods == _ROC_PERIODS
    assert detect_header(["x", "民國一一五年六月三十日、一一四年十二月三十一日", "115年6月30日 114年12月31日"]).periods \
        == ["115-06-30", "114-12-31"]
    h = detect_header(_PAGE_TOP + _IS_HDR)
    assert h.periods[2] == "115-01-01~115-06-30" and len(h.periods) == 4


def test_western_year_mutation_selfcheck(monkeypatch) -> None:
    """對照式：生產碼 → 西元年轉成民國期間；西元轉換拆掉 → 期間錯誤（026 年）。"""
    lines = ["x", "合併資產負債表", "2026年6月30日 2025年12月31日 2025年6月30日"]
    assert detect_header(lines).periods == _ROC_PERIODS
    monkeypatch.setattr(statements, "_ad_to_roc", lambda raw: raw)
    assert detect_header(lines).periods != _ROC_PERIODS


# ── 1.3 行組裝（I-15、I-16、I-17） ────────────────────────────────────────────

_L_2618 = [
    "4000 營業收入(附註六(二十二)及七) $ 67,769,702 100 55,307,234 100 128,285,547 100 110,251,392 100",
    "5000 營業成本(附註六(五)、六(八)、六(九)、六(十一)、",
    "六(十四)、六(十六)、六(十八)、六(二十三)、七及",
    "九) (58,193,926) (86) (41,327,439) (75) (102,844,203) (80) (83,692,639) (76)",
    "5900 營業毛利 9,575,776 14 13,979,795 25 25,441,344 20 26,558,753 24",
    "6000 營業費用(附註六(四)、六(八)、六(九)、六(十)、六",
    "(十一)、六(十四)、六(十八)、六(二十三)及七) (3,856,755) (6) (3,563,092) (6) (8,442,403) (7) (7,791,002) (7)",
    "6900 營業淨利(損) 5,719,021 8 10,416,703 19 16,998,941 13 18,767,751 17",
]


def test_multiline_note_label_keeps_cogs_and_opex_rows() -> None:
    """2618：`5000 營業成本(附註…` 斷 3 行、`6000 營業費用(附註…` 斷 2 行，兩列都要有且金額正確、毛利與營業利益勾稽通過。"""
    rows = _parse(_L_2618)
    assert _by_key(rows, "cogs").current == -102844203
    opex = _by_key(rows, "total_opex")
    assert (opex.code, opex.current, opex.prior) == ("6000", -8442403, -7791002)
    assert "營業費用" in opex.label
    cks = run_cross_checks(rows)
    assert [c.passed for c in _check(cks, "is_gross_profit")] == [True, True]
    assert [c.passed for c in _check(cks, "is_operating_income")] == [True, True]


def test_note_fragment_without_closing_paren_is_not_a_row() -> None:
    """2618 反例：續行 label 是普通科目時，帶代碼的標題列不被當成斷行科目（區段標題行為不變）。"""
    rows = _parse([
        "6000 營業費用",
        "6100 推銷費用 (1,000) (1) (900) (1) (2,000) (1) (1,800) (1)",
    ])
    assert _by_key(rows, "selling_expenses").current == -2000


_BS_HDR_6139 = [
    "亞翔工程股份有限公司及子公司", "合併資產負債表", "民國一一五年六月三十日、一一四年十二月三十一日及六月三十日",
    "單 位:新台幣仟元",
    "115年6月30日 114年12月31日 114年6月30日 115年6月30日 114年12月31日 114年6月30日",
    "資 產 附 註 金 額 % 金 額 % 金 額 % 負 債 及 權 益 附 註 金 額 % 金 額 % 金 額 %",
    "流動資產 流動負債",
]
_L_6139 = [
    "1100 現金及約當現金 六、1 $ 37,511,348 31 $ 43,537,242 53 $ 27,261,841 38 2100 短期借款 六、14及七、2 $ 1,783,129 1 $ 1,576,591 2 $ 1,568,397 2",
    "3XXX 權益總計 28,982,178 25 26,697,426 32 18,433,646 26",
    "1XXX 資產總計 $ 120,520,807 100 $ 83,381,417 100 $ 70,382,464 100 2-3XXX 負債及權益總計 $ 120,520,807 100 $ 83,381,417 100 $ 70,382,464 100",
]


def test_note_with_chapter_comma_arabic_and_range_code_6139() -> None:
    """6139：附註 `六、1`、`六、14及七、2` 不被當金額；右半代碼 `2-3XXX` 認得，負債及權益總計有值。"""
    assert _split_line("1100 現金及約當現金 六、1 $ 37,511,348 31")[1:3] == ("六、1", "1100")
    assert _split_line("2100 短期借款 六、14及七、2 $ 1,783,129 1")[1:3] == ("六、14及七、2", "2100")
    rows = _parse(_L_6139, "bs", top=_BS_HDR_6139)
    cash = _by_key(rows, "cash")
    assert (cash.note, cash.current) == ("六、1", 37511348)
    assert _by_key(rows, "total_assets").current == 120520807
    total = _by_key(rows, "total_liabilities_and_equity")
    assert (total.code, total.current) == ("2-3XXX", 120520807)


_IS_HDR_5871 = [
    "中租控股股份有限公司及子公司", "合併綜合損益表",
    "二○二六年及二○二五年四月一日至六月三十日及二○二六年及二○二五年一月一日至六月三十日", "單位：新台幣千元",
    "2026年4月至6月 2025年4月至6月 2026年1月至6月 2025年1月至6月",
    "金　額 ％ 金　額 ％ 金　額 ％ 金　額 ％",
]
_L_5871_COGS = [
    "營業收入淨額 24,296,357 100 24,574,334 100 48,294,600 100 49,280,844 100",
    "營業成本(附註七)：",
    "5111 　銷貨成本 1,393,476 6 1,383,823 6 2,635,504 6 2,539,237 6",
    "5240 　利息費用 4,803,447 20 4,765,744 19 9,518,554 20 9,750,618 19",
    "5300 　租賃成本 1,288,190 5 1,225,530 5 2,568,489 5 2,455,395 5",
    "5800 　其他營業成本 737,174 3 927,868 4 1,511,245 3 1,941,160 4",
    "8,222,287 34 8,302,965 34 16,233,792 34 16,686,410 34",
    "營業毛利 16,074,070 66 16,271,369 66 32,060,808 66 32,594,434 66",
]
_L_5871_OPEX = [
    "6400 營業費用(附註七) 4,553,526 18 4,803,686 19 9,114,476 19 9,753,755 20",
    "6450 預期信用減損損失(附註六(四)) 4,340,861 18 4,859,718 20 8,861,602 18 9,828,533 20",
    "6500 其他收益及費損淨額(附註六(二十)) 481,424 2 303,596 1 1,001,111 2 673,796 1",
    "營業淨利 7,661,107 32 6,911,561 28 15,085,841 31 13,685,942 27",
]


def test_cost_section_header_needs_colon() -> None:
    """契約 1.3：只有帶冒號的 `營業成本:` 是區段標題；沒有冒號的「營業成本」（斷行科目名）不是。"""
    sh = SECTION_HEADERS["is"]
    assert _is_header("營業成本:", sh) is True
    assert _is_header("營業成本", sh) is False
    rows = _parse(_L_5871_COGS, top=_IS_HDR_5871)
    assert _by_key(rows, "cogs_total").current == 16233792  # `營業成本(附註七)：` 區段下的無名小計不被丟掉
    gp = _check(run_cross_checks(rows), "is_gross_profit")
    assert [c.passed for c in gp] == [True, True]


def test_ecl_counted_only_between_total_opex_and_operating_income() -> None:
    """契約 1.3：預期信用減損損失位於營業費用之後、營業利益之前 → 營業利益勾稽扣 |v|；位置不符 → 不計入。"""
    base = _L_5871_COGS[-1:]
    rows = _parse(base + _L_5871_OPEX, top=_IS_HDR_5871)
    assert _by_key(rows, "ecl_operating").current == 8861602
    op = _check(run_cross_checks(rows), "is_operating_income")
    assert [c.passed for c in op] == [True, True]
    # 位置在 total_opex 之前 → 不計入 → 勾稽不通過（對照：同一份列、僅順序不同）
    swapped = [_L_5871_OPEX[1], _L_5871_OPEX[0], *_L_5871_OPEX[2:]]
    op = _check(run_cross_checks(_parse(base + swapped, top=_IS_HDR_5871)), "is_operating_income")
    assert [c.passed for c in op] == [False, False]


# ── 1.4 續頁與並排歸屬（I-18、I-19） ──────────────────────────────────────────

_CF_HDR_2002 = ["115 年1 月1 日 114 年1 月1 日", "代 碼 至6 月30 日 至6 月30 日"]


def _cf_doc(second_page_head: str) -> pdf_doc.PdfDoc:
    p8 = ["中國鋼鐵股份有限公司及子公司", "合併現金流量表", "民國115 及114 年1 月1 日至6 月30 日",
          "單位：新台幣千元", *_CF_HDR_2002, "營業活動之現金流量",
          "A10000 本期稅前淨利(損) $ 2,339,078 $ (1,567,631)"]
    p9 = [second_page_head, "代 碼 至6 月30 日 至6 月30 日", "A31150 應收帳款 (226,467) 3,085,741"]
    p10 = ["115 年1 月1 日 114 年1 月1 日", "代 碼 至6 月30 日 至6 月30 日", "B07500 收取之利息 632,287 649,877"]
    return pdf_doc.PdfDoc(path=Path("x.pdf"), pages=[
        pdf_doc.Page(number=8, text="", tables=[], lines=p8),
        pdf_doc.Page(number=9, text="", tables=[], lines=p9),
        pdf_doc.Page(number=10, text="", tables=[], lines=p10),
    ])


def test_continuation_page_with_same_column_header_row_is_collected(monkeypatch) -> None:
    """2002：續頁無表名、無承前頁，頁首列＝首頁的期間欄列 → 收為續頁；對照：首列不同 → 停在首頁。"""
    rng = PageRange(8, 10)
    assert statement_pages(_cf_doc("115 年1 月1 日 114 年1 月1 日"), rng, "現金流量表") == [8, 9, 10]
    assert statement_pages(_cf_doc("其他 頁首 雜訊"), rng, "現金流量表") == [8]
    monkeypatch.setattr(statements, "_COL_DATES_RE", re.compile(r"(?!)"))
    assert statement_pages(_cf_doc("115 年1 月1 日 114 年1 月1 日"), rng, "現金流量表") == [8]


_BS_2409 = [
    "友達光電股份有限公司及子公司",
    "合併資產負債表",
    "民國一一五年六月三十日、一一四年十二月三十一日及六月三十日 單位：新台幣千元",
    "115.6.30 114.12.31 114.6.30 115.6.30 114.12.31 114.6.30",
    "資　　產 　負債及權益 金　　額 % 金　　額 % 金　　額 %",
    "金　　額 % 金　　額 % 金　　額 %",
    "流動資產： 流動負債：",
    "2280 租賃負債－流動(附註六(十一)) 752,620 - 810,558 - 785,923 -",
    "1410 　預付款項(附註六(十四)) 3,402,087 1 2,678,705 1 3,566,498 1 2399 其他流動負債(附註六(十二)、(十九)、(廿",
    "1460 　待出售非流動資產(附註六(十)、(十一)及 一)及(廿二)) 30,692,323 8 29,349,198 8 28,654,356 8",
    "(十二)) 684,171 - 984,345 - 340,415 - 2322 一年內到期長期借款(附註六(十六)及八) 18,417,703 5 23,101,224 6 14,818,346 4",
    "1476 　其他金融資產－流動(附註六(五)、(十)、 　　 123,417,456 33 123,527,758 32 108,578,011 29",
    "(廿一)及八) 7,732,668 2 6,410,501 2 5,732,418 2 非流動負債：",
]


def test_right_half_amounts_reclaimed_for_split_left_label(monkeypatch) -> None:
    """2409：左科目名換行、同列右半是附註殘片＋金額 → 上一列金額歸右半（2399 其他流動負債）。"""
    rows = _parse(_BS_2409, "bs", top=[])
    other = _by_key(rows, "other_current_liabilities")
    assert (other.code, other.current, other.prior) == ("2399", 30692323, 29349198)
    assert next(r for r in rows if r.code == "1460").current == 684171  # 左半金額仍歸左半
    monkeypatch.setattr(statements, "_reclaim_right_amounts", lambda *a, **k: None)  # 對照：拆掉 → 右半金額遺失
    assert not any(r.key == "other_current_liabilities" for r in _parse(_BS_2409, "bs", top=[]))


def _entry(label: str, code: str | None, has_amt: bool = True):
    return (5, 1, label, "", code, ([1.0], [None], 0) if has_amt else None)


@pytest.mark.parametrize("frag,moved", [
    ("(十二))", True),       # 非空附註殘片 → 觸發
    ("", False),             # 空殘片（左半無名小計：2382、2615）→ 不動
    ("一般科目", False),      # 非附註殘片的普通科目名 → 不動
    ("一)及(廿二))", True),   # 2409 真實殘片 → 觸發
    ("(減：備抵損失)", False),  # `(` 開頭的一般科目名（審查 🟡-2）→ 不動
])
def test_reclaim_triggers_only_for_non_empty_note_fragment(frag, moved) -> None:
    """契約 1.4：只在左半是非空的附註殘片時觸發。"""
    left = [_entry("預付款項", "1410")]
    streams = [left, []]
    statements._reclaim_right_amounts(streams, _entry(frag, None), True)
    assert (len(streams[1]) == 1) is moved
    assert (left[0][5] is None) is moved


def test_reclaim_requires_left_only_previous_row() -> None:
    left = [_entry("預付款項", "1410")]
    streams = [left, []]
    statements._reclaim_right_amounts(streams, _entry("(十二))", None), False)
    assert streams[1] == [] and left[0][5] is not None


# ── 1.5 單步式損益表（I-12） ──────────────────────────────────────────────────

_L_2207 = [
    "4290 已實現銷貨損益 - - - - 62,214 - 82,160 -",
    "收入合計 89,551,521 100 68,531,434 100 160,882,752 100 141,644,419 100",
    "支出",
    "5320 其他支出 ( 89,065 ) - ( 97,447 ) - ( 363,134) - ( 206,854 ) -",
    "支出合計 ( 78,865,303 ) ( 88) ( 62,136,049 ) ( 91) ( 143,660,885) ( 89) ( 129,291,395 ) ( 91)",
    "6100 繼續營業單位稅前淨利 10,686,218 12 6,395,385 9 17,221,867 11 12,353,024 9",
    "6200 所得稅費用 六(三十三) ( 2,183,758 ) ( 3) ( 1,407,922 ) ( 2) ( 3,462,097) ( 2) ( 2,622,166 ) ( 2)",
    "6500 本期淨利 $ 8,502,460 9 $ 4,987,463 7 $ 13,759,770 9 $ 9,730,858 7",
]


def test_single_step_is_detected_and_pretax_uses_totals() -> None:
    rows = _parse(_L_2207)
    warnings: list[str] = []
    cks = run_cross_checks(rows, warnings=warnings)
    assert SINGLE_STEP_WARNING in warnings
    assert [c.passed for c in _check(cks, "is_pretax")] == [True, True]
    na = [c for c in cks if c.name in ("is_gross_profit", "is_operating_income")]
    assert len(na) == 4 and all(c.passed is None for c in na)


def test_single_step_requires_both_totals_and_no_gross_or_operating_rows() -> None:
    """契約 1.5：只有同時有收入合計與支出合計、且沒有毛利與營業利益列時才是單步式。"""
    def run(texts):
        w: list[str] = []
        cks = run_cross_checks(_parse(texts), warnings=w)
        return SINGLE_STEP_WARNING in w, cks

    only_income = [t for t in _L_2207 if not t.startswith("支出合計")]
    assert run(only_income)[0] is False
    only_expense = [t for t in _L_2207 if not t.startswith("收入合計")]
    assert run(only_expense)[0] is False
    with_gross = _L_2207 + ["5900 營業毛利 1,000 1 1,000 1 1,000 1 1,000 1"]
    assert run(with_gross)[0] is False
    with_op = _L_2207 + ["6900 營業淨利 1,000 1 1,000 1 1,000 1 1,000 1"]
    assert run(with_op)[0] is False


def _checks22(na_names: tuple[str, ...] = ()) -> list[CrossCheck]:
    out = []
    for i in range(11):
        for p in ("current", "prior"):
            name = f"chk{i}"
            if i < len(na_names):
                name = na_names[i]
            out.append(CrossCheck(name=name, period=p, lhs=1.0, rhs=1.0,
                                  passed=None if name in na_names else True))
    return out


def test_acceptance_treats_single_step_na_checks_as_not_failed() -> None:
    """驗收：帶單步式標記時 is_gross_profit／is_operating_income 的 None 算不適用；無標記時仍算未通過。"""
    checks = _checks22(("is_gross_profit", "is_operating_income"))
    got = fs_acceptance.evaluate_checks("2207", "industrial", checks, [SINGLE_STEP_WARNING])
    assert got["conform"] is True and got["not_passed"] == []
    assert sorted(got["not_applicable"]) == [
        "is_gross_profit/current", "is_gross_profit/prior",
        "is_operating_income/current", "is_operating_income/prior",
    ]
    plain = fs_acceptance.evaluate_checks("2207", "industrial", checks, [])
    assert plain["conform"] is False and len(plain["not_passed"]) == 4
    # 標記只豁免這兩項：別的項目 None 仍是失敗
    other = _checks22(("is_gross_profit", "cf_ending"))
    got = fs_acceptance.evaluate_checks("2207", "industrial", other, [SINGLE_STEP_WARNING])
    assert got["conform"] is False
    assert sorted(got["not_passed"]) == ["cf_ending/current", "cf_ending/prior"]


# ── 逐家勾稽（本地 PDF，OCR 只讀快取；PDF 不在則 skip） ───────────────────────

_TARGETS = [
    "1519", "1802", "2618", "6139", "2002", "2409", "2492", "3293", "3532", "6239",
    "2337", "6415", "5871", "2207",
]
_REGRESSION = ["2301", "2382", "2615"]


def _company(ticker: str) -> dict:
    inp = load_inputs(ticker, base_dir=ROOT)
    if inp.consolidated_fs_path is None or not Path(inp.consolidated_fs_path).exists():
        pytest.skip(f"{ticker} 財報 PDF 不在本機")
    return fs_acceptance.check_company(ticker, inp.group, ROOT)


@pytest.mark.parametrize("ticker", _TARGETS + _REGRESSION)
def test_company_conforms(ticker) -> None:
    rec = _company(ticker)
    assert rec.get("conform") is True, (rec.get("error"), rec.get("not_passed"))


def test_2207_single_step_na_items_are_the_gross_and_operating_checks() -> None:
    rec = _company("2207")
    assert sorted(rec["not_applicable"]) == [
        "is_gross_profit/current", "is_gross_profit/prior",
        "is_operating_income/current", "is_operating_income/prior",
    ]
