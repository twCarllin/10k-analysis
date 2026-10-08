"""test_tables_t10_pledge.py — parse_pledges（item 2.4，Spec §2.3.4）。"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.tables import PledgeTable, parse_pledges

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"


def test_real_p57_rows():
    doc = pdf_doc.from_json(json.loads((_FIX / "ar_3653_pages.json").read_text(encoding="utf-8")))
    page = next(p for p in doc.pages if p.number == 57)
    r = parse_pledges(page.tables, page.text)
    assert isinstance(r, PledgeTable)
    assert r.status == "rows"
    assert len(r.rows) == 1
    g = r.rows[0]
    assert (g.name, g.reason, g.date) == ("恆山股份有限公司", "質押", "114.08.11")
    assert g.counterparty == "兆豐國際商業銀行股份有限公司桃興分公司"
    assert (g.shares, g.holding_pct, g.pledge_pct) == (1000000, 11.36, 17.99)
    assert g.relation is None and g.amount is None
    assert r.max_pledge_pct == 17.99
    assert r.to_dict()["rows"][0]["pledge_pct"] == 17.99


def test_external_reference():
    r = parse_pledges([], "(三)股權質押資訊：\n請參閱公開資訊觀測站。")
    assert (r.status, r.rows) == ("external_reference", [])


def test_none():
    r = parse_pledges([], "(三)股權質押資訊：無股權質押之相對人為關係人之情形。")
    assert (r.status, r.rows) == ("none", [])


def test_unknown_when_no_table_no_keywords():
    r = parse_pledges([], "(三)股權質押資訊：\n詳如下列說明文字。")
    assert (r.status, r.rows) == ("unknown", [])


def test_external_reference_wins_over_none():
    r = parse_pledges([], "(三)股權質押資訊：無異動，請參閱公開資訊觀測站。")
    assert r.status == "external_reference"


def test_keywords_before_marker_are_ignored():
    r = parse_pledges([], "無異動。(三)股權質押資訊：詳如下")
    assert (r.status, r.rows) == ("unknown", [])
