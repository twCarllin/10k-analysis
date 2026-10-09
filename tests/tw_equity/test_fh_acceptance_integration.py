"""test_fh_acceptance_integration.py — run 2026-10-09-tw-equity-fh-schema item 6.2（6 家 fixture 版 fh_acceptance 對映 §0.3）。

契約表（Task 6.2）：
  I1: fixture 版 6 家 facts 經 judge_company 全 ok，且逐條對映 §0.3（勾稽 18/18、三錨點、FY usable／scope、TTM ok、
      附註逐值、bridge 殘差 ≤ 2）
  I2: [邊界] 勾稽誤差超過容許（真實 run_cross_checks 重算）→ 該家 FAIL、輸出含項目與根因，PASS 不含該家
  I3: [邊界] 錨點缺 → 該家 FAIL、PASS 不含該家
  I4: 2887 整份 H1 PDF（本地存在才跑）npl.entity＝台新銀行、entities 為 2 家
fixture 只讀 tests/fixtures/tw_equity/fh_*.json（不讀 data/cache、不打 API）。
sabotage（任務驗收用，非常駐）：statements 勾稽容許誤差改 100000 → I2 FAIL；fh_acceptance._anchor_found 改恆真 → I3 FAIL。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.tw_equity import fh_acceptance as fa
from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import PageRange, find_annual_report_sections
from runtime.tw_equity.fh_acceptance import TICKERS, facts_from_bundle, judge_company, main, render_company
from runtime.tw_equity.fh_notes import extract_fh_notes
from runtime.tw_equity.fy_income import extract_fy_income
from runtime.tw_equity.metrics import compute_metrics
from runtime.tw_equity.statements import extract_statements, run_cross_checks

ROOT = Path(__file__).resolve().parent.parent.parent
_FIX = ROOT / "tests/fixtures/tw_equity"


def _load(name: str) -> dict:
    return json.loads((_FIX / name).read_text(encoding="utf-8"))


_ST, _NT, _FY, _AR = (_load(n) for n in (
    "fh_statements_pages.json", "fh_notes_pages.json", "fh_fy_income_pages.json", "fh_ar_headings.json"))

_CACHE: dict[str, tuple[SimpleNamespace, dict]] = {}


def bundle_and_anchors(t: str) -> tuple[SimpleNamespace, dict]:
    if t not in _CACHE:
        e = _ST[t]
        anchors = {k: (PageRange(*r) if r else None) for k, r in e["fs_anchors"].items()}
        led = extract_statements(pdf_doc.from_json(e["doc"]), anchors, group="fh")
        notes = extract_fh_notes(pdf_doc.from_json(_NT[t]["doc"]),
                                 bs_current_period=led.column_periods["bs"][led.current_col["bs"]])
        fy = extract_fy_income(pdf_doc.from_json(_FY[t]["doc"]),
                               {k: PageRange(start=v[0], end=v[1]) for k, v in _FY[t]["anchors"].items()},
                               roc_year=114, group="fh")
        bundle = SimpleNamespace(statements=led, fy_income=fy, fh_notes=notes, fh_notes_error=None,
                                 metrics=compute_metrics(led, fy, group="fh", notes=notes))
        ar_anchors = find_annual_report_sections(pdf_doc.from_json(_AR[t]["doc"]), required=set(), group="fh")
        _CACHE[t] = (bundle, ar_anchors)
    return _CACHE[t]


def facts(t: str, *, bundle=None, ar_anchors=None) -> dict:
    b, a = bundle_and_anchors(t)
    return facts_from_bundle(t, bundle or b, ar_anchors or a)


@pytest.mark.parametrize("t", TICKERS)
def test_fixture_facts_map_to_every_threshold(t):  # I1
    f = facts(t)
    v = judge_company(t, f)
    assert v["ok"] is True, v["failures"]
    assert len(f["checks"]) == 18 and all(c["passed"] is True for c in f["checks"])  # §0.3-1
    assert all(isinstance(f["anchors"][k], int) for k in fa.ANCHOR_KEYS)  # §0.3-3
    assert f["fy"]["usable"] is True and f["fy"]["scope"] == fa.EXPECTED_SCOPE[t]  # §0.3-4
    assert f["ttm"]["status"] == "ok" and f["ttm"]["scope"] == fa.EXPECTED_SCOPE[t]
    assert (f["npl"]["npl_ratio"], f["npl"]["coverage_ratio"]) == fa.EXPECTED_NPL[t]  # §0.3-5
    assert (f["car"]["value"], f["car"]["period"]) == fa.EXPECTED_CAR[t]
    assert abs(f["bridge_residual"]) <= 2  # §0.3-6
    assert isinstance(f["ifrs17_break"], bool) and isinstance(f["n_unmapped"], int)


def test_cli_over_fixture_facts_is_pass_6_of_6(capsys):  # I1
    assert main([], collect=facts) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "PASS 6/6"


def _perturbed_bundle(t: str, delta: float):
    """取 fixture 帳本、把 IS net_income 現期值加 delta，勾稽以真實 run_cross_checks 重算。"""
    b, _ = bundle_and_anchors(t)
    led = b.statements
    rows = [dataclasses.replace(r, current=r.current + delta) if r.statement == "is" and r.key == "net_income" and
            r.current is not None else r for r in led.rows]
    new = dataclasses.replace(led, rows=rows, checks=run_cross_checks(rows, led.column_periods, schema="fh"))
    return SimpleNamespace(**{**vars(b), "statements": new})


def test_check_beyond_tolerance_fails_company_and_excluded_from_pass(capsys):  # I2
    def collect(t):
        return facts(t, bundle=_perturbed_bundle(t, 5000.0)) if t == "2886" else facts(t)
    rc = main([], collect=collect)
    out = capsys.readouterr().out
    assert rc != 0 and out.strip().splitlines()[-1] == "PASS 5/6"
    assert "[2886] FAIL" in out and all(f"[{t}] PASS" in out for t in TICKERS if t != "2886")
    line = next(x for x in out.splitlines() if "FAIL 家別=2886" in x and "is_net_income" in x)
    assert "根因=" in line
    v = judge_company("2886", facts("2886", bundle=_perturbed_bundle("2886", 5000.0)))
    assert "is_net_income" in render_company(v)


def test_missing_anchor_fails_company_and_excluded_from_pass(capsys):  # I3
    def collect(t):
        if t != "2891":
            return facts(t)
        _, a = bundle_and_anchors(t)
        return facts(t, ar_anchors={**a, "ar_mdna": None})
    rc = main([], collect=collect)
    out = capsys.readouterr().out
    assert rc != 0 and out.strip().splitlines()[-1] == "PASS 5/6"
    assert "[2891] FAIL" in out and "錨點:ar_mdna" in out


_PDF_2887 = ROOT / "tw_report/2887_2026Q2財報.pdf"


@pytest.mark.skipif(not _PDF_2887.exists(), reason="本地無 2887 H1 PDF")
def test_2887_full_pdf_entity_is_taishin_with_two_entities():  # I4
    n = extract_fh_notes(pdf_doc.load_pdf(_PDF_2887))
    assert n.npl["entity"] == "台新銀行" and len(n.npl["entities"]) == 2
