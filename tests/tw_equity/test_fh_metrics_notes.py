"""test_fh_metrics_notes.py — run 2026-10-09-tw-equity-fh-schema item 3.2：附註指標＋extract_tables 接線。

契約表：
  N1: 合成 FhNotes npl 115-06-30 (0.11,1112.78)、114-06-30 (0.10,1000.0) → npl_ratio current 0.11／prior 0.10，
      source.period 各為 115-06-30／114-06-30、stale False
  N2: group_car 114-06-30 值 → source.stale True；group_car 值 None（2887）→ current None、source 含 reason
  N3: [邊界] group=None → extract_tables 不產生 fh_notes（bundle.fh_notes is None、to_dict 無 fh_notes 鍵）、metrics 無附註指標
  N4: [組合] group=="fh" × fs 無「資產品質」頁 → npl_ratio None、其他 fh 指標不受影響；bundle.fh_notes 為 FhNotes、進 to_dict
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
from runtime.tw_equity.fh_notes import CarResult, FhNotes  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402
from runtime.tw_equity.tables import extract_tables  # noqa: E402

_FH = json.loads((ROOT / "tests/fixtures/tw_equity/fh_statements_pages.json").read_text(encoding="utf-8"))["2881"]


def _ledger() -> StatementLedger:
    rows = [StatementRow("bs", None, k, k, None, v, v, None, None, 1, 0, columns=[v, v, v])
            for k, v in {"total_equity": 100, "total_assets": 1000}.items()]
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": ["115-06-30", "114-12-31", "114-06-30"], "is": [], "cf": []},
        basis="H1", periods={"bs_current": "115-06-30", "bs_prior_same": "114-06-30",
                             "bs_prior_fy_end": "114-12-31"}, schema="fh")


def _npl():
    return {"entity": "富邦銀行", "periods": [
        {"period": "115-06-30", "npl_ratio": 0.11, "coverage_ratio": 1112.78, "total_loans": 5, "page": 9},
        {"period": "114-06-30", "npl_ratio": 0.10, "coverage_ratio": 1000.0, "total_loans": 4, "page": 9}],
        "entities": []}


def _m(pack, key, period):
    return next(m for m in pack.metrics if m.key == key and m.period == period)


def test_npl_current_prior_and_source():  # N1
    notes = FhNotes(group_car=CarResult(139.13, "114-06-30", 7, True), npl=_npl())
    pack = compute_metrics(_ledger(), None, group="fh", notes=notes)
    cur, pri = _m(pack, "npl_ratio", "current"), _m(pack, "npl_ratio", "prior")
    assert (cur.value, pri.value) == (0.11, 0.10)
    assert (cur.source["period"], pri.source["period"]) == ("115-06-30", "114-06-30")
    assert cur.source["stale"] is False and pri.source["stale"] is False
    assert cur.source["doc"] == "fs" and cur.source["entity"] == "富邦銀行" and cur.source["page"] == 9
    assert _m(pack, "coverage_ratio", "current").value == 1112.78
    json.dumps(pack.to_dict())


def test_group_car_stale_and_undisclosed():  # N2
    stale = compute_metrics(_ledger(), None, group="fh",
                            notes=FhNotes(group_car=CarResult(139.13, "114-06-30", 7, True), npl=_npl()))
    c = _m(stale, "group_car", "current")
    assert c.value == 139.13 and c.source["stale"] is True and c.source["period"] == "114-06-30"
    none = compute_metrics(_ledger(), None, group="fh",
                           notes=FhNotes(group_car=CarResult(None, reason="未揭露（延後補正）"), npl=_npl()))
    c = _m(none, "group_car", "current")
    assert c.value is None and c.source["reason"]


def _bundle(**kw):
    fs = pdf_doc.from_json(_FH["doc"])
    anchors = {k: (PageRange(*r) if r else None) for k, r in _FH["fs_anchors"].items()}
    ar = pdf_doc.PdfDoc(path=Path(""), pages=[])
    return extract_tables(ar, {}, fs, anchors, None, None, roc_year=115, **kw)


def test_group_none_has_no_fh_notes():  # N3
    b = _bundle(group=None)
    assert b.fh_notes is None and "fh_notes" not in b.to_dict()
    assert not {"group_car", "npl_ratio", "coverage_ratio"} & {m.key for m in b.metrics.metrics}


def test_group_fh_without_asset_quality_page():  # N4
    b = _bundle(group="fh")
    assert isinstance(b.fh_notes, FhNotes) and b.fh_notes.npl is None
    assert "fh_notes" in b.to_dict() and json.dumps(b.to_dict()["fh_notes"])
    assert _m(b.metrics, "npl_ratio", "current").value is None
    assert _m(b.metrics, "equity_to_assets", "current").value is not None


def test_extract_fh_notes_exception_isolated(monkeypatch):  # N5：系統邊界例外 → 不中斷、附註指標 None
    import runtime.tw_equity.fh_notes as fn

    def boom(*a, **k):
        raise ValueError("壞頁")

    monkeypatch.setattr(fn, "extract_fh_notes", boom)
    b = _bundle(group="fh")
    assert b.statements is not None and b.fh_notes is None
    assert b.fh_notes_error and "ValueError" in b.fh_notes_error
    assert b.to_dict()["fh_notes_error"] == b.fh_notes_error
    assert _m(b.metrics, "equity_to_assets", "current").value is not None
    assert _m(b.metrics, "npl_ratio", "current").value is None
    assert _m(b.metrics, "group_car", "current").source["reason"]


def test_npl_prior_differs_from_bs_prior_gets_reason():  # N6：三期附註、BS prior 是 114-12-31 以外的日期
    npl = _npl()
    npl["periods"].insert(1, {"period": "114-12-31", "npl_ratio": 0.12, "coverage_ratio": 1050.0,
                              "total_loans": 4, "page": 9})
    notes = FhNotes(group_car=CarResult(139.13, "114-06-30", 7, True), npl=npl)
    pack = compute_metrics(_ledger(), None, group="fh", notes=notes)  # 帳本 bs_prior_same＝114-06-30
    pri = _m(pack, "npl_ratio", "prior")
    assert pri.value == 0.12 and pri.source["period"] == "114-12-31"
    assert pri.source["reason"] == "附註期別與帳本 prior 期不同" and pri.source["stale"] is False
    assert "reason" not in _m(pack, "npl_ratio", "current").source


def test_npl_no_period_matching_bs_current():  # N7：鎖定現行行為——無同日期 → current None（reason「附註無對應期間」）、prior 仍取早於 bs_current 最新期
    npl = _npl()
    npl["periods"] = npl["periods"][1:]  # 只剩 114-06-30
    pack = compute_metrics(_ledger(), None, group="fh",
                           notes=FhNotes(group_car=CarResult(None, reason="x"), npl=npl))
    cur = _m(pack, "npl_ratio", "current")
    assert cur.value is None and cur.source["reason"] == "附註無對應期間"
    assert _m(pack, "npl_ratio", "prior").value == 0.10
