"""test_ar_sections.py — `ar_sections.parse_cashflow`（item 1.2）、`parse_contracts`（item 1.3）、
`parse_special`（item 1.4）黑箱行為測試。

契約 row（Task 1.2）：
  R1: 金標 10 家表 A、表 B 數字欄全對
  R2: 表頭兩種寫法（投資及籌資合併欄、全年現金流出量）與 6 欄寫法（2330）
  R3: 單位換算為仟元；單位讀不到 → failed
  R4: arith_ok 依 Spec §2.1(a)，容差 2 仟元（含不平案例）；表 B 只記 arith_diff
  R5: actual_explanations／forecast_explanations 存營業／投資／籌資原文
  R6: 章節沒找到 → not_found；表 B 寫「不適用」→ forecast.applicable=False、status 不變 failed

（item 1.3 的契約 row 見 `parse_contracts` 區段開頭；item 1.4 的見檔尾 `parse_special` 區段開頭。）

說明文字比對前兩邊都做 NFKC 並去空白（金標已去開頭編號，保留「營業活動：」類標籤）。
2412 文字層字型損壞（金標以頁面圖像為準），其說明文字不比對（見 test_garbled_text_known_limit）。
每條新規則附「相近但不該觸發」的反例；TestMutationControls 以改輸入、看輸出同步翻轉自證測試有效。
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unicodedata
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity import pdf_doc as _pdf_doc  # noqa: E402
from runtime.tw_equity.ar_sections import (  # noqa: E402
    STATUS_FAILED,
    STATUS_NONE,
    STATUS_NOT_FOUND,
    STATUS_PARSED,
    CashflowSection,
    ContractRow,
    ContractsSection,
    SpecialSection,
    CashflowTable,
    apply_cashflow_basis,
    cashflow_basis,
    STATUS_DISCLOSED,
    STATUS_SEE_MOPS,
    parse_cashflow,
    parse_contracts,
    parse_special,
)
from runtime.tw_equity.pdf_doc import Page, PdfDoc  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402

_FIX = _REPO_ROOT / "tests" / "fixtures" / "tw_equity"
_PAGES_JSON = _FIX / "ar_sections_pages.json"
_GOLD_JSON = _FIX / "ar_sections_gold_expected.json"

_TICKERS = ["3653", "2330", "2317", "1216", "2454", "2603", "2881", "2886", "1301", "2412"]
_NUM = ["opening_cash", "cfo", "cfi", "cff", "cfi_cff", "outflow", "fx", "closing_cash"]
_TXT = ["remedy_invest", "remedy_finance"]

needs_fixture = pytest.mark.skipif(
    not (_PAGES_JSON.exists() and _GOLD_JSON.exists()), reason="金標 fixture 不存在"
)


def _n(s: str | None) -> str | None:
    return None if s is None else re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


@pytest.fixture(scope="module")
def _pages() -> dict:
    return json.loads(_PAGES_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def _gold() -> dict:
    return json.loads(_GOLD_JSON.read_text(encoding="utf-8"))


def _load(pages: dict, ticker: str) -> PdfDoc:
    doc = _pdf_doc.from_json(copy.deepcopy(pages[ticker]))
    assert doc is not None
    return doc


# ── 合成文件 builder（單一出處）───────────────────────────────────────────────

_HDR = [
    ["期初現金餘額", "全年來自營業活動淨現金流量", "全年因投資及籌資活動淨現金流量", "現金剩餘數額", "現金不足額之補救措施", None],
    [None, None, None, None, "投資計畫", "理財計畫"],
]
_ROW = ["1,000", "500", "(200)", "1,300", "無", "無"]  # 1,000+500-200=1,300 平
_UNIT = "單位：新台幣仟元"


def _page(n: int, lines: list[str], tables: list | None = None) -> Page:
    return Page(number=n, text="\n".join(lines), tables=tables or [], lines=lines)


def _doc(*pages: Page) -> PdfDoc:
    return PdfDoc(path=Path("synthetic.pdf"), pages=list(pages))


def _lines(unit: str | None = _UNIT, row_line: str = "1,000 500 (200) 1,300 無 無", body: list[str] | None = None,
           head: str = "三、現金流量", tail: str = "四、最近年度重大資本支出") -> list[str]:
    out = [head, "(一)本年度現金流量"]
    if unit:
        out.append(unit)
    out += ["期初現金餘額 營業活動 投資及籌資 現金剩餘", row_line]
    out += body if body is not None else [
        "(1) 營業活動：營運現金流入。", "(2) 投資活動：購置設備。", "(3) 籌資活動：發放股利。"]
    out.append(tail)
    return out


def _cf(row: list | None = None, unit: str | None = _UNIT, hdr: list | None = None, body: list[str] | None = None,
        row_line: str | None = None, extra_lines: list[str] | None = None) -> CashflowSection:
    row = row or _ROW
    tbl = (hdr or _HDR) + [row]
    lines = _lines(unit, row_line or " ".join(c for c in row if c), body)
    if extra_lines:
        lines[2:2] = extra_lines
    return parse_cashflow(_doc(_page(10, lines, [tbl])))


# ═══ R1/R5/R6 金標 10 家 ═════════════════════════════════════════════════════


@needs_fixture
@pytest.mark.parametrize("ticker", _TICKERS)
class TestGold:
    def test_tables_numeric_fields(self, ticker: str, _pages: dict, _gold: dict) -> None:
        """R1：表 A、表 B 數字欄與補救措施全對（無表 A → actual=None 對應金標全 null）。"""
        sec = parse_cashflow(_load(_pages, ticker)).to_dict()
        gold = _gold[ticker]["cashflow"]
        assert sec["status"] == gold["status"] == STATUS_PARSED
        for key in ("actual", "forecast"):
            got = sec[key] or {}
            for f in _NUM:
                assert got.get(f) == gold[key][f], (ticker, key, f)
            for f in _TXT:
                assert _n(got.get(f)) == _n(gold[key][f]), (ticker, key, f)
            assert got.get("page") == gold[key]["page"], (ticker, key, "page")
        assert (sec["actual"] is None) == (gold["actual"]["page"] is None)

    def test_status_pages_applicable_label(self, ticker: str, _pages: dict, _gold: dict) -> None:
        """R6＋章節頁碼、forecast.applicable、組標題（basis_label）。"""
        sec = parse_cashflow(_load(_pages, ticker)).to_dict()
        gold = _gold[ticker]["cashflow"]
        assert sec["pages"] == gold["pages"]
        assert sec["forecast"]["applicable"] == gold["forecast"]["applicable"]
        assert _n(sec["basis_label"]) == _n(gold["basis_label"])
        assert sec["unit_text"] and ("仟元" in sec["unit_text"] or "千元" in sec["unit_text"])

    def test_explanations(self, ticker: str, _pages: dict, _gold: dict) -> None:
        """R5：說明原文（NFKC＋去空白後相等）。2412 文字層損壞，由 test_garbled_text_known_limit 處理。"""
        if ticker == "2412":
            pytest.skip("2412 文字層字型損壞，金標以圖像為準")
        sec = parse_cashflow(_load(_pages, ticker)).to_dict()
        gold = _gold[ticker]["cashflow"]
        for key in ("actual_explanations", "forecast_explanations"):
            for k in ("operating", "investing", "financing"):
                assert _n(sec[key][k]) == _n(gold[key][k]), (ticker, key, k)

    def test_arith(self, ticker: str, _pages: dict, _gold: dict) -> None:
        """R4：金標表 A 皆平 → arith_ok=True；無表 A → None。"""
        sec = parse_cashflow(_load(_pages, ticker))
        has_a = _gold[ticker]["cashflow"]["actual"]["page"] is not None
        assert sec.arith_ok is (True if has_a else None)


@needs_fixture
def test_forecast_arith_diff_recorded_only(_pages: dict) -> None:
    """R4：表 B 不平只記 arith_diff（3653 差 214,583、2881 差 1），status 仍 parsed。"""
    s3653 = parse_cashflow(_load(_pages, "3653"))
    assert s3653.status == STATUS_PARSED and s3653.forecast.arith_diff == 214583
    s2881 = parse_cashflow(_load(_pages, "2881"))
    assert s2881.status == STATUS_PARSED and s2881.forecast.arith_diff == 1
    assert parse_cashflow(_load(_pages, "2317")).forecast.arith_diff == 0
    s2886 = parse_cashflow(_load(_pages, "2886"))  # 表頭公式（1）＋（2）－（3）：依公式代入帶號值
    assert s2886.status == STATUS_PARSED and s2886.forecast.arith_diff == 0
    assert parse_cashflow(_load(_pages, "1301")).forecast.arith_diff == 0  # 無公式、帶負號：照舊相加


@needs_fixture
def test_garbled_text_known_limit(_pages: dict, _gold: dict) -> None:
    """2412 文字層標籤亂碼：說明文字無法分類 → 對應 key 為 None（不猜）；數字照常（見 TestGold）。"""
    sec = parse_cashflow(_load(_pages, "2412"))
    assert all(v is None for v in sec.actual_explanations.values())
    assert all(v is None for v in sec.forecast_explanations.values())


# ═══ R2 三種版面寫法 ═════════════════════════════════════════════════════════


@needs_fixture
class TestLayouts:
    def test_merged_invest_finance_column(self, _pages: dict) -> None:
        a = parse_cashflow(_load(_pages, "3653")).actual
        assert a.cfi_cff == 2063139 and a.cfi is None and a.cff is None and a.outflow is None

    def test_annual_outflow_column(self, _pages: dict) -> None:
        a = parse_cashflow(_load(_pages, "1216")).actual
        assert a.outflow == 18087649 and a.cfi_cff is None and a.cfi is None

    def test_six_numeric_columns(self, _pages: dict) -> None:
        a = parse_cashflow(_load(_pages, "2330")).actual
        assert (a.opening_cash, a.cfo, a.cfi, a.cff, a.fx, a.closing_cash) == (
            2127627043, 2274975625, -1144393407, -440344692, -50008167, 2767856402)
        assert a.cfi_cff is None and a.outflow is None

    def test_vertical_two_year_table_takes_current_year(self, _pages: dict) -> None:
        a = parse_cashflow(_load(_pages, "2412")).actual
        assert (a.cfo, a.cfi, a.cff, a.fx) == (77445547, -28283839, -48456928, -20263)


# ═══ R3 單位 ═════════════════════════════════════════════════════════════════


class TestUnit:
    @pytest.mark.parametrize("unit,cells,expect", [
        ("單位：新台幣仟元", ["1,000", "500", "(200)", "1,300"], (1000, 500, -200, 1300)),
        ("單位：新臺幣千元", ["1,000", "500", "(200)", "1,300"], (1000, 500, -200, 1300)),
        ("單位：倝台幣仟元", ["1,000", "500", "(200)", "1,300"], (1000, 500, -200, 1300)),  # 2412 的亂碼字
        ("單位：新台幣百萬元", ["1", "2", "(1)", "2"], (1000, 2000, -1000, 2000)),
        ("單位：新台幣元", ["1,000,000", "500,000", "(200,000)", "1,300,000"], (1000, 500, -200, 1300)),
    ])
    def test_converted_to_thousand(self, unit: str, cells: list[str], expect: tuple) -> None:
        sec = _cf(row=cells + ["無", "無"], unit=unit)
        a = sec.actual
        assert sec.status == STATUS_PARSED
        assert (a.opening_cash, a.cfo, a.cfi_cff, a.closing_cash) == expect
        assert sec.arith_ok is True

    def test_unit_unreadable_is_failed(self) -> None:
        sec = _cf(unit=None)
        assert sec.status == STATUS_FAILED and "單位" in (sec.reason or "")

    def test_non_ntd_unit_is_failed(self) -> None:
        """反例：單位存在但不是新台幣（美金仟元）→ 不當成仟元，failed。"""
        assert _cf(unit="單位：美金仟元").status == STATUS_FAILED

    @needs_fixture
    def test_gold_doc_without_unit_lines_is_failed(self, _pages: dict) -> None:
        doc = _load(_pages, "3653")
        for p in doc.pages:
            p.lines = [ln for ln in p.lines if "單位" not in ln]
        sec = parse_cashflow(doc)
        assert sec.status == STATUS_FAILED and sec.actual is None



# ═══ R4 算術 ═════════════════════════════════════════════════════════════════


class TestArith:
    def test_balanced(self) -> None:
        assert _cf().arith_ok is True

    @pytest.mark.parametrize("closing,ok", [("1,302", True), ("1,298", True), ("1,303", False), ("1,297", False)])
    def test_tolerance_two(self, closing: str, ok: bool) -> None:
        assert _cf(row=["1,000", "500", "(200)", closing, "無", "無"]).arith_ok is ok

    def test_unbalanced_actual_is_false_but_still_parsed(self) -> None:
        sec = _cf(row=["1,000", "500", "(200)", "9,999", "無", "無"])
        assert sec.status == STATUS_PARSED and sec.arith_ok is False

    _OUT_HDR = [
        ["期初現金餘額(1)", "全年來自營業活動淨現金流量(2)", "全年現金流出量(3)", "現金剩餘(不足)數額", "現金不足額之補救措施", None],
        [None, None, None, None, "投資計劃", "理財計劃"],
    ]

    @pytest.mark.parametrize("outflow,closing,ok", [
        ("200", "1,300", True),      # 原文正數 → 減去
        ("200", "1,700", False),     # 反例：正數不可當帶號淨流量相加
        ("(200)", "1,300", True),    # 原文括號 → 帶號淨流量
        ("-200", "1,300", True),     # 原文負號 → 帶號淨流量
        ("(200)", "1,700", False),   # 反例：括號者不是流出量要減去
    ])
    def test_outflow_sign_rule(self, outflow: str, closing: str, ok: bool) -> None:
        sec = _cf(row=["1,000", "500", outflow, closing, "無", "無"], hdr=self._OUT_HDR)
        assert sec.actual.outflow in (200, -200) and sec.actual.cfi_cff is None
        assert sec.arith_ok is ok

    def test_header_formula_governs_signed_outflow(self) -> None:
        """表頭寫明公式 (1)+(2)-(3) → 依公式代入帶號值（2886 型：營業、流出量都帶括號）。"""
        hdr = [["期初現金餘額（1）", "全年來自營業活動淨現金流量（2）", "全年現金流出量（3）",
                "現金剩餘（不足）數額（1）＋（2）－（3）", "補救措施", None], [None] * 4 + ["投資計畫", "籌資計劃"]]
        sec = _cf(row=["1,000", "(500)", "(200)", "700", "無", "無"], hdr=hdr)  # 1,000-500-(-200)=700
        assert sec.arith_ok is True

    def test_signed_outflow_without_formula_not_subtracted(self) -> None:
        """反例：表頭沒有公式、流出量帶負號 → 當帶號淨流量相加，不可套「-(3)」（1301 型）。"""
        row = ["1,000", "(500)", "(200)", "300", "無", "無"]  # 1,000-500+(-200)=300
        assert _cf(row=row, hdr=self._OUT_HDR_NOFORMULA).arith_ok is True
        assert _cf(row=row[:3] + ["700"] + row[4:], hdr=self._OUT_HDR_NOFORMULA).arith_ok is False

    _OUT_HDR_NOFORMULA = [
        ["期初現金餘額", "全年來自營業活動淨現金流量", "全年現金流出量", "現金剩餘(不足)數額", "補救措施", None],
        [None] * 4 + ["投資計劃", "理財計劃"],
    ]

    def test_fx_included(self) -> None:
        hdr = [["期初現金餘額", "全年來自營業活動淨現金流量", "全年因投資活動淨現金流量", "全年因籌資活動淨現金流量",
                "匯率影響數", "現金剩餘數額", "補救措施", None], [None] * 6 + ["投資計劃", "融資計劃"]]
        row = ["1,000", "500", "(100)", "(100)", "(50)", "1,250", "無", "無"]
        sec = _cf(row=row, hdr=hdr)
        assert sec.actual.fx == -50 and sec.arith_ok is True
        assert _cf(row=row[:5] + ["1,300"] + row[6:], hdr=hdr).arith_ok is False  # 少算匯率就不平

    def test_only_one_of_cfi_cff_not_verifiable(self) -> None:
        """只有投資、沒有籌資欄：缺的一欄不可當 0 → 無法驗證（arith_ok None），不得判平或不平；兩欄都有 → 照常驗證。"""
        hdr = [["期初現金餘額", "全年來自營業活動淨現金流量", "全年因投資活動淨現金流量", "現金剩餘數額",
                "現金不足額之補救措施", None], [None] * 4 + ["投資計畫", "理財計畫"]]
        for closing in ("1,300", "9,999"):
            sec = _cf(row=["1,000", "500", "(200)", closing, "無", "無"], hdr=hdr)
            assert sec.actual.cfi == -200 and sec.actual.cff is None
            assert sec.arith_ok is None, closing

    def test_forecast_only_records_diff(self) -> None:
        hdr_b = [["期初現金餘額(1)", "預計全年來自營業活動淨現金流量(2)", "預計全年因投資及籌資活動淨現金流量(3)",
                  "預計現金剩餘數額", "預計現金不足額之補救措施", None], [None, None, None, None, "投資計劃", "理財計劃"]]
        lines = _lines()
        lines[4:4] = ["預計 期初現金餘額", "1,000 500 (200) 1,400 無 無"]
        sec = parse_cashflow(_doc(_page(10, lines, [_HDR + [_ROW], hdr_b + [["1,000", "500", "(200)", "1,400", "無", "無"]]])))
        assert sec.arith_ok is True and sec.status == STATUS_PARSED
        assert sec.forecast.arith_diff == 100


# ═══ R6 找不到／不適用 ═══════════════════════════════════════════════════════


class TestNotFoundAndNotApplicable:
    def test_no_heading_not_found(self) -> None:
        sec = parse_cashflow(_doc(_page(10, ["二、財務績效", "營業收入 1,000"])))
        assert sec.status == STATUS_NOT_FOUND and sec.pages == []

    def test_toc_hit_not_adopted(self) -> None:
        toc = _page(2, ["壹、致股東報告書.....................3", "三、現金流量.....................94"])
        assert parse_cashflow(_doc(toc)).status == STATUS_NOT_FOUND

    @pytest.mark.parametrize("head", ["三、現金流量表", "三、現金流量比率", "(三)現金流量", "現金流量", "三、現金流量 94"])
    def test_non_heading_lines_not_adopted(self, head: str) -> None:
        """反例：相近但不是節標題（現金流量表／比率、無編號、括號編號、目錄式頁碼尾）。"""
        assert parse_cashflow(_doc(_page(10, _lines(head=head), [_HDR + [_ROW]]))).status == STATUS_NOT_FOUND

    @pytest.mark.parametrize("head", ["三、現金流量", "三、現金流量分析", "三、現金流量之檢討與分析-個體報表",
                                       "5.3 現金流量", "5-3 現金流量分析", "3. 現金流量分析", "6.1.3 現金流量分析 6.2 風險管理"])
    def test_heading_variants_adopted(self, head: str) -> None:
        assert parse_cashflow(_doc(_page(10, _lines(head=head), [_HDR + [_ROW]]))).status == STATUS_PARSED

    def test_forecast_not_applicable_marker(self) -> None:
        sec = _cf(extra_lines=["●未來一年現金流動性分析：不適用。"])
        assert sec.status == STATUS_PARSED
        assert sec.forecast.applicable is False and sec.forecast.opening_cash is None

    def test_marker_without_not_applicable_stays_applicable(self) -> None:
        """反例：有「未來一年現金流動性分析」標題但沒寫不適用、也沒有表 B → applicable 仍為 True。"""
        sec = _cf(body=["(1) 營業活動：營運現金流入。", "(三) 未來一年現金流動性分析"])  # 標題在表 A 之後（在表之前會把該表判成表 B）
        assert sec.forecast.applicable is True and sec.forecast.cfo is None

    def test_no_table_and_not_applicable_is_none(self) -> None:
        sec = parse_cashflow(_doc(_page(10, ["三、現金流量", "未來一年現金流動性分析：不適用。", "四、其他"])))
        assert sec.status == STATUS_NONE and sec.forecast.applicable is False

    def test_no_table_otherwise_failed(self) -> None:
        sec = parse_cashflow(_doc(_page(10, ["三、現金流量", "本公司現金充裕。", "四、其他"])))
        assert sec.status == STATUS_FAILED and sec.reason


# ═══ 合併組選擇（組標題的可觀察字）════════════════════════════════════════════


def _two_groups(t1: str, t2: str) -> CashflowSection:
    lines = ["三、現金流量", t1, _UNIT, "1,000 500 (200) 1,300 無 無", t2, _UNIT, "9,000 800 (300) 9,500 無 無", "四、其他"]
    return parse_cashflow(_doc(_page(10, lines, [_HDR + [_ROW], _HDR + [["9,000", "800", "(300)", "9,500", "無", "無"]]])))


class TestConsolidatedGroup:
    def test_consolidated_group_wins_regardless_of_order(self) -> None:
        first = _two_groups("2.1 個體財務報表", "2.2 合併財務報表")
        assert first.actual.opening_cash == 9000 and first.basis_label == "2.2 合併財務報表"
        second = _two_groups("2.1 合併財務報表", "2.2 個體財務報表")
        assert second.actual.opening_cash == 1000 and second.basis_label == "2.1 合併財務報表"

    def test_and_subsidiaries_wording(self) -> None:
        sec = _two_groups("甲公司財務報表", "甲公司及子公司財務報表")
        assert sec.actual.opening_cash == 9000

    def test_no_consolidated_word_falls_back_to_first_group(self) -> None:
        """反例：兩組標題都沒有「合併」「及子公司」→ 不能判合併組，取文件順序第一組。"""
        sec = _two_groups("甲公司財務報表", "乙公司財務報表")
        assert sec.actual.opening_cash == 1000

    def test_plain_analysis_heading_is_not_group_title(self) -> None:
        """反例：「●本年度現金流量變動分析」不是組標題（無合併／個體／子公司字樣）→ 單一組、basis_label=None。"""
        sec = _cf(extra_lines=["●本年度現金流量變動分析"])
        assert sec.basis_label is None

    def test_single_table_ignores_title(self) -> None:
        lines = ["三、現金流量", "2.1 個體財務報表", _UNIT, "1,000 500 (200) 1,300 無 無", "四、其他"]
        sec = parse_cashflow(_doc(_page(10, lines, [_HDR + [_ROW]])))
        assert sec.actual.opening_cash == 1000


# ═══ 直式兩年比較表 ══════════════════════════════════════════════════════════


def _vertical(rows: list[list[str]], head: list[str] | None = None) -> CashflowSection:
    head = head or ["年度\n項目", "114年", "113年", "增（減）金額", "變動比例"]
    lines = ["三、現金流量", _UNIT, "年度 項目", "100 90 10 11", "四、其他"]
    return parse_cashflow(_doc(_page(10, lines, [[head] + rows])))


_V6 = [["年初現金", "100", "90", "10", "11"], ["營業", "50", "40", "10", "25"], ["投資", "(20)", "(10)", "(10)", "100"],
       ["籌資", "(10)", "(10)", "0", "0"], ["匯率", "(1)", "1", "(2)", "0"], ["年底現金", "119", "111", "8", "7"]]


class TestVerticalTable:
    def test_six_rows(self) -> None:
        sec = _vertical(_V6)
        a = sec.actual
        assert (a.opening_cash, a.cfo, a.cfi, a.cff, a.fx, a.closing_cash) == (100, 50, -20, -10, -1, 119)
        assert sec.arith_ok is True

    def test_five_rows_has_no_fx(self) -> None:
        sec = _vertical(_V6[:4] + [["年底現金", "120", "111", "8", "7"]])
        assert sec.actual.fx is None and sec.actual.closing_cash == 120 and sec.arith_ok is True

    def test_takes_latest_year_column_wherever_it_is(self) -> None:
        swapped = [[r[0], r[2], r[1]] + r[3:] for r in _V6]
        sec = _vertical(swapped, head=["年度\n項目", "113年", "114年", "增減", "比例"])
        assert sec.actual.opening_cash == 100

    def test_unbalanced_six_rows_not_recognised(self) -> None:
        """反例：6 列兩年表但年初＋各列≠年底 → 不當成現金流量表。"""
        bad = [r[:] for r in _V6]
        bad[-1][1] = "130"
        assert _vertical(bad).status == STATUS_FAILED

    def test_three_row_ratio_table_not_recognised(self) -> None:
        """反例：3 列比率表（2317／2881 型）不是現金流量表。"""
        assert _vertical(_V6[:3]).status == STATUS_FAILED

    def test_header_without_item_column_not_recognised(self) -> None:
        """反例：列數、平衡都對但表頭首欄沒有「項目」。"""
        assert _vertical(_V6, head=["年度", "114年", "113年", "增減", "比例"]).status == STATUS_FAILED


# ═══ 表頭角色、空白格、補救措施欄 ═══════════════════════════════════════════════


class TestHeaderRoles:
    def test_garbled_header_fallback_roles(self) -> None:
        """表頭缺字時：含「來自」→ 營業、含「出量」→ 流出量（2412 表 B 型）。"""
        hdr = [["年初現金餘額", "預計�年來自��活動\n淨現金�量", "預計�年現金\n�出量", "預計現金剩餘數額", "預計現金不足額之補救措�", None],
               [None, None, None, None, "投資計畫", "理財計畫"]]
        sec = _cf(row=["1,000", "500", "200", "1,300", "-", "-"], hdr=hdr)
        f = sec.forecast
        assert (f.cfo, f.outflow, f.remedy_invest) == (500, 200, "-")

    def test_unrecognised_column_stays_unmapped(self) -> None:
        """反例：缺字表頭但不含「來自」「出量」→ 不猜角色，該欄不入任何欄位。"""
        hdr = [["年初現金餘額", "全年XX活動淨現金流量", "全年因投資及籌資活動淨現金流量", "預計現金剩餘數額", "補救措施", None],
               [None, None, None, None, "投資計畫", "理財計畫"]]
        sec = _cf(row=["1,000", "500", "(200)", "1,300", "無", "無"], hdr=hdr)
        assert sec.forecast.cfo is None and sec.forecast.cfi_cff == -200 and sec.forecast.opening_cash == 1000

    def test_blank_opening_cell_filled_from_matching_line(self) -> None:
        """2330 型：表格期初現金欄空白，同頁列文字有完整一列 → 補齊。"""
        sec = _cf(row=["", "500", "(200)", "1,300", "無", "無"], row_line="1,000 500 (200) 1,300 無 無")
        assert sec.actual.opening_cash == 1000 and sec.arith_ok is True

    def test_blank_cell_not_filled_when_no_line_matches(self) -> None:
        """反例：列文字的其餘數字對不上 → 不補，期初為 None，arith_ok 無法判定。"""
        sec = _cf(row=["", "500", "(200)", "1,300", "無", "無"], row_line="1,000 777 (200) 1,300 無 無")
        assert sec.actual.opening_cash is None and sec.arith_ok is None

    def test_merged_remedy_cell_copied_to_adjacent_column(self) -> None:
        sec = _cf(row=["1,000", "500", "(200)", "1,300", "無", None])
        assert (sec.actual.remedy_invest, sec.actual.remedy_finance) == ("無", "無")

    def test_empty_remedy_cells_stay_none(self) -> None:
        """反例：兩個補救措施欄都空 → None，不憑空填。"""
        sec = _cf(row=["1,000", "500", "(200)", "1,300", None, None])
        assert (sec.actual.remedy_invest, sec.actual.remedy_finance) == (None, None)

    def test_a_table_with_forecast_wording_in_remedy_header_is_actual(self) -> None:
        """2603 型：表 A 只有補救措施欄寫「預計」，仍是表 A。"""
        hdr = [_HDR[0][:4] + ["預計現金不足額之補救措施", None], _HDR[1]]
        sec = _cf(row=_ROW, hdr=hdr)
        assert sec.actual is not None and sec.actual.cfi_cff == -200

    def test_dollar_sign_and_fullwidth_amounts(self) -> None:
        sec = _cf(row=["$1,000", "$500", "$(200)", "$1,300", "-", "-"])
        assert sec.actual.cfi_cff == -200 and sec.arith_ok is True


# ═══ 表 A／表 B 子標題判別（表頭沒寫「預計」的表 B，2308 型）══════════════════════════


def _sub_page(n: int, heading: str, row: list[str] = _ROW, hdr: list | None = None, locate: bool = True,
              head: str | None = "三、現金流量") -> Page:
    lines = ([head] if head else []) + [heading, _UNIT]
    if locate:
        lines.append(" ".join(c for c in row if c))
    return _page(n, lines, [(hdr or _HDR) + [row]])


_ROW2 = ["1,300", "600", "(100)", "1,800", "無", "無"]
_HDR_FC = [["期初現金餘額", "預計全年來自營業活動淨現金流量", "預計全年因投資及籌資活動淨現金流量", "預計現金剩餘數額",
            "預計現金不足額之補救措施", None], _HDR[1]]


class TestSubheadingAB:

    def test_forecast_heading_without_forecast_wording_is_table_b(self) -> None:
        """2308 型：「(三) 未來一年現金流動性分析」下、表頭無「預計」→ 表 B；沒有表 A → actual None、arith_ok None。"""
        sec = parse_cashflow(_doc(_sub_page(10, "(三) 未來一年現金流動性分析")))
        assert sec.status == "parsed" and sec.actual is None and sec.arith_ok is None
        assert sec.forecast.applicable is True and sec.forecast.opening_cash == 1000 and sec.forecast.cfo == 500

    def test_actual_heading_same_header_is_table_a(self) -> None:
        """反例：「(一) 本年度現金流量變動情形分析」下的同樣表頭 → 表 A。"""
        sec = parse_cashflow(_doc(_sub_page(10, "(一) 本年度現金流量變動情形分析")))
        assert sec.actual is not None and sec.actual.opening_cash == 1000 and sec.arith_ok is True

    def test_keyword_inside_sentence_is_not_subheading(self) -> None:
        """反例：句中提到「未來一年」、編號後不是以關鍵字起頭 → 不算子標題，沿用表頭判別（表 A）。"""
        for heading in ("(三) 說明：未來一年現金流動性分析另見後述。", "本公司就未來一年現金流動性分析如下"):
            sec = parse_cashflow(_doc(_sub_page(10, heading)))
            assert sec.actual is not None and sec.actual.opening_cash == 1000, heading

    def test_unnumbered_whole_line_heading_counts(self) -> None:
        sec = parse_cashflow(_doc(_sub_page(10, "未來一年度現金流動性分析：")))
        assert sec.actual is None and sec.forecast.opening_cash == 1000

    def test_heading_on_previous_page(self) -> None:
        p1 = _page(10, ["三、現金流量", "(三) 未來一年現金流動性分析"])
        p2 = _sub_page(11, _UNIT, head=None)
        sec = parse_cashflow(_doc(p1, p2))
        assert sec.actual is None and sec.forecast.page == 11 and sec.forecast.cfo == 500

    def test_forecast_header_under_actual_heading_keeps_header_rule(self) -> None:
        """子標題（A）與表頭「預計」矛盾 → 不猜，沿用表頭判別（表 B）。"""
        sec = parse_cashflow(_doc(_sub_page(10, "(一) 最近年度現金流量變動情形分析", hdr=_HDR_FC)))
        assert sec.actual is None and sec.forecast.opening_cash == 1000

    def test_unlocatable_table_keeps_header_rule(self) -> None:
        """表格第一個數字列在 Page.lines 找不到 → 不猜，沿用表頭判別（表 A）。"""
        sec = parse_cashflow(_doc(_sub_page(10, "(三) 未來一年現金流動性分析", locate=False)))
        assert sec.actual is not None and sec.actual.opening_cash == 1000

    def test_two_tables_decided_by_their_own_headings(self) -> None:
        p = _page(10, ["三、現金流量", "(一) 最近年度現金流量變動情形分析", _UNIT, "1,000 500 (200) 1,300 無 無",
                       "(三) 未來一年現金流動性分析", _UNIT, "1,300 600 (100) 1,800 無 無"],
                  [_HDR + [_ROW], _HDR + [_ROW2]])
        sec = parse_cashflow(_doc(p))
        assert sec.actual.opening_cash == 1000 and sec.forecast.opening_cash == 1300 and sec.forecast.cfo == 600

    def test_two_tables_all_decided_same_kind_both_adopted(self) -> None:
        """兩張表都明確判成 B（都在「未來一年」下，2885 型）→ 都是表 B：actual None、forecast 取第一張。"""
        p = _page(10, ["三、現金流量", "(三) 未來一年現金流動性分析", _UNIT, "1,000 500 (200) 1,300 無 無",
                       "(四) 未來一年現金流動性分析", _UNIT, "1,300 600 (100) 1,800 無 無"],
                  [_HDR + [_ROW], _HDR + [_ROW2]])
        sec = parse_cashflow(_doc(p))
        assert sec.actual is None and sec.arith_ok is None and sec.forecast.opening_cash == 1000

    def test_two_tables_one_undecided_keeps_header_rule(self) -> None:
        p = _page(10, ["三、現金流量", "(一) 最近年度現金流量變動情形分析", _UNIT, "1,000 500 (200) 1,300 無 無",
                       _UNIT, "1,300 600 (100) 1,800 無 無"],
                  [_HDR + [_ROW], _HDR_FC + [_ROW2]])
        sec = parse_cashflow(_doc(p))
        assert sec.actual.opening_cash == 1000 and sec.forecast.opening_cash == 1300


# ═══ 章節範圍與說明文字 ═══════════════════════════════════════════════════════


class TestSectionScopeAndExplanations:
    def test_explanations_by_prefix_variants_and_continuation(self) -> None:
        body = ["(1) 營業活動：甲，主係", "乙。", "2. 投資活動：丙。", "-籌資活動：丁。"]
        e = _cf(body=body).actual_explanations
        assert e == {"operating": "營業活動：甲，主係乙。", "investing": "投資活動：丙。", "financing": "籌資活動：丁。"}

    def test_label_without_prefix_and_without_colon(self) -> None:
        e = _cf(body=["營業活動之現金流入約22,750億：主要係淨利。", "投資活動產生淨現金流出1,013 仟元。"]).actual_explanations
        assert e["operating"].startswith("營業活動之現金流入") and e["investing"].startswith("投資活動產生")

    def test_other_label_forms_by_colon_label(self) -> None:
        body = ["1. 期初現金餘額：114年底現金。", "2. 全年來自營業活動淨現金流量：預估流入。",
                "3. 全年來自投資及融資淨現金流量：償還借款。"]
        e = _cf(body=body).actual_explanations
        assert e["operating"].startswith("全年來自營業活動") and e["financing"].startswith("全年來自投資及融資")
        assert e["investing"] is None  # 投資及融資合併段記在 financing；期初現金餘額不是說明項

    def test_free_text_mentioning_activity_is_not_an_item(self) -> None:
        """反例：句中提到營業活動（非行首標籤、無編號）不是說明項。"""
        e = _cf(body=["本公司營業活動良好：詳財報。", "說明：營業活動正常。"]).actual_explanations
        assert e == {"operating": None, "investing": None, "financing": None}

    def test_heading_stops_unfinished_item(self) -> None:
        e = _cf(body=["(1) 營業活動：甲（沒有句號）", "(二)現金流動性不足之改善計畫：不適用"]).actual_explanations
        assert e["operating"] == "營業活動：甲（沒有句號）"

    def test_year_columns_line_does_not_end_section(self) -> None:
        """反例：「114 年 113 年」「12.07 1.78」開頭的列不是章節編號，不可截斷章節。"""
        body = ["114 年 113 年 增減", "12.07 1.78 (85.29)", "(1) 營業活動：甲。"]
        assert _cf(body=body).actual_explanations["operating"] == "營業活動：甲。"

    def test_next_same_level_heading_ends_section(self) -> None:
        lines = _lines(body=[], tail="四、最近年度重大資本支出") + ["(1) 營業活動：不該被收進來。"]
        sec = parse_cashflow(_doc(_page(10, lines, [_HDR + [_ROW]])))
        assert sec.actual_explanations["operating"] is None

    def test_forecast_explanations_after_marker_without_table(self) -> None:
        body = ["(1) 營業活動：實際甲。", "(三) 未來一年現金流動性分析", "1. 營業活動：預估乙。", "2. 籌資活動：預估丙。"]
        sec = _cf(body=body)
        assert sec.actual_explanations["operating"] == "營業活動：實際甲。"
        assert sec.forecast_explanations["operating"] == "營業活動：預估乙。"
        assert sec.forecast_explanations["financing"] == "籌資活動：預估丙。"

    def test_table_on_previous_page_of_forecast(self) -> None:
        """表 A 在前一頁、表 B 在後一頁；章節頁碼涵蓋兩頁。"""
        hdr_b = [["期初現金餘額", "預計全年來自營業活動淨現金流量", "預計全年因投資及籌資活動淨現金流量", "預計現金剩餘數額",
                  "預計現金不足額之補救措施", None], [None, None, None, None, "投資計畫", "理財計畫"]]
        p1 = _page(10, ["三、現金流量", _UNIT, "1,000 500 (200) 1,300 無 無"], [_HDR + [_ROW]])
        p2 = _page(11, ["(二)未來一年現金流動性分析", _UNIT, "1,300 600 (100) 1,800 無 無", "四、其他"],
                   [hdr_b + [["1,300", "600", "(100)", "1,800", "無", "無"]]])
        sec = parse_cashflow(_doc(p1, p2))
        assert sec.pages == [10, 11] and sec.actual.page == 10 and sec.forecast.page == 11
        assert sec.forecast.cfo == 600 and sec.forecast.arith_diff == 0


# ═══ to_dict 欄名（producer 側 schema＝金標欄名）═════════════════════════════════


@needs_fixture
def test_to_dict_keys_match_gold_schema(_pages: dict, _gold: dict) -> None:
    d = parse_cashflow(_load(_pages, "3653")).to_dict()
    g = _gold["3653"]["cashflow"]
    for k in ("status", "pages", "basis_label", "unit_text", "actual", "actual_explanations", "forecast",
              "forecast_explanations"):
        assert k in d and k in g
    assert set(g["actual"]) <= set(d["actual"])
    assert set(g["forecast"]) <= set(d["forecast"])
    assert "arith_ok" in d and "arith_diff" in d["forecast"]
    assert parse_cashflow(_load(_pages, "2317")).to_dict()["actual"] is None


# ═══ mutation self-check（改輸入 → 輸出必須同步翻轉）══════════════════════════════


class TestMutationControls:
    def test_mutating_cfo_flips_arith_ok(self) -> None:
        assert _cf().arith_ok is True
        assert _cf(row=["1,000", "510", "(200)", "1,300", "無", "無"]).arith_ok is False

    def test_mutating_header_role_moves_value(self) -> None:
        base = _cf()
        assert base.actual.cfi_cff == -200 and base.actual.cfi is None
        hdr = [r[:] for r in _HDR]
        hdr[0][2] = "全年因投資活動淨現金流量"
        moved = _cf(hdr=hdr)
        assert moved.actual.cfi == -200 and moved.actual.cfi_cff is None

    def test_mutating_unit_line_flips_status(self) -> None:
        assert _cf().status == STATUS_PARSED
        assert _cf(unit="單位：新台幣仟").status == STATUS_FAILED

    def test_mutating_heading_flips_not_found(self) -> None:
        ok = parse_cashflow(_doc(_page(10, _lines(), [_HDR + [_ROW]])))
        bad = parse_cashflow(_doc(_page(10, _lines(head="三、現金流量表"), [_HDR + [_ROW]])))
        assert (ok.status, bad.status) == (STATUS_PARSED, STATUS_NOT_FOUND)

    def test_mutating_group_title_flips_group_choice(self) -> None:
        assert _two_groups("甲公司財務報表", "甲公司合併財務報表").actual.opening_cash == 9000
        assert _two_groups("甲公司財務報表", "甲公司財務報表").actual.opening_cash == 1000

    @needs_fixture
    def test_mutating_gold_cell_breaks_gold_equality(self, _pages: dict, _gold: dict) -> None:
        doc = _load(_pages, "3653")
        for p in doc.pages:
            for t in p.tables:
                for row in t:
                    for i, c in enumerate(row):
                        if c == "9,134,067":
                            row[i] = "9,134,068"
        sec = parse_cashflow(doc)
        assert sec.actual.closing_cash != _gold["3653"]["cashflow"]["actual"]["closing_cash"]
        assert sec.arith_ok is True  # 差 1 仟元仍在容差內
        for p in doc.pages:
            for t in p.tables:
                for row in t:
                    for i, c in enumerate(row):
                        if c == "9,134,068":
                            row[i] = "9,134,099"
        assert parse_cashflow(doc).arith_ok is False


# ═══ Task 3.1 泛化：標題寫法、文字列退回解析、單位、列標籤式直式表 ═══════════════════════════════
#
# 契約（Task 3.1 DoD）：
#   ②文字列退回解析：pdfplumber 沒抓到表格時，用文字列解析一列式數字列；欄數與表頭對不上、或表 A 算術不平 → failed，不猜
#   ④新的標題寫法各有反例測試
# 另：新規則（單位寫法、列標籤式直式表、表頭欄號、補救措施「0 0」）各附相近反例。

_TXT_HDR = ["期初現金餘額 全年來自營業活動 全年因投資及籌資活動 現金剩餘(不足)數額"]
_TXT_ROW = "1,000 500 (200) 1,300 無 無"


def _tx(*body: str, head: str = "三、現金流量", unit: str | None = _UNIT, tail: str = "四、最近年度重大資本支出") -> CashflowSection:
    """沒有 pdfplumber 表格的單頁（逼出文字列退回解析）。"""
    lines = [head, "(一)本年度現金流量"] + ([unit] if unit else []) + list(body) + [tail]
    return parse_cashflow(_doc(_page(10, lines)))


class TestHeadingVariants:
    """新的章節標題寫法；每條附相近但不該觸發的反例（反例回 not_found）。"""

    @pytest.mark.parametrize("head", [
        "三、現金流量：最近年度現金流量變動之分析說明",    # 冒號接標題
        "參、現金流量",                                    # 大寫國字編號
        " 三、現金流量",                             # 私有區項目符號
        "5.3 現金流量變動分析說明",                        # 「變動分析說明」
        "三、現金流動性分析",
        "三、流動性分析",
        "三、 現金流量之檢討與分析表",
        "三、 三、 現金流量 現金流量",                      # 疊印列
        "項 之 三、現金流量：最近年度現金流量變動之分析說明",  # 版面側欄殘字
    ])
    def test_new_heading_is_found(self, head: str) -> None:
        sec = _tx(*_TXT_HDR, _TXT_ROW, head=head)
        assert sec.status == STATUS_PARSED and sec.actual is not None and sec.actual.cfo == 500

    @pytest.mark.parametrize("head", [
        "三、現金流量表：",              # 「現金流量表」不是節標題
        "5.3 現金流量表",
        "三、流動性風險分析",
        "三、 三、 現金流量",            # 只有部分 token 疊印
        "項 之 現金流量：最近年度",      # 側欄殘字後面沒有章節編號
        "現金流量：",                    # 沒有編號
    ])
    def test_near_miss_heading_not_found(self, head: str) -> None:
        assert _tx(*_TXT_HDR, _TXT_ROW, head=head).status == STATUS_NOT_FOUND

    def test_big_numeral_start_ends_at_next_big_numeral(self) -> None:
        """參、現金流量 的節到「肆、」為止：肆之後的數字列不入本節。"""
        lines = ["參、現金流量", _UNIT, *_TXT_HDR, _TXT_ROW, "(1) 營業活動：流入。", "肆、其他", *_TXT_HDR, "9 9 9 9 無 無"]
        sec = parse_cashflow(_doc(_page(10, lines)))
        assert sec.status == STATUS_PARSED and sec.actual.cfo == 500

    def test_small_numeral_section_not_cut_by_big_numeral_page_header(self) -> None:
        """反例：小寫編號（三、）的節，次頁頁首的「伍、…」章名不是終點（2383 型）。"""
        p1 = _page(10, ["三、現金流量", _UNIT, *_TXT_HDR, _TXT_ROW])
        p2 = _page(11, ["伍、財務狀況及財務績效之檢討分析與風險事項", "未來一年現金流動性分析", "(1) 營業活動：預計流入。", "四、其他"])
        sec = parse_cashflow(_doc(p1, p2))
        assert sec.status == STATUS_PARSED and 11 in sec.pages


class TestTextFallback:
    def test_combined_investing_financing_column(self) -> None:
        sec = _tx(*_TXT_HDR, _TXT_ROW)
        a = sec.actual
        assert (a.opening_cash, a.cfo, a.cfi_cff, a.closing_cash) == (1000, 500, -200, 1300)
        assert (a.remedy_invest, a.remedy_finance) == ("無", "無")
        assert sec.arith_ok is True and a.page == 10

    def test_outflow_column_with_formula_in_header(self) -> None:
        sec = _tx("期初現金餘額(1) 全年來自營業活動淨現金流量(2) 全年現金流出量(3) 現金剩餘 (1)+(2)-(3)", "1,000 500 200 1,300 - -")
        a = sec.actual
        assert (a.outflow, a.closing_cash) == (200, 1300) and sec.arith_ok is True

    def test_separate_investing_and_financing_columns(self) -> None:
        sec = _tx("年初現金餘額 營業活動 投資活動 籌資活動 現金剩餘", "1,000 500 (100) (100) 1,300 - -")
        a = sec.actual
        assert (a.cfi, a.cff, a.cfi_cff) == (-100, -100, None) and sec.arith_ok is True

    def test_fx_column_when_header_says_exchange_rate(self) -> None:
        sec = _tx("期初現金 營業活動 投資活動 籌資活動 匯率影響數 現金剩餘", "1,000 500 (100) (100) (10) 1,290 - -")
        assert sec.actual.fx == -10 and sec.arith_ok is True

    def test_forecast_row_after_marker_is_table_b(self) -> None:
        sec = _tx(*_TXT_HDR, _TXT_ROW, "未來一年現金流動性分析",
                  "期初現金餘額 預計全年來自營業活動 預計全年現金流出量 預計現金剩餘(不足)數額 (1)+(2)-(3)",
                  "1,300 600 400 1,500 - -")
        f = sec.forecast
        assert sec.actual.closing_cash == 1300
        assert (f.opening_cash, f.cfo, f.outflow, f.closing_cash) == (1300, 600, 400, 1500) and f.applicable is True

    def test_header_word_split_across_lines_still_recognised(self) -> None:
        """「營業活動」被換行拆成「營業活／動」仍認得（營業活 片段）。"""
        sec = _tx("期初現金 全年來自營業活 全年因投資及籌資活 現金剩餘", "動淨現金流量 動淨現金流量", "1,000 500 (200) 1,300 - -")
        assert sec.status == STATUS_PARSED and sec.actual.cfo == 500

    def test_not_applicable_closing_wording(self) -> None:
        """剩餘寫成「現金餘額(不足)數」也算剩餘欄。"""
        sec = _tx("期初現金餘額 全年來自營業活動 全年現金流出量 現金餘額(不足)數", "1,000 500 200 1,300 無 無")
        assert sec.status == STATUS_PARSED and sec.actual.closing_cash == 1300

    def test_column_number_markers_are_not_a_data_row(self) -> None:
        """表頭欄號列「(1) (2) (3) (1)+(2)+(3)」不是資料列。"""
        sec = _tx("期初現金餘額 全年來自營業活動 全年來自非營業活動 現金餘額 現金不足額之補救措施", "(1) (2) (3) (1)+(2)+(3)", "1,000 500 (200) 1,300 無 無")
        assert sec.status == STATUS_PARSED and sec.actual.cfi_cff == -200

    def test_marker_like_numbers_without_parentheses_are_data(self) -> None:
        """相近反例：欄號寫成純數字「1 2 3」且表頭沒有可解析欄 → 整節 failed，不把它當成資料列略過。"""
        sec = _tx(*_TXT_HDR, "1 2 3 99", _TXT_ROW)
        assert sec.status == STATUS_FAILED

    def test_remedy_zeros_dropped_only_with_remedy_header(self) -> None:
        hdr = "期初現金 全年來自營業活動 全年來自非營業活動 現金剩餘 現金不足額 之補救措施 投資 理財"
        sec = _tx(hdr, "1,000 500 (200) 1,300 0 0")
        assert sec.status == STATUS_PARSED and sec.actual.cfi_cff == -200 and sec.actual.remedy_invest == "0"

    def test_trailing_zeros_without_remedy_header_fail(self) -> None:
        """相近反例：兩個尾端 0，但表頭沒有補救措施字樣 → 欄數對不上 → failed。"""
        sec = _tx(*_TXT_HDR, "1,000 500 (200) 1,300 0 0")
        assert sec.status == STATUS_FAILED

    def test_trailing_nonzero_with_remedy_header_fail(self) -> None:
        """相近反例：有補救措施字樣，但尾端兩個數字不是 0 0 → 不丟，failed。"""
        hdr = "期初現金 全年來自營業活動 全年來自非營業活動 現金剩餘 現金不足額 之補救措施"
        assert _tx(hdr, "1,000 500 (200) 1,300 5 5").status == STATUS_FAILED

    def test_extra_number_fails_with_reason(self) -> None:
        sec = _tx(*_TXT_HDR, "1,000 500 (200) 1,300 77 無")
        assert sec.status == STATUS_FAILED and "文字列" in (sec.reason or "")

    def test_missing_one_column_fails(self) -> None:
        """缺一欄：表頭有匯率欄但只有 4 個數字 → failed，不以缺值代 0。"""
        sec = _tx("期初現金 全年來自營業活動 全年因投資及籌資活動 匯率影響數 現金剩餘", "1,000 500 (200) 1,300 無 無")
        assert sec.status == STATUS_FAILED and sec.actual is None

    def test_unbalanced_arith_fails(self) -> None:
        """算術不平（差 100 仟元 > 容差）→ failed、不產出表。"""
        sec = _tx(*_TXT_HDR, "1,000 500 (200) 1,400 無 無")
        assert sec.status == STATUS_FAILED and sec.actual is None

    def test_arith_within_tolerance_passes(self) -> None:
        """近反例：差 2 仟元（容差內）仍採用。"""
        assert _tx(*_TXT_HDR, "1,000 500 (200) 1,302 無 無").status == STATUS_PARSED

    def test_header_without_opening_word_ignored(self) -> None:
        """表頭沒有「期初／年初」→ 不是現金流量資料列，不觸發文字列解析（整節回找不到表格）。"""
        sec = _tx("項目 營業活動 投資活動 籌資活動", _TXT_ROW)
        assert sec.status == STATUS_FAILED and sec.reason == "找不到現金流量表格"

    def test_header_without_closing_word_fails(self) -> None:
        sec = _tx("期初現金餘額 全年來自營業活動 全年因投資及籌資活動", _TXT_ROW)
        assert sec.status == STATUS_FAILED and "文字列" in (sec.reason or "")

    def test_investing_and_combined_wording_conflict_fails(self) -> None:
        """表頭寫了「投資及籌資」合計欄，數字卻是 5 個（投資、籌資分欄）→ failed，不猜。"""
        sec = _tx(*_TXT_HDR, "1,000 500 (100) (100) 1,300 無 無")
        assert sec.status == STATUS_FAILED

    def test_pdfplumber_table_takes_precedence_over_text(self) -> None:
        """有表格時不走文字列：表格值與文字列不同時以表格為準。"""
        sec = _cf(row=["1,000", "500", "(200)", "1,300", "無", "無"], row_line="1,000 500 (200) 1,300 無 無")
        assert sec.actual.cfo == 500

    def test_amounts_after_non_amount_token_not_leading(self) -> None:
        """相近反例：資料列前面有文字 token（說明文字夾數字）→ 不是資料列。"""
        sec = _tx(*_TXT_HDR, "合計 1,000 500 (200) 1,300")
        assert sec.status == STATUS_FAILED and sec.reason == "找不到現金流量表格"


class TestUnitWordings:
    @pytest.mark.parametrize("unit,scale", [
        ("單位：新台幣仟元；%", 1), ("單位：新臺幣千元;%", 1), ("單位：新台幣佰萬元", 1000),
        ("單位：千元", 1), ("單位：仟元", 1), ("單位：百萬元", 1000),
    ])
    def test_unit_scaled_to_thousand(self, unit: str, scale: int) -> None:
        sec = _tx(*_TXT_HDR, _TXT_ROW, unit=unit)
        assert sec.status == STATUS_PARSED and sec.actual.cfo == 500 * scale

    @pytest.mark.parametrize("unit", ["單位：美金千元", "單位：人民幣仟元；%", "單位：%", "單位：元新台幣"])
    def test_foreign_or_unreadable_unit_fails(self, unit: str) -> None:
        """相近反例：有其他幣別、非金額單位、順序顛倒 → 單位讀不到。"""
        sec = _tx(*_TXT_HDR, _TXT_ROW, unit=unit)
        assert sec.status == STATUS_FAILED and sec.reason == "單位讀不到"


class TestExplanationsOnly:
    """沒有表 A 與表 B、只有說明文字（使用者裁示）：parsed、表為 None、只存說明；沒有任何說明 → failed。"""

    def test_explanations_only_is_parsed_with_no_tables(self) -> None:
        sec = _tx("(1)營業活動：淨現金流入，主係營業獲利。", "2.投資活動：淨現金流出，主係購置設備。", unit=None)
        assert sec.status == STATUS_PARSED and sec.actual is None and sec.forecast is None and sec.arith_ok is None
        assert "營業獲利" in sec.actual_explanations["operating"] and "購置設備" in sec.actual_explanations["investing"]
        assert sec.actual_explanations["financing"] is None and 10 in sec.pages

    def test_single_item_is_enough(self) -> None:
        sec = _tx("3.籌資活動：發放現金股利。", unit=None)
        assert sec.status == STATUS_PARSED and "股利" in sec.actual_explanations["financing"]

    def test_forecast_explanations_split_at_marker(self) -> None:
        sec = _tx("1.營業活動：本年流入。", "未來一年現金流動性分析", "1.營業活動：預計流入。", unit=None)
        assert sec.status == STATUS_PARSED and sec.forecast is None
        assert "本年" in sec.actual_explanations["operating"] and "預計" in sec.forecast_explanations["operating"]

    def test_ratio_table_without_explanations_fails(self) -> None:
        """反例：只有比率表、沒有營業／投資／籌資說明 → failed。"""
        sec = _tx("現金流量比率 87.67% 103.27% (15.60)", "現金流量允當比率 130.32% 143.65% (13.33)", unit=None)
        assert sec.status == STATUS_FAILED and sec.reason == "找不到現金流量表格"

    def test_mid_sentence_mention_is_not_an_explanation(self) -> None:
        """反例：句中提到營業活動（不在行首、也沒有編號標籤）不算說明項。"""
        sec = _tx("本行2025年度營業活動現金流量呈淨流入29,150百萬元；投資活動現金流量呈淨流入。", unit=None)
        assert sec.status == STATUS_FAILED

    def test_comparison_table_rows_are_not_explanations(self) -> None:
        """反例：年度比較表的資料列（行首營業活動＋≥3 個金額）不是說明；其後的編號說明才是。"""
        sec = _tx("營業活動流入 10,678 7,666 (3,011)", "1.營業活動淨現金流入減少，主係收款較少。", unit=None)
        assert sec.status == STATUS_PARSED and sec.actual_explanations["operating"].startswith("營業活動淨現金流入減少")
        assert _tx("營業活動流入 10,678 7,666 (3,011)", "投資活動流出 (3,696) (969) 2,727", unit=None).status == STATUS_FAILED

    def test_marker_mentioned_inside_heading_does_not_split(self) -> None:
        """反例：標題列後半句提到「未來一年現金流動性分析」不是切分點；(三)起頭的才是。"""
        sec = _tx("及未來一年現金流動性分析。", "1.營業活動：本年流入。", "(三)、未來一年現金流動性分析：", "1.營業活動：預計流入。", unit=None)
        assert "本年" in sec.actual_explanations["operating"] and "預計" in sec.forecast_explanations["operating"]

    def test_not_applicable_marker_still_none(self) -> None:
        """既有行為不變：未來一年寫「不適用」且沒有說明項 → none。"""
        sec = _tx("未來一年現金流動性分析：不適用", unit=None)
        assert sec.status == STATUS_NONE

    def test_numeric_row_failure_not_downgraded_to_explanations(self) -> None:
        """相近反例：有數字列但算術不平 → 仍 failed，不因有說明文字改判 parsed。"""
        sec = _tx(*_TXT_HDR, "1,000 500 (200) 1,400 無 無", "(1)營業活動：流入。")
        assert sec.status == STATUS_FAILED and "文字列" in (sec.reason or "")


def _vl(rows: list[list[str]], head: list[list[str]] | None = None) -> CashflowSection:
    head = head or [["年 度\n項 目", "113年度", "114年度", "變動數", "變動比率"]]
    return parse_cashflow(_doc(_page(10, ["5.3 現金流量變動分析說明", "單位：千元", "年度 項目", "期初現金及約當現金餘額 1 2 3 4", "5.4 其他"],
                                      [head + rows])))


_VL = [["期初現金及約當現金餘額", "90", "100", "10", "11%"], ["營業活動", "40", "50", "10", "25%"], ["投資活動", "(10)", "(20)", "(10)", "100%"],
       ["籌資活動", "(10)", "(10)", "0", "0%"], ["匯率變動", "1", "(1)", "(2)", "0%"], ["本期增(減)數", "21", "19", "(2)", "0%"],
       ["期末現金及約當現金餘額", "111", "119", "8", "7%"]]


class TestLabeledVerticalTable:
    def test_seven_row_table_takes_latest_year(self) -> None:
        sec = _vl(_VL)
        a = sec.actual
        assert (a.opening_cash, a.cfo, a.cfi, a.cff, a.fx, a.closing_cash) == (100, 50, -20, -10, -1, 119)
        assert sec.arith_ok is True and sec.status == STATUS_PARSED

    def test_without_fx_and_net_rows(self) -> None:
        rows = [_VL[0], _VL[1], _VL[2], _VL[3], ["期末現金及約當現金餘額", "111", "120", "9", "8%"]]
        sec = _vl(rows)
        assert sec.actual.fx is None and sec.actual.closing_cash == 120 and sec.arith_ok is True

    def test_header_year_wording_with_du(self) -> None:
        """表頭「114年度」「113年度」才認；「114年」寫法由既有直式表處理（兩者都找得到最新年度）。"""
        assert _vl(_VL).actual.opening_cash == 100

    def test_unbalanced_not_recognised(self) -> None:
        bad = [r[:] for r in _VL]
        bad[-1][2] = "130"
        assert _vl(bad).status == STATUS_FAILED

    def test_net_change_row_inconsistent_not_recognised(self) -> None:
        """相近反例：流量加總平衡，但「本期增(減)數」≠ 期末－期初。"""
        bad = [r[:] for r in _VL]
        bad[5][2] = "25"
        assert _vl(bad).status == STATUS_FAILED

    def test_labels_out_of_order_not_recognised(self) -> None:
        rows = [_VL[0], _VL[2], _VL[1], _VL[3], _VL[6]]
        assert _vl(rows).status == STATUS_FAILED

    def test_missing_financing_row_not_recognised(self) -> None:
        """缺一列（沒有籌資活動）→ 不認，不以 0 代入。"""
        assert _vl([_VL[0], _VL[1], _VL[2], ["期末現金及約當現金餘額", "111", "110", "0", "0%"]]).status == STATUS_FAILED

    def test_single_year_header_not_recognised(self) -> None:
        assert _vl(_VL, head=[["項目", "114年度", "變動數", "比率", ""]]).status == STATUS_FAILED


class TestInOutFlowHeader:
    def test_flow_in_out_wording_is_outflow_column(self) -> None:
        """表頭「全年現金流入(出)量」→ outflow 欄（帶號），表 A 算術可驗。"""
        hdr = [["期初現金餘額", "全年來自營業活動淨現金流入(出)量", "全年現金流入(出)量", "現金剩餘數額", "現金不足額之補救措施", None],
               [None, None, None, None, "投資計畫", "融資計畫"]]
        sec = _cf(row=["1,000", "500", "(200)", "1,300", "-", "-"], hdr=hdr)
        assert sec.actual.outflow == -200 and sec.arith_ok is True

    def test_other_inflow_wording_not_outflow(self) -> None:
        """相近反例：「全年現金流入量」（沒有「(出)」）不是流出量欄。"""
        hdr = [["期初現金餘額", "全年來自營業活動淨現金流量", "全年現金流入量", "現金剩餘數額", "現金不足額之補救措施", None],
               [None, None, None, None, "投資計畫", "融資計畫"]]
        sec = _cf(row=["1,000", "500", "(200)", "1,300", "-", "-"], hdr=hdr)
        assert sec.actual.outflow is None


# ═══════════════════════════════════════════════════════════════════════════════
# parse_contracts（item 1.3）
#
# 契約 row（Task 1.3，DoD／契約）：
#   C1: 金標 10 家列數相同；nature／period／parties 全對，content／restrictions 去空白後全對
#   C2: 先用 Page.tables，退回文字列解析；列邊界不確定 → 該頁計入 failed，不產出猜測的列
#   C3: 跨頁合併（續頁沒有表頭沿用欄位對應；跨頁切開的儲存格接回同一列）
#   C4: 金控子公司分段：entity 與 none_entities（2881）
#   C5: 目錄頁的命中不採用（2603）
#   C6: 寫「無」→ none；欄序依表頭欄名決定，不依位置
#   C7（補，Spec §2.6）: 任一列的文字欄含 U+FFFD → 該頁不產出列、計入 failed，reason 寫「文字層缺字」與頁碼
#       （2412 實測 10 列全部缺字 → failed）；沒有 U+FFFD 的頁照常產出
# 文字欄比對：兩邊 NFKC＋去空白（_n）。2412 因 C7 回 failed、無列可比（Spec §2.6：金標比對列為已知不符），
# 由 test_2412_garbled_contracts_failed 斷言新行為。
# ═══════════════════════════════════════════════════════════════════════════════

_CHDR = ["契約性質", "當事人", "契約起訖日期", "主要內容", "限制條款"]
_CHLINE = "契約性質 當事人 契約起訖日期 主要內容 限制條款"
_CTEXT = ("period", "content", "restrictions")


def _cr(nature: str = "買賣契約", party: str = "甲公司", period: str = "111.1~112.1", content: str = "供貨",
        restr: str = "無") -> list:
    return [nature, party, period, content, restr]


def _ctbl(*rows: list, hdr: list | None = None) -> list:
    return [hdr or _CHDR, *rows]


def _cstart(rows: list[list], hdr: list | None = None, head: str = "七、重要契約", mid: tuple = (),
            tail: str | None = "八、其他事項", n: int = 10) -> Page:
    """合成節起頁：節標題、（子公司標題）、表頭列、結尾標題；表格＝表頭＋rows。"""
    lines = [head, *mid, _CHLINE] + ([tail] if tail else [])
    return _page(n, lines, [_ctbl(*rows, hdr=hdr)])


def _ccont(n: int, rows: list[list], with_hdr: bool = True, lines: list[str] | None = None) -> Page:
    """合成續頁：with_hdr＝表格含表頭；否則是沒有表頭的續表。"""
    tbl = _ctbl(*rows) if with_hdr else rows
    return _page(n, lines if lines is not None else ([_CHLINE] if with_hdr else []), [tbl])


def _csec(*pages: Page) -> ContractsSection:
    return parse_contracts(_doc(*pages))


def _parties_of(cell: str) -> list[str]:
    sec = _csec(_cstart([_cr(party=cell)]))
    assert sec.status == STATUS_PARSED and len(sec.rows) == 1
    return sec.rows[0].parties


# ── C1／C4／C5 金標 ─────────────────────────────────────────────────────────


@needs_fixture
@pytest.mark.parametrize("ticker", _TICKERS)
class TestContractsGold:
    def test_status_pages_and_rows(self, ticker: str, _pages: dict, _gold: dict) -> None:
        """C1：status、pages、列數；逐列 page／nature／period／parties／content／restrictions 全對。
        2412 例外：文字層缺字 → failed（C7，Spec §2.6 已知不符），見 test_2412_garbled_contracts_failed。"""
        if ticker == "2412":
            return
        sec = parse_contracts(_load(_pages, ticker))
        g = _gold[ticker]["contracts"]
        assert sec.status == g["status"]
        assert sec.pages == g["pages"]
        assert len(sec.rows) == len(g["rows"])
        for i, (row, gr) in enumerate(zip(sec.rows, g["rows"])):
            assert row.page == gr["page"], (ticker, i, "page")
            assert (row.entity is None) == (gr["entity"] is None), (ticker, i, "entity 存在性")
            assert _n(row.nature) == _n(gr["nature"]), (ticker, i, "nature")
            assert _n(row.period) == _n(gr["period"]), (ticker, i, "period")
            assert [_n(x) for x in row.parties] == [_n(x) for x in gr["parties"]], (ticker, i, "parties")
            assert _n(row.content) == _n(gr["content"]), (ticker, i, "content")
            assert _n(row.restrictions) == _n(gr["restrictions"]), (ticker, i, "restrictions")


@needs_fixture
def test_2412_garbled_contracts_failed(_pages: dict) -> None:
    """C7：2412 重要契約 10 列文字欄全含 U+FFFD → status failed、不產出列、reason 寫「文字層缺字」與頁碼 114；
    反例（同一份輸入把 U+FFFD 換成一般字元）→ 照常產出 10 列、不 failed。"""
    doc = _load(_pages, "2412")
    sec = parse_contracts(doc)
    assert sec.status == STATUS_FAILED
    assert sec.rows == []
    assert 114 in sec.pages
    assert "文字層缺字" in (sec.reason or "") and "114" in (sec.reason or "")
    for p in doc.pages:
        p.tables = [[[None if c is None else c.replace("\ufffd", "?") for c in row] for row in t] for t in p.tables]
    fixed = parse_contracts(doc)
    assert fixed.status == STATUS_PARSED and len(fixed.rows) == 10


@needs_fixture
def test_2881_entity_and_none_entities(_pages: dict, _gold: dict) -> None:
    """C4：子公司分段——entity 逐列與金標一致，none_entities 為「：無」的 5 家；非金控 entity 為 None。"""
    sec = parse_contracts(_load(_pages, "2881"))
    g = _gold["2881"]["contracts"]
    assert [_n(r.entity) for r in sec.rows] == [_n(r["entity"]) for r in g["rows"]]
    assert [_n(x) for x in sec.none_entities] == [_n(x) for x in g["none_entities"]]
    assert all(r.entity is None for r in parse_contracts(_load(_pages, "2886")).rows)  # 金控但無分段


@needs_fixture
def test_2603_toc_hit_not_adopted(_pages: dict) -> None:
    """C5：2603 目錄頁（p3）也有「重要契約」字樣；節起頁是正文 p123，目錄頁不在 pages。
    目錄頁補上「4-7 重要契約」整列（合成）仍不採用；拿掉引導線後它就不是目錄頁、會被採用。"""
    doc = _load(_pages, "2603")
    toc = next(p for p in doc.pages if p.number == 3)
    toc.lines = ["目 錄", "4-1 業務內容------------------------- 98", "4-7 重要契約", "無"]
    sec = parse_contracts(doc)
    assert sec.status == STATUS_PARSED and sec.pages[0] == 123 and 3 not in sec.pages and len(sec.rows) == 54
    toc.lines = ["目 錄", "4-1 業務內容", "4-7 重要契約", "無"]
    assert parse_contracts(doc).status == STATUS_NONE  # 拿掉引導線 → 這頁被當成正文節起頁


@needs_fixture
def test_contracts_to_dict_schema_matches_gold(_pages: dict, _gold: dict) -> None:
    """producer 側 schema：to_dict 欄名與金標逐欄一致（金標另有人工 notes 欄，不由程式產出）。"""
    d = parse_contracts(_load(_pages, "3653")).to_dict()
    g = _gold["3653"]["contracts"]
    assert set(g) - {"notes"} == set(d) - {"reason"}
    assert set(g["rows"][0]) == set(d["rows"][0])
    assert d["reason"] is None


# ── C6 標題、無、欄序 ───────────────────────────────────────────────────────


class TestContractsHeadingAndNone:
    @pytest.mark.parametrize("head", ["七、重要契約", "九、重要契約：", "5.7 重要契約", "4-7 重要契約", "4.17重要契約", "4. 重要契約"])
    def test_heading_forms_adopted(self, head: str) -> None:
        sec = _csec(_cstart([_cr()], head=head, tail=None))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 1

    @pytest.mark.parametrize("head", ["重要契約", "詳見七、重要契約", "七、重要契約 105", "七、重要契約說明", "七、重要契約-----------105"])
    def test_non_heading_lines_not_adopted(self, head: str) -> None:
        assert _csec(_cstart([_cr()], head=head, tail=None)).status == STATUS_NOT_FOUND

    @pytest.mark.parametrize("stmt", ["本公司目前並無簽訂重要契約。", "無", "無。"])
    def test_written_none(self, stmt: str) -> None:
        sec = _csec(_page(10, ["七、重要契約", stmt, "八、其他事項"]))
        assert sec.status == STATUS_NONE and sec.rows == [] and sec.pages == [10]

    def test_none_counter_examples(self) -> None:
        for stmt in ["本公司有簽訂重要契約。", "無法取得相關資料", "目前無"]:
            sec = _csec(_page(10, ["七、重要契約", stmt, "八、其他事項"]))
            assert sec.status == STATUS_FAILED and sec.rows == [], stmt

    def test_none_line_not_adopted_when_table_header_present(self) -> None:
        """反例：沒抓到表格、但頁上有契約表頭與資料列，限制條款欄換行後單獨成列的「無」不可判整節 none → failed。"""
        lines = ["七、重要契約", _CHLINE, "買賣契約 甲公司 111.1~112.1 供貨", "無"]
        sec = _csec(_page(10, lines, []))
        assert sec.status == STATUS_FAILED and sec.rows == []
        # 相近但該判 none：同樣的「無」沒有表頭列 → none（見 test_written_none）；整句「並無簽訂」即使頁上有表頭字樣也維持 none
        lines2 = ["七、重要契約", "本公司目前並無簽訂重要契約。", "八、其他事項"]
        assert _csec(_page(10, lines2, [])).status == STATUS_NONE

    def test_merged_cell_spill_fragment_is_continuation(self) -> None:
        """🟡 合併儲存格推斷：三欄溢出的續行片段（期間只有半截、當事人以「公司」起頭）接回前一列，不得產生新列。"""
        sec = _csec(_cstart([
            _cr(party="甲股份有限", period="111.1~", content="供貨", restr="詳合約"),
            ["", "公司", "112.1", "", "第三條"],
        ]))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 1
        r = sec.rows[0]
        assert r.parties == ["甲股份有限公司"] and _n(r.period) == "111.1~112.1"

    def test_merged_cell_full_row_still_splits(self) -> None:
        """相近但該拆列：期間起訖完整、當事人為完整名稱 → 繼承性質、內容，產出新列。"""
        sec = _csec(_cstart([_cr(), ["", "乙公司", "112.2~113.2", "", "無"]]))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 2
        assert sec.rows[1].parties == ["乙公司"] and sec.rows[1].nature == "買賣契約" and sec.rows[1].content == "供貨"

    def test_merged_cell_open_ended_period_still_splits(self) -> None:
        """🟡-A：期間「起日~迄今」是完整寫法 → 合併儲存格新列，不得接進前一列。"""
        sec = _csec(_cstart([_cr(), ["", "乙公司", "112.1.1~迄今", "", "無"]]))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 2
        assert sec.rows[1].parties == ["乙公司"] and _n(sec.rows[1].period) == "112.1.1~迄今"

    def test_merged_cell_ambiguous_period_not_guessed(self) -> None:
        """🟡-A：期間無起訖符號（「112.1起三年」）、當事人是完整名稱 → 列邊界不明，該頁 failed、不產出猜測列。"""
        sec = _csec(_cstart([_cr(), ["", "乙公司", "112.1起三年", "", "無"]]))
        assert sec.status == STATUS_FAILED and sec.rows == []

    def test_party_split_not_on_zhi_continuation(self) -> None:
        """換行斷名：「公司」之後接「之」「的」開頭的列是同一個當事人；反例：接另一家完整名稱 → 拆 2 人。"""
        assert _parties_of("台積電公司\n之子公司") == ["台積電公司之子公司"]
        assert _parties_of("台積電公司\n的子公司") == ["台積電公司的子公司"]
        assert _parties_of("甲公司\n乙公司") == ["甲公司", "乙公司"]

    def test_holding_all_subsidiaries_none(self) -> None:
        sec = _csec(_page(10, ["4.17重要契約", "(1) 甲金控：無", "(2) 乙銀行：無", "4.18 其他"]))
        assert sec.status == STATUS_NONE and sec.none_entities == ["甲金控", "乙銀行"]
        sec2 = _csec(_page(10, ["4.17重要契約", "(1) 甲金控：無", "(2) 乙銀行", "4.18 其他"]))
        assert sec2.status == STATUS_FAILED  # 乙銀行不是「：無」、又沒有表格

    def test_toc_page_candidate_skipped(self) -> None:
        toc = _page(3, ["目 錄", "壹、致股東報告書---------------- 1", "七、重要契約", "無"])
        body = _cstart([_cr()], n=50)
        sec = _csec(toc, body)
        assert sec.status == STATUS_PARSED and sec.pages == [50]
        toc_no_leader = _page(3, ["目 錄", "壹、致股東報告書", "七、重要契約", "無"])
        assert _csec(toc_no_leader, body).status == STATUS_NONE  # 反例：不是目錄頁 → 採用

    def test_columns_by_header_name_not_position(self) -> None:
        hdr = ["當事人", "契約性質", "限制條款", "契約起訖日期", "主要內容"]
        sec = _csec(_cstart([["乙公司", "租賃契約", "保密", "1~2", "辦公室"]], hdr=hdr))
        r = sec.rows[0]
        assert (r.nature, r.parties, r.restrictions, r.period, r.content) == ("租賃契約", ["乙公司"], "保密", "1~2", "辦公室")

    def test_duplicate_role_header_is_not_a_header(self) -> None:
        hdr = ["契約性質", "當事人", "他方當事人", "契約起訖日期", "主要內容", "限制條款"]
        sec = _csec(_page(10, ["七、重要契約", _CHLINE], [[hdr, ["買賣", "甲公司", "乙公司", "1~2", "供貨", "無"]]]))
        assert sec.status == STATUS_FAILED and sec.rows == []

    @pytest.mark.parametrize("col", ["契約期間", "契約起迄日期", "期間"])
    def test_period_header_variants(self, col: str) -> None:
        hdr = ["契約性質", "當事人", col, "主要內容", "限制條款"]
        assert _csec(_cstart([_cr(period="9~10")], hdr=hdr)).rows[0].period == "9~10"


# ── C2 列邊界不確定 → failed，不產出猜測的列；文字列退回 ─────────────────────────


class TestContractsUncertain:
    def test_no_table_no_statement_is_failed(self) -> None:
        sec = _csec(_page(10, ["七、重要契約", "截至年報刊印日止之契約如下：", "八、其他事項"]))
        assert sec.status == STATUS_FAILED and sec.rows == [] and "第 10 頁" in sec.reason

    def test_conflicting_columns_in_same_span_fail_the_page_only(self) -> None:
        hdr = ["契約性質", "當事人", None, "契約起訖日期", "主要內容", "限制條款"]
        bad = ["租賃契約", "乙公司", "丙公司", "3~4", "辦公室", "無"]  # 當事人欄與併入的空白欄文字不同
        sec = _csec(
            _page(10, ["七、重要契約", _CHLINE], [[hdr, ["買賣契約", "甲公司", "", "1~2", "供貨", "無"]]]),
            _page(11, [_CHLINE], [[hdr, bad]]),
        )
        assert sec.status == STATUS_FAILED and sec.pages == [10, 11]
        assert [r.parties for r in sec.rows] == [["甲公司"]] and "第 11 頁" in sec.reason
        fixed = _csec(
            _page(10, ["七、重要契約", _CHLINE], [[hdr, ["買賣契約", "甲公司", "", "1~2", "供貨", "無"]]]),
            _page(11, [_CHLINE], [[hdr, ["租賃契約", "乙公司", "", "3~4", "辦公室", "無"]]]),
        )
        assert fixed.status == STATUS_PARSED and len(fixed.rows) == 2

    def test_unrecognized_header_column_with_text_fails(self) -> None:
        hdr = _CHDR + ["備註"]
        sec = _csec(_page(10, ["七、重要契約", _CHLINE], [[hdr, _cr() + ["附註"]]]))
        assert sec.status == STATUS_FAILED and sec.rows == []
        ok = _csec(_page(10, ["七、重要契約", _CHLINE], [[hdr, _cr() + [""]]]))
        assert ok.status == STATUS_PARSED  # 反例：備註欄是空的 → 不影響

    def test_continuation_fragment_without_previous_row_fails(self) -> None:
        sec = _csec(_cstart([["", "限公司", "112.1", "零件", ""]]))
        assert sec.status == STATUS_FAILED and sec.rows == []

    def test_text_fallback_five_cells_per_line(self) -> None:
        lines = ["七、重要契約", "契約性質  當事人  契約起訖日期  主要內容  限制條款",
                 "買賣契約  甲公司  111.1~112.1  供貨  無", "租賃契約  乙公司  112.1~113.1  辦公室  無"]
        sec = _csec(_page(10, lines))
        assert sec.status == STATUS_PARSED
        assert [(r.nature, r.parties, r.period) for r in sec.rows] == [
            ("買賣契約", ["甲公司"], "111.1~112.1"), ("租賃契約", ["乙公司"], "112.1~113.1")]

    def test_text_fallback_uncertain_line_fails_without_guessing(self) -> None:
        lines = ["七、重要契約", "契約性質  當事人  契約起訖日期  主要內容  限制條款",
                 "買賣契約  甲公司  111.1~112.1  供貨  無", "租賃契約 乙公司 112.1~113.1 辦公室 無"]  # 單一空白、切不出 5 欄
        sec = _csec(_page(10, lines))
        assert sec.status == STATUS_FAILED and sec.rows == [] and "第 10 頁" in sec.reason

    @needs_fixture
    def test_fixture_lines_with_single_spaces_do_not_guess(self, _pages: dict) -> None:
        """2603 的列文字是單一空白，退回文字列時切不出欄 → 不猜（拿掉表格 → failed、無列）。"""
        doc = _load(_pages, "2603")
        for p in doc.pages:
            p.tables = []
        sec = parse_contracts(doc)
        assert sec.status == STATUS_FAILED and sec.rows == []


# ── C3 跨頁 ─────────────────────────────────────────────────────────────────


class TestContractsCrossPage:
    def test_split_cells_join_into_one_row(self) -> None:
        sec = _csec(
            _cstart([_cr("買賣契約", "丙股份有", "111.1-", "供應", "無")], tail=None),
            _ccont(11, [["", "限公司", "112.1", "零件", ""]]),
        )
        assert sec.status == STATUS_PARSED and len(sec.rows) == 1
        r = sec.rows[0]
        assert (r.page, r.parties, r.period, r.content) == (10, ["丙股份有限公司"], "111.1-112.1", "供應零件")
        assert sec.pages == [10, 11]

    def test_next_page_row_with_nature_is_a_new_row(self) -> None:
        sec = _csec(_cstart([_cr()], tail=None), _ccont(11, [_cr("租賃契約", "乙公司")]))
        assert [r.nature for r in sec.rows] == ["買賣契約", "租賃契約"] and [r.page for r in sec.rows] == [10, 11]

    def test_headerless_continuation_reuses_column_mapping(self) -> None:
        sec = _csec(_cstart([_cr()], tail=None), _ccont(11, [_cr("租賃契約", "乙公司")], with_hdr=False))
        assert len(sec.rows) == 2 and sec.rows[1].parties == ["乙公司"] and sec.pages == [10, 11]

    def test_headerless_table_with_other_column_count_ignored(self) -> None:
        sec = _csec(_cstart([_cr()], tail=None), _ccont(11, [["項目", "金額", "比例", "備註"]], with_hdr=False))
        assert len(sec.rows) == 1 and sec.pages == [10]

    def test_non_contiguous_page_not_continued(self) -> None:
        sec = _csec(_cstart([_cr()], tail=None), _ccont(13, [_cr("租賃契約", "乙公司")]))
        assert len(sec.rows) == 1 and sec.pages == [10]

    def test_table_after_end_heading_not_adopted(self) -> None:
        """3653 型：下一章標題在頁首、其後的 5 欄表不是續表（含「伍、」大寫數字章名）。"""
        other = [["買賣契約", "一", "二", "三", "四"]]
        after = _ccont(11, other, with_hdr=False, lines=["伍、財務狀況", "買賣契約 一 二 三 四"])
        assert _csec(_cstart([_cr()], tail=None), after).pages == [10]
        before = _ccont(11, other, with_hdr=False, lines=["買賣契約 一 二 三 四", "伍、財務狀況"])
        sec = _csec(_cstart([_cr()], tail=None), before)  # 反例：表在標題之前 → 是續表
        assert sec.pages == [10, 11] and len(sec.rows) == 2

    def test_headerless_table_position_unknown_next_to_end_heading_fails(self) -> None:
        unknown = _ccont(11, [["買賣契約", "一", "二", "三", "四"]], with_hdr=False, lines=["伍、財務狀況"])
        sec = _csec(_cstart([_cr()], tail=None), unknown)
        assert sec.status == STATUS_FAILED and [r.page for r in sec.rows] == [10] and "第 11 頁" in sec.reason

    def test_party_enumeration_is_not_an_end_heading(self) -> None:
        """當事人儲存格內的「5. 乙公司」編號不是節終點；同一行不在儲存格內才是標題。"""
        rows = [_cr(party="1. 甲公司\n5. 乙公司")]
        cont = _ccont(11, [_cr("租賃契約", "丙公司")])
        in_cell = _csec(_cstart(rows, head="4-7 重要契約", mid=("5. 乙公司",), tail=None), cont)
        assert in_cell.pages == [10, 11]
        not_in_cell = _csec(_cstart([_cr()], head="4-7 重要契約", mid=("5. 乙公司",), tail=None), cont)
        assert not_in_cell.pages == [10]  # 反例：該行不在任何儲存格內 → 是下一章標題

    def test_end_heading_levels(self) -> None:
        cont = _ccont(11, [_cr("租賃契約", "丙公司")])
        assert _csec(_cstart([_cr()], head="5.7 重要契約", tail="5.8 其他"), cont).pages == [10]
        assert _csec(_cstart([_cr()], head="5.7 重要契約", tail="5.7.1 子節"), cont).pages == [10, 11]  # 更深層級不算終點


# ── 列切分：區塊、續行、合併儲存格、分隔列 ─────────────────────────────────────


class TestContractsRowSegmentation:
    def test_blank_row_separated_blocks_form_one_row(self) -> None:
        """2317 型：一列被切成多個表格列、以全空白列分隔；表頭也跨列。"""
        blank = ["", "", "", "", ""]
        tbl = [blank, ["契約", None, None, "主要", None], [None, "他方當事人", "契約起迄日期", None, "限制條款"],
               ["性質", None, None, "內容", None], blank,
               ["買賣", "Apple Computer,", "1999/12/07 至", "產品之", "保留"], ["契約", "Inc.", "終止。", "買賣", "權利"], blank,
               ["買賣", "Dell", None, "產品之", "保留"], [None, "Products L.P.", "1999/12/01", None, None], ["契約", None, None, "買賣", "權利"],
               [None, "成立之", None, None, None], blank,
               ["專利", None, None, "技術", None], [None, "MPEG LA", "2009/12/28", None, "非專屬"], ["授權", None, None, "授權", None]]
        sec = _csec(_page(10, ["七、重要契約"], [tbl]))
        assert sec.status == STATUS_PARSED
        assert [(r.nature, r.parties, r.content) for r in sec.rows[:1]] == [("買賣契約", ["Apple Computer, Inc."], "產品之買賣")]
        assert sec.rows[0].period == "1999/12/07 至終止。" and sec.rows[0].restrictions == "保留權利"
        assert len(sec.rows) == 3 and sec.rows[2].nature == "專利授權"

    def test_block_after_blank_without_nature_is_continuation(self) -> None:
        blank = ["", "", "", "", ""]
        tbl = [_CHDR, blank, ["買賣", "India Chip Private", "2025", "授權", "無"], ["", "Limited", "", "", ""], blank,
               ["", "*註記", "", "", ""]]
        sec = _csec(_page(10, ["七、重要契約"], [tbl]))
        assert len(sec.rows) == 1 and sec.rows[0].parties == ["India Chip Private Limited*註記"]

    def test_without_blank_rows_each_table_row_is_one_row(self) -> None:
        sec = _csec(_cstart([_cr(), _cr("租賃契約", "乙公司")]))
        assert len(sec.rows) == 2

    def test_fragment_rows_merge_into_previous_row(self) -> None:
        rows = [_cr("租賃契約", "遠雄流通事業(股)", "1~2", "租賃契約書", "無"), ["", "公司", "", "(台中商場", ""],
                _cr("買賣契約", "乙公司")]
        sec = _csec(_cstart(rows))
        assert len(sec.rows) == 2 and sec.rows[0].parties == ["遠雄流通事業(股)公司"] and sec.rows[0].content == "租賃契約書(台中商場"

    def test_merged_nature_and_content_rows_inherit(self) -> None:
        rows = [["設計契約", "A公司", "1~2", "整廠工程", "無"], [None, "B公司", "3~4", None, "無"], [None, "C公司", "5~6", None, "無"]]
        sec = _csec(_cstart(rows))
        assert [(r.nature, r.parties, r.content, r.period) for r in sec.rows] == [
            ("設計契約", ["A公司"], "整廠工程", "1~2"), ("設計契約", ["B公司"], "整廠工程", "3~4"),
            ("設計契約", ["C公司"], "整廠工程", "5~6")]
        # 依主 flow 補表 row：性質欄空白、內容欄有字、期間完整、當事人完整名稱、限制欄有字 → 新列，只沿用性質
        two = _csec(_cstart([rows[0], [None, "B公司", "3~4", "另案工程", "無"]]))
        assert [(r.nature, r.parties, r.content) for r in two.rows] == [
            ("設計契約", ["A公司"], "整廠工程"), ("設計契約", ["B公司"], "另案工程")]
        # 反例：期間不完整（半截）→ 續行
        assert len(_csec(_cstart([["設計契約", "A公司", "1~", "整廠工程", "無"], [None, "B公司", "2", "另案工程", "無"]])).rows) == 1

    def test_full_width_separator_row_skipped(self) -> None:
        sec = _csec(_cstart([_cr(), ["關係企業", None, None, None, None], _cr("租賃契約", "乙公司")]))
        assert [r.nature for r in sec.rows] == ["買賣契約", "租賃契約"]
        counter = _csec(_cstart([_cr(), ["關係企業", "丙公司", None, None, None]]))  # 其他欄有字 → 是一列
        assert [r.nature for r in counter.rows] == ["買賣契約", "關係企業"]

    def test_span_columns_merge_and_identical_duplicates_collapse(self) -> None:
        hdr = ["契約性質", "當事人", None, "契約起訖日期", None, "主要內容", "限制條款"]
        row = ["買賣契約", "", "甲公司", "1~2", "1~2", "供貨", "無"]  # 當事人落在空白欄；期間兩欄文字完全相同
        sec = _csec(_page(10, ["七、重要契約", _CHLINE], [[hdr, row]]))
        assert sec.status == STATUS_PARSED and sec.rows[0].parties == ["甲公司"] and sec.rows[0].period == "1~2"


# ── 當事人拆分 ──────────────────────────────────────────────────────────────


class TestContractsParties:
    @pytest.mark.parametrize("cell, expected", [
        ("甲公司\n乙公司", ["甲公司", "乙公司"]),                                   # 前一行以「公司」結尾 → 換人
        ("健策精密工業股份有限公司\n桃園市政府", ["健策精密工業股份有限公司", "桃園市政府"]),
        ("潘冀聯合建築師事\n務所", ["潘冀聯合建築師事務所"]),                          # 斷行但前一行不是結尾 → 同一人
        ("Apple Computer,\nInc.", ["Apple Computer, Inc."]),
        ("India Chip Private\nLimited\n*被授權法人", ["India Chip Private Limited*被授權法人"]),  # * 接續前一人
        ("(1) 甲建設\n股份有限公司\n(2) 乙工程", ["甲建設股份有限公司", "乙工程"]),
        ("1. OOCL (ASIA\nPACIFIC) LTD.\n2. YANGMING (UK)\nLTD.", ["OOCL (ASIA PACIFIC) LTD.", "YANGMING (UK) LTD."]),
        ("甲方：\n甲建設股份有限\n公司\n乙方：\n乙資產股份\n有限公司", ["甲方：甲建設股份有限公司", "乙方：乙資產股份有限公司"]),
        ("甲銀行股份有限公司及乙署(簡稱X)", ["甲銀行股份有限公司", "乙署(簡稱X)"]),
        ("甲公司、乙署(簡稱X)\n及丙廳(簡稱Y)", ["甲公司", "乙署(簡稱X)", "丙廳(簡稱Y)"]),
        ("主要參與合約再保\n人包括:\n甲再保險公司\n(ABC\nCORP)、乙再保險公司\n(DEF CO)及\n丙再保險公司\n等", ["甲再保險公司(ABC CORP)", "乙再保險公司(DEF CO)", "丙再保險公司"]),
    ])
    def test_split(self, cell: str, expected: list[str]) -> None:
        assert [_n(x) for x in _parties_of(cell)] == [_n(x) for x in expected]

    @pytest.mark.parametrize("cell, expected", [
        ("甲及乙股份有限公司", ["甲及乙股份有限公司"]),            # 「及」前不是「公司」或「)」
        ("甲公司及其子公司", ["甲公司及其子公司"]),                # 「及其」不拆
        ("甲公司等", ["甲公司等"]),                              # 沒有「包括：」前導 → 不去「等」
        ("合作金庫等16家銀行聯貸案", ["合作金庫等16家銀行聯貸案"]),
        ("2. 甲公司\n3. 乙公司", ["2. 甲公司", "3. 乙公司"]),    # 編號不是從 1 起、不算編號清單
        ("甲建設\n股份有限公司", ["甲建設股份有限公司"]),
        ("甲公司\n等級二公司", ["甲公司", "等級二公司"]),          # 只有單獨一列「等」才接回前一人
    ])
    def test_counter_examples_not_split(self, cell: str, expected: list[str]) -> None:
        assert [_n(x) for x in _parties_of(cell)] == [_n(x) for x in expected]


# ── C4 子公司分段標題（合成）──────────────────────────────────────────────────


class TestContractsEntities:
    def test_entity_from_numbered_headings(self) -> None:
        p10 = _cstart([_cr()], head="4.17重要契約", mid=("(1) 甲金控：無", "(2) 乙壽險"), tail=None)
        p11 = _page(11, ["(3) 丙銀行", _CHLINE], [_ctbl(_cr("租賃契約", "丁公司"))])
        p12 = _ccont(12, [_cr("買賣契約", "戊公司")], with_hdr=False)
        sec = _csec(p10, p11, p12)
        assert sec.none_entities == ["甲金控"]
        assert [r.entity for r in sec.rows] == ["乙壽險", "丙銀行", "丙銀行"]  # 續頁沿用前一個子公司

    def test_non_sequential_heading_not_adopted(self) -> None:
        sec = _csec(_cstart([_cr()], mid=("(2) 乙壽險",), tail=None))
        assert [r.entity for r in sec.rows] == [None]

    def test_numbered_cell_lines_are_not_headings(self) -> None:
        sec = _csec(_cstart([_cr(party="(1) 丙公司\n(2) 丁公司")], mid=("(1) 丙公司", "(2) 丁公司"), tail=None))
        assert sec.rows[0].entity is None and sec.rows[0].parties == ["丙公司", "丁公司"] and sec.none_entities == []

    def test_heading_position_unknown_fails(self) -> None:
        """子公司標題與表格先後對不到 → 不猜 entity。"""
        page = _page(10, ["七、重要契約", "(1) 甲壽險", "其他文字"], [_ctbl(_cr())])
        assert _csec(page).status == STATUS_FAILED


# ── mutation self-check（改輸入 → 輸出必須同步翻轉）──────────────────────────────


class TestContractsMutationControls:
    def test_swapping_header_names_swaps_fields(self) -> None:
        base = _csec(_cstart([_cr("買賣契約", "甲公司")])).rows[0]
        assert (base.nature, base.parties) == ("買賣契約", ["甲公司"])
        hdr = ["當事人", "契約性質", "契約起訖日期", "主要內容", "限制條款"]
        sw = _csec(_cstart([_cr("買賣契約", "甲公司")], hdr=hdr)).rows[0]
        assert (sw.nature, sw.parties) == ("甲公司", ["買賣契約"])

    def test_mutating_end_heading_changes_scope(self) -> None:
        cont = _ccont(11, [_cr("租賃契約", "乙公司")])
        assert _csec(_cstart([_cr()], tail="其他事項"), cont).pages == [10, 11]
        assert _csec(_cstart([_cr()], tail="八、其他事項"), cont).pages == [10]

    def test_mutating_nature_cell_splits_row(self) -> None:
        frag = ["", "限公司", "112.1", "零件", ""]
        assert len(_csec(_cstart([_cr(party="丙股份有")], tail=None), _ccont(11, [frag])).rows) == 1
        with_nature = ["賣出契約"] + frag[1:]
        assert len(_csec(_cstart([_cr(party="丙股份有")], tail=None), _ccont(11, [with_nature])).rows) == 2

    @needs_fixture
    def test_mutating_gold_cell_changes_row(self, _pages: dict, _gold: dict) -> None:
        doc = _load(_pages, "3653")
        gold_row = _gold["3653"]["contracts"]["rows"][0]
        assert _n(parse_contracts(doc).rows[0].content) == _n(gold_row["content"])
        for p in doc.pages:
            for t in p.tables:
                for row in t:
                    for i, c in enumerate(row):
                        if c == "土地買賣":
                            row[i] = "土地租賃"
        assert _n(parse_contracts(doc).rows[0].content) != _n(gold_row["content"])

    def test_mutating_blank_row_merges_blocks(self) -> None:
        blank = ["", "", "", "", ""]
        two = [_CHDR, blank, ["買賣", "甲公司", "1", "供貨", "無"], blank, ["租賃", "乙公司", "2", "辦公室", "無"]]
        one = [_CHDR, blank, ["買賣", "甲公司", "1", "供貨", "無"], ["租賃", "乙公司", "2", "辦公室", "無"]]
        assert len(_csec(_page(10, ["七、重要契約"], [two])).rows) == 2
        assert len(_csec(_page(10, ["七、重要契約"], [one])).rows) == 1  # 拿掉中間的空白列 → 兩列併成同一塊


# ── C7 文字層缺字（U+FFFD）─────────────────────────────────────────────────────


class TestContractsGarbledText:
    @pytest.mark.parametrize("col", range(5))
    def test_fffd_in_any_text_column_fails_the_page(self, col: int) -> None:
        """任一文字欄含 U+FFFD → 該頁不產出列、failed、reason 含「文字層缺字」與頁碼。"""
        row = _cr()
        row[col] = row[col] + "�"
        sec = _csec(_cstart([row]))
        assert sec.status == STATUS_FAILED and sec.rows == []
        assert "文字層缺字" in (sec.reason or "") and "10" in (sec.reason or "")

    def test_clean_page_still_produces_rows(self) -> None:
        """反例：同樣的輸入沒有 U+FFFD → 照常產出（含看起來相近的「?」「□」不觸發）。"""
        for ch in ("", "?", "□"):
            sec = _csec(_cstart([_cr(content="供貨" + ch)]))
            assert sec.status == STATUS_PARSED and len(sec.rows) == 1

    def test_only_garbled_page_is_dropped(self) -> None:
        """缺字只影響該頁：前一頁沒有 U+FFFD 的列照常產出，failed 的 reason 只列缺字頁。"""
        sec = _csec(_cstart([_cr("買賣契約")], tail=None), _ccont(11, [_cr("租賃契約", content="辦公�")]))
        assert sec.status == STATUS_FAILED
        assert [r.nature for r in sec.rows] == ["買賣契約"] and sec.rows[0].page == 10
        assert "文字層缺字" in (sec.reason or "") and "11" in (sec.reason or "")
        assert 10 not in [int(n) for n in re.findall(r"第 (\d+) 頁", sec.reason or "")]


# ── Task 3.2：重要契約泛化（101 家）。每條新規則一個正例＋一個相近但不該觸發的反例 ──────────────────────


class TestContractsGeneralizedHeadings:
    @pytest.mark.parametrize("head", [
        "柒、重要契約",                                   # 大寫數字章名（2379、3045）
        "(七)重要契約：",                                  # 括號數字（2313）
        " 七、重要契約",                             # 行首私有區項目符號字型（2308）
        "七、重要契約（截至年報刊印日115年3月31日止）",        # 尾綴（3036）
        "十、 十、 重要契約 重要契約",                      # 每個詞連續重複兩遍（2887）
        "七、重要契約：列示截至年報刊印日止仍有效存續之契約",   # 標題與說明同列（6274）
        "七、重要契約（列示截至年報刊印日止仍有效存續之契約",   # 標題與說明同列、全形括號（6505）
    ])
    def test_new_heading_forms_adopted(self, head: str) -> None:
        sec = _csec(_cstart([_cr()], head=head, tail=None))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 1

    @pytest.mark.parametrize("head", [
        "柒重要契約",                                      # 沒有頓號
        "※ 七、重要契約",                                  # 行首符號不是私有區字元
        "七、重要契約（詳見附表）",                          # 括號內不是「截至…止」
        "十、 重要契約 重要契約",                           # 沒有每個詞都重複
        "七、重要契約：列示其他事項",                        # 說明不是「列示截至年報刊印日止」
        "(七)重要契約說明",
        "七、重要契約：無法取得",                            # 「無」後面還有字
        "七、重要契約（截至年報刊印日止",                     # 括號沒有收尾
    ])
    def test_near_miss_headings_not_adopted(self, head: str) -> None:
        assert _csec(_cstart([_cr()], head=head, tail=None)).status == STATUS_NOT_FOUND

    def test_paren_heading_ends_at_next_paren_heading(self) -> None:
        """(七) 起頭的節，終點是 (八)；反例：同為括號但編號較小的 (六) 不是終點，表格照常續接。"""
        cont = _ccont(11, [_cr("租賃契約", "丙公司")])
        assert _csec(_cstart([_cr()], head="(七)重要契約", tail="(八)其他事項"), cont).pages == [10]
        assert _csec(_cstart([_cr()], head="(七)重要契約", tail="(六)其他事項"), cont).pages == [10, 11]

    def test_same_line_none_is_none(self) -> None:
        for stmt in ("七、 重要契約：無。", "七、重要契約：無", "(七)重要契約：無。"):
            sec = _csec(_page(10, [stmt, "(八)其他事項"]))
            assert sec.status == STATUS_NONE and sec.rows == [] and sec.pages == [10], stmt

    def test_same_line_none_not_in_toc(self) -> None:
        toc = _page(3, ["目 錄", "壹、致股東報告書---------------- 1", "七、重要契約：無。"])
        assert _csec(toc, _cstart([_cr()], n=50)).status == STATUS_PARSED  # 反例：目錄頁的同列「無」不採用

    @pytest.mark.parametrize("stmt", ["本公司並無簽訂性質特殊之重要契約。", "尚無足以影響投資人權益之重要契約。", "尚無足以影響股東權益之重要契約"])
    def test_new_none_statements(self, stmt: str) -> None:
        sec = _csec(_page(10, ["七、重要契約", stmt, "八、其他事項"]))
        assert sec.status == STATUS_NONE and sec.rows == []

    def test_none_statement_counter_examples(self) -> None:
        for stmt in ["本公司有簽訂性質特殊之重要契約。", "足以影響投資人權益之重要契約之當事人、主要內容、限制條款及契約起訖日期：", "尚無足以影響投資人權益之契約"]:
            sec = _csec(_page(10, ["七、重要契約", stmt, "八、其他事項"]))
            assert sec.status == STATUS_FAILED and sec.rows == [], stmt


class TestContractsHeaderAliases:
    @pytest.mark.parametrize("col, role", [("契約對象", "parties"), ("對象", "parties"), ("相對人", "parties"), ("契 約 起 訖 期", "period"),
                                           ("契約起迄年月", "period")])
    def test_new_aliases_map_to_role(self, col: str, role: str) -> None:
        hdr = list(_CHDR)
        hdr[1 if role == "parties" else 2] = col
        r = _csec(_cstart([_cr(party="乙公司", period="9~10")], hdr=hdr)).rows[0]
        assert (r.parties, r.period) == (["乙公司"], "9~10")

    def test_alias_counter_examples(self) -> None:
        # 反例 1：「對象」與「當事人」並存 → 同角色兩欄，不是契約表頭
        dup = ["契約性質", "當事人", "契約對象", "契約起訖日期", "主要內容", "限制條款"]
        sec = _csec(_page(10, ["七、重要契約", _CHLINE], [[dup, ["買賣", "甲公司", "乙公司", "1~2", "供貨", "無"]]]))
        assert sec.status == STATUS_FAILED and sec.rows == []
        # 反例 2：只有 3 個角色（沒有「性質」「限制」）的表頭不採用
        three = ["對象", "契約起訖日期", "主要內容"]
        assert _csec(_page(10, ["七、重要契約"], [[three, ["甲公司", "1~2", "供貨"]]])).status == STATUS_FAILED


class TestContractsMultiRecordBlocks:
    def test_block_with_two_date_started_periods_fails(self) -> None:
        """全空白列分塊後，同一塊內兩列的期間各自以日期起頭（多筆契約沒有空白列分隔）→ 不確定，不合併成一列。"""
        blank = ["", "", "", "", ""]
        tbl = [_CHDR, blank, ["工程合約", "甲公司", "民國114年05月27日起生效", "A案", "無"],
               ["工程合約", "乙公司", "民國114年07月01日起生效", "B案", "無"], blank, _cr("租賃契約", "丙公司")]
        sec = _csec(_page(10, ["七、重要契約"], [tbl]))
        assert sec.status == STATUS_FAILED and "第 10 頁" in sec.reason and sec.rows == []

    def test_block_with_party_name_wrapped_across_rows_is_one_record(self) -> None:
        """相近反例（2002 型）：同一筆契約有兩段期間、當事人名稱斷在兩列（第二列以「Ltd.」起頭）→ 只有一個起點 → 一列。"""
        blank = ["", "", "", "", ""]
        tbl = [_CHDR, blank, ["採購", "Hamersley Iron Pty.", "111.04.01~114.03.31", "", ""], ["", "", "", "鐵礦", "無"],
               ["契約", "Ltd. (澳洲)", "114.04.01~115.03.31", "", ""]]
        sec = _csec(_page(10, ["七、重要契約"], [tbl]))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 1
        assert sec.rows[0].parties == ["Hamersley Iron Pty. Ltd. (澳洲)"]

    def test_block_with_wrapped_period_still_one_row(self) -> None:
        """相近反例：期間被切成「111.1~」「112.1」兩列（上一列以起訖符號結尾）→ 仍是同一筆；只有一列以日期起頭 → 一列。"""
        blank = ["", "", "", "", ""]
        tbl = [_CHDR, blank, ["買賣契約", "甲公司", "111.1~", "供貨", "無"], ["", "", "112.1", "", ""], blank,
               ["租賃契約", "乙公司", "1999/12/07 至", "場地", "無"], ["", "", "終止。", "", ""]]
        sec = _csec(_page(10, ["七、重要契約"], [tbl]))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 2
        assert [r.period for r in sec.rows] == ["111.1~112.1", "1999/12/07 至終止。"]


class TestContractsColumnAlignment:
    def test_data_only_in_blank_extension_columns_fails(self) -> None:
        """表頭欄名在第 1、4、7 欄、資料全落在表頭的空白延伸欄（差一欄）→ 對位不確定 → failed。"""
        hdr = ["", "契約性質", "", "", "當事人", "", "", "契約起迄日期", "", "", "主要內容", "", "", "限制條款", ""]
        row = ["", "", "", "買賣", "", "", "甲公司", "", "", "1~2", "", "", "供貨", "", "無"]
        sec = _csec(_page(10, ["七、重要契約", _CHLINE], [[hdr, row]]))
        assert sec.status == STATUS_FAILED and sec.rows == []

    def test_data_on_header_columns_is_fine(self) -> None:
        """反例：同樣寬表頭，資料在表頭欄上（或至少一格在表頭欄上）→ 照常產出。"""
        hdr = ["", "契約性質", "", "", "當事人", "", "", "契約起迄日期", "", "", "主要內容", "", "", "限制條款", ""]
        row = ["", "買賣", "", "", "甲公司", "", "", "1~2", "", "", "供貨", "", "", "無", ""]
        sec = _csec(_page(10, ["七、重要契約", _CHLINE], [[hdr, row]]))
        assert sec.status == STATUS_PARSED and sec.rows[0].parties == ["甲公司"]
        mixed = ["", "買賣", "", "", "", "", "甲公司", "", "", "1~2", "", "", "供貨", "", "無"]  # 性質在表頭欄、其餘在延伸欄 → 照舊
        sec2 = _csec(_page(10, ["七、重要契約", _CHLINE], [[hdr, mixed]]))
        assert sec2.status == STATUS_PARSED and sec2.rows[0].parties == ["甲公司"]


class TestContractsMergedNatureOnly:
    """【Spec 縫隙，待主 flow 補表】性質空白、內容有字、期間完整、當事人完整名稱 → 新列、只沿用性質。
    與既有 test_merged_nature_and_content_rows_inherit 的反例（內容欄有字 → 續行）相衝突，見工作報告仲裁記錄。"""

    def test_content_present_full_period_is_new_row_inheriting_nature_only(self) -> None:
        rows = [["代理契約", "A公司", "2011/1/1-2011/12/31", "代理經銷", "區域限制"], [None, "B公司", "2012/1/1-2012/12/31", "代理銷售", "區域限制"]]
        sec = _csec(_cstart(rows))
        assert [(r.nature, r.parties, r.content) for r in sec.rows] == [("代理契約", ["A公司"], "代理經銷"), ("代理契約", ["B公司"], "代理銷售")]

    def test_counter_examples_stay_continuations(self) -> None:
        # 期間沒有起訖（半截片段）→ 續行；當事人以尾綴詞起頭 → 續行；沒有限制欄 → 續行
        first = ["代理契約", "A股份有限", "2011/1/1-", "代理", "區域限制"]
        for tail in ([None, "公司", "2011/12/31", "經銷", "區域限制"], [None, "B公司", "同上", "經銷", "區域限制"]):
            sec = _csec(_cstart([first, tail]))
            assert sec.status == STATUS_PARSED and len(sec.rows) == 1, tail


class TestContractsDittoParties:
    def test_blank_parties_with_ditto_period_inherits_previous_parties(self) -> None:
        rows = [["銷售合約", "HP Inc.", "1998/6/1 起三年", "接單生產", "保密責任"], ["品質合約", "", "同上", "品質要求", "保密責任"]]
        sec = _csec(_cstart(rows))
        assert sec.status == STATUS_PARSED and [r.parties for r in sec.rows] == [["HP Inc."], ["HP Inc."]]
        assert sec.rows[1].period == "同上"

    def test_blank_parties_without_ditto_is_failed(self) -> None:
        """反例：當事人空白但期間不是「同上」 → 不猜 → failed。"""
        rows = [["銷售合約", "HP Inc.", "1998/6/1 起三年", "接單生產", "保密責任"], ["品質合約", "", "1999/1/1 起三年", "品質要求", "保密責任"]]
        sec = _csec(_cstart(rows))
        assert sec.status == STATUS_FAILED and "品質合約" not in [r.nature for r in sec.rows]

    def test_ditto_without_previous_row_is_failed(self) -> None:
        sec = _csec(_cstart([["品質合約", "", "同上", "品質要求", "保密責任"]]))
        assert sec.status == STATUS_FAILED and sec.rows == []


class TestContractsTextHeaderAboveTable:
    def _page_with(self, hline: str, rows: list[list]) -> Page:
        lines = ["七、重要契約", hline, "工程合約 甲公司 1~2 供貨 無", "八、其他事項"]
        return _page(10, lines, [rows])

    def test_header_line_above_headerless_table_is_used(self) -> None:
        sec = _csec(self._page_with(_CHLINE, [["工程合約", "甲公司", "1~2", "供貨", "無"], ["租賃契約", "乙公司", "3~4", "場地", "無"]]))
        assert sec.status == STATUS_PARSED and [r.parties for r in sec.rows] == [["甲公司"], ["乙公司"]]

    def test_counter_examples_not_used(self) -> None:
        rows = [["工程合約", "甲公司", "1~2", "供貨", "無"]]
        # 欄名段數與表格欄數不同／含欄名的句子（不是整段都是欄名）／表格各列欄數不一 → 不採用
        for hline in ("契約性質 當事人 契約起訖日期 主要內容", "請參閱 契約性質 當事人 契約起訖日期 主要內容 限制條款 說明"):
            assert _csec(self._page_with(hline, rows)).status == STATUS_FAILED, hline
        ragged = [["工程合約", "甲公司", "1~2", "供貨", "無"], ["租賃契約", "乙公司", "3~4", "場地"]]
        assert _csec(self._page_with(_CHLINE, ragged)).status == STATUS_FAILED

    def test_header_line_after_the_table_not_used(self) -> None:
        lines = ["七、重要契約", "工程合約 甲公司 1~2 供貨 無", _CHLINE]
        assert _csec(_page(10, lines, [[["工程合約", "甲公司", "1~2", "供貨", "無"]]])).status == STATUS_FAILED


class TestContractsEndHeadingFirstLine:
    def test_table_chars_all_after_first_line_end_heading_is_after_the_section(self) -> None:
        """終點標題是頁首第一列，表格的每個字都出現在其後的列文字（只是逐字對不上位置）→ 表在終點之後，不是續表。"""
        tbl = [["流動資產", "一", "二", "三", "四"]]
        page = _ccont(11, tbl, with_hdr=False, lines=["肆、財務狀況", "流動資 產 一 二 三 四"])
        sec = _csec(_cstart([_cr()], tail=None), page)
        assert sec.status == STATUS_PARSED and sec.pages == [10] and len(sec.rows) == 1

    def test_table_chars_not_found_after_heading_still_fails(self) -> None:
        """反例：表格有字元不在標題之後的列文字（位置真的不明）→ failed（既有測試 test_headerless_table_position_unknown… 同一行為）。"""
        tbl = [["買賣契約", "一", "二", "三", "四"]]
        page = _ccont(11, tbl, with_hdr=False, lines=["肆、財務狀況", "流動資產 一 二 三"])
        assert _csec(_cstart([_cr()], tail=None), page).status == STATUS_FAILED


class TestContractsColonEntityHeading:
    def test_company_colon_heading_without_enumeration_fails(self) -> None:
        """金控子公司分段標題寫成「○○公司：」（不是「(n) 名稱」）→ entity 不確定 → failed。"""
        page = _page(10, ["七、重要契約", "台新國際商業銀行股份有限公司：", _CHLINE], [_ctbl(_cr())])
        sec = _csec(page)
        assert sec.status == STATUS_FAILED and sec.rows == []

    def test_counter_examples_do_not_trigger(self) -> None:
        # 短稱「本公司：」「子公司：」不是分段標題；同一行在表格儲存格內也不是；「(n) 名稱」寫法照舊
        for line in ("本公司：", "子公司："):
            assert _csec(_page(10, ["七、重要契約", line, _CHLINE], [_ctbl(_cr())])).status == STATUS_PARSED, line
        in_cell = _page(10, ["七、重要契約", _CHLINE, "乙銀行股份有限公司："], [_ctbl(_cr(content="乙銀行股份有限公司："))])
        assert _csec(in_cell).status == STATUS_PARSED
        numbered = _page(10, ["4.17重要契約", "(1) 甲金控", _CHLINE], [_ctbl(_cr())])
        assert _csec(numbered).status == STATUS_PARSED and _csec(numbered).rows[0].entity == "甲金控"


# ═══════════════════════════════════════════════════════════════════════════════
# 契約 row（Task 1.4，DoD／契約）：
#   S1: 金標 10 家 4 項 status 全對（含 page；text 前綴比對）
#   S2: 章名找不到 → 子項退回（連續 ≤3 頁內 ≥2 種「行首編號＋關鍵字」標題；3653、1301）
#   S3: 第 36 條另立一章（2317）；寫在「其他必要補充說明事項」內文（1216，主 flow 裁示）
#   S4: 子項順序不固定（2454）
#   S5: 4 個 key 固定；status ∈ {none, see_mops, disclosed, not_found}；to_dict 欄名與金標一致
# 已知不符（金標比對列為例外，不改金標）：2330 章名在圖片頁（chapter_heading 無、pages 少 p88、
# 子項 1 的 text 因雙欄交錯起頭不同）、2603 chapter_heading 金標含頁首章號「06」、2412 文字層亂碼（text 不比對）。
# ═══════════════════════════════════════════════════════════════════════════════

_SP_TITLES = {
    "affiliates": "關係企業相關資料",
    "private_placement": "最近年度及截至年報刊印日止，私募有價證券辦理情形",
    "other_supplement": "其他必要補充說明事項",
    "material_events_36": "最近年度及截至年報刊印日止，如發生證券交易法第三十六條第三項第二款所定對股東權益或證券價格有重大影響之事項",
}
_SP_KEYS = list(_SP_TITLES)
_SP_BODIES = {
    "affiliates": ["請參閱公開資訊觀測站>單一公司>電子文件下載>關係企業三書表專區。"],
    "private_placement": ["無。"],
    "other_supplement": ["無。"],
    "material_events_36": ["無。"],
}
_SP_STATUS_SET = {"none", "see_mops", "disclosed", "not_found"}
_SP_KNOWN_TEXT_GAP = {("2330", "affiliates"), ("2412", "private_placement"), ("2412", "other_supplement"),
                      ("2412", "material_events_36")}
_SP_GARBLED_2412 = ("private_placement", "other_supplement", "material_events_36")  # 文字層「無。」缺字，已知限制


def _sp_lines(bodies: dict[str, list[str]] | None = None, order: list[str] | None = None,
              head: str | None = "陸、特別記載事項") -> list[str]:
    """合成章：章名（可省）＋依 order 的子項（編號一、二、…），內文取 bodies。"""
    bodies = {**_SP_BODIES, **(bodies or {})}
    out = [head] if head else []
    for n, k in enumerate(order or _SP_KEYS):
        out += [f"{'一二三四'[n]}、{_SP_TITLES[k]}", *bodies[k]]
    return out


def _sp(*pages: Page) -> SpecialSection:
    return parse_special(_doc(*pages))


def _sp1(bodies: dict[str, list[str]] | None = None, **kw) -> SpecialSection:
    return _sp(_page(10, _sp_lines(bodies, **kw)))


def _statuses(sec: SpecialSection) -> dict[str, str]:
    return {k: v.status for k, v in sec.items.items()}


# ── S1／S3／S4 金標 ─────────────────────────────────────────────────────────


@needs_fixture
@pytest.mark.parametrize("ticker", _TICKERS)
def test_special_gold(ticker: str, _pages: dict, _gold: dict) -> None:
    """S1：4 項 status 全對（S3 的 2317、1216 與 S4 的 2454 也在內）；page 全對，text 以金標為前綴。"""
    sec = parse_special(_load(_pages, ticker))
    g = _gold[ticker]["special"]
    assert sec.status == g["status"]
    assert list(sec.items) == list(g["items"])
    for k, gi in g["items"].items():
        it = sec.items[k]
        if ticker == "2412" and k in _SP_GARBLED_2412:
            continue  # 已知限制：見 test_special_2412_garbled_known_limit
        assert it.status == gi["status"], (ticker, k, "status")
        assert it.page == gi["page"], (ticker, k, "page")
        if (ticker, k) not in _SP_KNOWN_TEXT_GAP:
            assert _n(it.text).startswith(_n(gi["text"])), (ticker, k, "text")
        else:
            assert it.text, (ticker, k, "text 存在")
    if ticker != "2330":  # testlint: allow — 2330 章名在圖片頁，pages 為 Spec §2.6 已知限制
        assert sec.pages == g["pages"]
    if ticker not in ("2330", "2603"):  # testlint: allow — 2330／2603 chapter_heading 為 Spec §2.6 已知限制
        assert _n(sec.chapter_heading) == _n(g["chapter_heading"])


@needs_fixture
def test_special_2412_garbled_known_limit(_pages: dict) -> None:
    """2412 文字層缺字（「無。」變成「搁。」）：這 3 項 status 不比對金標（Spec §2.6 已知不符），只驗 page 仍是 179
    且 status 是 disclosed 或 none；affiliates 不受影響。"""
    sec = parse_special(_load(_pages, "2412"))
    for k in _SP_GARBLED_2412:
        assert sec.items[k].page == 179 and sec.items[k].status in (STATUS_DISCLOSED, STATUS_NONE), k
    assert sec.items["affiliates"].status == STATUS_DISCLOSED and sec.items["affiliates"].page == 167


@needs_fixture
def test_special_2330_known_gaps(_pages: dict) -> None:
    """2330 章名在圖片頁：無章名 → chapter_heading None，pages 從子項起頁（p89）算起。"""
    sec = parse_special(_load(_pages, "2330"))
    assert sec.chapter_heading is None and sec.pages == [89, 90, 91]


@needs_fixture
def test_special_to_dict_schema_matches_gold(_pages: dict, _gold: dict) -> None:
    """S5 producer 側 schema：to_dict 欄名與金標逐欄一致（金標另有人工 notes 欄，程式多一個 reason）。"""
    d = parse_special(_load(_pages, "3653")).to_dict()
    g = _gold["3653"]["special"]
    assert set(g) - {"notes"} == set(d) - {"reason"}
    assert list(g["items"]) == list(d["items"]) == _SP_KEYS
    assert set(g["items"]["affiliates"]) == set(d["items"]["affiliates"])
    assert d["reason"] is None


# ── S2 章名找不到 → 子項退回 ─────────────────────────────────────────────────


@needs_fixture
@pytest.mark.parametrize("ticker", ["3653", "1301"])
def test_special_fallback_without_chapter_heading(ticker: str, _pages: dict, _gold: dict) -> None:
    """金標的章名列拿掉後，用子項退回仍找到該章：4 項 status 與有章名時相同，chapter_heading 為 None。"""
    doc = _load(_pages, ticker)
    heading = _gold[ticker]["special"]["chapter_heading"]
    n_removed = 0
    for p in doc.pages:
        keep = [ln for ln in p.lines if _n(ln) != _n(heading)]
        n_removed += len(p.lines) - len(keep)
        p.lines = keep
    assert n_removed >= 1  # 章名列真的拿掉了
    sec = parse_special(doc)
    assert sec.status == STATUS_PARSED and sec.chapter_heading is None
    assert _statuses(sec) == {k: v["status"] for k, v in _gold[ticker]["special"]["items"].items()}
    assert sec.pages == _gold[ticker]["special"]["pages"]


class TestSpecialFallback:
    def test_two_keys_within_three_pages_found(self) -> None:
        """退回規則：連續 ≤3 頁內 ≥2 種子項標題（第 1、3 頁）→ 認定為該章。"""
        p10 = _page(10, ["一、關係企業相關資料", "請參閱公開資訊觀測站。"])
        p12 = _page(12, ["二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。"])
        sec = _sp(p10, _page(11, ["其他文字"]), p12)
        assert sec.status == STATUS_PARSED and sec.chapter_heading is None
        assert (sec.items["affiliates"].page, sec.items["private_placement"].page) == (10, 12)

    def test_fallback_pages_start_at_first_item_page(self) -> None:
        """3.4 抽驗（2801 pages 5–114）：退回路徑的章節範圍取子項實際所在頁，前面只有標題、沒有內文的索引頁不納入；
        反例：子項跨兩頁時兩頁都納入。"""
        p8 = _page(8, ["一、關係企業相關資料", "二、最近年度及截至年報刊印日止，私募有價證券辦理情形"])
        p9 = _page(9, ["一、關係企業相關資料", "請參閱公開資訊觀測站。", "二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。"])
        sec = _sp(p8, p9)
        assert sec.status == STATUS_PARSED and sec.pages == [9]
        p10 = _page(10, ["一、關係企業相關資料", "請參閱公開資訊觀測站。"])
        p11 = _page(11, ["二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。"])
        assert _sp(p10, p11).pages == [10, 11]

    def test_two_keys_spread_over_four_pages_not_found(self) -> None:
        """反例：同樣兩種標題相隔 4 頁（第 1、5 頁）→ 不是同一章。"""
        sec = _sp(_page(10, ["一、關係企業相關資料", "請參閱公開資訊觀測站。"]),
                  _page(14, ["二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。"]))
        assert sec.status == STATUS_NOT_FOUND

    def test_single_key_not_found(self) -> None:
        """反例：只有 1 種子項標題 → 不退回。"""
        assert _sp(_page(10, ["一、關係企業相關資料", "請參閱公開資訊觀測站。"])).status == STATUS_NOT_FOUND

    def test_sentence_mentions_not_titles(self) -> None:
        """反例：治理章內文句中出現「關係企業相關資料」等字（無行首編號）、「(一)」括號編號都不算標題。"""
        lines = ["本公司關係企業相關資料如下表。", "(一) 關係企業相關資料", "(二) 其他必要補充說明事項",
                 "其他必要補充說明事項：無。", "最近年度私募有價證券辦理情形：無。"]
        assert _sp(_page(10, lines)).status == STATUS_NOT_FOUND

    def test_toc_title_lines_not_counted(self) -> None:
        """反例：目錄列（列尾頁碼）不算標題；同樣的標題拿掉頁碼就算。"""
        base = ["一、關係企業相關資料", "請參閱公開資訊觀測站。", "二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。"]
        tailed = [ln + " 95" if ln[:2] in ("一、", "二、") else ln for ln in base]
        assert _sp(_page(10, tailed)).status == STATUS_NOT_FOUND
        assert _sp(_page(10, base)).status == STATUS_PARSED

    def test_toc_leader_page_skipped(self) -> None:
        """目錄頁（任一列為「引導線＋頁碼」）整頁不採用；拿掉引導線列 → 同樣的標題被採用。"""
        titles = ["一、關係企業相關資料", "請參閱公開資訊觀測站。", "二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。"]
        assert _sp(_page(10, ["三、現金流量-------------------- 90", *titles])).status == STATUS_NOT_FOUND
        assert _sp(_page(10, titles)).status == STATUS_PARSED


# ── 章名 ───────────────────────────────────────────────────────────────────


class TestSpecialHeading:
    def test_heading_variants_found(self) -> None:
        for head in ("陸、特別記載事項", "6. 特別記載事項", "特別記載事項"):
            sec = _sp1(head=head)
            assert sec.status == STATUS_PARSED and sec.chapter_heading == head

    def test_heading_pages_start_at_heading_page(self) -> None:
        """章扉頁（只有章名）在前、正文在後：pages 從章名頁起算。"""
        sec = _sp(_page(10, ["特別記載事項", "Special Disclosure"]), _page(11, _sp_lines(head=None)))
        assert sec.pages == [10, 11] and sec.chapter_heading == "特別記載事項"

    def test_toc_and_embedded_heading_not_adopted(self) -> None:
        """反例：目錄列（帶頁碼）、句中的「特別記載事項」不是章名；沒有子項時整體 not_found。"""
        lines = ["特別記載事項 164", "陸、特別記載事項-------------- 95", "詳見有關特別記載事項之說明。"]
        sec = _sp(_page(10, lines))
        assert sec.status == STATUS_NOT_FOUND and sec.chapter_heading is None
        assert sec.reason and _statuses(sec) == {k: "not_found" for k in _SP_KEYS}
        assert all(it.page is None and it.text is None for it in sec.items.values())

    def test_heading_without_items_falls_through_to_next_heading(self) -> None:
        """第一個章名後沒有子項（只是頁首文字）→ 改用下一個章名。"""
        sec = _sp(_page(9, ["特別記載事項"]), _page(20, _sp_lines()))
        assert sec.status == STATUS_PARSED and sec.pages == [20]

    def test_other_chapter_heading_ends_stream(self) -> None:
        """反例：另一個大寫數字章名之後的標題不屬於本章。"""
        lines = _sp_lines({"other_supplement": ["無。"]}, order=["affiliates", "private_placement"])
        lines += ["捌、公司治理", "三、其他必要補充說明事項：無。"]
        sec = _sp(_page(10, lines))
        assert sec.items["other_supplement"].status == "not_found"
        assert sec.items["private_placement"].status == STATUS_NONE


# ── 章扉頁子項目錄、跨頁 ─────────────────────────────────────────────────────


class TestSpecialPages:
    def test_listing_page_titles_without_body_skipped(self) -> None:
        """章扉頁的子項目錄（標題所在頁沒有內文）不採用，取正文頁的標題（2412、1216 型）。"""
        listing = _page(10, ["特別記載事項"] + [f"{'一二三四'[n]}、{_SP_TITLES[k]}" for n, k in enumerate(_SP_KEYS)])
        sec = _sp(listing, _page(11, _sp_lines(head=None)))
        assert {it.page for it in sec.items.values()} == {11}
        assert _statuses(sec) == {"affiliates": "see_mops", "private_placement": "none",
                                  "other_supplement": "none", "material_events_36": "none"}

    def test_title_with_body_on_first_page_is_adopted(self) -> None:
        """反例：同樣的目錄頁但每個標題下都有內文 → 採用第一頁。"""
        sec = _sp(_page(10, _sp_lines()), _page(11, _sp_lines(head=None)))
        assert {it.page for it in sec.items.values()} == {10}

    def test_body_continues_across_pages_until_next_title(self) -> None:
        """子項內文跨頁到下一個標題前（2412 型），page 記標題所在頁。"""
        p10 = _page(10, ["特別記載事項", "一、關係企業相關資料", "第一頁內文。"])
        p11 = _page(11, ["第二頁內文。", "二、最近年度及截至年報刊印日止，私募有價證券辦理情形", "無。"])
        sec = _sp(p10, p11)
        aff = sec.items["affiliates"]
        assert aff.page == 10 and _n(aff.text) == "第一頁內文。第二頁內文。" and aff.status == STATUS_DISCLOSED
        assert sec.items["private_placement"].page == 11

    def test_last_item_stops_at_its_page_end(self) -> None:
        """最後一個標題只取到所在頁底，下一頁的內容（別的章）不併入；頁碼列也不併入。"""
        p10 = _page(10, _sp_lines() + ["-95-"])
        p11 = _page(11, ["後續章節的文字。"])
        sec = _sp(p10, p11)
        assert sec.items["material_events_36"].text == "無。" and sec.pages == [10]

    def test_noncontiguous_pages_not_merged(self) -> None:
        """反例：頁碼不連續的下一頁不併入列流。"""
        p10 = _page(10, ["特別記載事項", "一、關係企業相關資料", "第一頁內文。"])
        p12 = _page(12, ["二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。"])
        sec = _sp(p10, p12)
        assert _n(sec.items["affiliates"].text) == "第一頁內文。" and sec.items["private_placement"].status == "not_found"


# ── 子項 status ─────────────────────────────────────────────────────────────

_MOPS = "請參閱公開資訊觀測站>單一公司>電子文件下載>關係企業三書表專區。"


class TestSpecialItemStatus:
    @pytest.mark.parametrize("body, expected", [
        (["無。"], STATUS_NONE),
        (["不適用。"], STATUS_NONE),
        (["最近年度及截至年報刊印日止，有無發生第三十六條事項：無。"], STATUS_NONE),
        ([_MOPS], STATUS_SEE_MOPS),
        (["本公司已於官網揭露相關資料。"], STATUS_DISCLOSED),
        (["已核准。"], STATUS_DISCLOSED),
    ])
    def test_status_by_body(self, body: list[str], expected: str) -> None:
        assert _sp1({"other_supplement": body}).items["other_supplement"].status == expected

    def test_inline_body_after_title_colon(self) -> None:
        """內文與標題同列（「…情形：無。」）、標題斷成多列、「，亦應逐項載明：」都取標題之後的原文。"""
        sec = _sp(_page(10, ["陸、特別記載事項", "二、最近年度及截至年報刊印日止，私募有價證券辦理情形：無。",
                             "四、最近年度及截至年報刊印日止，如發生證券交易法第三十六條第三項第二款所定對股東",
                             "權益或證券價格有重大影響之事項，亦應逐項載明：無。"]))
        assert sec.items["private_placement"].text == "無。"
        assert sec.items["material_events_36"].text == "無。" and sec.items["material_events_36"].status == STATUS_NONE

    def test_none_beats_see_mops(self) -> None:
        """第一句「無」優先於 see_mops；反例：第一句不是「無」、只提觀測站 → 仍是 see_mops。"""
        assert _sp1({"other_supplement": ["無。詳細資料請至公開資訊觀測站查詢。"]}).items["other_supplement"].status == STATUS_NONE
        assert _sp1({"other_supplement": ["有。請至公開資訊觀測站查詢。"]}).items["other_supplement"].status == STATUS_SEE_MOPS
        # 反例（2317 型）：各小項沒有句號、整段成一句，句首已是觀測站連結、結尾才是「不適用」→ see_mops，不是 none
        no_period = ["(一) 關係企業合併營業報告書請參閱公開資訊觀測站>單一公司>電子文件下載", "(二) 關係企業報告書：不適用。"]
        assert _sp1({"affiliates": no_period}).items["affiliates"].status == STATUS_SEE_MOPS

    def test_mops_in_first_sentence_not_none_even_if_long(self) -> None:
        """🟡-B：第一句本身提到觀測站、結尾「不適用」，全文超過 600 字 → 不判 none（長文 → disclosed）。"""
        long_tail = "本公司另有補充說明" * 80 + "。"
        no_period = ["(一) 關係企業合併營業報告書請參閱公開資訊觀測站>單一公司>電子文件下載", "(二) 關係企業報告書：不適用。", long_tail]
        assert _sp1({"affiliates": no_period}).items["affiliates"].status == STATUS_DISCLOSED

    def test_long_first_sentence_ending_none_is_disclosed(self) -> None:
        """3.4 抽驗（2379、6505）：第一句超過 200 字（組織圖等揭露、無句號）、最後一小項「：無」→ disclosed，不是整項 none；
        反例：多分項但都短、都寫「無」（2892 型）→ none；長但 ≤200 字的單一陳述（私募「，應揭露…：無」）→ none。"""
        chart = "甲公司100%乙公司60%丙公司研發與技術服務" * 12  # 約 260 字
        multi = ["(一)關係企業組織圖" + chart, "(二)推定為有控制與從屬關係者其相同股東資料：無"]
        assert _sp1({"affiliates": multi}).items["affiliates"].status == STATUS_DISCLOSED
        short_multi = ["(一)前一年度及截至年報刊印日止，發生證券交易法第三十六條第三項第二款所定對股東權益或證券價格有重大影響之事項：無。", "(二)重要期後事項：無。"]
        assert _sp1({"other_supplement": short_multi}).items["other_supplement"].status == STATUS_NONE
        long_single = ["，應揭露股東會或董事會通過日期與數額、價格訂定之依據及合理性、特定人選擇之方式及辦理私募之必要理由及預計效益：無"]
        assert _sp1({"private_placement": long_single}).items["private_placement"].status == STATUS_NONE

    def test_none_only_when_first_sentence_says_none(self) -> None:
        """反例：「無」出現在後面的句子、或前面有實質說明 → disclosed。"""
        assert _sp1({"other_supplement": ["本公司另有說明如下。", "無。"]}).items["other_supplement"].status == STATUS_DISCLOSED
        assert _sp1({"other_supplement": ["本公司無此情形，詳見內文說明。"]}).items["other_supplement"].status == STATUS_DISCLOSED

    def test_none_followed_by_noise_still_none(self) -> None:
        """第一句為「無。」，其後混入頁尾雜訊（2886「OUR VISION」）→ none。"""
        assert _sp1({"private_placement": ["無。", "OUR VISION—成為亞洲區域性金融集團"]}).items["private_placement"].status == STATUS_NONE

    def test_single_char_plus_period_not_none(self) -> None:
        """反例：內文是單字＋句號（「有。」「搁。」）不可判為 none；只有結尾是「無」「不適用」才是。"""
        for body in ("有。", "搁。", "搁", "搁搁。"):
            assert _sp1({"other_supplement": [body]}).items["other_supplement"].status == STATUS_DISCLOSED, body
        assert _sp1({"other_supplement": ["無。"]}).items["other_supplement"].status == STATUS_NONE

    def test_see_mops_needs_mops_and_short(self) -> None:
        """see_mops 需提到「公開資訊觀測站」且不超過 600 字；長篇實質揭露、或沒提觀測站的連結 → disclosed。"""
        long_body = [_MOPS, "說明" * 300]
        assert _sp1({"affiliates": long_body}).items["affiliates"].status == STATUS_DISCLOSED
        assert _sp1({"affiliates": ["請參閱 https://mopsov.twse.com.tw/mops/web/t57sb01_q10。"]}).items["affiliates"].status == STATUS_DISCLOSED
        assert _sp1({"affiliates": [_MOPS, "(三) 關係企業報告書：不適用。"]}).items["affiliates"].status == STATUS_SEE_MOPS

    def test_not_found_item_has_no_page_or_text(self) -> None:
        sec = _sp1(order=["affiliates", "private_placement"])
        assert sec.status == STATUS_PARSED
        for k in ("other_supplement", "material_events_36"):
            assert (sec.items[k].status, sec.items[k].page, sec.items[k].text) == ("not_found", None, None)

    def test_status_always_in_contract_set(self) -> None:
        for sec in (_sp1(), _sp1(order=["affiliates"]), _sp(_page(10, ["無關文字"]))):
            assert list(sec.items) == _SP_KEYS and set(_statuses(sec).values()) <= _SP_STATUS_SET


# ── 第 36 條事項的三種寫法 ────────────────────────────────────────────────────


class TestSpecialMaterialEvents36:
    _CH36 = "柒、對股東權益或證券價格有重大影響之事項"
    _STMT = "最近年度及截至年報刊印日止，依證券交易法第三十六條第三項第二款所定對股東權益或證券價格有重大影響之事項：無。"

    def _chapter_split(self, head36: str) -> SpecialSection:
        lines = _sp_lines(order=["affiliates", "private_placement", "other_supplement"]) + [head36, self._STMT]
        return _sp(_page(10, lines))

    def test_separate_chapter(self) -> None:
        """S3：另立一章「柒、對股東權益或證券價格有重大影響之事項」→ 取章下整段文字。"""
        it = self._chapter_split(self._CH36).items["material_events_36"]
        assert (it.status, it.page, it.text) == (STATUS_NONE, 10, self._STMT)

    def test_separate_chapter_title_needs_big_numeral(self) -> None:
        """反例：同樣文字但沒有大寫數字章號 → 不是另立章：該列與條文都併入「其他必要補充說明事項」內文
        （第 36 條事項改由內文推導，其他補充的 text 含該列）。"""
        assert self._chapter_split(self._CH36).items["other_supplement"].text == "無。"
        head = "對股東權益或證券價格有重大影響之事項"
        assert head in self._chapter_split(head).items["other_supplement"].text

    def test_statement_inside_other_supplement(self) -> None:
        """S3（1216）：第 36 條陳述寫在「其他必要補充說明事項」內文 → 兩項都是 none，text 同一段。"""
        stmt = self._STMT
        sec = _sp1({"other_supplement": [stmt]}, order=["affiliates", "private_placement", "other_supplement"])
        assert sec.items["other_supplement"].status == STATUS_NONE
        m36 = sec.items["material_events_36"]
        assert (m36.status, m36.page, m36.text) == (STATUS_NONE, 10, stmt)
        assert sec.items["other_supplement"].text == stmt

    def test_statement_inside_other_supplement_with_extra_text(self) -> None:
        """內文另有實質說明時：其他補充 → disclosed，第 36 條 → none（各自看自己的句子）。"""
        sec = _sp1({"other_supplement": ["本公司另有說明如下。", self._STMT]},
                   order=["affiliates", "private_placement", "other_supplement"])
        assert sec.items["other_supplement"].status == STATUS_DISCLOSED
        assert sec.items["material_events_36"].status == STATUS_NONE

    def test_other_supplement_without_statement_has_no_36(self) -> None:
        """反例：其他補充內文沒有第 36 條條文 → 第 36 條事項 not_found。"""
        sec = _sp1({"other_supplement": ["無。"]}, order=["affiliates", "private_placement", "other_supplement"])
        assert sec.items["material_events_36"].status == "not_found"

    def test_own_title_wins_over_other_supplement_statement(self) -> None:
        """有獨立標題時不從其他補充內文推導（status 各自看自己的內文）。"""
        sec = _sp1({"other_supplement": [self._STMT], "material_events_36": ["本公司說明如下。"]})
        assert sec.items["material_events_36"].status == STATUS_DISCLOSED
        assert sec.items["other_supplement"].status == STATUS_NONE


# ── S4 子項順序不固定 ────────────────────────────────────────────────────────


def test_special_order_not_fixed() -> None:
    """S4：子項順序（2454：第 36 條在第 3 項、其他補充在第 4 項）不影響各 key 的 status 與頁碼。"""
    bodies = {"affiliates": [_MOPS], "private_placement": ["無。"], "other_supplement": ["本公司另有說明。"],
              "material_events_36": ["無。"]}
    std = _sp1(bodies)
    swapped = _sp1(bodies, order=["affiliates", "private_placement", "material_events_36", "other_supplement"])
    reversed_ = _sp1(bodies, order=list(reversed(_SP_KEYS)))
    assert _statuses(std) == _statuses(swapped) == _statuses(reversed_) == {
        "affiliates": "see_mops", "private_placement": "none", "other_supplement": "disclosed",
        "material_events_36": "none"}
    assert swapped.items["material_events_36"].text == "無。"


# ── mutation self-check（改輸入 → 輸出必須同步翻轉）──────────────────────────────


class TestSpecialMutationControls:
    @needs_fixture
    def test_mutating_gold_page_text_flips_status(self, _pages: dict, _gold: dict) -> None:
        """3653：私募項內文「無。」改成實質說明 → none 翻成 disclosed；改回即還原。"""
        doc = _load(_pages, "3653")
        assert parse_special(doc).items["private_placement"].status == STATUS_NONE
        p = next(p for p in doc.pages if p.number == 99)
        i = next(i for i, ln in enumerate(p.lines) if "私募有價證券辦理情形" in ln)
        orig = p.lines[i]
        p.lines[i] = orig.replace("：無。", "：已核准辦理。")
        assert parse_special(doc).items["private_placement"].status == STATUS_DISCLOSED
        p.lines[i] = orig
        assert parse_special(doc).items["private_placement"].status == STATUS_NONE

    @needs_fixture
    def test_mutating_title_keyword_removes_item(self, _pages: dict) -> None:
        """3653：把「其他必要補充說明事項」標題的關鍵字改掉 → 該項 not_found，其他項不變。"""
        doc = _load(_pages, "3653")
        assert parse_special(doc).items["other_supplement"].status == STATUS_NONE
        for p in doc.pages:
            p.lines = [unicodedata.normalize("NFKC", ln).replace("其他必要補充說明事項", "其他補充") for ln in p.lines]  # 原文有 CJK 相容字，先 NFKC
        sec = parse_special(doc)
        assert sec.items["other_supplement"].status == "not_found"
        assert sec.items["private_placement"].status == STATUS_NONE

    def test_mutating_mops_wording_flips_see_mops(self) -> None:
        assert _sp1({"affiliates": [_MOPS]}).items["affiliates"].status == STATUS_SEE_MOPS
        assert _sp1({"affiliates": [_MOPS.replace("公開資訊觀測站", "公司網站")]}).items["affiliates"].status == STATUS_DISCLOSED

    def test_mutating_numbering_removes_title(self) -> None:
        """標題行首編號拿掉 → 不再是標題（句中出現的關鍵字不算）。"""
        with_num = _sp1(order=["affiliates", "private_placement"])
        assert with_num.items["private_placement"].status == STATUS_NONE
        lines = [ln.replace("二、", "") for ln in _sp_lines(order=["affiliates", "private_placement"])]
        assert _sp(_page(10, lines)).items["private_placement"].status == "not_found"


# ═══════════════════════════════════════════════════════════════════════════════
# item 3.3：特別記載事項泛化（101 家全量）——新的章名／子項寫法＋「相近但不該觸發」的反例
# ═══════════════════════════════════════════════════════════════════════════════

_SP_T_AFF = "關係企業相關資料"
_SP_T_PRIV = "最近年度及截至年報刊印日止，私募有價證券辦理情形"
_SP_T_OTH = "其他必要補充說明事項"
_SP_T_36 = "最近年度及截至年報刊印日止，發生證券交易法第三十六條第三項第二款所定對股東權益或證券價格有重大影響之事項"


def _spx(lines: list[str]) -> SpecialSection:
    return _sp(_page(10, lines))


def _first3(head: str | None = "陸、特別記載事項") -> list[str]:
    out = [head] if head else []
    return out + [f"一、{_SP_T_AFF}：", _MOPS, f"二、{_SP_T_PRIV}：無。", f"三、{_SP_T_OTH}：無。"]


class TestSpecial36TitleVariants:
    @pytest.mark.parametrize("title", [
        "最近年度及截至年報刊印日止，發生證券交易法第三十六條第二項第二款所定對股東權益或證券價格有重大影響之事項",
        "最近年度及截至年報刊印日止，發生證券交易法第36 條第3 項第2 款所定對股東權益或證券價格有重大影響之事項",
        "最近年度及截至年報刊印日止，發生對股東權益或證券價格有重大影響之事項",
        "對股東權益或證券價格有重大影響事項",
    ])
    def test_variant_titles_found(self, title: str) -> None:
        sec = _spx(_first3() + [f"四、{title}：無。"])
        assert sec.items["material_events_36"].status == STATUS_NONE
        assert sec.items["other_supplement"].text == "無。"  # 第 4 項標題不再併進第 3 項內文

    def test_title_split_across_lines(self) -> None:
        sec = _spx(_first3() + ["四、最近年度及截至年報刊印日止，如發生證券交易法第三十六條第三項第", "二款所定對股東權益或證券價格有重大影響之事", "項：無。"])
        assert sec.items["material_events_36"].status == STATUS_NONE

    def test_first_clause_title_not_36(self) -> None:
        """相近反例：第三十六條第三項「第一款」不是第 36 條事項。"""
        sec = _spx(_first3() + ["四、最近年度及截至年報刊印日止，發生證券交易法第三十六條第三項第一款所定之事項：無。"])
        assert sec.items["material_events_36"].status == "not_found"

    def test_body_sentence_not_title(self) -> None:
        """相近反例：編號列的句子只是「…有重大影響者」（訴訟內文），不是標題。"""
        sec = _spx(_first3() + ["四、訴訟事件，其結果可能對股東權益或證券價格有重大影響者：無。"])
        assert sec.items["material_events_36"].status == "not_found"

    def test_truncated_clause_with_other_column_text(self) -> None:
        """1101：雙欄交錯，「第三項第」後接別欄文字，款次不是「第一款」→ 仍是標題。"""
        sec = _spx(_first3() + ["四、最近年度及截至年報刊印日止，發生證券交易法第三十六條第三項第 桃園二廠 (436) 台中市清水區", "二款所定對股東權益或證券價格有動大影響之事項：", "本公司之子公司發生火災事故。"])
        assert sec.items["material_events_36"].status == STATUS_DISCLOSED


class TestSpecialBigNumber36Chapter:
    def test_big_number_36_chapter_kept_in_stream(self) -> None:
        sec = _spx(_first3() + [f"柒、{_SP_T_36}：無。"])
        assert sec.items["material_events_36"].status == STATUS_NONE
        assert sec.items["other_supplement"].text == "無。"

    def test_big_number_36_title_over_five_lines(self) -> None:
        sec = _spx(_first3() + ["捌、最近年度及截至年報刊印日止，是", "否發生證交法第 條第 項", "36 3 第2", "款所定對股東權益或證券價格有重", "大影響之事項：無。"])
        assert sec.items["material_events_36"].status == STATUS_NONE

    def test_other_big_number_chapter_ends_stream(self) -> None:
        """相近反例：「柒、其他事項」不是第 36 條事項，章到此為止。"""
        sec = _spx(_first3() + ["柒、其他事項", f"四、{_SP_T_36}：無。"])
        assert sec.items["material_events_36"].status == "not_found"

    def test_big_number_toc_line_not_title(self) -> None:
        sec = _spx(_first3() + [f"柒、{_SP_T_36} ........ 175"])
        assert sec.items["material_events_36"].status == "not_found"


class TestSpecialNestedBigNumber:
    def test_smaller_big_number_after_sub_item_is_nested(self) -> None:
        """6223：「陸、特別記載事項」下的「貳、關係企業營運概況」章號較小、且已讀到子項編號列 → 子節，章不結束。"""
        sec = _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}：", "本公司關係企業如下。", "貳、關係企業營運概況", "各關係企業營運如下。",
                    f"二、{_SP_T_PRIV}：無。", f"三、{_SP_T_OTH}：無。", f"四、{_SP_T_36}：無。"])
        assert _statuses(sec)["private_placement"] == STATUS_NONE
        assert sec.items["material_events_36"].status == STATUS_NONE

    def test_larger_big_number_ends_chapter(self) -> None:
        """相近反例：章號較大的「柒、…」結束章。"""
        sec = _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}：", "本公司關係企業如下。", "柒、財務概況", f"二、{_SP_T_PRIV}：無。"])
        assert sec.items["private_placement"].status == "not_found"

    def test_smaller_big_number_without_sub_item_ends_chapter(self) -> None:
        """相近反例（3711 型章名清單頁）：還沒讀到子項編號列就出現章號較小的大寫章名 → 章結束。"""
        sec = _spx(["陸、特別記載事項", "貳、公司治理報告", f"二、{_SP_T_PRIV}：無。"])
        assert sec.items["private_placement"].status == "not_found"


class TestSpecialBigNumberSubItems:
    def _lines(self, extra: list[str] | None = None) -> list[str]:
        return ["特別記載事項", f"壹、 {_SP_T_AFF}", "一、關係企業合併營業報告書", "見本表。",
                f"貳、 {_SP_T_36}：無。", "參、 私募有價證券辦理情形：無。", "肆、 其他必要補充說明事項：無。", *(extra or [])]

    def test_big_number_sub_items_found(self) -> None:
        """2379：章名不帶章號，子項用「壹、貳、參、肆」編號。"""
        sec = _spx(self._lines())
        assert _statuses(sec) == {"affiliates": STATUS_DISCLOSED, "private_placement": STATUS_NONE,
                                  "other_supplement": STATUS_NONE, "material_events_36": STATUS_NONE}

    def test_big_number_non_title_still_ends_chapter(self) -> None:
        """相近反例：「伍、公司治理報告」不含子項關鍵字 → 章結束，後面的標題不採用。"""
        sec = _spx(["特別記載事項", f"壹、 {_SP_T_AFF}", "見本表。", "伍、公司治理報告", "參、 私募有價證券辦理情形：無。"])
        assert sec.items["private_placement"].status == "not_found"


class TestSpecialHeadingAndNumbering:
    def test_dot_separated_big_number_heading_and_bullets(self) -> None:
        """2308：章名「柒 ‧ 特別記載事項」，子項行首有私用區項目符號（U+F075）。"""
        lines = ["柒 ‧ 特別記載事項", f" 一、{_SP_T_AFF}：", _MOPS, f" 二、{_SP_T_PRIV}：無此情形。",
                 f" 三、{_SP_T_OTH}", "(一) 證照情形。", f" 四、{_SP_T_36}", "本公司發生火災。"]
        sec = _spx(lines)
        assert _statuses(sec) == {"affiliates": STATUS_SEE_MOPS, "private_placement": STATUS_DISCLOSED,
                                  "other_supplement": STATUS_DISCLOSED, "material_events_36": STATUS_DISCLOSED}
        assert sec.chapter_heading == "柒 ‧ 特別記載事項"

    def test_other_dot_heading_not_chapter(self) -> None:
        """相近反例：「柒 ‧ 財務概況」不是章名；沒有章名、也沒有 ≥2 種子項標題 → not_found。"""
        assert _spx(["柒 ‧ 財務概況", f"一、{_SP_T_AFF}：", _MOPS]).status == "not_found"

    def test_cjk_stroke_one_numeral(self) -> None:
        """2207：「㇐、」（U+31D0）是「一、」。"""
        sec = _spx(["陸、特別記載事項", f"㇐、{_SP_T_AFF}", _MOPS, f"二、{_SP_T_PRIV}：無。"])
        assert sec.items["affiliates"].status == STATUS_SEE_MOPS

    def test_stroke_numeral_mid_sentence_not_title(self) -> None:
        """相近反例：句中的「㇐、關係企業相關資料」不是標題（行首沒有編號）。"""
        sec = _spx(["陸、特別記載事項", f"本公司㇐、{_SP_T_AFF}", _MOPS, f"二、{_SP_T_PRIV}：無。"])
        assert sec.items["affiliates"].status == "not_found"

    def test_lone_vertical_chapter_number_not_body(self) -> None:
        """2002：直排章號單獨成列（「柒」）不併進前一子項內文。"""
        sec = _spx(_first3() + ["柒", f"柒、{_SP_T_36}：無。"])
        assert sec.items["other_supplement"].text == "無。"

    def test_two_char_line_kept_in_body(self) -> None:
        """相近反例：兩字以上的列（「柒元」）仍是內文。"""
        sec = _spx(_first3() + ["柒元"])
        assert sec.items["other_supplement"].text == "無。柒元"


class TestSpecialTitleWordings:
    @pytest.mark.parametrize("key,line", [
        ("other_supplement", "三、其他必補充說明事項：無。"),
        ("other_supplement", "三、其他必要補充事項：無。"),
        ("other_supplement", "三、其他必要補充說明：無。"),
        ("private_placement", "二、最近年度及截至年報刊印日止，私募有價證券及金融債券辦理情形：無。"),
        ("private_placement", "二、最近年度及截至年報刊印日止，私募有價證券之辦理情形：無。"),
        ("affiliates", "一、係企業相關資料"),
    ])
    def test_wording_found(self, key: str, line: str) -> None:
        sec = _spx(["陸、特別記載事項", "一、關係企業相關資料", _MOPS, line] if key != "affiliates" else ["陸、特別記載事項", line, _MOPS, f"二、{_SP_T_PRIV}：無。"])
        assert sec.items[key].status != "not_found"

    @pytest.mark.parametrize("line", [
        "二、私募有價證券及公司債辦理情形：無。",
        "二、最近年度及截至年報刊印日止，私募有價證券辦理：無。",
    ])
    def test_near_wording_not_title(self, line: str) -> None:
        """相近反例：缺「辦理情形」結尾、或夾別的債券名稱 → 不是私募標題。"""
        sec = _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}", _MOPS, line])
        assert sec.items["private_placement"].status == "not_found"

    def test_midline_other_column_fragment(self) -> None:
        """4958：別欄儲存格殘字（≤12 字）在編號標題前。"""
        sec = _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}", _MOPS, f"二、{_SP_T_PRIV}：無。", f"有限公司 三、{_SP_T_OTH}：無。"])
        assert sec.items["other_supplement"].status == STATUS_NONE

    def test_midline_fragment_too_long_not_title(self) -> None:
        """相近反例：標題前的殘字超過 12 字 → 不是標題。"""
        sec = _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}", _MOPS, f"二、{_SP_T_PRIV}：無。", f"某某某某某某某某某某某某某有限公司 三、{_SP_T_OTH}：無。"])
        assert sec.items["other_supplement"].status == "not_found"

    def test_midline_without_numbering_not_title(self) -> None:
        """相近反例：標題前有殘字但沒有編號 → 不是標題。"""
        sec = _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}", _MOPS, f"二、{_SP_T_PRIV}：無。", f"有限公司 {_SP_T_OTH}：無。"])
        assert sec.items["other_supplement"].status == "not_found"


class TestSpecialIndexPageAndCandidates:
    _IDX = ["特別記載事項", f"一、{_SP_T_AFF}", f"二、{_SP_T_PRIV}", f"三、{_SP_T_OTH}", f"四、{_SP_T_36}", "106 年度年報 Annual Report 107"]

    def test_index_page_titles_not_adopted(self) -> None:
        """3443：章扉的子項目錄頁（≥2 種子項在後頁還有標題）不採用，取後頁的標題。"""
        real = _first3(None) + [f"四、{_SP_T_36}：無。"]
        sec = _sp(_page(10, self._IDX), _page(11, real))
        assert {k: v.page for k, v in sec.items.items()} == dict.fromkeys(_SP_KEYS, 11)

    def test_single_duplicate_title_keeps_index_page(self) -> None:
        """相近反例：後頁只重複 1 種標題 → 前頁不算目錄頁，沒有重複的最後一個子項（內文只有頁尾）仍取前頁。"""
        sec = _sp(_page(10, self._IDX), _page(11, [f"二、{_SP_T_PRIV}：無。"]))
        assert sec.items["material_events_36"].page == 10
        assert sec.items["private_placement"].page == 11

    def test_candidate_with_more_items_wins(self) -> None:
        """2801：無引導線的目錄頁也有章名，但只讀到 2 項；後頁的真章節讀到 4 項 → 採用後者。"""
        toc = _page(5, ["陸、特別記載事項", f"一、{_SP_T_AFF}", "本文。", f"二、{_SP_T_PRIV}：無。"])
        real = _page(20, ["陸、特別記載事項", *_first3(None), f"四、{_SP_T_36}：無。"])
        sec = _sp(toc, real)
        assert {v.page for v in sec.items.values()} == {20}

    def test_tie_keeps_earliest_candidate(self) -> None:
        """相近反例：項數相同 → 取最早的候選。"""
        a = _page(5, ["陸、特別記載事項", *_first3(None), f"四、{_SP_T_36}：無。"])
        b = _page(20, ["陸、特別記載事項", *_first3(None), f"四、{_SP_T_36}：無。"])
        assert {v.page for v in _sp(a, b).items.values()} == {5}


# ═══ 修正輪 1（sub_task 3 review 🟡1–🟡5）═══════════════════════════════════════


class TestContractPartyFragments:
    """當事人欄首行是名稱斷行殘片（中文尾綴、英文尾綴、括號開頭）→ 不是新契約起點。"""

    _BLANK = ["", "", "", "", ""]

    def test_paren_fragment_in_block_is_not_new_start(self) -> None:
        """2002 p194：「(原Teck…」以括號開頭、期間完整，是同一當事人的第二段期間 → 一列、parsed。"""
        rows = [
            ["採購", "EVR Operations Ltd.", "113.04.01~114.03.31", "", ""],
            ["", "(加拿大)", "", "原料煤", "無"],
            ["契約", "", "", "", ""],
            ["", "(原Teck Coal Limited)", "114.04.01~115.03.31", "", ""],
            self._BLANK,
        ]
        sec = _csec(_cstart(rows))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 1
        assert "EVR Operations Ltd." in "".join(sec.rows[0].parties)
        assert "114.04.01~115.03.31" in sec.rows[0].period

    def test_complete_names_in_block_still_multiple_contracts(self) -> None:
        """相近反例：當事人是完整名稱（非括號開頭）且期間完整 → 仍算新起點，分塊內 2 筆契約 → failed。"""
        rows = [
            ["採購", "甲公司", "113.04.01~114.03.31", "", ""],
            ["", "乙公司", "114.04.01~115.03.31", "供貨", "無"],
            self._BLANK,
        ]
        sec = _csec(_cstart(rows))
        assert sec.status == STATUS_FAILED and "多筆契約" in (sec.reason or "")

    def test_english_tail_with_nature_blank_is_continuation(self) -> None:
        """R2：性質空白、當事人「Ltd. (澳洲)」（英文尾綴斷行）、期間完整、內容有字 → 續行，不是新列。"""
        sec = _csec(_cstart([
            ["採購契約", "Hamersley Iron Pty.", "111.04.01~114.03.31", "鐵礦", "無"],
            ["", "Ltd. (澳洲)", "114.04.01~115.03.31", "鐵礦", "無"],
        ]))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 1
        assert "Ltd." in "".join(sec.rows[0].parties)

    def test_paren_party_with_full_period_is_uncertain(self) -> None:
        """審查 Task 3 修正輪 🟡2：合併儲存格形狀、期間完整、當事人以括號起頭（可能是「(原…」殘片，也可能是「（株）…」新當事人）
        → 不猜，該頁 failed、不產出猜測列。反例：括號起頭但期間不完整（半截）→ 明確片段，續行。"""
        sec = _csec(_cstart([
            ["採購契約", "EVR Operations Ltd.", "113.04.01~114.03.31", "原料煤", "無"],
            ["", "(原Teck Coal Limited)", "114.04.01~115.03.31", "原料煤", "無"],
        ]))
        assert sec.status == STATUS_FAILED and sec.rows == []
        sec2 = _csec(_cstart([
            ["採購契約", "EVR Operations Ltd.", "113.04.01~", "原料煤", "無"],
            ["", "(原Teck Coal Limited)", "114.03.31", "", "無"],
        ]))
        assert sec2.status == STATUS_PARSED and len(sec2.rows) == 1

    def test_complete_party_with_nature_blank_is_new_row(self) -> None:
        """相近反例：性質空白、當事人是完整名稱、期間完整、內容有字 → 新列（沿用性質）。"""
        sec = _csec(_cstart([
            ["採購契約", "甲公司", "111.1~112.1", "供貨", "無"],
            ["", "乙公司", "112.2~113.1", "供貨", "無"],
        ]))
        assert sec.status == STATUS_PARSED and len(sec.rows) == 2
        assert sec.rows[1].nature == "採購契約"

    def test_english_tail_in_merged_cell_shape_is_continuation(self) -> None:
        """Task 1 合併儲存格形狀（性質、內容皆空白）：當事人英文尾綴殘片＋完整期間 → 續行；完整名稱 → 新列。"""
        base = ["採購契約", "Hamersley Iron Pty.", "111.04.01~114.03.31", "鐵礦", "無"]
        frag = _csec(_cstart([base, ["", "Ltd. (澳洲)", "114.04.01~115.03.31", "", "無"]]))
        assert frag.status == STATUS_PARSED and len(frag.rows) == 1
        full = _csec(_cstart([base, ["", "乙公司", "114.04.01~115.03.31", "", "無"]]))
        assert full.status == STATUS_PARSED and len(full.rows) == 2


class TestCashflowCandidateOrder:
    def test_explanation_only_candidate_does_not_beat_later_table(self) -> None:
        """前一個候選只有說明文字、後一個候選有表格 → 取有表格的。"""
        expl = _page(10, ["三、現金流量", "(1)營業活動：淨現金流入，主係營業獲利。", "四、最近年度重大資本支出"])
        real = _page(20, _lines(), [_HDR + [_ROW]])
        sec = parse_cashflow(_doc(expl, real))
        assert sec.status == STATUS_PARSED and sec.actual is not None and sec.actual.page == 20

    def test_only_explanation_candidate_still_returned(self) -> None:
        """相近反例：沒有更好的候選 → 仍回傳說明候選（parsed、無表）。"""
        expl = _page(10, ["三、現金流量", "(1)營業活動：淨現金流入，主係營業獲利。", "四、最近年度重大資本支出"])
        sec = parse_cashflow(_doc(expl))
        assert sec.status == STATUS_PARSED and sec.actual is None


class TestInOutFlowFallbackNeedsArith:
    _HDR2 = [["期初現金餘額", "全年來自營業活動淨現金流入(出)量", "全年現金流入(出)量", "現金剩餘數額", "現金不足額之補救措施", None],
             [None, None, None, None, "投資計畫", "融資計畫"]]

    def test_net_change_column_not_adopted(self) -> None:
        """3702 型：該欄是含營業的淨變動（期初＋該欄＝期末）→ 採用後算術不成立 → outflow 留 None，arith_ok 為 None（不當 0、不當 False）。"""
        sec = _cf(row=["1,000", "500", "300", "1,300", "-", "-"], hdr=self._HDR2)
        assert sec.status == STATUS_PARSED
        assert sec.actual.outflow is None and sec.arith_ok is None
        assert sec.actual.opening_cash == 1000 and sec.actual.closing_cash == 1300

    def test_signed_outflow_adopted_when_arith_holds(self) -> None:
        """2885 型：採用後算術成立（1,000＋500＋(200)＝1,300）→ 採用為 outflow。"""
        sec = _cf(row=["1,000", "500", "(200)", "1,300", "-", "-"], hdr=self._HDR2)
        assert sec.actual.outflow == -200 and sec.arith_ok is True



    def test_alt_not_adopted_when_combined_flow_column_present(self) -> None:
        """審查 Task 3 修正輪 🟡1：表有「投資及籌資」合併欄時，驗算用不到 outflow → 「流入(出)量」欄不採用（即使算術平衡）。"""
        hdr = ["期初現金餘額", "全年來自營業活動淨現金流量", "全年因投資及籌資活動淨現金流量", "全年現金流入(出)量", "現金剩餘數額"]
        sec = parse_cashflow(_doc(_page(10, ["三、現金流量", "單位：新台幣仟元"], tables=[[hdr, ["1,000", "500", "(200)", "(999)", "1,300"]]])))
        assert sec.actual is not None and sec.actual.cfi_cff == -200 and sec.actual.outflow is None and sec.arith_ok is True

class TestSpecialTitleNarrowing:
    @staticmethod
    def _with(title: str) -> SpecialSection:
        return _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}：", _MOPS, f"二、{_SP_T_PRIV}：無。", title])

    def test_other_supplement_with_detail_wording_not_title(self) -> None:
        sec = self._with("三、其他必要補充資料詳見附註。")
        assert sec.items["other_supplement"].status == "not_found"

    def test_other_supplement_accounting_policy_not_title(self) -> None:
        sec = self._with("三、本公司對於其他必要補充之會計政策說明。")
        assert sec.items["other_supplement"].status == "not_found"

    def test_third_clause_not_36(self) -> None:
        sec = self._with("三、依證券交易法第36條第2項第3款規定辦理。")
        assert sec.items["material_events_36"].status == "not_found"

    @pytest.mark.parametrize("title", [
        "三、其他必要補充說明事項：無。",
        "三、其他必要補充事項：無。",
        "三、其他必要補充說明：無。",
    ])
    def test_other_supplement_title_forms_found(self, title: str) -> None:
        assert self._with(title).items["other_supplement"].status == STATUS_NONE

    def test_other_supplement_title_at_line_end_found(self) -> None:
        """2890 型：標題寫到「其他必要補充說明」列尾，下一列才是內文 → 仍是標題。"""
        sec = _spx(["陸、特別記載事項", f"一、{_SP_T_AFF}：", _MOPS, f"二、{_SP_T_PRIV}：無。", "三、其他必要補充說明", "本公司無其他補充事項。"])
        assert sec.items["other_supplement"].status != "not_found"


class TestArithOutflowHeaderSign:
    """表頭寫「流出量」的 cfi／cff／cfi_cff 欄：有公式依公式符號、沒有公式正數相減（括號／負號相加）；「淨現金流量」欄照舊相加。"""

    _SUB = [None, None, None, None, None, "投資計畫", "理財計畫"]

    @classmethod
    def _h(cls, cfi: str, cff: str) -> list:
        return [["年初現金餘額", "全年來自營業活動淨現金流入量", cfi, cff, "現金剩餘數額", "現金不足額之補救措施", None], cls._SUB]

    def test_3293_positive_outflow_columns_subtracted(self) -> None:
        sec = _cf(row=["1,000", "500", "200", "100", "1,200", "-", "-"],
                  hdr=self._h("全年因投資活動淨現金流出量", "全年因籌資活動淨現金流出量"))
        assert sec.arith_ok is True

    def test_parenthesised_outflow_columns_added(self) -> None:
        sec = _cf(row=["1,000", "500", "(200)", "(100)", "1,200", "-", "-"],
                  hdr=self._h("全年因投資活動淨現金流出量", "全年因籌資活動淨現金流出量"))
        assert sec.arith_ok is True

    def test_net_flow_header_positive_columns_still_added(self) -> None:
        """相近反例：表頭「淨現金流量」（無「出」字）的正數欄照舊相加。"""
        sec = _cf(row=["1,000", "500", "200", "100", "1,800", "-", "-"],
                  hdr=self._h("全年因投資活動淨現金流量", "全年因籌資活動淨現金流量"))
        assert sec.arith_ok is True
        wrong = _cf(row=["1,000", "500", "200", "100", "1,200", "-", "-"],
                    hdr=self._h("全年因投資活動淨現金流量", "全年因籌資活動淨現金流量"))
        assert wrong.arith_ok is False

    @staticmethod
    def _h3529(flow: str) -> list:
        return [["期初現金餘額(1)", "全年來自營業活動淨現金流入量(2)", flow, "匯率變動對現金之影響(4)",
                 "現金剩餘(不足)數額(1)+(2)-(3)+(4)", "現金不足額之補救措施", None],
                [None, None, None, None, None, "投資計畫", "理財計畫"]]

    def test_3529_formula_sign_applied_to_combined_outflow(self) -> None:
        """表頭公式 (1)+(2)-(3)+(4)：cfi_cff 流出量 200 依公式相減。"""
        sec = _cf(row=["1,000", "500", "200", "(10)", "1,290", "0", "0"],
                  hdr=self._h3529("全年來自投資及籌資活動淨現金流出量(3)"))
        assert sec.actual.cfi_cff == 200 and sec.arith_ok is True

    def test_formula_not_applied_to_net_flow_column(self) -> None:
        """相近反例：同樣有公式，但欄名是「淨現金流量(3)」（無「流出量」）→ 不套公式符號，照舊相加。"""
        sec = _cf(row=["1,000", "500", "200", "(10)", "1,690", "0", "0"],
                  hdr=self._h3529("全年來自投資及籌資活動淨現金流量(3)"))
        assert sec.arith_ok is True


# ═══════════════════════════════════════════════════════════════════════════════
# 口徑判定（item 2.1）。契約 row：
#   B1: 期初與年底都比對，兩個都 ≤2 仟元才 consolidated（半年報帳本 H1：cash_beginning 本期＝年底、上期＝期初；
#       全年帳本 FY：cash_beginning 本期＝期初、cash_ending 本期＝年底）
#   B2: 任一不符 → non_consolidated，basis_note 寫兩邊數字
#   B3: 帳本沒有期初 → 只比年底並在 basis_note 註明；缺值不可當 0
#   B4: 無帳本 → unknown（另：帳本沒有可比數字、單位無法換算、期間類型不支援 → unknown）
#   B5: 沒有表 A → 用表 B 的 opening_cash 比對年底（note 註明只比對年底）
#   B6: 帳本單位換算為仟元後比對；容差 2 仟元（含邊界）
#   B7: to_dict 輸出 basis／basis_note
# ═══════════════════════════════════════════════════════════════════════════════


def _srow(key: str, cur: float | None, prior: float | None) -> StatementRow:
    return StatementRow(statement="cf", section=None, label=key, key=key, note=None, current=cur, prior=prior,
                        current_pct=None, prior_pct=None, page=1, line_idx=0)


def _ledger(basis: str, rows: list[StatementRow], unit: str = "新台幣仟元") -> StatementLedger:
    return StatementLedger(unit=unit, period_current="c", period_prior="p", rows=rows, checks=[],
                           unmapped_labels=[], basis=basis)


def _h1(closing: float | None, opening: float | None, unit: str = "新台幣仟元") -> StatementLedger:
    """半年報帳本：cash_beginning 本期值＝年報年底、上期值＝年報期初。"""
    return _ledger("H1", [_srow("cash_beginning", closing, opening)], unit)


def _fy(opening: float | None, closing: float | None, unit: str = "新台幣仟元") -> StatementLedger:
    return _ledger("FY", [_srow("cash_beginning", opening, None), _srow("cash_ending", closing, None)], unit)


def _sec(opening: float | None = 1000, closing: float | None = 5000, forecast_opening: float | None = None,
         actual: bool = True) -> CashflowSection:
    return CashflowSection(
        status=STATUS_PARSED,
        actual=CashflowTable(opening_cash=opening, closing_cash=closing) if actual else None,
        forecast=CashflowTable(opening_cash=forecast_opening) if forecast_opening is not None else None)


class TestCashflowBasis:
    def test_h1_ledger_both_match_consolidated(self) -> None:
        basis, note, compared = cashflow_basis(_sec(1000, 5000), _h1(closing=5000, opening=1000))
        assert (basis, note, compared) == ("consolidated", None, ["opening", "closing"])

    def test_fy_ledger_both_match_consolidated(self) -> None:
        basis, note, compared = cashflow_basis(_sec(1000, 5000), _fy(opening=1000, closing=5000))
        assert (basis, note, compared) == ("consolidated", None, ["opening", "closing"])

    def test_opening_mismatch_is_non_consolidated_with_both_numbers(self) -> None:
        """年底剛好相等、期初不符（Q1：只比年底會誤判）→ non_consolidated，note 有兩邊數字。"""
        basis, note, compared = cashflow_basis(_sec(97737, 5000), _h1(closing=5000, opening=100442))
        assert basis == "non_consolidated" and compared == ["opening", "closing"]
        assert "97,737" in note and "100,442" in note

    def test_closing_mismatch_is_non_consolidated(self) -> None:
        basis, note, _ = cashflow_basis(_sec(1000, 5000), _fy(opening=1000, closing=9000))
        assert basis == "non_consolidated" and "5,000" in note and "9,000" in note

    @pytest.mark.parametrize("diff,expected", [(2, "consolidated"), (3, "non_consolidated")])
    def test_tolerance_two_thousand(self, diff: int, expected: str) -> None:
        assert cashflow_basis(_sec(1000, 5000), _fy(opening=1000, closing=5000 + diff))[0] == expected
        assert cashflow_basis(_sec(1000, 5000), _fy(opening=1000 - diff, closing=5000))[0] == expected

    def test_ledger_without_opening_compares_year_end_only(self) -> None:
        """B3：H1 帳本上期值缺 → 只比年底，note 註明；缺值不當 0（年報期初非 0 也不判不符）。"""
        basis, note, compared = cashflow_basis(_sec(1000, 5000), _h1(closing=5000, opening=None))
        assert basis == "consolidated" and compared == ["closing"] and "只比對年底" in note

    def test_ledger_without_opening_year_end_mismatch_still_non_consolidated(self) -> None:
        basis, note, compared = cashflow_basis(_sec(1000, 5000), _h1(closing=7000, opening=None))
        assert basis == "non_consolidated" and compared == ["closing"]

    def test_missing_ar_opening_compares_year_end_only(self) -> None:
        basis, note, compared = cashflow_basis(_sec(None, 5000), _fy(opening=1000, closing=5000))
        assert basis == "consolidated" and compared == ["closing"] and "只比對年底" in note

    def test_missing_year_end_not_treated_as_zero(self) -> None:
        """缺一欄反例：帳本年底缺、期初相符 → 只比期初（consolidated＋註明），不是把缺值當 0 判不符。"""
        basis, note, compared = cashflow_basis(_sec(1000, 5000), _fy(opening=1000, closing=None))
        assert basis == "consolidated" and compared == ["opening"] and "只比對期初" in note

    def test_no_ledger_unknown(self) -> None:
        basis, note, compared = cashflow_basis(_sec(), None)
        assert basis == "unknown" and note and compared == []

    def test_ledger_without_comparable_numbers_unknown(self) -> None:
        assert cashflow_basis(_sec(), _h1(closing=None, opening=None))[0] == "unknown"
        assert cashflow_basis(_sec(), _ledger("H1", []))[0] == "unknown"  # 帳本沒有 cash_beginning 列
        assert cashflow_basis(_sec(None, None), _fy(1000, 5000))[0] == "unknown"  # 年報沒有數字

    def test_unsupported_ledger_basis_or_unit_unknown(self) -> None:
        assert cashflow_basis(_sec(), _ledger("other", [_srow("cash_beginning", 5000, 1000)]))[0] == "unknown"
        assert cashflow_basis(_sec(), _h1(5000, 1000, unit="美元仟元"))[0] == "unknown"
        assert cashflow_basis(_sec(), _h1(5000, 1000, unit=""))[0] == "unknown"

    def test_forecast_opening_used_when_no_table_a(self) -> None:
        """B5：沒有表 A → 表 B 期初＝年底現金，只比年底。"""
        basis, note, compared = cashflow_basis(_sec(actual=False, forecast_opening=5000), _h1(5000, 1000))
        assert basis == "consolidated" and compared == ["closing"] and "只比對年底" in note
        basis, note, _ = cashflow_basis(_sec(actual=False, forecast_opening=134), _h1(664534, 1000))
        assert basis == "non_consolidated" and "134" in note and "664,534" in note

    def test_no_table_a_and_no_table_b_unknown(self) -> None:
        assert cashflow_basis(_sec(actual=False), _h1(5000, 1000))[0] == "unknown"

    def test_ledger_unit_converted_to_thousands(self) -> None:
        assert cashflow_basis(_sec(1000, 5000), _fy(1_000_000, 5_000_000, unit="新台幣元"))[0] == "consolidated"
        assert cashflow_basis(_sec(1000, 5000), _fy(1, 5, unit="新台幣百萬元"))[0] == "consolidated"
        assert cashflow_basis(_sec(1000, 5000), _fy(1000, 5000, unit="新台幣百萬元"))[0] == "non_consolidated"

    def test_apply_sets_fields_and_to_dict_outputs_them(self) -> None:
        sec = _sec(1000, 5000)
        assert sec.to_dict()["basis"] is None and sec.to_dict()["basis_note"] is None
        assert apply_cashflow_basis(sec, _fy(1000, 9000)) is sec
        d = sec.to_dict()
        assert d["basis"] == "non_consolidated" and "9,000" in d["basis_note"]
