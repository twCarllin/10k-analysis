"""test_statements.py — 合併財報三表逐列解析與科目對照（item 1.1、1.2）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from runtime.tw_equity.doc_anchor import PageRange
from runtime.tw_equity.pdf_doc import Page, PdfDoc
from runtime.tw_equity.statements import (
    BS_SECTION_HEADERS,
    CF_SECTION_HEADERS,
    IS_SECTION_HEADERS,
    StatementLedger,
    StatementRow,
    extract_statements,
    map_key,
    parse_statement_lines,
    statement_pages,
)


def _parse(lines: list[str], st: str, headers: frozenset[str], page: int = 10):
    triples = [(page, i + 10, t) for i, t in enumerate(lines)]  # idx≥5：避開頁首跳過規則
    return parse_statement_lines(triples, st, section_headers=headers)


def _doc(pages: dict[int, list[str]]) -> PdfDoc:
    return PdfDoc(
        path=Path("x.pdf"),
        pages=[Page(number=n, text="", tables=[], lines=ls) for n, ls in sorted(pages.items())],
    )


# ── 1.1 列解析 ────────────────────────────────────────────────────────────────


class TestParseStatementLines:
    def test_is_continuation_note_and_negative_pct(self) -> None:
        rows, _, _ = _parse(
            ["營業成本 六(五)(二十一)", "及七 ( 11,841,587 ) ( 58) ( 8,912,721) ( 62 )"],
            "is", IS_SECTION_HEADERS,
        )
        assert len(rows) == 1
        r = rows[0]
        assert r.label == "營業成本"
        assert r.note == "六(五)(二十一)及七"
        assert (r.current, r.current_pct, r.prior, r.prior_pct) == (-11841587, -58, -8912721, -62)

    def test_bs_label_continuation_prior_none(self) -> None:
        rows, _, _ = _parse(
            ["透過損益按公允價值衡量之金融資產－流 六(二)", "動 157,576 1 - -"],
            "bs", BS_SECTION_HEADERS,
        )
        assert len(rows) == 1
        r = rows[0]
        assert r.label == "透過損益按公允價值衡量之金融資產-流動"
        assert r.note == "六(二)"
        assert (r.current, r.current_pct, r.prior, r.prior_pct) == (157576, 1, None, None)
        assert r.key == "fvtpl_current"

    def test_section_header_no_row_and_sets_section(self) -> None:
        rows, _, _ = _parse(
            ["流動資產", "現金及約當現金 六(一) $ 9,134,067 33 $ 2,267,253 12"],
            "bs", BS_SECTION_HEADERS,
        )
        assert len(rows) == 1
        assert rows[0].section == "流動資產"
        assert rows[0].label == "現金及約當現金"
        assert (rows[0].current, rows[0].current_pct, rows[0].prior, rows[0].prior_pct) == (
            9134067, 33, 2267253, 12)

    def test_cf_continuation_note_two_tokens(self) -> None:
        rows, _, _ = _parse(
            ["折舊費用 六(七)(八)", "(二十一) 629,171 576,411"], "cf", CF_SECTION_HEADERS
        )
        assert len(rows) == 1
        r = rows[0]
        assert r.label == "折舊費用"
        assert r.note == "六(七)(八)(二十一)"
        assert (r.current, r.prior, r.current_pct) == (629171, 576411, None)

    def test_period_lines_three_styles_no_row(self) -> None:
        for line in ["114 年 12 月 31 日 113 年 12 月 31 日", "114 年 度 113 年 度",
                     "附註 1 1 4 年 度 1 1 3 年 度"]:
            rows, pc, pp = _parse([line], "bs", BS_SECTION_HEADERS)
            assert rows == []
            assert (pc, pp) == ("114", "113")

    def test_trailer_lines_no_row(self) -> None:
        rows, _, _ = _parse(
            ["(續 次 頁)", "~10~", "董事長：趙宗信 經理人：趙永昌 會計主管：潘虹萍",
             "後附合併財務報表附註為本合併財務報告之一部分，請併同參閱。"],
            "bs", BS_SECTION_HEADERS,
        )
        assert rows == []

    def test_amount_token_counts(self) -> None:
        bs, _, _ = _parse(["存貨 六(四) 100 5 200 6", "應付帳款 300 400"], "bs", BS_SECTION_HEADERS)
        assert (bs[0].current, bs[0].current_pct, bs[0].prior, bs[0].prior_pct) == (100, 5, 200, 6)
        assert (bs[1].current, bs[1].current_pct, bs[1].prior, bs[1].prior_pct) == (300, None, 400, None)
        cf, _, _ = _parse(["折舊費用 10", "攤銷費用 20 30"], "cf", CF_SECTION_HEADERS)
        assert (cf[0].current, cf[0].prior) == (10, None)
        assert (cf[1].current, cf[1].prior) == (20, 30)

    def test_column_header_line_skipped_next_row_intact(self) -> None:
        rows, _, _ = _parse(
            ["項目 附註 金額 % 金額 %",
             "營業收入 六(十八)及七 $ 20,275,577 100 $ 14,278,187 100"],
            "is", IS_SECTION_HEADERS,
        )
        assert len(rows) == 1
        assert rows[0].label == "營業收入"
        assert rows[0].note == "六(十八)及七"
        assert (rows[0].current, rows[0].prior) == (20275577, 14278187)

    def test_bare_numeral_note(self) -> None:
        rows, _, _ = _parse(["預付設備款 七 538,055 2 501,204 3"], "bs", BS_SECTION_HEADERS)
        assert len(rows) == 1
        assert rows[0].label == "預付設備款"
        assert rows[0].note == "七"
        assert (rows[0].current, rows[0].prior) == (538055, 501204)

    def test_memo_line_with_bare_note_dropped(self) -> None:
        rows, _, _ = _parse(
            ["重大之期後事項 十一", "負債及權益總計 $ 27,968,731 100 $ 18,461,872 100"],
            "bs", BS_SECTION_HEADERS,
        )
        assert len(rows) == 1
        assert rows[0].label == "負債及權益總計"
        assert rows[0].current == 27968731

    def test_bs_three_tokens(self) -> None:
        # 3-token 遇前導 `-`（`X - 100 5`）會錯位，為 Spec §2.1 第 5 點的已知歧義，
        # 真實資料以 4-token 佔位，不在此修。
        rows, _, _ = _parse(["存貨 100 5 200"], "bs", BS_SECTION_HEADERS)
        r = rows[0]
        assert (r.current, r.current_pct, r.prior, r.prior_pct) == (100, None, 200, None)

    def test_is_total_split_by_section(self) -> None:
        rows, _, _ = _parse(
            ["淨利歸屬於：", "合計 $ 5,310,342 27 $ 3,415,162 24",
             "綜合損益總額歸屬於：", "合計 $ 5,309,571 27 $ 3,746,552 26"],
            "is", IS_SECTION_HEADERS,
        )
        assert [r.key for r in rows] == ["net_income_attrib_total", "tci_attrib_total"]

    def test_bs_liability_header_sets_section(self) -> None:
        rows, _, _ = _parse(
            ["負債", "現金及約當現金 六(一) 100 5 200 6"], "bs", BS_SECTION_HEADERS
        )
        assert len(rows) == 1
        assert (rows[0].label, rows[0].section, rows[0].key) == ("現金及約當現金", "負債", "cash")

    def test_unmapped_label_key_none(self) -> None:
        rows, _, _ = _parse(["不存在的科目 1,000 2,000"], "bs", BS_SECTION_HEADERS)
        assert rows[0].key is None


class TestStatementPages:
    def test_none_range_empty(self) -> None:
        assert statement_pages(_doc({1: ["合併資產負債表"]}), None, "資產負債表") == []

    def test_stops_at_first_non_matching(self) -> None:
        doc = _doc({
            9: ["x", "y", "z"],
            10: ["公司", "合併資產 負債表", "單位"],
            11: ["公司", "合併資產負債表", "單位"],
            12: ["公司", "合併綜合損益表", "單位"],
            13: ["公司", "合併資產負債表", "單位"],
        })
        assert statement_pages(doc, PageRange(9, 13), "資產負債表") == [10, 11]


# ── 1.2 對照與入口 ────────────────────────────────────────────────────────────


class TestMapKey:
    def test_examples(self) -> None:
        assert map_key("bs", "現金及約當現金", None) == "cash"
        assert map_key("bs", "應收帳款淨額", None) == "accounts_receivable"
        assert map_key("is", "母公司業主", "淨利歸屬於:") == "net_income_parent"
        assert map_key("is", "母公司業主", "綜合損益總額歸屬於:") == "tci_parent"
        assert map_key("cf", "應收帳款", None) == "change_receivables"
        assert map_key("bs", "不存在的科目", None) is None


def _ledger_doc() -> PdfDoc:
    bs = ["公司名稱", "合併資產負債表", "單位：新台幣仟元", "114 年 12 月 31 日 113 年 12 月 31 日", "資產",
          "流動資產",
          "現金及約當現金 六(一) $ 9,134,067 33 $ 2,267,253 12",
          "不存在的科目 1 2 3 4",
          "不存在的科目 5 6 7 8",
          "資產總計 $ 27,968,731 100 $ 18,461,872 100"]
    return _doc({10: bs})


class TestExtractStatements:
    def test_none_inputs(self) -> None:
        assert extract_statements(None, None) is None
        assert extract_statements(_ledger_doc(), None) is None

    def test_no_statement_pages_returns_none(self) -> None:
        doc = _doc({10: ["a", "b", "c", "d"]})
        assert extract_statements(doc, {"fs_bs": PageRange(10, 10)}) is None

    def test_ledger_get_unmapped_and_json(self) -> None:
        led = extract_statements(_ledger_doc(), {"fs_bs": PageRange(10, 10)})
        assert isinstance(led, StatementLedger)
        assert led.unit == "新台幣仟元"
        assert (led.period_current, led.period_prior) == ("114", "113")
        assert led.get("total_assets") == (27968731, 18461872)
        assert led.get("nope") == (None, None)
        assert led.unmapped_labels == ["不存在的科目"]
        d = led.to_dict()
        json.dumps(d)
        assert d["row_counts"] == {"bs": 4, "is": 0, "cf": 0}
        assert all(isinstance(r, StatementRow) for r in led.rows)
