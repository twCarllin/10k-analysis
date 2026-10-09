"""左右並排資產負債表（fs-generalize item 1.4，Spec §2.1、§2.2；F9）。

契約 row：
  S1: 1303 → BS rows 含 key==cash（current 41946162）與 short_term_borrowings（current 20485100）
  S2: 1303 現金及約當現金 列 label 不含 短期借款
  S3: 1303 BS 勾稽 bs_assets_eq_liab_equity current／prior 皆 True
  S4: [邊界] 非並排頁（2059）BS 列序＝原頁序（不分流）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"


def _ledger(ticker: str):
    entry = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))[ticker]
    doc = pdf_doc.from_json(entry["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
    return extract_statements(doc, anchors)


@pytest.fixture(scope="module")
def led_1303():
    return _ledger("1303")


def _bs(led):
    return [r for r in led.rows if r.statement == "bs"]


def test_1303_left_and_right_halves_split(led_1303) -> None:
    by_key = {r.key: r for r in _bs(led_1303) if r.key}
    assert by_key["cash"].current == 41946162
    assert by_key["short_term_borrowings"].current == 20485100


def test_1303_cash_label_excludes_right_half(led_1303) -> None:
    cash = next(r for r in _bs(led_1303) if r.key == "cash")
    assert cash.label == "現金及約當現金"
    assert "短期借款" not in cash.label


def test_1303_bs_balance_check_passes(led_1303) -> None:
    chk = {(c.name, c.period): c.passed for c in led_1303.checks}
    assert chk[("bs_assets_eq_liab_equity", "current")] is True
    assert chk[("bs_assets_eq_liab_equity", "prior")] is True


def test_1303_note_fragments_do_not_leak_into_rows(led_1303) -> None:
    bs = _bs(led_1303)
    assert all("附註" not in r.label for r in bs)
    assert any(r.code == "2170" and r.current == 9657579 for r in bs)  # 殘片列後的右半科目仍完整


def test_non_side_by_side_page_keeps_page_order() -> None:
    bs = _bs(_ledger("2059"))
    assert [(r.page, r.line_idx) for r in bs] == sorted((r.page, r.line_idx) for r in bs)
