"""test_extract_tables.py — TablesBundle & extract_tables 行為契約測試（item 3.3）。

契約 row：
  R1: 全 fixture 齊 → 各欄非 None、missing_tables 空
  R2: fs=None 且 ps=None → 對應表全進 missing_tables、不 raise
  R3: 個體＋合併營業成本齊 → parent_cost_coverage 落 0–1
  R4: [邊界] 缺個體或合併營業成本 → parent_cost_coverage=None
  R5: [組合] fs 缺、ps 在 → 只 fs 系列表進 missing_tables
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import pytest

from runtime.tw_equity.pdf_doc import Page, PdfDoc, from_json
from runtime.tw_equity.doc_anchor import PageRange
from runtime.tw_equity.tables import TablesBundle, extract_tables

_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "tw_equity"
_FS_FIXTURE = _FIXTURE_DIR / "fs_pages_synthetic.json"
_PS_FIXTURE = _FIXTURE_DIR / "ps_pages_synthetic.json"

# ── 共用 fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def fs_doc() -> PdfDoc:
    data = json.loads(_FS_FIXTURE.read_text(encoding="utf-8"))
    doc = from_json(data)
    assert doc is not None
    return doc


@pytest.fixture(scope="module")
def ps_doc() -> PdfDoc:
    data = json.loads(_PS_FIXTURE.read_text(encoding="utf-8"))
    doc = from_json(data)
    assert doc is not None
    return doc


def _make_full_ar() -> PdfDoc:
    """合成 AR PdfDoc：含 T7a / T7b / T8_sales / T8_purchase / T6 及合併損益文字。"""

    # T7a 財務狀況（p10）
    t7a = Page(
        number=10,
        text="一、財務狀況\n單位：新台幣仟元；%",
        tables=[[
            ["項目", "114年度", "113年度", "差異", None],
            [None, None, None, "金額", "%"],
            ["資產總額", "10,000,000", "8,000,000", "2,000,000", "25.00"],
        ]],
    )

    # T7b 財務績效（p11）+ 合併損益文字
    t7b = Page(
        number=11,
        text=(
            "二、財務績效\n"
            "單位：新台幣仟元；%\n"
            "營業收入 20,000,000 15,000,000\n"
            "營業成本 12,000,000 9,000,000\n"
            "營業毛利 8,000,000 6,000,000\n"
            "營業費用 2,000,000 1,500,000\n"
            "營業利益 6,000,000 4,500,000\n"
            "本期淨利 5,000,000 3,500,000\n"
        ),
        tables=[[
            ["項目", "114年度", "113年度", "差異", None],
            [None, None, None, "金額", "%"],
            ["營業收入", "20,000,000", "15,000,000", "5,000,000", "33.33"],
            ["營業成本", "12,000,000", "9,000,000", "3,000,000", "33.33"],
        ]],
    )

    # T8 銷貨客戶 ＋ 進貨客戶（p12，兩張表同頁）
    t8 = Page(
        number=12,
        text="主要進銷貨客戶",
        tables=[
            # 銷貨：row 1 含「銷貨」→ find_table row_keywords=["銷貨"] 命中
            [
                ["年度", "113年度", None, None, None, "114年度", None, None, None],
                ["銷貨", "名稱", "金額", "比率(%)", "關係", "名稱", "金額", "比率(%)", "關係"],
                ["1", "客A", "1,000,000", "50.00", "無", "客A", "2,000,000", "60.00", "無"],
                ["", "其他", "1,000,000", "50.00", "－", "其他", "1,333,333", "40.00", "－"],
                ["", "總計", "2,000,000", "100.00", "－", "總計", "3,333,333", "100.00", "－"],
            ],
            # 進貨：row 1 含「進貨」→ find_table row_keywords=["進貨"] 命中
            [
                ["年度", "113年度", None, None, None, "114年度", None, None, None],
                ["進貨", "名稱", "金額", "比率(%)", "關係", "名稱", "金額", "比率(%)", "關係"],
                ["1", "供A", "500,000", "30.00", "無", "供A", "600,000", "30.00", "無"],
                ["", "其他", "1,166,667", "70.00", "－", "其他", "1,400,000", "70.00", "－"],
                ["", "總計", "1,666,667", "100.00", "－", "總計", "2,000,000", "100.00", "－"],
            ],
        ],
    )

    # T6 產銷量值（p13）
    t6 = Page(
        number=13,
        text="產銷量值\n單位：新台幣仟元",
        tables=[[
            ["品名", "生產量", "生產值", "銷售量", "銷售值"],
            ["產品X", "1,000", "5,000", "900", "4,500"],
        ]],
    )

    return PdfDoc(path=Path("synthetic_ar.pdf"), pages=[t7a, t7b, t8, t6])


# ── 錨點常數（合成 AR） ───────────────────────────────────────────────────────

_SYNTH_AR_ANCHORS = {
    "ar_fin_position": PageRange(10, 10),
    "ar_fin_performance": PageRange(11, 11),
    "ar_customers": PageRange(12, 12),
    "ar_production_sales": PageRange(13, 13),
}

_FS_ANCHORS = {
    "fs_note_expense_nature": PageRange(1, 1),
    "fs_note_inventory": PageRange(2, 2),
}

_PS_ANCHORS = {
    "ps_cogs_detail": PageRange(1, 1),
    "ps_mfg_overhead": PageRange(2, 2),
    "ps_opex_detail": PageRange(3, 3),
    "ps_is": PageRange(1, 1),
}


# ── R1: 全 fixture 齊 → 各欄非 None、missing_tables 空 ───────────────────────


class TestAllTablesPresent:
    """R1: 全 fixture 齊 → 各欄非 None、missing_tables 空。"""

    @pytest.fixture(scope="class")
    def bundle(self, fs_doc, ps_doc) -> TablesBundle:
        ar = _make_full_ar()
        return extract_tables(
            ar, _SYNTH_AR_ANCHORS,
            fs_doc, _FS_ANCHORS,
            ps_doc, _PS_ANCHORS,
            roc_year=114,
        )

    def test_missing_tables_only_1b1_names(self, bundle: TablesBundle) -> None:
        """合成 fixture 齊（無 lines、無 gov_anchors）時 missing_tables 只剩 T9、T10_pledge、T10_top10。"""
        assert sorted(bundle.missing_tables) == ["T10_pledge", "T10_top10", "T9"]

    def test_ar_tables_not_none(self, bundle: TablesBundle) -> None:
        """年報各表非 None。"""
        assert bundle.fin_position is not None
        assert bundle.fin_performance is not None
        assert bundle.customers_sales is not None
        assert bundle.customers_purchase is not None
        assert bundle.production_sales is not None

    def test_fs_tables_not_none(self, bundle: TablesBundle) -> None:
        """合併財報各表非 None。"""
        assert bundle.expense_nature is not None
        assert bundle.inventory is not None

    def test_ps_tables_not_none(self, bundle: TablesBundle) -> None:
        """個體財報各表非 None。"""
        assert bundle.cost_detail_cogs is not None
        assert bundle.cost_detail_mfg is not None
        assert bundle.cost_detail_opex is not None

    def test_key_lines_not_none(self, bundle: TablesBundle) -> None:
        """key_lines 有非 None 數值。"""
        cur, _ = bundle.consolidated_key_lines.get("營業成本", (None, None))
        assert cur is not None
        cur2, _ = bundle.parent_key_lines.get("營業成本", (None, None))
        assert cur2 is not None


# ── R2: fs=None 且 ps=None → 對應表進 missing_tables、不 raise ───────────────


class TestFsPsNone:
    """R2: fs=None 且 ps=None → 對應表全進 missing_tables、不 raise。"""

    @pytest.fixture(scope="class")
    def bundle(self) -> TablesBundle:
        ar = _make_full_ar()
        return extract_tables(
            ar, _SYNTH_AR_ANCHORS,
            None, None,
            None, None,
            roc_year=114,
        )

    def test_does_not_raise(self, bundle: TablesBundle) -> None:
        """fs=None 且 ps=None 時不 raise，回傳 TablesBundle。"""
        assert isinstance(bundle, TablesBundle)

    def test_fs_tables_in_missing(self, bundle: TablesBundle) -> None:
        """fs 缺時 T4、T5 進 missing_tables。"""
        assert "T4" in bundle.missing_tables
        assert "T5" in bundle.missing_tables

    def test_ps_tables_in_missing(self, bundle: TablesBundle) -> None:
        """ps 缺時 T1、T2、T3 進 missing_tables。"""
        assert "T1" in bundle.missing_tables
        assert "T2" in bundle.missing_tables
        assert "T3" in bundle.missing_tables

    def test_all_absent_missing_full_fixed_names(self) -> None:
        """ar 錨點全缺 + fs/ps 缺 → missing_tables 為完整 13 個固定名稱。"""
        empty_ar = PdfDoc(
            path=Path("empty_ar.pdf"),
            pages=[Page(number=1, text="年報無財務表", tables=[])],
        )
        bundle = extract_tables(empty_ar, {}, None, None, None, None, roc_year=114)
        assert set(bundle.missing_tables) == {
            "T1", "T2", "T3", "T4", "T5", "T6",
            "T7a", "T7b", "T8_sales", "T8_purchase",
            "T9", "T10_pledge", "T10_top10",
        }

    def test_ar_tables_not_in_missing(self, bundle: TablesBundle) -> None:
        """ar 正常時 T7a、T7b、T8_sales 不在 missing_tables（ar 表應正常解析）。"""
        assert "T7a" not in bundle.missing_tables
        assert "T7b" not in bundle.missing_tables
        assert "T8_sales" not in bundle.missing_tables


# ── R3 + R4: parent_cost_coverage ────────────────────────────────────────────


class TestParentCostCoverage:
    """R3: 個體＋合併營業成本齊 → coverage 落 0–1。
    R4: 缺個體或合併 → coverage=None。
    """

    def test_coverage_in_range_when_both_present(
        self, fs_doc: PdfDoc, ps_doc: PdfDoc
    ) -> None:
        """R3: 個體＋合併皆有 → 0 <= parent_cost_coverage <= 1。"""
        ar = _make_full_ar()
        bundle = extract_tables(
            ar, _SYNTH_AR_ANCHORS,
            fs_doc, _FS_ANCHORS,
            ps_doc, _PS_ANCHORS,
            roc_year=114,
        )
        assert bundle.parent_cost_coverage is not None
        # 個體損益文字營業成本 11,841,587（ps_pages_synthetic.json p1）
        # / 合併營業成本 12,000,000（_make_full_ar 損益文字）
        assert bundle.parent_cost_coverage == pytest.approx(11841587 / 12000000)

    def test_coverage_none_when_ps_missing(self) -> None:
        """R4: ps=None → 個體成本缺 → parent_cost_coverage=None。"""
        ar = _make_full_ar()
        bundle = extract_tables(
            ar, _SYNTH_AR_ANCHORS,
            None, None,
            None, None,
            roc_year=114,
        )
        assert bundle.parent_cost_coverage is None

    def test_coverage_none_when_cons_cogs_missing(self, ps_doc: PdfDoc) -> None:
        """R4: 合併營業成本抓不到（空錨點 + 無 T7b 表）→ parent_cost_coverage=None。"""
        # 建一個 AR：只有頁面文字，不含任何表格，且無 key lines
        empty_ar = PdfDoc(
            path=Path("empty_ar.pdf"),
            pages=[Page(number=1, text="年報無財務表", tables=[])],
        )
        empty_ar_anchors: dict = {}  # 所有錨點皆缺 → 回傳 ([], "")
        bundle = extract_tables(
            empty_ar, empty_ar_anchors,
            None, None,
            ps_doc, _PS_ANCHORS,
            roc_year=114,
        )
        # consolidated_key_lines["營業成本"] = (None, None)，fin_performance=None → None
        assert bundle.parent_cost_coverage is None


# ── R5: fs 缺、ps 在 → 只 fs 系列表進 missing_tables ────────────────────────


class TestFsMissingPsPresent:
    """R5: fs 缺、ps 在 → 只 T4/T5 進 missing_tables；T1/T2/T3 不在。"""

    @pytest.fixture(scope="class")
    def bundle(self, ps_doc: PdfDoc) -> TablesBundle:
        ar = _make_full_ar()
        return extract_tables(
            ar, _SYNTH_AR_ANCHORS,
            None, None,        # fs 缺
            ps_doc, _PS_ANCHORS,
            roc_year=114,
        )

    def test_fs_tables_in_missing(self, bundle: TablesBundle) -> None:
        """fs 缺時 T4、T5 進 missing_tables。"""
        assert "T4" in bundle.missing_tables
        assert "T5" in bundle.missing_tables

    def test_ps_tables_not_in_missing(self, bundle: TablesBundle) -> None:
        """ps 在時 T1、T2、T3 不在 missing_tables。"""
        assert "T1" not in bundle.missing_tables
        assert "T2" not in bundle.missing_tables
        assert "T3" not in bundle.missing_tables
