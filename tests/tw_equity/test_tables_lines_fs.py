"""test_tables_lines_fs.py — parse_expense_nature_lines／parse_inventory_note_lines（item 2.2，Spec §2.3.1）。"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.tables import (
    ExpenseNature,
    InventoryNote,
    parse_expense_nature_lines,
    line_amounts,
    parse_inventory_note_lines,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"


def _doc() -> pdf_doc.PdfDoc:
    return pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))


def _en() -> ExpenseNature:
    r = parse_expense_nature_lines(_doc().lines_of(46, 47))
    assert isinstance(r, ExpenseNature)
    return r


def _inv() -> InventoryNote:
    r = parse_inventory_note_lines(_doc().lines_of(31, 31))
    assert isinstance(r, InventoryNote)
    return r


def test_expense_nature_periods_and_salary_row():
    en = _en()
    assert en.periods == ["114年度", "113年度"]
    row = next(r for r in en.rows if r.label == "薪資費用")
    assert row.cost_of_sales == [2094512, 1920837]
    assert row.opex == [939419, 788584]
    assert row.total == [3033931, 2709421]


def test_expense_nature_depreciation_amortization_and_subtotal():
    rows = {r.label: r for r in _en().rows}
    assert rows["折舊費用"].total == [629171, 576411]
    assert rows["攤銷費用"].cost_of_sales == [None, None]
    assert rows["攤銷費用"].total == [18877, 20513]
    assert rows["員工福利費用合計"].total == [3541694, 3119813]


def test_inventory_rows_net_only():
    inv = _inv()
    rows = {r.label: r for r in inv.rows}
    assert rows["商品"].net == [49180, 21891]
    assert rows["製成品"].net == [1438027, 1072266]
    assert rows["在製品"].net == [1482200, 1286372]
    assert rows["原物料"].net == [682934, 681107]
    assert rows["合計"].net == [3652341, 3061636]
    assert all(r.cost == [None, None] and r.allowance == [None, None] for r in inv.rows)
    assert "應收票據" not in rows


def test_inventory_periods():
    assert _inv().periods == ["114年12月31日", "113年12月31日"]


def test_line_amounts_skips_date_unit_numbers():
    assert line_amounts("營業收入 114年度 1,234") == [1234.0]


def test_inventory_writedown():
    assert _inv().writedown == [19263, 12851]


def test_no_header_returns_none():
    lines = ["薪資費用 $ 1,000 $ 2,000 $ 3,000", "商 品 $ 49,180 $ 21,891"]
    assert parse_expense_nature_lines(lines) is None
    assert parse_inventory_note_lines(lines) is None
