"""test_tables_lines_keylines.py — line_amounts／parse_key_lines_from_lines（item 2.1，Spec §2.3.1）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.tables import line_amounts, parse_key_lines_from_lines

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"
_LABELS = ["營業收入", "營業成本", "營業毛利", "營業費用", "營業利益", "本期淨利"]


def _p12_lines() -> list[str]:
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    return doc.lines_of(12, 12)


@pytest.mark.parametrize("line,expected", [
    ("( 11,841,587 )", [-11841587]),
    ("($ 2,277)", [-2277]),
    ("$ 4,567,472", [4567472]),
    ("0.13%", [0.13]),
    ("-", [None]),
    ("3,048", [3048]),
])
def test_line_amounts_tokens(line, expected):
    assert line_amounts(line) == expected


def test_p12_key_lines_real_fixture():
    got = parse_key_lines_from_lines(_p12_lines(), _LABELS)
    assert got == {
        "營業收入": (20275577, 14278187),
        "營業成本": (11841587, 8912721),
        "營業毛利": (8433990, 5365466),
        "營業費用": (1935857, 1566907),
        "營業利益": (6498133, 3798559),
        "本期淨利": (5310342, 3415162),
    }


def test_continuation_line_merge():
    lines = ["營業成本 六(五)(二十一)", "及七 ( 11,841,587 ) ( 58 ) ( 8,912,721 ) ( 62 )"]
    assert parse_key_lines_from_lines(lines, ["營業成本"])["營業成本"] == (11841587, 8912721)


def test_opex_without_amount_uses_total_row():
    lines = ["營業費用 六(二十一)及七", "推銷費用 ( 241,214 ) ( 1) ( 182,238) ( 1 )",
             "營業費用合計 ( 1,935,857 ) ( 10) ( 1,566,907) ( 11 )"]
    assert parse_key_lines_from_lines(lines, ["營業費用"])["營業費用"] == (1935857, 1566907)


def test_non_cost_labels_keep_sign_and_two_three_tokens():
    lines = ["所得稅費用 ( 1,296,613 ) ( 830,267 )", "營業利益 6,498,133 3,798,559 9"]
    got = parse_key_lines_from_lines(lines, ["所得稅費用", "營業利益"])
    assert got["所得稅費用"] == (-1296613, -830267)
    assert got["營業利益"] == (6498133, 3798559)


def test_missing_label_is_none_pair():
    assert parse_key_lines_from_lines(["營業收入 1,000 100 900 100"], ["本期淨利"]) == {"本期淨利": (None, None)}
