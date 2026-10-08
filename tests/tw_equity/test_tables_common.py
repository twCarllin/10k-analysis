"""test_tables_common.py — parse_amount 與 find_table 行為契約測試（item 2.2）。"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity.tables import find_table, parse_amount


# ── parse_amount 契約測試 ─────────────────────────────────────────────────────


class TestParseAmount:
    def test_half_width_comma_positive(self) -> None:
        """parse_amount("1,359,995") → 1359995.0"""
        assert parse_amount("1,359,995") == 1359995.0

    def test_half_width_paren_negative(self) -> None:
        """parse_amount("(2,788,651)") → -2788651.0"""
        assert parse_amount("(2,788,651)") == -2788651.0

    def test_fullwidth_dash_returns_none(self) -> None:
        """parse_amount("－") → None（全形破折號）"""
        assert parse_amount("－") is None

    def test_empty_string_returns_none(self) -> None:
        """parse_amount("") → None"""
        assert parse_amount("") is None

    def test_none_returns_none(self) -> None:
        """parse_amount(None) → None"""
        assert parse_amount(None) is None

    def test_decimal_value(self) -> None:
        """parse_amount("9.52") → 9.52"""
        assert parse_amount("9.52") == 9.52

    def test_fullwidth_comma_positive(self) -> None:
        """全形逗號千分位：parse_amount("1，359，995") → 1359995.0"""
        assert parse_amount("1，359，995") == 1359995.0

    def test_fullwidth_paren_negative(self) -> None:
        """全形括號負數：parse_amount("（2，788，651）") → -2788651.0"""
        assert parse_amount("（2，788，651）") == -2788651.0


# ── find_table 契約測試 ───────────────────────────────────────────────────────


def _sample_tables() -> list[list[list[str | None]]]:
    """建立供 find_table 測試用的合成表格列表。"""
    table_a = [
        ["項目", "114年度", "113年度", "差異", None],
        [None, None, None, "金額", "%"],
        ["資產", "1,000", "800", "200", "25.00"],
        ["負債", "300", "250", "50", "20.00"],
    ]
    table_b = [
        ["客戶", "金額", "佔比"],
        ["客戶A", "500", "50%"],
    ]
    return [table_a, table_b]


class TestFindTable:
    def test_header_match_returns_correct_table(self) -> None:
        """header 全含 header_keywords → 回傳該表（非 None）。"""
        tables = _sample_tables()
        result = find_table(tables, header_keywords=["114年度", "113年度", "差異"])
        assert result is not None
        # 確認是 table_a（row 0 第一格 "項目"）
        assert result[0][0] == "項目"

    def test_header_and_row_keywords_match(self) -> None:
        """header 全含且 row 命中 row_keywords → 回傳表。"""
        tables = _sample_tables()
        result = find_table(
            tables,
            header_keywords=["114年度", "差異"],
            row_keywords=["資產"],
        )
        assert result is not None

    def test_row_keywords_no_match_returns_none(self) -> None:
        """header 全含但 row_keywords 無列命中 → None。"""
        tables = _sample_tables()
        result = find_table(
            tables,
            header_keywords=["114年度", "差異"],
            row_keywords=["不存在的關鍵字XYZ"],
        )
        assert result is None

    def test_no_matching_header_returns_none(self) -> None:
        """沒有表符合 header_keywords → None。"""
        tables = _sample_tables()
        result = find_table(tables, header_keywords=["完全不存在的欄位"])
        assert result is None

    def test_empty_tables_returns_none(self) -> None:
        """空表列表 → None。"""
        assert find_table([], header_keywords=["任何關鍵字"]) is None
