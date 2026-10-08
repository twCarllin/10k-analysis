"""test_tables_concentration.py — TablesBundle.to_dict()['concentration']（Spec §2.3.2）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import ANNUAL_REPORT_ANCHORS, find_sections
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import (
    CustomerEntry,
    CustomerTable,
    CustomerYear,
    TablesBundle,
    extract_tables,
)

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tw_equity"


def _bundle(sales: CustomerTable | None, purchase: CustomerTable | None = None) -> TablesBundle:
    return TablesBundle(
        fin_position=None, fin_performance=None,
        customers_sales=sales, customers_purchase=purchase,
        production_sales=None, expense_nature=None, inventory=None,
        cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=[], unit_notes={},
    )


def _table(pcts: list[float | None]) -> CustomerTable:
    entries = [CustomerEntry(i + 1, f"C{i + 1}", 100.0, p, None) for i, p in enumerate(pcts)]
    return CustomerTable("sales", "unknown", [CustomerYear("114年度", entries, None, None)])


def _conc(pcts: list[float | None]) -> dict:
    return _bundle(_table(pcts)).to_dict()["concentration"]["T8_sales"][0]


def test_real_3653_t8_sales_top1() -> None:
    doc = from_json(json.loads((_FIXTURE_DIR / "ar_3653_pages.json").read_text(encoding="utf-8")))
    anchors = find_sections(
        doc, ANNUAL_REPORT_ANCHORS,
        required={"ar_customers", "ar_fin_position", "ar_fin_performance"},
        order=list(ANNUAL_REPORT_ANCHORS),
    )
    d = extract_tables(doc, anchors, None, None, None, None, roc_year=114).to_dict()
    y114 = next(y for y in d["concentration"]["T8_sales"] if "114" in y["label"])
    assert y114["top1_pct"] == 22.82


def test_five_named_top3_and_total() -> None:
    c = _conc([30.1, 20.2, 10.3, 5.04, 1.11])
    assert c["label"] == "114年度"
    assert c["top1_pct"] == 30.1
    assert c["top3_pct"] == 60.6
    assert c["named_total_pct"] == 66.75


def test_two_named_top3_is_named_sum() -> None:
    c = _conc([12.34, 7.0])
    assert c["top3_pct"] == 19.34
    assert c["named_total_pct"] == 19.34


def test_partial_none_excluded_from_sums() -> None:
    c = _conc([10.0, None, 5.0, 2.0])
    assert c["top1_pct"] == 10.0
    assert c["top3_pct"] == 15.0
    assert c["named_total_pct"] == 17.0


@pytest.mark.parametrize("bundle, expected", [
    (_bundle(_table([None, None])), {"top1_pct": None, "top3_pct": None, "named_total_pct": None}),
    (_bundle(None), None),
])
def test_all_none_or_missing_table(bundle: TablesBundle, expected: dict | None) -> None:
    out = bundle.to_dict()["concentration"]
    assert out["T8_purchase"] == []
    if expected is None:
        assert out["T8_sales"] == []
    else:
        row = out["T8_sales"][0]
        assert {k: row[k] for k in expected} == expected
