"""test_cross_year_fin.py — build_cross_year 骨架／fin_performance_series／overlap_checks（item 4.1，Spec §2.5）。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.cross_year import build_cross_year
from runtime.tw_equity.doc_anchor import find_annual_report_sections
from runtime.tw_equity.ocr import markdown_to_page
from runtime.tw_equity.tables import TablesBundle, TwoYearRow, TwoYearTable, extract_tables

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity"


def _load(name: str):
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


def _bundle(doc, roc):
    anchors = find_annual_report_sections(doc, required=set())
    return extract_tables(doc, anchors, None, None, None, None,
                          roc_year=roc, gov_anchors=anchors)


def _real():
    cur = _bundle(_load("ar_3653_pages.json"), 114)
    md = json.loads((_FIX / "mistral_3653_2024_p51_p79.json").read_text(encoding="utf-8"))["pages"]
    fake = {int(n): markdown_to_page(int(n), t) for n, t in md.items()}
    prior_doc = pdf_doc.apply_ocr_policy(_load("ar2024_3653_pages.json"), lambda p, pg: fake)
    return cur, _bundle(prior_doc, 113)


def _tbl(cl, pl, rows):
    return TwoYearTable("新台幣仟元", cl, pl,
                        [TwoYearRow(l, c, p, None, None) for l, c, p in rows])


def _synth(fin_perf):
    base = {f.name: None for f in dataclasses.fields(TablesBundle)}
    base.update(consolidated_key_lines={}, parent_key_lines={}, missing_tables=[], unit_notes={})
    base["fin_performance"] = fin_perf
    return TablesBundle(**base)


def test_real_series_and_overlap():
    cur, prior = _real()
    out = build_cross_year(cur, prior, current_roc=114, prior_roc=113)
    assert out["years"] == {"current": 114, "prior": 113}
    rev = next(s for s in out["fin_performance_series"] if s["label"] == "營業收入")
    assert rev["values"] == {"112年度": 12062664, "113年度": 14278187, "114年度": 20275577}
    chk = [c for c in out["overlap_checks"]
           if c["table"] == "T7b" and c["label"] == "營業收入" and c["year"] == "113年度"]
    assert len(chk) == 1 and chk[0]["match"] is True


def test_real_t7a_ocr_p79_parses_and_overlap_matches():
    cur, prior = _real()
    assert prior.fin_position is not None
    row = next(r for r in prior.fin_position.rows if r.label == "資產總額")
    assert (row.current, row.prior) == (18461872, 15845649)
    out = build_cross_year(cur, prior, current_roc=114, prior_roc=113)
    chk = [c for c in out["overlap_checks"]
           if c["table"] == "T7a" and c["label"] == "資產總額" and c["year"] == "113年度"]
    assert len(chk) == 1 and chk[0]["match"] is True


def test_skeleton_keys_present():
    cur, prior = _real()
    out = build_cross_year(cur, prior, current_roc=114, prior_roc=113)
    assert set(out) == {"years", "fin_performance_series", "overlap_checks",
                        "customer_concentration_series", "top_shareholders_change",
                        "pledge_change"}


def test_synthetic_diff_5_not_match():
    cur = _synth(_tbl("114年度", "113年度", [("營業收入", 200, 100)]))
    prior = _synth(_tbl("113年度", "112年度", [("營業收入", 105, 90)]))
    out = build_cross_year(cur, prior, current_roc=114, prior_roc=113)
    chk = out["overlap_checks"]
    assert len(chk) == 1 and chk[0]["match"] is False and chk[0]["year"] == "113年度"


def test_synthetic_diff_1_matches():
    cur = _synth(_tbl("114年度", "113年度", [("營業收入", 200, 100)]))
    prior = _synth(_tbl("113年度", "112年度", [("營業收入", 101, 90)]))
    out = build_cross_year(cur, prior, current_roc=114, prior_roc=113)
    assert out["overlap_checks"][0]["match"] is True


def test_synthetic_series_prefers_current_doc():
    cur = _synth(_tbl("114年度", "113年度", [("營業收入", 200, 100)]))
    prior = _synth(_tbl("113年度", "112年度", [("營業收入", 105, 90)]))
    out = build_cross_year(cur, prior, current_roc=114, prior_roc=113)
    assert out["fin_performance_series"] == [
        {"label": "營業收入", "values": {"112年度": 90, "113年度": 100, "114年度": 200}}]


def test_t7a_none_only_drops_t7a_overlap():
    cur, prior = _real()
    out = build_cross_year(dataclasses.replace(cur, fin_position=None), prior,
                           current_roc=114, prior_roc=113)
    assert out["fin_performance_series"] != []
    tables = {c["table"] for c in out["overlap_checks"]}
    assert tables == {"T7b"}


def test_none_table_gives_empty_no_raise():
    ok = _synth(_tbl("114年度", "113年度", [("營業收入", 200, 100)]))
    none = _synth(None)
    for a, b in ((ok, none), (none, ok), (none, none)):
        out = build_cross_year(a, b, current_roc=114, prior_roc=113)
        assert out["fin_performance_series"] == []
        assert out["overlap_checks"] == []
