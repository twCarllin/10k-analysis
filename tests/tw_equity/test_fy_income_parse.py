"""FY 損益頁文字列解析與科目對照（Spec 2026-10-09-tw-equity-period-model §2.3／§2.4）。

fixture：tests/fixtures/tw_equity/fy_income_lines.json（依據 pdf_doc.py:26 Page.lines，
各區塊來源 PDF 與頁碼見 JSON 內 source 欄；producer＝make_fy_income_fixture.py）。
合成列（%成對、跨列）為內嵌字串，不代表真實頁。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.fy_income import map_fy_label, parse_page_rows

_FIX = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity" / "fy_income_lines.json")
    .read_text(encoding="utf-8")
)


def _by_key(rows):
    return {r["key"]: r for r in rows}


def test_3653_year_columns_not_percent():
    rows = _by_key(parse_page_rows(_FIX["3653"]["lines"], 114))
    assert (rows["revenue"]["current"], rows["revenue"]["prior"]) == (20275577, 14278187)
    assert rows["net_income"]["current"] == 5310342


def test_percent_pairs_take_amount_only():
    # 合成：表頭兩個年度標記之間出現 %（每年度佔 2 token）
    lines = [
        "項目 114 年度 % 113 年度 %",
        "營業收入 20,275,577 100 14,278,187 100",
        "營業成本 11,841,587 58 8,912,721 62",
        "營業毛利 8,433,990 42 5,365,466 38",
    ]
    rows = _by_key(parse_page_rows(lines, 114))
    assert (rows["revenue"]["current"], rows["revenue"]["prior"]) == (20275577, 14278187)
    assert (rows["gross_profit"]["current"], rows["gross_profit"]["prior"]) == (8433990, 5365466)


def test_2301_prior_year_first():
    rows = _by_key(parse_page_rows(_FIX["2301"]["lines"], 114))
    assert (rows["revenue"]["current"], rows["revenue"]["prior"]) == (166084859, 137133894)
    assert rows["operating_income"]["current"] == 16737802


def test_2308_dollar_and_notes_ignored():
    rows = _by_key(parse_page_rows(_FIX["2308"]["lines"], 114))
    assert (rows["revenue"]["current"], rows["revenue"]["prior"]) == (554885168, 421147557)
    assert rows["gross_profit_net"]["current"] == 190156558
    lines = [
        "項目 114 年度 113 年度",
        "營業收入淨額 $554,885,168 $421,147,557 $133,737,611 32 (註1)",
        "營業成本 364,728,610 284,567,383 80,161,227 28 註2",
    ]
    r2 = _by_key(parse_page_rows(lines, 114))
    assert (r2["revenue"]["current"], r2["revenue"]["prior"]) == (554885168, 421147557)
    assert r2["cogs"]["current"] == 364728610


def test_4958_side_by_side_only_is_segment():
    rows = parse_page_rows(_FIX["4958"]["lines"], 114)
    by = _by_key(rows)
    assert (by["revenue"]["current"], by["revenue"]["prior"]) == (182521620, 171663845)
    assert all(r["key"] is not None for r in rows)
    assert not any("流動資產" in r["label"] or "資產總額" in r["label"] for r in rows)


def test_cross_line_label_gives_warning_no_row():
    lines = [
        "項目 114 年度 113 年度",
        "營業收入 1,000 900",
        "營業成本",
        "600 500",
        "營業毛利 400 400",
    ]
    warnings: list[str] = []
    rows = _by_key(parse_page_rows(lines, 114, warnings))
    assert "cogs" not in rows
    assert "revenue" in rows and "gross_profit" in rows
    assert len(warnings) == 1


@pytest.mark.parametrize(
    "label,key",
    [
        ("營業收入淨額", "revenue"),
        ("合併營業收入淨額", "revenue"),
        ("減:銷貨退回及折讓", None),
        ("營業收入總額", "revenue"),
        ("營業損失", "operating_income"),
        ("本期稅後淨利", "net_income"),
        ("營業費用", "total_opex"),
        ("營業外收入(支出)", "nonoperating_total"),
        ("營業毛利淨額", "gross_profit_net"),
        ("營業毛利", "gross_profit"),
        ("流動資產", None),
    ],
)
def test_map_fy_label(label, key):
    assert map_fy_label(label) == key
