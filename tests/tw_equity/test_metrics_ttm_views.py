"""TTM／FY 兩期指標、2 個 bridge 與 TtmView.to_dict（period-model item 3.2，Spec §3.2）。

契約 row：
  V1: TTM gross_margin＝TTM gross_profit/TTM revenue×100（兩期各自）
  V2: fcf 等 CF 類指標兩期皆 None
  V3: operating_income bridge 殘差＝target_delta − Σ非 None delta、top_drivers ≤3
  V4: net_income bridge 含 5 個 component
  V5: to_dict()["ttm_vs_fy"]["assurance"]=="mixed"、source_page==fy_income.page、values[k] 含 fy／h1_current／h1_prior／ttm，可 json.dumps
  V6: [邊界] status=="unavailable" 時 metrics／bridges 為空 list、values 為空 dict、reason 保留
fixture 沿用 test_metrics_ttm_values.py 的合成帳本與 FyIncome（單一出處）；
預期值：FY 損益 revenue 1000/cogs -500/gross_profit 500/total_opex -200/operating_income 300/
net_income 260；H1 (cur,prior) revenue (600,500)、cogs (-300,-250)、gross_profit (300,250)、
total_opex (-100,-90)、operating_income (200,160)。
"""
from __future__ import annotations

import json

from runtime.tw_equity.metrics import compute_metrics
from tests.tw_equity.test_metrics_ttm_values import _fy, _ledger


def _ttm():
    return compute_metrics(_ledger(), _fy()).ttm


def test_gross_margin_both_periods():  # V1
    t = _ttm()
    assert t.get("gross_margin", "ttm") == (500 + 300 - 250) / (1000 + 600 - 500) * 100
    assert t.get("gross_margin", "fy") == 500 / 1000 * 100


def test_cf_metrics_none_both_periods():  # V2
    t = _ttm()
    for period in ("ttm", "fy"):
        assert t.get("fcf", period) is None
        assert t.get("cfo_to_net_income", period) is None


def test_operating_income_bridge():  # V3
    b = {x.target: x for x in _ttm().bridges}["operating_income"]
    assert (b.target_current, b.target_prior, b.target_delta) == (340, 300, 40)
    assert {c.key for c in b.components} == {"revenue", "cogs", "total_opex"}
    known = [c.delta for c in b.components if c.delta is not None]
    assert b.residual == b.target_delta - sum(known)
    assert len(b.top_drivers) <= 3 and b.top_drivers[0] == "revenue"


def test_net_income_bridge_has_five_components():  # V4
    b = {x.target: x for x in _ttm().bridges}["net_income"]
    assert [c.key for c in b.components].__len__() == 5
    assert {c.key for c in b.components} == {"revenue", "cogs", "total_opex", "nonoperating_total", "income_tax"}
    assert b.target_delta == 295 - 260
    assert [x.target for x in _ttm().bridges] == ["operating_income", "net_income"]


def test_to_dict_shape_ok():  # V5
    d = compute_metrics(_ledger(), _fy()).to_dict()["ttm_vs_fy"]
    assert d["status"] == "ok" and d["assurance"] == "mixed" and d["source_page"] == 7
    for k in ("reason", "period_ttm", "period_fy", "values", "metrics", "bridges", "index"):
        assert k in d
    assert d["metrics"] and len(d["bridges"]) == 2
    for k, v in d["values"].items():
        assert {"fy", "h1_current", "h1_prior", "ttm"} <= set(v)
    json.dumps(d)


def test_to_dict_unavailable_keeps_reason():  # V6
    d = compute_metrics(_ledger(), _fy(usable=False)).to_dict()["ttm_vs_fy"]
    assert d["status"] == "unavailable" and d["reason"]
    assert d["metrics"] == [] and d["bridges"] == [] and d["values"] == {}
    json.dumps(d)
