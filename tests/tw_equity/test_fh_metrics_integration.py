"""test_fh_metrics_integration.py — run 2026-10-09-tw-equity-fh-schema item 3.5：6 家金控 fh 指標全流程。

契約表：
  I1: 6 家 metrics key 集合＝§3 的 13 項
  I2: 附註指標值等於 Spec §4 期望（group_car：2881 139.13／2882 120.22／2885 130.70／2886 133.83 stale／2887 None／
      2891 125.07；npl_ratio／coverage_ratio 115-06-30 主值）
  I3: 2881／2882／2887／2891 ifrs17_break True；[邊界] 為 False 者 evidence 為 None
  I4: 6 家 bridge 殘差絕對值 ≤ 2 仟元
  I5: ROE＝net_income ÷ total_equity（期末）——sabotage（分母改 total_assets）必 FAIL；I3 對 ifrs17 恆 False 必 FAIL
全流程入口：extract_tables 需年報參數，故直接組 extract_statements(group="fh")＋extract_fh_notes＋
compute_metrics(group="fh", notes=…)（比照 item 1.5 裁決）。三表 fixture 與附註 fixture 分別餵給對應函式。
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
from runtime.tw_equity.fh_notes import extract_fh_notes  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_ST = json.loads((_FIX / "fh_statements_pages.json").read_text(encoding="utf-8"))
_NT = json.loads((_FIX / "fh_notes_pages.json").read_text(encoding="utf-8"))
_TICKERS = ("2881", "2882", "2885", "2886", "2887", "2891")

_KEYS_13 = {"equity_to_assets", "group_car", "npl_ratio", "coverage_ratio", "credit_cost", "cost_income_ratio",
            "roa", "roe", "nii_share", "fee_share", "pretax_margin", "loan_to_deposit", "liquid_to_assets"}
_CAR = {"2881": 139.13, "2882": 120.22, "2885": 130.70, "2886": 133.83, "2887": None, "2891": 125.07}
_NPL = {"2881": (0.11, 1112.78), "2882": (0.14, 1100.45), "2885": (0.11, 1091.36),
        "2886": (0.20, 813.14), "2887": (0.13, 922.63), "2891": (0.54, 280.47)}

_CACHE: dict[str, tuple] = {}


def _run(t: str):
    if t not in _CACHE:
        e = _ST[t]
        anchors = {k: (PageRange(*r) if r else None) for k, r in e["fs_anchors"].items()}
        led = extract_statements(pdf_doc.from_json(e["doc"]), anchors, group="fh")
        bs_cur = led.column_periods["bs"][led.current_col["bs"]]
        notes = extract_fh_notes(pdf_doc.from_json(_NT[t]["doc"]), bs_current_period=bs_cur)
        _CACHE[t] = (led, compute_metrics(led, None, group="fh", notes=notes))
    return _CACHE[t]


@pytest.mark.parametrize("t", _TICKERS)
def test_metric_keys_13(t):  # I1
    _, pack = _run(t)
    assert {m.key for m in pack.metrics} == _KEYS_13
    print(t, {k: pack.get(k) for k in sorted(_KEYS_13)})


@pytest.mark.parametrize("t", _TICKERS)
def test_notes_metrics_match_spec(t):  # I2
    _, pack = _run(t)
    car = pack.get("group_car")
    if _CAR[t] is None:
        assert car is None
    else:
        assert car == pytest.approx(_CAR[t])
        assert next(m for m in pack.metrics if m.key == "group_car" and m.period == "current").source["stale"] is True  # 6 家 car 期間皆早於 BS current
    npl, cov = _NPL[t]
    assert pack.get("npl_ratio") == pytest.approx(npl)
    assert pack.get("coverage_ratio") == pytest.approx(cov)


@pytest.mark.parametrize("t", _TICKERS)
def test_ifrs17_flag(t):  # I3
    _, pack = _run(t)
    assert isinstance(pack.ifrs17_break, bool)
    assert pack.ifrs17_break or t not in ("2881", "2882", "2887", "2891")  # Spec §7：至少這 4 家為 True
    # evidence 與旗標一致：False → None；True → 有原文列名
    assert (pack.ifrs17_evidence is None) == (not pack.ifrs17_break)
    assert not pack.ifrs17_break or pack.ifrs17_evidence["label"]
    print(t, pack.ifrs17_break, pack.ifrs17_evidence)


@pytest.mark.parametrize("t", _TICKERS)
def test_bridge_residual_within_2(t):  # I4
    _, pack = _run(t)
    b = pack.bridges[0]
    assert b.target == "net_income" and abs(b.residual) <= 2
    print(t, "residual", b.residual)


@pytest.mark.parametrize("t", _TICKERS)
def test_roe_is_period_end_equity(t):  # I5
    led, pack = _run(t)
    ni, eq = led.value_at("net_income", "flow_current"), led.value_at("total_equity", "bs_current")
    assert pack.get("roe") == pytest.approx(ni / eq * 100)
