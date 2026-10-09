"""TtmView 可用條件與 TTM 損益組成（period-model item 3.1，Spec §3.2、§2.7 第 4、6 點）。

契約 row：
  T1: H1 帳本 revenue (600,500)、FY revenue 1000 → ttm["revenue"]==1100
  T2: cogs 帳本 (-300,-250)、FY 取 -abs → ttm 依正規化後相加
  T3: fy_income.usable False 或 roc_year 與 flow_prior 年不符 → status=="unavailable" 且 reason 非空字串
  T4: ledger basis=="FY" → ttm is None
  T5: [邊界] 任一 key 的 fy／h1_cur／h1_prior 為 None → 該 ttm[k] None，其他 key 不受影響
  T6: 不傳 fy_income → H1 帳本 ttm 為 unavailable，主視圖指標不變；to_dict 可 json.dumps
  T7: net_income_basis=="parent" → net_income 的 H1 兩期取 net_income_parent，values 帶 basis "parent"
  T8: 帳本 unit 非仟元／千元 → unavailable，reason "unit_mismatch"
  T9: 帳本 H1 income_tax 依 §2.4 正規化（與 FY 同規則）
fixture 為合成物件（非 PDF 頁文字）；StatementRow／FyIncome 欄位依據 statements.py:StatementRow、fy_income.py:FyIncome。
"""
from __future__ import annotations

import json

from runtime.tw_equity.fy_income import FyIncome
from runtime.tw_equity.metrics import TTM_KEYS, TtmView, compute_metrics
from runtime.tw_equity.statements import StatementLedger, StatementRow

_PERIODS = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
            "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": "114-12-31"}


def _row(st, key, cur, pri, columns, label=None):
    return StatementRow(st, None, label or key, key, None, cur, pri, None, None, 1, 0, columns=columns)


def _ledger(extra=(), basis="H1", unit="仟元", periods=None, drop=()) -> StatementLedger:
    rows = [
        _row("is", "revenue", 600, 500, [600, 500]),
        _row("is", "cogs", -300, -250, [-300, -250]),
        _row("is", "gross_profit", 300, 250, [300, 250]),
        _row("is", "total_opex", -100, -90, [-100, -90]),
        _row("is", "operating_income", 200, 160, [200, 160]),
        _row("is", "nonoperating_total", 10, 5, [10, 5]),
        _row("is", "pretax_income", 210, 165, [210, 165]),
        _row("is", "income_tax", -40, -30, [-40, -30], label="所得稅費用"),
        _row("is", "net_income", 170, 135, [170, 135]),
        _row("is", "net_income_parent", 150, 120, [150, 120]),
        _row("bs", "total_assets", 1000, 0, [1000, 900, 800]),
        _row("bs", "cash", 50, 0, [50, 30, 40]),
    ]
    rows = [r for r in rows if r.key not in drop] + list(extra)
    return StatementLedger(
        unit=unit, period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": ["115-06-30", "114-12-31", "114-06-30"],
                        "is": ["115-01-01~115-06-30", "114-01-01~114-06-30"], "cf": []},
        basis=basis, periods=dict(periods or _PERIODS), days={"current": 181, "prior": 181})


def _fy(roc_year=114, usable=True, net_income_basis="total", drop=(), income_tax_label="所得稅費用") -> FyIncome:
    cur = {"revenue": 1000, "cogs": 500, "gross_profit": 500, "total_opex": 200, "operating_income": 300,
           "nonoperating_total": 20, "pretax_income": 320, "income_tax": 60, "net_income": 260}
    rows = [{"label": income_tax_label if k == "income_tax" else k, "key": k, "current": v, "prior": v}
            for k, v in cur.items() if k not in drop]
    return FyIncome(roc_year=roc_year, page=7, unit="仟元", scale=1.0, rows=rows, usable=usable,
                    net_income_basis=net_income_basis)


def test_ttm_revenue_adds_fy_and_h1_delta():  # T1
    pack = compute_metrics(_ledger(), _fy())
    assert isinstance(pack.ttm, TtmView) and pack.ttm.status == "ok"
    assert pack.ttm.values["revenue"] == {"fy": 1000, "h1_current": 600, "h1_prior": 500, "ttm": 1100}
    assert set(TTM_KEYS) <= set(pack.ttm.values)


def test_ttm_cogs_uses_normalized_values():  # T2
    ttm = compute_metrics(_ledger(), _fy()).ttm
    # FY 原值 +500 取 -abs → -500；H1 (-300,-250)；ttm = -500 + -300 - -250
    assert ttm.values["cogs"] == {"fy": -500, "h1_current": -300, "h1_prior": -250, "ttm": -550}


def test_ttm_unavailable_when_fy_unusable_or_year_mismatch():  # T3
    for fy in (_fy(usable=False), _fy(roc_year=113)):
        ttm = compute_metrics(_ledger(), fy).ttm
        assert ttm.status == "unavailable"
        assert isinstance(ttm.reason, str) and ttm.reason
        assert ttm.metrics == [] and ttm.bridges == [] and ttm.values == {}


def test_ttm_none_for_fy_basis_ledger():  # T4
    pack = compute_metrics(_ledger(basis="FY"), _fy())
    assert pack.ttm is None
    assert pack.to_dict()["ttm_vs_fy"] is None


def test_ttm_missing_key_isolated():  # T5
    base = compute_metrics(_ledger(), _fy()).ttm.values
    for pack in (compute_metrics(_ledger(), _fy(drop=("revenue",))),          # fy 缺
                 compute_metrics(_ledger(drop=("revenue",)), _fy())):         # h1 缺
        v = pack.ttm.values
        assert v["revenue"]["ttm"] is None
        for k in [k for k in TTM_KEYS if k != "revenue"]:
            assert v[k]["ttm"] == base[k]["ttm"]
    # h1_prior 單獨缺：以只有 current 欄的列模擬（欄不存在 → None）
    short = _ledger(drop=("revenue",), extra=(_row("is", "revenue", 600, 500, [600]),))
    v = compute_metrics(short, _fy()).ttm.values
    assert v["revenue"]["h1_prior"] is None and v["revenue"]["ttm"] is None
    assert v["cogs"]["ttm"] == base["cogs"]["ttm"]


def test_no_fy_income_gives_unavailable_and_json_dict():  # T6
    with_fy = compute_metrics(_ledger(), _fy())
    without = compute_metrics(_ledger())
    assert without.ttm.status == "unavailable" and without.ttm.reason
    assert [m.to_dict() for m in without.metrics] == [m.to_dict() for m in with_fy.metrics]
    d = with_fy.to_dict()
    assert d["ttm_vs_fy"]["status"] == "ok"
    json.dumps(d)


def test_parent_net_income_substitution():  # T7
    ttm = compute_metrics(_ledger(), _fy(net_income_basis="parent")).ttm
    ni = ttm.values["net_income"]
    assert ni["basis"] == "parent"
    assert (ni["h1_current"], ni["h1_prior"]) == (150, 120)
    assert ni["ttm"] == 260 + 150 - 120
    assert "basis" not in ttm.values["revenue"]


def test_unit_mismatch_unavailable():  # T8
    ttm = compute_metrics(_ledger(unit="元"), _fy()).ttm
    assert ttm.status == "unavailable" and ttm.reason == "unit_mismatch"


def test_h1_income_tax_normalized_like_fy():  # T9
    # 標籤含 (利益)：帳本值 -x；FY 同標籤同規則
    led = _ledger(drop=("income_tax",),
                  extra=(_row("is", "income_tax", 40, 30, [40, 30], label="所得稅(利益)"),))
    v = compute_metrics(led, _fy(income_tax_label="所得稅(利益)")).ttm.values["income_tax"]
    assert (v["fy"], v["h1_current"], v["h1_prior"]) == (-60, -40, -30)
    assert v["ttm"] == -60 - 40 + 30


# 補斷言（reason 具體碼；主 flow 裁決 row「ledger basis=="other" → unavailable、reason ledger_not_h1」）
def test_unavailable_reason_codes():
    other = compute_metrics(_ledger(basis="other"), _fy()).ttm
    assert other.status == "unavailable" and other.reason == "ledger_not_h1"
    assert compute_metrics(_ledger(), None).ttm.reason == "fy_income_missing"
    assert compute_metrics(_ledger(), _fy(usable=False)).ttm.reason == "fy_income_unusable"
