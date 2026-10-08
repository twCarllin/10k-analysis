"""test_tables_fs.py — parse_expense_nature / parse_inventory_note / parse_production_sales
行為契約測試（item 3.2）。

使用合成 fixture tests/fixtures/tw_equity/fs_pages_synthetic.json（單一 source）：
  - Page 1：T4 費用性質附註表
  - Page 2：T5 存貨附註表（含跌價損失列）
  - Page 3：T6 產銷量值表
  - Page 4：T5 存貨附註表（無跌價損失列，邊界情境）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import pytest

from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import (
    parse_expense_nature,
    parse_inventory_note,
    parse_production_sales,
)

_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "tw_equity" / "fs_pages_synthetic.json"


@pytest.fixture(scope="module")
def fs_doc():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    doc = from_json(data)
    assert doc is not None, "fs_pages_synthetic.json 格式不符"
    return doc


def _page(doc, number: int):
    for p in doc.pages:
        if p.number == number:
            return p
    raise ValueError(f"Page {number} not in fixture")


# ── T4 費用性質 ────────────────────────────────────────────────────────────────


class TestExpenseNature:
    def test_has_expected_rows(self, fs_doc) -> None:
        """T4 → 員工福利/折舊/攤銷列存在"""
        page = _page(fs_doc, 1)
        result = parse_expense_nature(page.tables)
        assert result is not None
        labels = [r.label for r in result.rows]
        assert "員工福利費用" in labels
        assert "折舊費用" in labels
        assert "攤銷費用" in labels

    def test_cost_of_sales_opex_total_filled(self, fs_doc) -> None:
        """T4 員工福利費用列 cost_of_sales/opex/total 正確解析"""
        page = _page(fs_doc, 1)
        result = parse_expense_nature(page.tables)
        assert result is not None
        row = next(r for r in result.rows if r.label == "員工福利費用")
        # period 0 (114年度): cost_of_sales=2,000,000, opex=500,000, total=2,500,000
        assert row.cost_of_sales[0] == pytest.approx(2_000_000.0, abs=1.0)
        assert row.opex[0] == pytest.approx(500_000.0, abs=1.0)
        assert row.total[0] == pytest.approx(2_500_000.0, abs=1.0)

    def test_missing_returns_none(self) -> None:
        """[邊界] 表缺 → None"""
        assert parse_expense_nature([]) is None


# ── T5 存貨附註 ────────────────────────────────────────────────────────────────


class TestInventoryNote:
    def test_has_expected_labels(self, fs_doc) -> None:
        """T5 → 原料/在製品/製成品/合計列存在"""
        page = _page(fs_doc, 2)
        result = parse_inventory_note(page.tables)
        assert result is not None
        labels = [r.label for r in result.rows]
        assert "原料" in labels
        assert "在製品" in labels
        assert "製成品" in labels
        assert "合計" in labels

    def test_cost_allowance_net_filled(self, fs_doc) -> None:
        """T5 原料列 cost/allowance/net 正確解析"""
        page = _page(fs_doc, 2)
        result = parse_inventory_note(page.tables)
        assert result is not None
        row = next(r for r in result.rows if r.label == "原料")
        # 114年度: cost=1,000,000, allowance=(50,000)→-50,000, net=950,000
        assert row.cost[0] == pytest.approx(1_000_000.0, abs=1.0)
        assert row.allowance[0] == pytest.approx(-50_000.0, abs=1.0)
        assert row.net[0] == pytest.approx(950_000.0, abs=1.0)

    def test_writedown_filled(self, fs_doc) -> None:
        """[組合] T5 有跌價損失列 → writedown 填值"""
        page = _page(fs_doc, 2)
        result = parse_inventory_note(page.tables)
        assert result is not None
        assert result.writedown is not None
        assert result.writedown[0] == pytest.approx(80_000.0, abs=1.0)   # 114年度
        assert result.writedown[1] == pytest.approx(50_000.0, abs=1.0)   # 113年度

    def test_no_writedown_returns_none(self, fs_doc) -> None:
        """[邊界] T5 無跌價損失列 → writedown=None"""
        page = _page(fs_doc, 4)
        result = parse_inventory_note(page.tables)
        assert result is not None
        assert result.writedown is None

    def test_missing_returns_none(self) -> None:
        """[邊界] 表缺 → None"""
        assert parse_inventory_note([]) is None


# ── T6 產銷量值 ────────────────────────────────────────────────────────────────


class TestProductionSales:
    def test_has_rows_with_implied_values(self, fs_doc) -> None:
        """T6 有表 → rows 含 implied_unit_cost／implied_asp"""
        page = _page(fs_doc, 3)
        result = parse_production_sales(page.tables, page.text)
        assert result is not None
        assert len(result.rows) > 0
        row = next(r for r in result.rows if r.product == "產品A")
        # implied_unit_cost = 5,000,000 / 100,000 = 50.0
        assert row.implied_unit_cost == pytest.approx(50.0, abs=0.01)
        # implied_asp = 4,500,000 / 90,000 = 50.0
        assert row.implied_asp == pytest.approx(50.0, abs=0.01)

    def test_missing_returns_none(self) -> None:
        """[邊界] T6 錨不到 → None"""
        assert parse_production_sales([]) is None
        tables_no_t6 = [[["品名", "金額"], ["產品A", "100,000"]]]
        assert parse_production_sales(tables_no_t6) is None
