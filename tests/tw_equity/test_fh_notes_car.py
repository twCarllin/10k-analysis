"""fh_notes 集團資本適足率測試（Spec 2026-10-09-tw-equity-fh-schema §4.1／§4.3；fixture fh_notes_pages.json）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.fh_notes import extract_fh_notes

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity" / "fh_notes_pages.json"
_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _notes(ticker: str, **kw):
    return extract_fh_notes(pdf_doc.from_json(_DATA[ticker]["doc"]), **kw)


@pytest.mark.parametrize("ticker,value,period,page", [
    ("2881", 139.13, "114-06-30", 354),   # 無 % 號；單位列／金額欄不可誤取
    ("2882", 120.22, "114-06-30", 280),
    ("2885", 130.70, "114-06-30", 212),
    ("2886", 133.83, "114-06-30", 160),   # p159 的 115.6.30 金額欄全「註」
    ("2891", 125.07, "114-12-31", 118),   # 兩期、% 前空格，取最新可得
])
def test_car_value_period_page(ticker, value, period, page):
    car = _notes(ticker, bs_current_period="115-06-30").group_car
    assert car.value == value
    assert car.period == period
    assert car.page == page
    assert car.reason is None
    assert car.stale is True


def test_stale_false_when_period_not_earlier_than_bs_current():
    assert _notes("2881", bs_current_period="114-06-30").group_car.stale is False
    assert _notes("2881").group_car.stale is False


def test_undisclosed_2887_value_none_with_reason():
    car = _notes("2887", bs_current_period="115-06-30").group_car
    assert car.value is None
    assert car.reason == "未揭露（延後補正）"
    assert car.period is None
    assert car.stale is False


def test_unavailable_lists_rbc_and_json_roundtrip():
    notes = _notes("2881")
    items = " ".join(u["item"] for u in notes.unavailable)
    assert notes.unavailable and "RBC" in items
    d = json.loads(json.dumps(notes.to_dict(), ensure_ascii=False))
    assert set(d) == {"group_car", "npl", "unavailable"}
    assert d["group_car"]["value"] == 139.13
