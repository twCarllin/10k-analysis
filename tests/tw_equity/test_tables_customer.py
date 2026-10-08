"""test_tables_customer.py — parse_customer_table 行為契約測試（item 2.4）。

使用真實 fixture tests/fixtures/tw_equity/ar_3653_pages.json（3653 年報 p81/p82）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import pytest

from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import parse_customer_table

_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "tw_equity" / "ar_3653_pages.json"


@pytest.fixture(scope="module")
def ar_doc():
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    doc = from_json(data)
    assert doc is not None
    return doc


def _page(doc, number: int):
    for p in doc.pages:
        if p.number == number:
            return p
    raise ValueError(f"Page {number} not in fixture")


# ── T8 銷貨客戶（p82）────────────────────────────────────────────────────────


class TestSalesCustomer:
    def test_current_year_entry_a(self, ar_doc) -> None:
        """p82 kind="sales" A客戶 114年度 amount=4627203 / pct=22.82"""
        page = _page(ar_doc, 82)
        result = parse_customer_table(page.tables, kind="sales")
        assert result is not None
        # years[1] = 114年度（右欄）
        year_114 = result.years[1]
        entry_a = next((e for e in year_114.entries if "A客戶" in e.name), None)
        assert entry_a is not None
        assert entry_a.amount == pytest.approx(4627203.0, abs=1.0)
        assert entry_a.pct == pytest.approx(22.82, abs=0.01)

    def test_prior_year_entry_b_pct(self, ar_doc) -> None:
        """113年度 B客戶 pct=16.62"""
        page = _page(ar_doc, 82)
        result = parse_customer_table(page.tables, kind="sales")
        assert result is not None
        # years[0] = 113年度（左欄）
        year_113 = result.years[0]
        entry_b = next((e for e in year_113.entries if "B客戶" in e.name), None)
        assert entry_b is not None
        assert entry_b.pct == pytest.approx(16.62, abs=0.01)

    def test_others_pct_and_total(self, ar_doc) -> None:
        """others_pct / total 數值正確（113年度 others_pct=73.86；114年度 total=20275577）"""
        page = _page(ar_doc, 82)
        result = parse_customer_table(page.tables, kind="sales")
        assert result is not None
        year_113, year_114 = result.years[0], result.years[1]
        assert year_113.others_pct == pytest.approx(73.86, abs=0.01)
        assert year_114.others_pct == pytest.approx(63.62, abs=0.01)
        assert year_113.total == pytest.approx(14278187.0, abs=1.0)
        assert year_114.total == pytest.approx(20275577.0, abs=1.0)

    def test_two_years_structure(self, ar_doc) -> None:
        """[組合] kind="sales" + 兩年並排 → years 含兩年度各自 entries"""
        page = _page(ar_doc, 82)
        result = parse_customer_table(page.tables, kind="sales")
        assert result is not None
        assert len(result.years) == 2
        # 確認兩年各有 entries
        assert len(result.years[0].entries) >= 1
        assert len(result.years[1].entries) >= 1
        # 年度標籤含「年度」字樣
        assert "年度" in result.years[0].label
        assert "年度" in result.years[1].label


# ── T8 進貨供應商（p81）──────────────────────────────────────────────────────


class TestPurchaseCustomer:
    def test_purchase_table_found(self, ar_doc) -> None:
        """kind="purchase" → 正確找到進貨表。"""
        page = _page(ar_doc, 81)
        result = parse_customer_table(page.tables, kind="purchase")
        assert result is not None
        assert result.kind == "purchase"
        assert len(result.years) == 2


# ── 邊界測試 ─────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_matching_kind_returns_none(self) -> None:
        """[邊界] 表內無 row_keywords 對應段 → None。"""
        # 只有員工表（無「銷貨」、無「進貨」）
        tables = [
            [
                ["項目", "113年度", "114年度"],
                ["員工數", "3339", "3353"],
            ]
        ]
        result = parse_customer_table(tables, kind="sales")
        assert result is None

    def test_empty_tables_returns_none(self) -> None:
        """空表列表 → None。"""
        result = parse_customer_table([], kind="sales")
        assert result is None
