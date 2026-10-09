"""batch_summary.py 跨公司摘要測試（run 2026-10-09-tw-equity-batch-runner，Task 2.1）。"""

from __future__ import annotations

import json

from runtime.tw_equity.batch_summary import build_summary, render_md, write_summary


def _rec(ticker="1111", *, group="industrial", status="ok", metrics=None, values=None,
         checks=None, ttm=None, error=None):
    return {"ticker": ticker, "company_name": f"公司{ticker}", "group": group, "status": status,
            "error": error, "fs_period": "2026H1", "basis": "H1",
            "metrics": metrics or {}, "values": values or {},
            "checks": checks or {"passed": 22, "failed": 0, "none": 0, "not_passed": []}, "ttm": ttm}


def _rules(rec):
    return {f["rule"] for f in build_summary([rec])["flags"]}


def test_r1_fcf_sign():
    assert "R1" in _rules(_rec(metrics={"fcf": {"current": -1}}))
    assert "R1" not in _rules(_rec(metrics={"fcf": {"current": 1}}))


def test_r2_cfo_to_net_income():
    assert "R2" in _rules(_rec(values={"net_income": {"current": 100}, "cfo": {"current": 40}}))
    assert "R2" not in _rules(_rec(values={"net_income": {"current": -10}, "cfo": {"current": 0}}))


def test_r6_revenue_yoy():
    assert "R6" in _rules(_rec(values={"revenue": {"current": 70, "prior": 100}}))
    assert "R6" not in _rules(_rec(values={"revenue": {"current": 81, "prior": 100}}))


def test_r7_gross_margin_drop():
    assert "R7" in _rules(_rec(metrics={"gross_margin": {"current": 20, "prior": 26}}))
    assert "R7" not in _rules(_rec(metrics={"gross_margin": {"current": 22, "prior": 26}}))


def test_r3_r4_r5_r8_thresholds():
    rules = _rules(_rec(metrics={"current_ratio": {"current": 90}, "liabilities_to_assets": {"current": 75},
                                 "interest_coverage": {"current": 2}, "dso": {"current": 140, "prior": 100}}))
    assert {"R3", "R4", "R5", "R8"} <= rules
    rules = _rules(_rec(metrics={"current_ratio": {"current": 110}, "liabilities_to_assets": {"current": 60},
                                 "interest_coverage": {"current": 5}, "dio": {"current": 120, "prior": 100}}))
    assert not {"R3", "R4", "R5", "R8"} & rules


def test_q1_data_quality():
    assert "Q1" in _rules(_rec(checks={"passed": 21, "failed": 1, "none": 0, "not_passed": ["x"]}))
    assert "Q1" in _rules(_rec(ttm={"status": "unavailable", "reason": "缺 FY", "values": {}}))
    assert "Q1" not in _rules(_rec())


def test_fh_and_error_excluded():
    s = build_summary([_rec("2881", group="fh", metrics={"fcf": {"current": -1}}),
                       _rec("9999", status="error", error="ValueError: boom"), _rec("1111")])
    assert [r["ticker"] for r in s["rows"]] == ["1111"]
    assert s["unsupported"] == [] and [r["ticker"] for r in s["fh_ranking"]] == ["2881"]
    assert s["failed"] == [{"ticker": "9999", "company_name": "公司9999", "group": "industrial",
                            "error": "ValueError: boom"}]
    assert all(f["ticker"] == "1111" for f in s["flags"])


def test_none_values_do_not_flag_and_render_blank():
    s = build_summary([_rec()])
    assert s["flags"] == []
    assert all(v is None for v in s["rows"][0]["values"].values())
    row = next(line for line in render_md(s).splitlines() if line.startswith("| 1111 "))
    assert row.endswith("|  |  |")


def test_ttm_and_amount_columns():
    s = build_summary([_rec(values={"revenue": {"current": 2_000_000}},
                            ttm={"status": "ok", "reason": "", "values": {"revenue": {"ttm": 5_000_000},
                                                                         "net_income": {"ttm": 1_000_000}}})])
    v = s["rows"][0]["values"]
    assert v["revenue"] == 2000 and v["ttm_revenue"] == 5000 and v["ttm_net_income"] == 1000


def test_write_summary_files(tmp_path):
    s = build_summary([_rec(metrics={"fcf": {"current": -1}})])
    write_summary(s, tmp_path)
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["flags"][0]["rule"] == "R1"
    md = (tmp_path / "summary.md").read_text(encoding="utf-8")
    for c in s["columns"]:
        assert c["title"] in md
    html = (tmp_path / "summary.html").read_text(encoding="utf-8")
    assert '"rule": "R1"' in html and "__DATA__" not in html
    assert "<script src=" not in html and "<link" not in html
