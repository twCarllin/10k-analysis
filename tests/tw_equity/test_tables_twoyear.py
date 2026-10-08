"""test_tables_twoyear.py — parse_two_year_table 行為契約測試（item 2.3）。

使用真實 fixture tests/fixtures/tw_equity/ar_3653_pages.json（3653 年報 p92/p93）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import pytest

from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import parse_two_year_table

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


# ── T7a 財務狀況表（p92）────────────────────────────────────────────────────


class TestT7aFinPosition:
    def test_total_assets_diff_pct(self, ar_doc) -> None:
        """3653 p92 T7a 資產總額列 → diff_pct=51.49"""
        page = _page(ar_doc, 92)
        result = parse_two_year_table(page.tables, page.text, roc_year=114)
        assert result is not None
        total_assets = next(
            (r for r in result.rows if "資產總額" in r.label), None
        )
        assert total_assets is not None
        assert total_assets.diff_pct == pytest.approx(51.49, abs=0.01)

    def test_header_labels(self, ar_doc) -> None:
        """欄頭含「114年度」「113年度」「差異」→ current_label/prior_label 正確設置。"""
        page = _page(ar_doc, 92)
        result = parse_two_year_table(page.tables, page.text, roc_year=114)
        assert result is not None
        assert result.current_label == "114年度"
        assert result.prior_label == "113年度"


# ── T7b 財務績效表（p93）────────────────────────────────────────────────────


class TestT7bFinPerformance:
    def test_operating_revenue_values(self, ar_doc) -> None:
        """p93 T7b 營業收入 current=20275577 / prior=14278187 / diff_pct=42.00"""
        page = _page(ar_doc, 93)
        result = parse_two_year_table(page.tables, page.text, roc_year=114)
        assert result is not None
        revenue = next(
            (r for r in result.rows if "營業收入" in r.label), None
        )
        assert revenue is not None
        assert revenue.current == pytest.approx(20275577.0, abs=1.0)
        assert revenue.prior == pytest.approx(14278187.0, abs=1.0)
        assert revenue.diff_pct == pytest.approx(42.00, abs=0.01)


# ── 邊界與組合 ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_missing_diff_column_returns_none(self) -> None:
        """欄頭缺「差異」→ None。"""
        tables = [
            [
                ["項目", "114年度", "113年度"],  # 沒有「差異」
                ["資產", "1,000", "800"],
            ]
        ]
        result = parse_two_year_table(tables, "單位：新台幣仟元", roc_year=114)
        assert result is None

    def test_missing_year_label_returns_none(self) -> None:
        """欄頭缺年度標籤 → None。"""
        tables = [
            [
                ["項目", "今年", "去年", "差異", None],  # 無「114年度」形式
                ["資產", "1,000", "800", "200", "25.00"],
            ]
        ]
        result = parse_two_year_table(tables, "單位：新台幣仟元", roc_year=114)
        assert result is None

    def test_wrong_roc_year_returns_none(self) -> None:
        """roc_year=2025 但表年度為 113/112（年度不符）→ None。"""
        tables = [
            [
                ["項目", "113年度", "112年度", "差異", None],
                [None, None, None, "金額", "%"],
                ["資產", "1,000", "800", "200", "25.00"],
            ]
        ]
        # roc_year=2025 → 尋找「2025年度」「2024年度」，表無此欄頭 → None
        result = parse_two_year_table(tables, "單位：新台幣仟元", roc_year=2025)
        assert result is None
