"""test_fh_acceptance.py — run 2026-10-09-tw-equity-fh-schema item 6.1（fh_acceptance 單元；合成 facts，不跑真實 PDF）。

契約表（Task 6.1）：
  A1: 全部符合 → 末行 `PASS 6/6`、exit 0
  A2: 某家勾稽 1 項未過 → 該家 FAIL、輸出含家別／項目／根因、末行 `PASS 5/6`、exit 非 0
  A3: `--tickers 2881,2886` → 只輸出 2 家、末行 `PASS n/2`
  A4: [邊界] 某家快取檔不存在 → 該家 FAIL 並記檔名、CLI 不中斷
  A5: [組合] `--tickers` 含未知代號 × 合法代號 → 未知者回報錯誤行、合法者照跑
  A6: §0.3 各門檻（錨點／FY scope・usable／TTM／CAR／npl／覆蓋率／bridge 殘差）任一不符 → 該家 FAIL 並列該項根因
"""

from __future__ import annotations

import copy
import json

import pytest

from runtime.tw_equity import fh_acceptance as fa
from runtime.tw_equity.fh_acceptance import TICKERS, judge_company, main
from runtime.tw_equity.fh_schema import FH_CHECK_SPECS


def good_facts(t: str) -> dict:
    car_v, car_p = fa.EXPECTED_CAR[t]
    npl, cov = fa.EXPECTED_NPL[t]
    return {
        "ticker": t, "error": None,
        "checks": [{"name": n, "period": p, "lhs": 1.0, "rhs": 1.0, "passed": True}
                   for n, _l, _r in FH_CHECK_SPECS for p in ("current", "prior")],
        "n_unmapped": 3,
        "car": {"value": car_v, "period": car_p},
        "npl": {"period": "115-06-30", "npl_ratio": npl, "coverage_ratio": cov, "entity": None},
        "notes_error": None,
        "anchors": {"ar_business": 10, "ar_mdna": 20, "ar_fin_performance": 21},
        "fy": {"scope": fa.EXPECTED_SCOPE[t], "usable": True, "page": 21},
        "ttm": {"status": "ok", "scope": fa.EXPECTED_SCOPE[t], "reason": "", "comparability": "ifrs17_break"},
        "ifrs17_break": True,
        "bridge_residual": 0.0,
    }


def run_cli(capsys, argv, collect):
    rc = main(argv, collect=collect)
    out = capsys.readouterr().out
    return rc, out, out.strip().splitlines()[-1]


def test_all_pass_last_line_and_exit0(capsys):  # A1
    rc, out, last = run_cli(capsys, [], good_facts)
    assert last == "PASS 6/6" and rc == 0
    assert all(f"[{t}] PASS" in out for t in TICKERS)


def test_one_failed_check_marks_company_fail(capsys):  # A2
    def collect(t):
        f = good_facts(t)
        if t == "2885":
            f["checks"][3] = {"name": "is_net_revenue", "period": "prior", "lhs": 100.0, "rhs": 90.0, "passed": False}
        return f
    rc, out, last = run_cli(capsys, [], collect)
    assert last == "PASS 5/6" and rc != 0
    assert "[2885] FAIL" in out and all(f"[{t}] PASS" in out for t in TICKERS if t != "2885")
    line = next(x for x in out.splitlines() if "FAIL 家別=2885" in x)
    assert "is_net_revenue" in line and "根因=" in line


def test_tickers_filter(capsys):  # A3
    rc, out, last = run_cli(capsys, ["--tickers", "2881,2886"], good_facts)
    assert last == "PASS 2/2" and rc == 0
    assert "[2881]" in out and "[2886]" in out and "[2882]" not in out


def test_missing_file_fails_company_and_continues(capsys, tmp_path):  # A4
    (tmp_path / "tw_equity_inputs").mkdir()
    (tmp_path / "tw_equity_inputs" / "2881.json").write_text(json.dumps({
        "ticker": "2881", "company_name": "x", "fiscal_year": 2025, "group": "fh",
        "annual_report_path": "tw_report/不存在的年報.pdf"}), encoding="utf-8")

    def collect(t):
        return fa.collect_company(t, tmp_path) if t == "2881" else good_facts(t)
    rc, out, last = run_cli(capsys, ["--tickers", "2881,2882"], collect)
    assert "[2881] FAIL" in out and "不存在的年報.pdf" in out
    assert "[2882] PASS" in out and last == "PASS 1/2" and rc != 0


def test_unknown_ticker_reports_error_and_runs_valid(capsys):  # A5
    rc, out, last = run_cli(capsys, ["--tickers", "9999,2881"], good_facts)
    assert any(x.startswith("ERROR") and "9999" in x for x in out.splitlines())
    assert "[2881] PASS" in out and "[9999]" not in out
    assert last == "PASS 1/1" and rc != 0


def _mut_checks(f):
    f["checks"][0]["passed"] = None


def _mut_anchor(f):
    f["anchors"]["ar_mdna"] = None


def _mut_scope(f):
    f["fy"]["scope"] = "parent_only" if f["fy"]["scope"] == "consolidated" else "consolidated"


def _mut_usable(f):
    f["fy"]["usable"] = False


def _mut_ttm(f):
    f["ttm"]["status"] = "unavailable"


def _mut_car(f):
    f["car"]["value"] = 1.0


def _mut_npl(f):
    f["npl"]["npl_ratio"] = 9.99


def _mut_cov(f):
    f["npl"]["coverage_ratio"] = 1.0


def _mut_resid(f):
    f["bridge_residual"] = 2.5


def _mut_checks_empty(f):
    f["checks"] = []


def _mut_checks_short(f):
    f["checks"] = f["checks"][:-1]


def _mut_fy_none(f):
    f["fy"] = None


def _mut_ttm_none(f):
    f["ttm"] = None


def _mut_npl_none(f):
    f["npl"] = None


def _mut_ttm_scope(f):
    f["ttm"]["scope"] = "parent_only" if f["ttm"]["scope"] == "consolidated" else "consolidated"


def _mut_check_false(f):
    f["checks"][0] = {"name": FH_CHECK_SPECS[0][0], "period": "current", "lhs": 10.0, "rhs": 5.0, "passed": False}


def _mut_resid_nan(f):
    f["bridge_residual"] = float("nan")


@pytest.mark.parametrize("mut,item", [
    (_mut_checks_empty, "勾稽"), (_mut_checks_short, "勾稽筆數"), (_mut_fy_none, "FY"),
    (_mut_ttm_none, "TTM"), (_mut_npl_none, "附註 npl"), (_mut_ttm_scope, "TTM scope"),
    (_mut_check_false, "勾稽"), (_mut_resid_nan, "bridge 殘差"),
    (_mut_checks, "勾稽"), (_mut_anchor, "錨點:ar_mdna"), (_mut_scope, "FY scope"), (_mut_usable, "FY usable"),
    (_mut_ttm, "TTM"), (_mut_car, "附註 group_car"), (_mut_npl, "附註 npl_ratio"),
    (_mut_cov, "附註 coverage_ratio"), (_mut_resid, "bridge 殘差"),
])
def test_each_threshold_violation_fails_with_cause(mut, item):  # A6
    f = copy.deepcopy(good_facts("2881"))
    mut(f)
    v = judge_company("2881", f)
    assert v["ok"] is False
    hit = [x for x in v["failures"] if x["item"].startswith(item)]
    assert hit and all(x["cause"] for x in hit)


def test_residual_boundary_two_is_pass():  # A6 邊界：≤ 2 仟元
    f = good_facts("2881")
    f["bridge_residual"] = -2.0
    assert judge_company("2881", f)["ok"] is True


def test_2887_car_none_is_expected():  # A6：2887 CAR 未揭露才是符合
    assert judge_company("2887", good_facts("2887"))["ok"] is True
    f = good_facts("2887")
    f["car"] = {"value": 120.0, "period": "114-06-30"}
    assert judge_company("2887", f)["ok"] is False


def test_failed_check_detail_has_diff_and_short_checks_name_missing():  # A6
    f = good_facts("2881")
    _mut_check_false(f)
    v = judge_company("2881", f)
    assert any("差=" in x["detail"] for x in v["failures"])
    g = good_facts("2881")
    _mut_checks_short(g)
    cause = next(x["cause"] for x in judge_company("2881", g)["failures"] if x["item"] == "勾稽筆數")
    assert FH_CHECK_SPECS[-1][0] in cause
