"""fh_notes 逾放比／覆蓋率測試（Spec 2026-10-09-tw-equity-fh-schema §4.2、F8；單一銀行；fixture fh_notes_pages.json）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.fh_notes import extract_fh_notes

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity" / "fh_notes_pages.json"
_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))

# 期望值（Spec §4.2／F8）：{ticker: {period: (npl_ratio, coverage_ratio)}}
_EXPECTED = {
    "2881": {"115-06-30": (0.11, 1112.78), "114-06-30": (0.12, 1067.19)},
    "2882": {"115-06-30": (0.14, 1100.45), "114-06-30": (0.14, 1200.00)},
    "2885": {"115-06-30": (0.11, 1091.36), "114-06-30": (0.10, 1282.23)},
    "2886": {"115-06-30": (0.20, 813.14), "114-06-30": (0.29, 575.37)},
    "2891": {"115-06-30": (0.54, 280.47), "114-06-30": (0.48, 324.16)},
}


def _npl(ticker: str, pages: list[int] | None = None):
    doc = pdf_doc.from_json(_DATA[ticker]["doc"])
    if pages is not None:
        doc.pages = [p for p in doc.pages if p.number in pages]
    return extract_fh_notes(doc).npl


@pytest.mark.parametrize("ticker", sorted(_EXPECTED))
def test_npl_periods_values(ticker):
    npl = _npl(ticker)
    got = {p["period"]: (p["npl_ratio"], p["coverage_ratio"]) for p in npl["periods"]}
    assert got == _EXPECTED[ticker]
    assert [p["period"] for p in npl["periods"]] == sorted(got, reverse=True)
    assert all(isinstance(p["page"], int) for p in npl["periods"])


def test_npl_2881_one_table_per_period_pages():
    pages = {p["period"]: p["page"] for p in _npl("2881")["periods"]}
    assert pages == {"115-06-30": 290, "114-06-30": 291}


def test_npl_2891_percent_with_space_not_shifting_numbers():
    p = {x["period"]: x for x in _npl("2891")["periods"]}["115-06-30"]
    assert (p["npl_ratio"], p["coverage_ratio"], p["total_loans"]) == (0.54, 280.47, 4734430668.0)


def test_npl_dollar_and_comma_styles_same_structure():
    def rows(t):
        return {p["period"]: (p["npl_ratio"], p["coverage_ratio"], p["total_loans"]) for p in _npl(t)["periods"]}

    # 2882：`$` 風格；2885：無 `$` 千分位風格 —— 同樣兩期並排結構
    assert rows("2882") == {"115-06-30": (0.14, 1100.45, 3061912387.0),
                            "114-06-30": (0.14, 1200.00, 2688522477.0)}
    assert rows("2885") == {"115-06-30": (0.11, 1091.36, 1572996203.0),
                            "114-06-30": (0.10, 1282.23, 1335424622.0)}


def test_npl_none_when_no_loan_business_row():
    assert _npl("2881", pages=[354]) is None
    assert _npl("2887", pages=[220]) is None  # 主 flow 裁決 2026-10-09：2.3 起 2887 fixture 含 p242／p259，邊界改以無 `放款業務合計` 列的 p220 驗


def test_npl_json_roundtrip():
    d = extract_fh_notes(pdf_doc.from_json(_DATA["2882"]["doc"])).to_dict()
    assert json.loads(json.dumps(d, ensure_ascii=False)) == d
