"""test_doc_anchor_real.py — FS_HEADING_ANCHORS／GOVERNANCE_HEADING_ANCHORS 真實 fixture 錨定（item 1.4）。

期望起頁依據 Spec §2.2.2（財報）、§2.2.3（年報治理）。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import (
    FS_HEADING_ANCHORS,
    GOVERNANCE_HEADING_ANCHORS,
    AnchorError,
    find_heading_sections,
)

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"

# Spec §2.2.2 表「3653 起頁」
_FS_EXPECTED = {
    "fs_audit_kam": 5, "fs_bs": 10, "fs_is": 12, "fs_cf": 14,
    "fs_note_items": 29, "fs_note_inventory": 31, "fs_note_expense_nature": 46,
    "fs_note_related": 51, "fs_note_contingent": 55, "fs_note_disclosure": 64,
}
# Spec §2.2.3 表「2025 起頁」
_AR_EXPECTED = {
    "ar_governance": 8, "ar_pledge": 57, "ar_top10": 58,
    "ar_capital": 59, "ar_operations": 65,
}


def _load(name: str) -> pdf_doc.PdfDoc:
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


def _starts(doc, anchors, required):
    r = find_heading_sections(doc, anchors, required=required)
    return {k: (v.start if v else None) for k, v in r.items()}


def test_fs_start_pages():
    got = _starts(_load("fs_3653_pages.json"), FS_HEADING_ANCHORS, {"fs_bs", "fs_is"})
    assert got == _FS_EXPECTED


def test_fs_toc_pages_not_used_as_start():
    got = _starts(_load("fs_3653_pages.json"), FS_HEADING_ANCHORS, {"fs_bs", "fs_is"})
    assert got["fs_bs"] not in (2, 3)
    assert got["fs_note_inventory"] == 31 and got["fs_note_inventory"] != 22


def test_ar_governance_start_pages():
    got = _starts(_load("ar_3653_pages.json"), GOVERNANCE_HEADING_ANCHORS, set())
    assert got == _AR_EXPECTED


def test_fs_missing_statement_pages_raises():
    doc = _load("fs_3653_pages.json")
    doc.pages = [p for p in doc.pages if p.number not in (10, 11, 12)]
    with pytest.raises(AnchorError):
        find_heading_sections(doc, FS_HEADING_ANCHORS, required={"fs_bs", "fs_is"})


def test_ar_governance_toc_row_with_page_tail_not_hit():
    """[邊界] 年報 p3 目錄列「貳、公司治理報告-----4」以頁碼結尾 → 不命中。"""
    doc = _load("ar_3653_pages.json")
    toc = next(p for p in doc.pages if p.number == 3)
    assert any(unicodedata.normalize("NFKC", l).replace(" ", "").startswith("貳、公司治理報告") for l in toc.lines)
    r = find_heading_sections(
        pdf_doc.PdfDoc(path=doc.path, pages=[toc]),
        GOVERNANCE_HEADING_ANCHORS,
        required=set(),
    )
    assert r["ar_governance"] is None
