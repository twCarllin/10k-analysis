"""帳本期間模型（period-model item 1.1，Spec §1.1）。

契約 row：
  P1: fs_h1_pages.json → basis=="H1"、days 181/181、bs_prior_same=="114-06-30"、bs_prior_fy_end=="114-12-31"
  P2: fs_3653_pages.json → basis=="FY"、days current==365、bs_prior_same==bs_prior_fy_end=="113-12-31"
  P3: 前 5 頁含「核閱報告」→ reviewed；含「查核報告」→ audited；皆無 → None
  P4: [邊界] 合成 IS 期間 113-01-01~113-12-31 → days 366
  P5: IS 無期間標籤改用 CF 判 basis
  P6: 期間全解析不到 → basis=="other"、days 兩值 None、periods 5 鍵皆在且 None
  P7: to_dict() 含 4 新鍵，既有鍵仍在
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, PageRange, find_heading_sections  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_KEYS = {"flow_current", "flow_prior", "bs_current", "bs_prior_same", "bs_prior_fy_end"}


def _h1(ticker: str):
    entry = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))[ticker]
    doc = pdf_doc.from_json(entry["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
    return doc, anchors


def _fy():
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    return doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())


def _synthetic(page_lines: dict[int, list[str]], texts: dict[int, str] | None = None) -> pdf_doc.PdfDoc:
    texts = texts or {}
    return pdf_doc.PdfDoc(
        path=Path("x.pdf"),
        pages=[pdf_doc.Page(number=n, text=texts.get(n, ""), tables=[], lines=ls)
               for n, ls in sorted(page_lines.items())],
    )


_BS_LINES = ["公司", "合併資產負債表", "單位：新台幣仟元", "114 年 12 月 31 日 113 年 12 月 31 日", "資產",
             "流動資產", "現金及約當現金 六(一) $ 9,134,067 33 $ 2,267,253 12"]
_IS_LINES = ["公司", "合併綜合損益表", "單位：新台幣仟元", "{hdr}", "營業收入 六(一) $ 100 100 $ 90 100"]
_CF_LINES = ["公司", "合併現金流量表", "單位：新台幣仟元", "{hdr}", "折舊費用 六(七) 10 20"]


def test_h1_period_model() -> None:
    led = extract_statements(*_h1("2059"))
    assert led.basis == "H1"
    assert led.days == {"current": 181, "prior": 181}
    assert set(led.periods) == _KEYS
    assert led.periods["bs_prior_same"] == "114-06-30"
    assert led.periods["bs_prior_fy_end"] == "114-12-31"


def test_fy_period_model() -> None:
    led = extract_statements(*_fy())
    assert led.basis == "FY"
    assert led.days["current"] == 365
    assert led.periods["bs_prior_same"] == led.periods["bs_prior_fy_end"] == "113-12-31"


def test_assurance_audited_from_real_fy_fixture() -> None:
    assert extract_statements(*_fy()).assurance == "audited"


def test_assurance_reviewed_audited_and_none_synthetic() -> None:
    anchors = {"fs_bs": PageRange(10, 10)}
    bs = {10: list(_BS_LINES)}
    reviewed = extract_statements(_synthetic({**bs, 1: ["x"]}, {1: "會計師核閱報告"}), anchors)
    audited = extract_statements(_synthetic({**bs, 1: ["x"]}, {1: "會計師查核報告"}), anchors)
    none = extract_statements(_synthetic(bs), anchors)
    assert reviewed.assurance == "reviewed"
    assert audited.assurance == "audited"
    assert none.assurance is None


def test_assurance_first_occurrence_wins_and_beyond_page5_ignored() -> None:
    anchors = {"fs_bs": PageRange(10, 10)}
    both = _synthetic({10: list(_BS_LINES), 1: ["x"]}, {1: "查核報告 ... 核閱報告"})
    assert extract_statements(both, anchors).assurance == "audited"
    pages = {n: ["x"] for n in range(1, 7)}
    late = _synthetic({**pages, 10: list(_BS_LINES)}, {6: "核閱報告"})
    assert extract_statements(late, anchors).assurance is None


def test_leap_year_days_366() -> None:
    is_lines = [l.replace("{hdr}", "113 年 度 112 年 度") for l in _IS_LINES]
    doc = _synthetic({10: list(_BS_LINES), 11: is_lines})
    led = extract_statements(doc, {"fs_bs": PageRange(10, 10), "fs_is": PageRange(11, 11)})
    assert led.periods["flow_current"] == "113-01-01~113-12-31"
    assert led.days["current"] == 366
    assert led.basis == "FY"


def test_basis_falls_back_to_cf_when_is_has_no_period() -> None:
    is_lines = [l.replace("{hdr}", "無期間") for l in _IS_LINES]
    cf_lines = [l.replace("{hdr}", "115 年 1 月 1 日至 6 月 30 日 114 年 1 月 1 日至 6 月 30 日") for l in _CF_LINES]
    doc = _synthetic({10: list(_BS_LINES), 11: is_lines, 12: cf_lines})
    anchors = {"fs_bs": PageRange(10, 10), "fs_is": PageRange(11, 11), "fs_cf": PageRange(12, 12)}
    led = extract_statements(doc, anchors)
    assert led.column_periods["is"] == []
    assert led.basis == "H1"


def test_unresolvable_periods_basis_other() -> None:
    doc = _synthetic({10: ["公司", "合併資產負債表", "單位：新台幣仟元", "無期間", "資產", "流動資產",
                           "現金及約當現金 六(一) $ 9,134,067 33 $ 2,267,253 12"]})
    led = extract_statements(doc, {"fs_bs": PageRange(10, 10)})
    assert led.basis == "other"
    assert led.days == {"current": None, "prior": None}
    assert set(led.periods) == _KEYS
    assert all(v is None for v in led.periods.values())


def test_to_dict_has_new_keys_and_keeps_old() -> None:
    d = extract_statements(*_fy()).to_dict()
    assert {"basis", "periods", "days", "assurance"} <= set(d)
    assert {"unit", "period_current", "period_prior", "rows", "checks", "unmapped_labels",
            "row_counts", "column_periods", "current_col", "prior_col", "parse_warnings"} <= set(d)
