"""batch_summary.py 金控排名表測試（run 2026-10-09-tw-equity-fh-schema，item 5.2；Spec §8.2）。"""

from __future__ import annotations

from runtime.tw_equity.batch_summary import FH_RANK_COLUMNS, build_summary


def fh_rec(ticker="2881", *, car="139.13", ifrs17=False, scope="consolidated", status="ok"):
    car_v = None if car is None else float(car)
    return {
        "ticker": ticker, "company_name": f"金控{ticker}", "group": "fh", "schema": "fh", "status": status,
        "error": None, "fs_period": "2026H1", "basis": "H1", "ifrs17_break": ifrs17,
        # 金控記錄刻意帶工業會命中的值：FCF<0、流動比率<100、TTM unavailable 以外的 Q1 條件
        "metrics": {"roe": {"current": 7.0}, "roa": {"current": 0.5}, "fcf": {"current": -1},
                    "current_ratio": {"current": 50}, "npl_ratio": {"current": 0.2},
                    "group_car": {"current": car_v, "source": {"current": {"period": "114-06-30"}}}},
        "values": {"net_revenue": {"current": 172_468_262.0}, "net_income": {"current": 97_780_594.0},
                   "net_income_parent": {"current": 97_391_130.0}},
        "checks": {"passed": 1, "failed": 3, "none": 2, "not_passed": ["x"]},
        "ttm": {"status": "ok", "reason": "", "scope": scope, "comparability": None,
                "values": {"net_income": {"ttm": 200_000.0}, "net_income_parent": {"ttm": 150_000.0}}},
    }


def ind_rec(ticker="1111"):
    return {"ticker": ticker, "company_name": f"公司{ticker}", "group": "industrial", "status": "ok",
            "error": None, "fs_period": "2026H1", "basis": "H1", "metrics": {}, "values": {},
            "checks": {"passed": 22, "failed": 0, "none": 0, "not_passed": []}, "ttm": None}


def test_fh_in_fh_ranking_not_in_industrial_or_unsupported():
    s = build_summary([ind_rec(), fh_rec()])
    assert [r["ticker"] for r in s["fh_ranking"]] == ["2881"]
    assert [r["ticker"] for r in s["rows"]] == ["1111"]
    assert s["unsupported"] == [] and s["failed"] == []
    assert s["fh_ranking"][0]["values"]["net_revenue"] == 172_468.262
    assert len(s["fh_columns"]) == len(FH_RANK_COLUMNS) == 11


def test_fh_gets_no_industrial_flags():
    s = build_summary([fh_rec()])
    assert s["flags"] == []


def test_ttm_parent_only_labelled():
    row = build_summary([fh_rec(scope="parent_only")])["fh_ranking"][0]
    assert row["ttm_label"] == "歸母" and row["values"]["ttm_net_income"] == 150.0
    row = build_summary([fh_rec()])["fh_ranking"][0]
    assert row["ttm_label"] is None and row["values"]["ttm_net_income"] == 200.0


def test_fh_ranking_empty_list_without_fh():
    s = build_summary([ind_rec()])
    assert "fh_ranking" in s and s["fh_ranking"] == []


def test_car_none_with_ifrs17_break_keeps_flag():
    row = build_summary([fh_rec("2887", car=None, ifrs17=True)])["fh_ranking"][0]
    assert row["values"]["group_car"] is None
    assert row["ifrs17_break"] is True
