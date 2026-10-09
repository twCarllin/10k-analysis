"""期間模型整合：真實 fixture 帳本 → extract_statements → compute_metrics 主視圖（period-model item 1.4）。

fixture 依據：tests/fixtures/tw_equity/fs_h1_pages.json（producer make_fs_h1_fixture.py；2308 取自 tw_report 半年報 PDF 頁文字，
經 pdf_doc 輸出）；FY 斷言維持在 test_metrics_real.py（fs_3653_pages.json）。

契約 row：
  I1: H1 fixture → pack.days["current"]==181、pack.periods["bs_prior_same"]=="114-06-30"
  I2: H1 fixture dso current == AR×181/revenue（容差 0.01）
  I3: FY fixture 既有 test_metrics_real.py 斷言不變（本檔不重複）
  I4: [邊界] H1 fixture total_assets bridge prior ≠ bs_prior_same 欄值（取 114-12-31 欄）
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
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity/fs_h1_pages.json"


@pytest.fixture(scope="module")
def h1():
    entry = json.loads(_FIX.read_text(encoding="utf-8"))["2308"]
    doc = pdf_doc.from_json(entry["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
    led = extract_statements(doc, anchors)
    return led, compute_metrics(led)


def test_main_view_periods_and_days(h1) -> None:
    _, pack = h1
    assert pack.days["current"] == 181
    assert pack.periods["bs_prior_same"] == "114-06-30"
    assert pack.basis == "H1"


def test_dso_uses_181_days(h1) -> None:
    led, pack = h1
    ar = led.value_at("accounts_receivable", "bs_current") + led.value_at("accounts_receivable_related", "bs_current")
    revenue = led.value_at("revenue", "flow_current")
    assert pack.get("dso") == pytest.approx(ar * 181 / revenue, abs=0.01)


def test_total_assets_bridge_prior_is_fy_end_not_same_period(h1) -> None:
    led, pack = h1
    bridge = next(b for b in pack.bridges if b.target == "total_assets")
    fy_end = led.value_at("total_assets", "bs_prior_fy_end")
    same = led.value_at("total_assets", "bs_prior_same")
    assert bridge.target_prior == fy_end
    assert fy_end != same
