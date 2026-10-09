"""TablesBundle.metrics 接線（run 2026-10-09-tw-equity-metrics-t1 item 2.1）。"""
import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import (FS_HEADING_ANCHORS, find_annual_report_sections,
                                          find_heading_sections)
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import extract_tables

_FIX = Path(__file__).parent.parent / "fixtures" / "tw_equity"


def _load(name):
    return from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ar():
    doc = _load("ar_3653_pages.json")
    return doc, find_annual_report_sections(doc, required=set())


def test_with_fs_metrics_present(ar):
    doc, ara = ar
    fs = _load("fs_3653_pages.json")
    b = extract_tables(doc, ara, fs, find_heading_sections(fs, FS_HEADING_ANCHORS, required=set()),
                       None, None, roc_year=114)
    assert b.metrics is not None
    d = b.to_dict()
    assert d["metrics"]["index"]["fcf"]["current"] == pytest.approx(3943937, abs=1)
    json.dumps(d)


def test_without_fs_metrics_none(ar):
    doc, ara = ar
    b = extract_tables(doc, ara, None, None, None, None, roc_year=114)
    assert b.metrics is None and b.statements is None
    assert b.to_dict()["metrics"] is None
    assert {"FS_BS", "FS_IS", "FS_CF"} <= set(b.missing_tables)
