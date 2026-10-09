"""H1 帳本＋FY 損益 → TTM → 附錄 E 全流程（period-model item 3.4）。

fixture 依據：tests/fixtures/tw_equity/fs_h1_pages.json（producer make_fs_h1_fixture.py；2308 取自
tw_report/2308_2026Q2財報.pdf 頁文字，經 pdf_doc 輸出）；FY 損益為合成 `FyIncome`
（欄位依據 runtime/tw_equity/fy_income.py:FyIncome；rows 形狀 {"label","key","current","prior"}）。

契約 row：
  J1: H1 revenue 本期 R1、上期 R0，FY revenue F → 報告 TTM 列 F+R1−R0
  J2: roc_year 不符 → 報告含 reason 一行
  J3: [邊界] FY 損益 usable=False（金控）→ ttm_vs_fy.status=="unavailable"，主視圖輸出不受影響
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.fy_income import FyIncome  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.report import _appendix_e  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402
from runtime.tw_equity.tables import TablesBundle  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity/fs_h1_pages.json"
_FY_REVENUE = 5_000_000.0


@pytest.fixture(scope="module")
def led():
    entry = json.loads(_FIX.read_text(encoding="utf-8"))["2308"]
    doc = pdf_doc.from_json(entry["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
    return extract_statements(doc, anchors)


def _fy(roc_year=114, usable=True) -> FyIncome:
    rows = [{"label": "營業收入", "key": "revenue", "current": _FY_REVENUE, "prior": 1.0}]
    return FyIncome(roc_year=roc_year, page=9, unit="仟元", scale=1.0, rows=rows, usable=usable)


def _bundle(metrics) -> TablesBundle:
    kl = {k: (None, None) for k in ["營業收入", "營業成本", "營業毛利", "營業費用", "營業利益", "本期淨利"]}
    return TablesBundle(None, None, None, None, None, None, None, None, None, None,
                        dict(kl), dict(kl), None, [], {}, metrics=metrics)


def _fmt(v: float) -> str:
    return f"{int(v):,}"


def test_ttm_revenue_in_report(led):  # J1
    r1, r0 = led.value_at("revenue", "flow_current"), led.value_at("revenue", "flow_prior")
    pack = compute_metrics(led, _fy())
    assert pack.ttm.values["revenue"]["ttm"] == _FY_REVENUE + r1 - r0
    text = "\n".join(_appendix_e(_bundle(pack)))
    assert f"| revenue | {_fmt(_FY_REVENUE)} | {_fmt(r1)} | {_fmt(r0)} | {_fmt(_FY_REVENUE + r1 - r0)} |" in text


def test_year_mismatch_reason_in_report(led):  # J2
    text = "\n".join(_appendix_e(_bundle(compute_metrics(led, _fy(roc_year=113)))))
    t = text[text.index("### TTM vs FY"):]
    body = [l for l in t.splitlines()[1:] if l.strip()]
    assert len(body) == 1 and "fy_year_mismatch" in body[0]


def test_unusable_fy_leaves_main_view_unchanged(led):  # J3
    base = compute_metrics(led)
    pack = compute_metrics(led, _fy(usable=False))
    assert pack.to_dict()["ttm_vs_fy"]["status"] == "unavailable"
    a, b = base.to_dict(), pack.to_dict()
    for k in ("metrics", "bridges", "index", "basis", "days", "periods", "assurance"):
        assert a[k] == b[k]
