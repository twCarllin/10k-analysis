"""fh_notes 6 家整合（Spec 2026-10-09-tw-equity-fh-schema §4.1／§4.2 期望表；fixture fh_notes_pages.json）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.fh_notes import extract_fh_notes

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity" / "fh_notes_pages.json"
_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))

# 115-06-30 期望（§4.2 表）與 CAR 期望（§4.1）
_NPL = {"2881": (0.11, 1112.78), "2882": (0.14, 1100.45), "2885": (0.11, 1091.36),
        "2886": (0.20, 813.14), "2887": (0.13, 922.63), "2891": (0.54, 280.47)}
_CAR = {"2881": 139.13, "2882": 120.22, "2885": 130.70, "2886": 133.83, "2887": None, "2891": 125.07}


def _notes(ticker):
    return extract_fh_notes(pdf_doc.from_json(_DATA[ticker]["doc"]), bs_current_period="115-06-30")


@pytest.mark.parametrize("ticker", sorted(_NPL))
def test_npl_latest_period_values(ticker):
    top = _notes(ticker).npl["periods"][0]
    assert top["period"] == "115-06-30"
    assert (top["npl_ratio"], top["coverage_ratio"]) == _NPL[ticker]


@pytest.mark.parametrize("ticker", sorted(_CAR))
def test_car_values(ticker):
    assert _notes(ticker).group_car.value == _CAR[ticker]


@pytest.mark.parametrize("ticker", sorted(_CAR))
def test_to_dict_json_serializable(ticker):
    d = _notes(ticker).to_dict()
    assert json.loads(json.dumps(d, ensure_ascii=False)) == d


def test_2887_car_none_but_npl_present():
    n = _notes("2887")
    assert n.group_car.value is None
    assert n.npl is not None and n.npl["periods"]


def test_car_takes_last_number_when_row_has_several():
    # 6 家真實列只有單一數字，無法區分列首／列尾；以合成列（前面多一個數字）鎖定「取最後一個」
    doc = pdf_doc.from_json(_DATA["2881"]["doc"])
    for pg in doc.pages:
        pg.lines = [ln.replace("集團資本適足比率 139.13", "集團資本適足比率 1,055,239,627 139.13") for ln in pg.lines]
    assert extract_fh_notes(doc).group_car.value == 139.13
