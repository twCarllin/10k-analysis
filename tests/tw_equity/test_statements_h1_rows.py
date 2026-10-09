"""半年報列解析：代碼、附註、多欄分配、選欄（fs-generalize item 1.3，Spec §1.1、§1.3、§2.2；F1–F4）。

契約 row：
  R1: 2059 BS 現金及約當現金 → code==1100、columns 三欄、current／prior（上年度末）
  R2: 2059 IS 營業收入 → columns 四欄、current／prior＝年初至今兩欄
  R3: 2059 BS 跨列附註 → label 不含 附註、current==23435
  R4: 2303 現金及約當現金 note == 四及六.1
  R5: [邊界] 3653 年度 (label,current,prior) 與本 run 前快照相同、22 項勾稽全 True
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import (  # noqa: E402
    FS_HEADING_ANCHORS,
    PageRange,
    find_heading_sections,
)
from runtime.tw_equity.statements import (  # noqa: E402
    CF_SECTION_HEADERS,
    extract_statements,
    parse_statement_lines,
)

_FIX = ROOT / "tests/fixtures/tw_equity"
# 本 run 前 3653 年度財報每列 [label, current, prior] 的 sha256（json，ensure_ascii=False）
_3653_ROWS_SHA256 = "3fe72d858e0dd040e3e4cb83e3f6fc835d343675e91b2410c1e189f243ed70e7"


def _h1(ticker: str):
    entry = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))[ticker]
    doc = pdf_doc.from_json(entry["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
    return doc, anchors


@pytest.fixture(scope="module")
def led_2059():
    return extract_statements(*_h1("2059"))


@pytest.fixture(scope="module")
def led_2303():
    return extract_statements(*_h1("2303"))


def _row(led, st, label):
    return next(r for r in led.rows if r.statement == st and r.label == label)


def test_2059_bs_cash_code_columns_and_selected_cols(led_2059) -> None:
    r = _row(led_2059, "bs", "現金及約當現金")
    assert r.code == "1100"
    assert r.columns == [29384179, 24079620, 19705092]
    assert r.current == 29384179
    assert r.prior == 24079620  # 上年度末
    assert (led_2059.current_col["bs"], led_2059.prior_col["bs"]) == (0, 1)


def test_2059_is_revenue_four_columns_ytd_selected(led_2059) -> None:
    r = _row(led_2059, "is", "營業收入")
    assert r.columns == [10830041, 4228734, 16279766, 8182933]
    assert r.current == 16279766
    assert r.prior == 8182933
    assert r.current_pct == 100  # 有 % 欄：current_pct 取同欄的 %


def test_2059_cross_line_note_stripped(led_2059) -> None:
    r = _row(led_2059, "bs", "按攤銷後成本衡量之金融資產-流動")
    assert "附註" not in r.label
    assert r.current == 23435


def test_2303_note_column_variant(led_2303) -> None:
    r = _row(led_2303, "bs", "現金及約當現金")
    assert r.note == "四及六.1"
    assert r.code == "1100"


def test_3653_annual_rows_unchanged_and_checks_pass() -> None:
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))
    triples = [[r.label, r.current, r.prior] for r in led.rows]
    assert hashlib.sha256(json.dumps(triples, ensure_ascii=False).encode()).hexdigest() == _3653_ROWS_SHA256
    assert len(led.checks) == 22 and all(c.passed is True for c in led.checks)
    assert all(r.columns == [r.current, r.prior] for r in led.rows)
    assert led.parse_warnings == []


# ── F1–F4 專屬（合成列） ──────────────────────────────────────────────────────

_H3 = "115年6月30日 114年12月31日 114年6月30日"


def _parse(lines: list[str], st: str = "bs", warnings: list[str] | None = None, start: int = 0):
    triples = [(1, start + i, t) for i, t in enumerate(lines)]  # start≥5：避開頁首無金額列跳過規則
    return parse_statement_lines(triples, st, section_headers=CF_SECTION_HEADERS, warnings=warnings)


def test_f1_token_count_mismatch_warns_and_blanks_columns() -> None:
    warns: list[str] = []
    rows, _, _ = _parse([_H3, "x", "y", "現金 1 2 3 4 5", "存貨 1,000 2,000 3,000"], warnings=warns)
    bad = next(r for r in rows if r.label == "現金")
    assert bad.columns == [None, None, None] and bad.current is None and bad.prior is None
    assert warns == ["bs p1 現金: 5 tokens"]
    ok = next(r for r in rows if r.label == "存貨")
    assert ok.columns == [1000, 2000, 3000]  # n 個 token → 全為金額


def test_f2_code_stripped_plain_and_glued() -> None:
    rows, _, _ = _parse([
        "1100 現金及約當現金 1,000 2,000",
        "A21200利息收入 300 400",
        "AAAA營業活動之淨現金流入 5,000 6,000",
    ], "cf")
    assert [(r.code, r.label, r.current) for r in rows] == [
        ("1100", "現金及約當現金", 1000),
        ("A21200", "利息收入", 300),
        ("AAAA", "營業活動之淨現金流入", 5000),
    ]
    assert rows[1].key == "interest_income_adj" and rows[2].key == "cfo"


def test_f3_parenthesised_notes_removed_nested_and_cross_line() -> None:
    rows, _, _ = _parse([
        "1100 現金及約當現金（附註六(一)及(二十三)） 1,000 2,000",
        "1136 按攤銷後成本衡量之金融資產－流動（附註",
        "七） 23,435 4,490",
    ], start=10)
    assert [r.label for r in rows] == ["現金及約當現金", "按攤銷後成本衡量之金融資產-流動"]
    assert rows[0].key == "cash" and rows[1].current == 23435


def test_f4_note_column_variants() -> None:
    rows, _, _ = _parse([
        "1100 現金 四、六.21及七 1,000 2,000",
        "1110 存貨 四及六.1 3,000 4,000",
    ])
    assert [(r.label, r.note, r.current) for r in rows] == [
        ("現金", "四、六.21及七", 1000),
        ("存貨", "四及六.1", 3000),
    ]


# ── Task 3.2（Spec §8.3.1–2）：黏著附註、含 x 代碼 ─────────────────────────────


def test_glued_note_stripped_from_label_tail() -> None:
    rows, _, _ = _parse([
        "營業成本六(九)(三十五)及七 -4,359,913,943 -1,000,000",
        "營業收入六(二十三)、七及十四 89,158,843 70,000,000",
        "營業收入(四)/(六).23 1,234,567 1,000,000",
    ], "is")
    assert [r.label for r in rows] == ["營業成本", "營業收入", "營業收入"]
    assert all(r.note for r in rows)
    assert rows[0].key == "cogs" and rows[1].key == "revenue"


def test_glued_note_stripped_when_label_wrapped_to_amount_line() -> None:
    rows, _, _ = _parse(["營業成本六(九)(三十五)及七", "-4,359,913,943 -1,000,000"], "is", start=6)
    assert [r.label for r in rows] == ["營業成本"] and rows[0].note


def test_label_own_parentheses_not_stripped() -> None:
    rows, _, _ = _parse(["營業利益(損失) 1,234,567 1,000,000"], "is")
    assert rows[0].label == "營業利益(損失)" and not rows[0].note


def test_x_code_stripped_to_code() -> None:
    rows, _, _ = _parse(["1xxx 資產總計 $590,457,205 100 $416,461,476 100"], "bs")
    assert (rows[0].code, rows[0].label, rows[0].key) == ("1xxx", "資產總計", "total_assets")
