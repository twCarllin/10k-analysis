"""test_statements_real.py — 3653 真實合併財報 fixture（p10–15）的帳本值（item 1.4，Spec §5、§6）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.statements import extract_statements, statement_pages

_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "tw_equity" / "fs_3653_pages.json"


@pytest.fixture(scope="module")
def doc():
    return from_json(json.loads(_FIXTURE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def anchors(doc):
    return find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())


@pytest.fixture(scope="module")
def ledger(doc, anchors):
    led = extract_statements(doc, anchors)
    assert led is not None
    return led


def test_statement_pages(doc, anchors) -> None:
    assert statement_pages(doc, anchors["fs_bs"], "資產負債表") == [10, 11]
    assert statement_pages(doc, anchors["fs_is"], "綜合損益表") == [12]  # p13 權益變動表不入
    assert statement_pages(doc, anchors["fs_cf"], "現金流量表") == [14, 15]  # 附註頁不入


@pytest.mark.parametrize("key,expected", [
    ("total_assets", (27968731, 18461872)),
    ("net_income", (5310342, 3415162)),
    ("cfo", (4773519, 2890676)),
    ("capex", (-829582, -217200)),
    ("cash_ending", (9134067, 2267253)),
    ("cogs", (-11841587, -8912721)),
    ("fvtpl_current", (157576, None)),
])
def test_known_values(ledger, key, expected) -> None:
    assert ledger.get(key) == expected


def test_all_checks_pass_and_all_mapped(ledger) -> None:
    assert len(ledger.checks) == 22
    assert [c for c in ledger.checks if c.passed is not True] == []
    assert ledger.unmapped_labels == []


def test_row_counts_and_meta(ledger) -> None:
    counts = ledger.to_dict()["row_counts"]
    assert counts["bs"] >= 45 and counts["is"] >= 25 and counts["cf"] >= 45
    assert ledger.unit == "新台幣仟元"
    assert (ledger.period_current, ledger.period_prior) == ("114", "113")
