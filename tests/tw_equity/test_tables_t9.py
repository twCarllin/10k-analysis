"""test_tables_t9.py — parse_guarantees_loans（item 2.3，Spec §2.3.3）。"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.tables import GuaranteesLoans, parse_guarantees_loans

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"


def _real() -> GuaranteesLoans:
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    r = parse_guarantees_loans(doc.lines_of(64, 67))
    assert isinstance(r, GuaranteesLoans)
    return r


def test_real_statuses_and_row_count():
    r = _real()
    assert r.loans_status == "none"
    assert r.guarantees_status == "table"
    assert len(r.guarantees) == 3
    assert r.loans_raw == []


def test_real_first_row_with_name_continuation():
    g = _real().guarantees[0]
    assert (g.no, g.guarantor, g.guaranteed, g.relation_code) == (0, "健策精密工業股份有限公司", "金利公司", "(4)")
    assert (g.single_limit, g.max_balance, g.ending_balance) == (4567472, 30000, 30000)
    assert g.drawn is None and g.collateral is None
    assert (g.pct_of_net_worth, g.max_limit) == (0.13, 9134944)
    assert (g.parent_to_sub, g.sub_to_parent, g.to_china) == ("Y", "N", "N")


def test_real_third_row_and_max_pct():
    r = _real()
    g = r.guarantees[2]
    assert (g.guarantor, g.guaranteed, g.pct_of_net_worth) == ("金利公司", "南通健策公司", 5.49)
    assert r.max_pct_of_net_worth == 5.49
    d = r.to_dict()
    assert d["guarantees"][2]["guaranteed"] == "南通健策公司" and d["max_pct_of_net_worth"] == 5.49


def test_synthetic_loans_table():
    row = "1 甲公司 乙公司 5,000 4.5%"
    r = parse_guarantees_loans(["1.資金貸與他人：請詳附表一。", "2.為他人背書保證：無。", "資金貸與他人", row])
    assert r.loans_status == "table"
    assert row in r.loans_raw
    assert r.guarantees_status == "none" and r.guarantees == []


def test_no_status_no_rows_returns_none():
    assert parse_guarantees_loans(["其他附註文字", "營業收入 1,000"]) is None
