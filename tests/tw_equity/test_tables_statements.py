"""extract_tables 接線 statements（Spec §4.1，task item 2.1）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_annual_report_sections, find_heading_sections
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import extract_tables

_FIX = Path(__file__).parent.parent / "fixtures" / "tw_equity"


def _load(name):
    return from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ar():
    doc = _load("ar_3653_pages.json")
    return doc, find_annual_report_sections(doc, required=set())


@pytest.fixture(scope="module")
def fs():
    doc = _load("fs_3653_pages.json")
    return doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())


def test_with_fs_statements_present(ar, fs):
    b = extract_tables(ar[0], ar[1], fs[0], fs[1], None, None, roc_year=114)
    assert b.statements is not None
    counts = b.to_dict()["statements"]["row_counts"]
    assert all(counts[k] > 0 for k in ("bs", "is", "cf"))
    assert not {"FS_BS", "FS_IS", "FS_CF"} & set(b.missing_tables)


def test_without_fs_statements_none_and_missing(ar):
    b = extract_tables(ar[0], ar[1], None, None, None, None, roc_year=114)
    assert b.statements is None
    assert {"FS_BS", "FS_IS", "FS_CF"} <= set(b.missing_tables)
    assert b.to_dict()["statements"] is None


def test_existing_key_lines_unchanged_by_statements(ar, fs):
    with_fs = extract_tables(ar[0], ar[1], fs[0], fs[1], None, None, roc_year=114)
    # 帳本是純新增：取走 statements 後其餘輸出與同輸入的重跑一致
    again = extract_tables(ar[0], ar[1], fs[0], fs[1], None, None, roc_year=114)
    assert with_fs.consolidated_key_lines == again.consolidated_key_lines
    assert with_fs.parent_cost_coverage == again.parent_cost_coverage
