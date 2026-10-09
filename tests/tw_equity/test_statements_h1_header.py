"""半年報表頭偵測與期間欄（fs-generalize item 1.2，Spec §1.2、§2.1、§2.3、§2.4）。

契約 row：
  C1: 2059 → column_periods bs／is／cf 與 unit == 新台幣千元
  C2: 2303 → BS 三欄標籤、unit == 新臺幣千元
  C3: 3653 年度 → column_periods["bs"]==["114-12-31","113-12-31"]、period_current=="114"
  C4: [邊界] rows 不含 label 為 代碼／金額%／(接次頁)／至6月30日 開頭的列
  C5: §2.4 續頁：2059 CF 第 8 頁（`（承前頁）`）入選；頁首含權益變動表者不入選
"""

from __future__ import annotations

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
from runtime.tw_equity.statements import extract_statements, statement_pages  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_BS_3COL = ["115-06-30", "114-12-31", "114-06-30"]
_NOISE_PREFIXES = ("代碼", "金額%", "(接次頁)", "至6月30日")


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


def test_2059_column_periods_and_unit(led_2059) -> None:
    assert led_2059.column_periods["bs"] == _BS_3COL
    assert led_2059.column_periods["is"] == [
        "115-04-01~115-06-30", "114-04-01~114-06-30",
        "115-01-01~115-06-30", "114-01-01~114-06-30",
    ]
    assert led_2059.column_periods["cf"] == ["115-01-01~115-06-30", "114-01-01~114-06-30"]
    assert led_2059.unit == "新台幣千元"


def test_2303_bs_periods_and_unit(led_2303) -> None:
    assert led_2303.column_periods["bs"] == _BS_3COL
    assert led_2303.unit == "新臺幣千元"


def test_3653_annual_bs_periods_and_period_current() -> None:
    doc = pdf_doc.from_json(
        json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8"))
    )
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    led = extract_statements(doc, anchors)
    assert led.column_periods["bs"] == ["114-12-31", "113-12-31"]
    assert led.period_current == "114"


@pytest.mark.parametrize("ticker", ["2059", "2303"])
def test_rows_exclude_header_noise(ticker, led_2059, led_2303) -> None:
    led = {"2059": led_2059, "2303": led_2303}[ticker]
    assert led.rows
    assert [r.label for r in led.rows if r.label.startswith(_NOISE_PREFIXES)] == []


def test_continuation_page_selected_for_2059_cf() -> None:
    doc, anchors = _h1("2059")
    pages = statement_pages(doc, anchors["fs_cf"], "現金流量表")
    assert 8 in pages and 7 in pages


def _doc(heads: dict[int, list[str]]) -> pdf_doc.PdfDoc:
    return pdf_doc.PdfDoc(
        path=Path("x.pdf"),
        pages=[pdf_doc.Page(number=n, text="", tables=[], lines=ls) for n, ls in heads.items()],
    )


def test_continuation_stops_at_equity_statement_page() -> None:
    doc = _doc({
        1: ["公司", "合併現金流量表"],
        2: ["（承前頁）", "合併權益變動表"],
    })
    assert statement_pages(doc, PageRange(1, 2), "現金流量表") == [1]


# ── F5–F8 專屬（合成列） ──────────────────────────────────────────────────────

from runtime.tw_equity.statements import (  # noqa: E402
    CF_SECTION_HEADERS,
    detect_header,
    detect_unit,
    parse_statement_lines,
    select_cols,
)

_3_BS = ["115-06-30", "114-12-31", "114-06-30"]


@pytest.mark.parametrize("lines,expected", [
    (["1 1 5 年 6 月 3 0 日 1 1 4 年 1 2 月 3 1 日 1 1 4 年 6 月 3 0 日"], _3_BS),
    (["115.6.30 114.12.31 114.6.30"], _3_BS),
    (["一一五年六月三十日 一一四年十二月三十一日 一一四年六月三十日"], _3_BS),
    (
        ["115年4月1日 114年4月1日", "至6月30日 至6月30日"],
        ["115-04-01~115-06-30", "114-04-01~114-06-30"],
    ),
])
def test_f5_period_title_variants(lines, expected) -> None:
    assert detect_header(lines).periods == expected


@pytest.mark.parametrize("lines,expected", [
    (["單位：新台幣千元"], "新台幣千元"),
    (["單位：新臺幣仟元"], "新臺幣仟元"),
    (["(金額均以新臺幣千元為單位)"], "新臺幣千元"),
    (["(金額除每股盈餘外，均以新臺幣千元為單位)"], "新臺幣千元"),
    (["單位：新台幣千元（惟每股", "盈餘為新台幣元）"], "新台幣千元"),
])
def test_f6_unit_variants(lines, expected) -> None:
    assert detect_unit(lines) == expected


def test_f7_header_and_noise_rows_not_in_rows() -> None:
    lines = [
        "代碼 金額% 金額%", "金額%金額%", "(接次頁)", "(承前頁)", "項目", "至6月30日 至6月30日",
        "1100 現金 1,000 2,000",
    ]
    triples = [(1, i + 6, t) for i, t in enumerate(lines)]  # idx≥5：避開頁首跳過規則
    rows, _, _ = parse_statement_lines(triples, "bs", section_headers=CF_SECTION_HEADERS)
    assert [r.label for r in rows] == ["現金"]


def test_f8_colon_group_title_sets_section() -> None:
    rows, _, _ = parse_statement_lines(
        [(1, 6, "營業活動之現金流量:"), (1, 7, "折舊費用 100 200")],
        "cf", section_headers=CF_SECTION_HEADERS,
    )
    assert rows[0].section == "營業活動之現金流量"


# ── Task 3.2（Spec §8.3.3）：IS 期間標題變體 ───────────────────────────────────

_IS_4 = ["115-04-01~115-06-30", "114-04-01~114-06-30", "115-01-01~115-06-30", "114-01-01~114-06-30"]


def test_is_header_quarter_and_half_year_wording() -> None:
    hdr = detect_header([
        "聯發科技股份有限公司及子公司", "合併綜合損益表", "民國一一五年一月一日至六月三十日",
        "及民國一一四年一月一日至六月三十日", "(金額除每股盈餘外，均以新台幣仟元為單位)",
        "一一五年第二季 一一四年第二季 一一五年上半年度 一一四年上半年度",
        "代碼 項目 附註", "4000 營業收入 $152,182,611 100",
    ])
    assert hdr.periods == _IS_4


def test_is_header_start_dates_with_end_date_on_next_row() -> None:
    hdr = detect_header([
        "台塑石化股份有限公司及子公司", "合併綜合損益表",
        "民國一一五年及一一四年四月一日至六月三十日及民國一一五年及一一四年一月一日至六月三十日",
        "單位：新台幣千元",
        "一一五年四月一日至 一一四年四月一日至 一一五年一月一日至 一一四年一月一日至",
        "代 六月三十日 六月三十日 六月三十日 六月三十日",
        "4000 營業收入 $182,982,929 100",
    ])
    assert hdr.periods == _IS_4
    assert select_cols("is", hdr.periods) == (2, 3)
