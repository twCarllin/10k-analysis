"""test_cross_year_gov.py — 客戶集中度／前十大股東／質押跨年比對（item 4.2，Spec §2.5）。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.cross_year import build_cross_year
from runtime.tw_equity.doc_anchor import (
    GOVERNANCE_HEADING_ANCHORS, find_annual_report_sections, find_heading_sections,
)
from runtime.tw_equity.tables import (
    CustomerEntry, CustomerTable, CustomerYear, PledgeTable, ShareholderRow,
    TablesBundle, TopShareholders, extract_tables,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"


def _bundle_from_fixture(name, roc):
    doc = pdf_doc.apply_ocr_policy(
        pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8"))), None)
    a = find_annual_report_sections(doc, required=set())
    g = find_heading_sections(doc, GOVERNANCE_HEADING_ANCHORS, required=set())
    return extract_tables(doc, a, None, None, None, None, roc_year=roc, gov_anchors=g)


def _synth(**kw):
    base = {f.name: None for f in dataclasses.fields(TablesBundle)}
    base.update(consolidated_key_lines={}, parent_key_lines={}, missing_tables=[], unit_notes={})
    base.update(kw)
    return TablesBundle(**base)


def _cust(label_pcts):
    years = [CustomerYear(l, [CustomerEntry(**{**dict.fromkeys(
        CustomerEntry.__dataclass_fields__), "pct": p, "name": "A", "rank": 1})], None, None)
        for l, p in label_pcts]
    return CustomerTable("sales", "仟元", years)


def _sh(name, pct, rep=False):
    return ShareholderRow(name, rep, None, pct, None, None, None, None)


def _run(cur, pri):
    return build_cross_year(cur, pri, current_roc=114, prior_roc=113)


def test_concentration_merge_current_wins_ascending():
    cur = _synth(customers_sales=_cust([("114年度", 20.0), ("113年度", 11.11)]))
    pri = _synth(customers_sales=_cust([("113年度", 99.0), ("112年度", 15.37)]))
    s = _run(cur, pri)["customer_concentration_series"]
    assert [e["label"] for e in s["T8_sales"]] == ["112年度", "113年度", "114年度"]
    assert {e["label"]: e["top1_pct"] for e in s["T8_sales"]}["113年度"] == 11.11
    assert s["T8_purchase"] == []


def test_shareholders_both_new_exited_and_rep_excluded():
    cur = _synth(top_shareholders=TopShareholders(
        [_sh("甲 公司", 10.456), _sh("乙", 5.0), _sh("某代表人", 1.0, rep=True)], []))
    pri = _synth(top_shareholders=TopShareholders(
        [_sh("甲公司", 8.1), _sh("丙", 3.0), _sh("某代表人", 2.0, rep=True)], []))
    got = {r["name"]: r for r in _run(cur, pri)["top_shareholders_change"]}
    assert set(got) == {"甲公司", "乙", "丙"}
    assert got["甲公司"]["status"] == "both" and got["甲公司"]["delta_pct"] == 2.36
    assert got["乙"] == {"name": "乙", "current_pct": 5.0, "prior_pct": None,
                        "delta_pct": None, "status": "new"}
    assert got["丙"] == {"name": "丙", "current_pct": None, "prior_pct": 3.0,
                        "delta_pct": None, "status": "exited"}


def test_pledge_real_2025_rows_vs_2024_none():
    cur = _bundle_from_fixture("ar_3653_pages.json", 114)
    pri = _bundle_from_fixture("ar2024_3653_pages.json", 113)
    out = _run(cur, pri)
    assert out["pledge_change"] == {"current_status": "rows", "prior_status": "none",
                                    "current_max_pct": 17.99, "prior_max_pct": None}
    json.dumps(out, ensure_ascii=False)


def test_pledge_none_object_unknown():
    cur = _synth(pledges=PledgeTable("rows", [], 12.5))
    out = _run(cur, _synth())["pledge_change"]
    assert out == {"current_status": "rows", "prior_status": "unknown",
                   "current_max_pct": 12.5, "prior_max_pct": None}
    out = _run(_synth(), cur)["pledge_change"]
    assert out["current_status"] == "unknown" and out["current_max_pct"] is None
