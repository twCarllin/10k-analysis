"""TablesBundle.metrics 接線（run 2026-10-09-tw-equity-metrics-t1 item 2.1）。"""
import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import (FS_HEADING_ANCHORS, find_annual_report_sections,
                                          find_heading_sections)
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import extract_tables

_FIX = Path(__file__).parent.parent / "fixtures" / "tw_equity"


def _load(name):
    return from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ar():
    doc = _load("ar_3653_pages.json")
    return doc, find_annual_report_sections(doc, required=set())


def test_with_fs_metrics_present(ar):
    doc, ara = ar
    fs = _load("fs_3653_pages.json")
    b = extract_tables(doc, ara, fs, find_heading_sections(fs, FS_HEADING_ANCHORS, required=set()),
                       None, None, roc_year=114)
    assert b.metrics is not None
    d = b.to_dict()
    assert d["metrics"]["index"]["fcf"]["current"] == pytest.approx(3943937, abs=1)
    json.dumps(d)


def test_without_fs_metrics_none(ar):
    doc, ara = ar
    b = extract_tables(doc, ara, None, None, None, None, roc_year=114)
    assert b.metrics is None and b.statements is None
    assert b.to_dict()["metrics"] is None
    assert {"FS_BS", "FS_IS", "FS_CF"} <= set(b.missing_tables)


# ── item 3.3：fy_income 接線（Spec §5）。契約 row：
#   W1: bundle.to_dict()["fy_income"] 為 dict 或 None；FY 帳本 → metrics.ttm is None
#   W2: [邊界] 無可解析 FY 損益頁（fy_income None）＋ H1 帳本 → 不拋例外、ttm unavailable；fin_performance 輸出不受影響


def test_fy_income_wired_and_fy_ledger_has_no_ttm(ar):
    doc, ara = ar
    fs = _load("fs_3653_pages.json")
    b = extract_tables(doc, ara, fs, find_heading_sections(fs, FS_HEADING_ANCHORS, required=set()),
                       None, None, roc_year=114)
    d = b.to_dict()
    assert d["fy_income"] is None or isinstance(d["fy_income"], dict)
    assert b.metrics.ttm is None
    assert d["metrics"]["ttm_vs_fy"] is None
    json.dumps(d)


def test_no_fy_income_pages_gives_unavailable_ttm_for_h1(ar):
    from runtime.tw_equity.pdf_doc import Page, PdfDoc

    doc, ara = ar
    base = extract_tables(doc, ara, None, None, None, None, roc_year=114)
    blank = PdfDoc(path=doc.path, pages=[Page(1, "", [], [])])
    h1 = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))["2308"]
    h1_doc = from_json(h1["doc"])
    from runtime.tw_equity.doc_anchor import PageRange
    h1_anchors = {k: (PageRange(*r) if r else None) for k, r in h1["fs_anchors"].items()}
    b = extract_tables(blank, {}, h1_doc, h1_anchors, None, None, roc_year=114)
    assert b.fy_income is None and b.to_dict()["fy_income"] is None
    assert b.metrics.ttm.status == "unavailable" and b.metrics.ttm.reason
    # 改用真年報不影響 fin_performance
    again = extract_tables(doc, ara, None, None, None, None, roc_year=114)
    assert (again.fin_performance.to_dict() if again.fin_performance else None) == \
           (base.fin_performance.to_dict() if base.fin_performance else None)


# ── run 2026-10-09-tw-equity-fy-income-guard item 1.1：extract_fy_income 例外保護＋警示。契約 row：
#   G1: extract_fy_income 拋 ValueError("boom") → extract_tables 不拋、fy_income None、fy_income_error "ValueError: boom"、
#       stdout 有警示行、H1 帳本 ttm unavailable
#   G2: [邊界] 解析成功 → fy_income_error None、stdout 無警示行


def _h1(ar):
    from runtime.tw_equity.doc_anchor import PageRange

    h1 = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))["2308"]
    return from_json(h1["doc"]), {k: (PageRange(*r) if r else None) for k, r in h1["fs_anchors"].items()}


def test_fy_income_exception_is_caught_and_warned(ar, monkeypatch, capsys, caplog):
    import runtime.tw_equity.fy_income as fy_mod

    def boom(*_a, **_k):
        raise ValueError("boom")

    monkeypatch.setattr(fy_mod, "extract_fy_income", boom)
    doc, ara = ar
    h1_doc, h1_anchors = _h1(ar)
    with caplog.at_level("WARNING", logger="runtime.tw_equity.tables"):
        b = extract_tables(doc, ara, h1_doc, h1_anchors, None, None, roc_year=114)
    assert b.fy_income is None
    assert b.fy_income_error == "ValueError: boom"
    assert b.to_dict()["fy_income_error"] == "ValueError: boom"
    assert "[tw-equity 警示] FY 損益表解析失敗：ValueError: boom；TTM 不可用" in capsys.readouterr().out
    assert any("FY 損益表解析失敗" in r.getMessage() for r in caplog.records)
    assert b.metrics.ttm.status == "unavailable"


def test_fy_income_success_has_no_warning(ar, capsys):
    doc, ara = ar
    h1_doc, h1_anchors = _h1(ar)
    b = extract_tables(doc, ara, h1_doc, h1_anchors, None, None, roc_year=114)
    assert b.fy_income_error is None
    assert b.to_dict()["fy_income_error"] is None
    assert "[tw-equity 警示]" not in capsys.readouterr().out
