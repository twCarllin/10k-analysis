"""test_tables_cost.py — parse_cost_detail / parse_key_lines 行為契約測試（item 3.1）。

使用合成 fixture tests/fixtures/tw_equity/ps_pages_synthetic.json（單一 source）：
  - Page 1：T1 cogs 明細表 + 損益關鍵列文字
  - Page 2：T2 mfg 製造費用明細表
  - Page 3：T3 opex 多欄版面（推銷/管理/研發）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import pytest

from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import parse_cost_detail, parse_key_lines

_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "tw_equity" / "ps_pages_synthetic.json"


@pytest.fixture(scope="module")
def ps_doc():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    doc = from_json(data)
    assert doc is not None, "ps_pages_synthetic.json 格式不符"
    return doc


def _page(doc, number: int):
    for p in doc.pages:
        if p.number == number:
            return p
    raise ValueError(f"Page {number} not in fixture")


# ── T1 cogs 營業成本明細 ──────────────────────────────────────────────────────


class TestCostDetailCogs:
    def test_cogs_contains_expected_labels(self, ps_doc) -> None:
        """kind="cogs" → rows 含直接原料／直接人工／製造費用／營業成本"""
        page = _page(ps_doc, 1)
        result = parse_cost_detail(page.tables, kind="cogs")
        assert result is not None
        labels = [r.label for r in result.rows]
        assert "直接原料" in labels
        assert "直接人工" in labels
        assert "製造費用" in labels
        assert "營業成本" in labels

    def test_cogs_periods(self, ps_doc) -> None:
        """cogs 表期間標籤正確解析。"""
        page = _page(ps_doc, 1)
        result = parse_cost_detail(page.tables, kind="cogs")
        assert result is not None
        assert result.periods == ["114年度", "113年度"]

    def test_cogs_negative_value(self, ps_doc) -> None:
        """括號負數正確解析（在製品存貨變動）。"""
        page = _page(ps_doc, 1)
        result = parse_cost_detail(page.tables, kind="cogs")
        assert result is not None
        row = next((r for r in result.rows if r.label == "在製品存貨變動"), None)
        assert row is not None
        assert row.values[0] == pytest.approx(-200000.0, abs=1.0)

    def test_cogs_missing_table_returns_none(self) -> None:
        """[邊界] 表缺 → None"""
        assert parse_cost_detail([], kind="cogs") is None


# ── T2 mfg 製造費用明細 ───────────────────────────────────────────────────────


class TestCostDetailMfg:
    def test_mfg_contains_indirect_labor(self, ps_doc) -> None:
        """kind="mfg" → 間接項列（間接人工）存在。"""
        page = _page(ps_doc, 2)
        result = parse_cost_detail(page.tables, kind="mfg")
        assert result is not None
        labels = [r.label for r in result.rows]
        assert "間接人工" in labels

    def test_mfg_missing_table_returns_none(self) -> None:
        """[邊界] 表缺 → None"""
        assert parse_cost_detail([], kind="mfg") is None


# ── T3 opex 多欄版面（推銷/管理/研發）────────────────────────────────────────


class TestCostDetailOpex:
    def test_opex_periods_multicolumn(self, ps_doc) -> None:
        """[組合] kind="opex"＋推銷/管理/研發多欄 → periods 正確。"""
        page = _page(ps_doc, 3)
        result = parse_cost_detail(page.tables, kind="opex")
        assert result is not None
        assert result.periods == ["推銷費用", "管理費用", "研發費用"]

    def test_opex_values_filled(self, ps_doc) -> None:
        """[組合] kind="opex"＋推銷/管理/研發多欄 → 各欄值填入。"""
        page = _page(ps_doc, 3)
        result = parse_cost_detail(page.tables, kind="opex")
        assert result is not None
        salary = next((r for r in result.rows if r.label == "薪資支出"), None)
        assert salary is not None
        assert salary.values[0] == pytest.approx(500000.0, abs=1.0)   # 推銷費用
        assert salary.values[1] == pytest.approx(800000.0, abs=1.0)   # 管理費用
        assert salary.values[2] == pytest.approx(300000.0, abs=1.0)   # 研發費用

    def test_opex_missing_table_returns_none(self) -> None:
        """[邊界] 表缺 → None"""
        assert parse_cost_detail([], kind="opex") is None


# ── parse_key_lines ───────────────────────────────────────────────────────────


class TestParseKeyLines:
    def test_existing_label_returns_values(self, ps_doc) -> None:
        """parse_key_lines(text, ["營業收入"]) → {"營業收入": (current, prior)}"""
        page = _page(ps_doc, 1)
        result = parse_key_lines(page.text, ["營業收入"])
        assert "營業收入" in result
        current, prior = result["營業收入"]
        assert current == pytest.approx(20275577.0, abs=1.0)
        assert prior == pytest.approx(14278187.0, abs=1.0)

    def test_missing_label_returns_none_tuple(self, ps_doc) -> None:
        """[邊界] 標籤不存在 → 該鍵值 (None, None)"""
        page = _page(ps_doc, 1)
        result = parse_key_lines(page.text, ["不存在科目XYZ"])
        assert result["不存在科目XYZ"] == (None, None)

    def test_multiple_labels(self, ps_doc) -> None:
        """多個標籤同時查找，各自回傳正確值。"""
        page = _page(ps_doc, 1)
        result = parse_key_lines(page.text, ["營業收入", "本期淨利"])
        assert result["營業收入"][0] == pytest.approx(20275577.0, abs=1.0)
        assert result["本期淨利"][0] == pytest.approx(5310342.0, abs=1.0)

    def test_header_line_before_numbers_line(self) -> None:
        """標題行含標籤但無金額時，繼續取下一個含金額的命中行。"""
        text = "營業成本明細表\n單位：新台幣仟元\n營業成本 1,000,000 800,000\n"
        result = parse_key_lines(text, ["營業成本"])
        assert result["營業成本"] == (1000000.0, 800000.0)
