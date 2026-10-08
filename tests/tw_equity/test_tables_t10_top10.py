"""test_tables_t10_top10.py — parse_top_shareholders（item 2.5，Spec §2.3.4）。"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.tables import TopShareholders, parse_top_shareholders

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"


def _real() -> TopShareholders:
    doc = pdf_doc.from_json(json.loads((_FIX / "ar_3653_pages.json").read_text(encoding="utf-8")))
    page = next(p for p in doc.pages if p.number == 58)
    r = parse_top_shareholders(page.tables, page.text)
    assert isinstance(r, TopShareholders)
    return r


def test_first_corporate_row_and_representative_split():
    rows = _real().rows
    a, b = rows[0], rows[1]
    assert (a.name, a.is_representative, a.shares, a.pct) == ("信昌國際實業股份有限公司", False, 17460592, 11.90)
    assert (b.name, b.is_representative, b.shares, b.pct) == ("趙宗信", True, 2032002, 1.38)
    assert b.spouse_shares == 10057


def test_non_representative_row_count():
    assert sum(1 for r in _real().rows if not r.is_representative) == 10


def test_relation_notes_count():
    r = _real()
    assert len(r.relation_notes) == 3
    assert r.to_dict()["rows"][1]["name"] == "趙宗信"


def test_header_mismatch_returns_none():
    assert parse_top_shareholders([[["姓名", "股數"], ["甲", "1"]]], "") is None
