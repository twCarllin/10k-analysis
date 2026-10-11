"""run 2026-10-11-tw-equity-sign-fix Task 1：bridge 費用符號正規化（1.1）、有效稅率（1.2）、折舊別名（1.4）。
信用成本率（1.3）見 test_fh_metrics.test_credit_cost_sign_provision。"""
import pytest

from runtime.tw_equity import metrics
from runtime.tw_equity.metrics import compute_bridges, compute_metrics
from runtime.tw_equity.qa import _gross_topics
from runtime.tw_equity.statements import StatementLedger, StatementRow, map_key

_PERIODS = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
            "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": "114-12-31"}

# 損益：營收／費用絕對值（cur, pri）；net_income = 營收 − 成本 − 三費 − 財務成本 − 所得稅
_ABS = {"revenue": (1000, 800), "cogs": (600, 500), "selling_expenses": (50, 40), "admin_expenses": (30, 20),
        "rd_expenses": (60, 50), "finance_costs": (5, 4), "income_tax": (40, 30)}
_EXPENSE = ("cogs", "selling_expenses", "admin_expenses", "rd_expenses", "finance_costs", "income_tax", "total_opex")


def _ledger(sign: int, tax_label: str = "所得稅費用", extra: dict | None = None) -> StatementLedger:
    """sign=+1 費用印正數、-1 費用印負數；其餘收入／損益項固定原值。"""
    vals = {k: v for k, v in _ABS.items()}
    vals["total_opex"] = (140, 110)
    vals["operating_income"] = (260, 190)
    vals["net_income"] = (215, 156)
    vals["pretax_income"] = (255, 186)
    vals["gross_profit"] = (400, 300)
    vals.update(extra or {})
    rows = []
    for i, (k, (c, p)) in enumerate(vals.items()):
        if k in _EXPENSE and k not in (extra or {}):  # extra 的值視為帳本原值，不再套 sign
            c, p = sign * abs(c), sign * abs(p)
        label = tax_label if k == "income_tax" else k
        rows.append(StatementRow("is", None, label, k, None, c, p, None, None, 1, i, columns=[c, p]))
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": [], "is": [_PERIODS["flow_current"], _PERIODS["flow_prior"]], "cf": []},
        basis="H1", periods=dict(_PERIODS), days={"current": 181, "prior": 181})


def _bridges(led):
    return {b.target: b for b in compute_bridges(led, compute_metrics(led))}


@pytest.mark.parametrize("target", ["net_income", "operating_income"])
def test_bridge_residual_zero_for_both_print_styles(target):
    pos, neg = _bridges(_ledger(+1))[target], _bridges(_ledger(-1))[target]
    assert pos.residual == pytest.approx(0)
    assert neg.residual == pytest.approx(0)
    # 費用印負數的公司結果不變：兩種印法的組成項 delta 完全一致
    assert {c.key: c.delta for c in pos.components} == {c.key: c.delta for c in neg.components}


def test_cogs_and_expense_components_have_contribution_sign():
    comps = {c.key: c for c in _bridges(_ledger(+1))["net_income"].components}
    assert comps["cogs"].delta == -100          # 成本增加 100 → 對淨利 −100
    assert comps["revenue"].delta == 200        # 收入照原值
    assert comps["rd_expenses"].delta == -10


def test_mutation_self_check_unnormalized_has_big_residual(monkeypatch):
    led = _ledger(+1)
    target = _bridges(led)["net_income"]
    assert abs(target.residual) < 0.05 * abs(target.target_delta)           # patch 前：正常
    monkeypatch.setattr(metrics, "_SIGNED_BRIDGE_KEYS", ())          # patch：退回原值相加
    broken = _bridges(led)["net_income"]
    assert abs(broken.residual) > 0.05 * abs(broken.target_delta)           # patch 後：偏離


@pytest.mark.parametrize("label,cur,pri,exp_cur,exp_pri", [
    ("所得稅(費用)利益", -40, 10, -40, 10),     # (費用)：照原值
    ("所得稅費用(利益)", 40, -10, -40, 10),     # (利益)：取 −v
    ("所得稅費用", 40, 30, -40, -30),           # 無括號詞：依帳上「淨利−稅前」定號，無法對照則 −|v|
])
def test_income_tax_bridge_value_by_label(label, cur, pri, exp_cur, exp_pri):
    comp = next(c for c in _bridges(_ledger(+1, tax_label=label, extra={"income_tax": (cur, pri)}))
                ["net_income"].components if c.key == "income_tax")
    assert (comp.current, comp.prior) == (exp_cur, exp_pri)


def test_income_tax_no_paren_negative_print_uses_neg_abs():
    comp = next(c for c in _bridges(_ledger(-1))["net_income"].components if c.key == "income_tax")
    assert (comp.current, comp.prior) == (-40, -30)


def test_gross_profit_bridge_cost_direction():
    for sign in (+1, -1):
        led = _ledger(sign)
        topic = _gross_topics(led, compute_metrics(led))["bridge:gross_profit"]
        comps = {c["key"]: c for c in topic["components"]}
        assert comps["cogs"]["delta"] == -100
        assert comps["revenue"]["delta"] == 200


def _rate(led, period):
    return compute_metrics(led).get("effective_tax_rate", period)


def test_effective_tax_rate_normal_unchanged():
    for sign in (+1, -1):
        assert _rate(_ledger(sign), "current") == pytest.approx(40 / 255 * 100)
        assert _rate(_ledger(sign), "prior") == pytest.approx(30 / 186 * 100)


def test_effective_tax_rate_negative_for_tax_benefit():
    # 2002 前期形態：標題「所得稅費用(利益)」且數值為負 → 稅利益 → 稅率為負
    led = _ledger(+1, tax_label="所得稅費用(利益)", extra={"income_tax": (40, -10)})
    assert _rate(led, "current") == pytest.approx(40 / 255 * 100)
    assert _rate(led, "prior") == pytest.approx(-10 / 186 * 100)
    # 「所得稅(費用)利益」且數值為正 → 稅利益
    led2 = _ledger(+1, tax_label="所得稅(費用)利益", extra={"income_tax": (-40, 10)})
    assert _rate(led2, "current") == pytest.approx(40 / 255 * 100)
    assert _rate(led2, "prior") == pytest.approx(-10 / 186 * 100)


_DEP_LABELS = [
    ("不影響現金流量之收益費損項目:折舊費用", "調整項目"),
    ("不影響現金流量之收益費損項目折舊費用(含投資性不動產及使用權資產)", "調整項目"),
    ("折舊費用(含使用權資產)", "調整項目"),
    ("折舊費用(含投資性不動產及使用權資產)", "調整項目"),
    ("不動產、廠房及設備折舊費用", "調整項目"),
    ("折舊", "調整項目"),
    ("折舊及攤銷費用", "調整項目"),
    ("折舊及攤銷", "調整項目"),
    ("不影響現金流量之收益費損項目折舊費用", "調整項目"),
    ("折舊及折耗費用", "調整項目"),
    ("折舊費用", "調整項目"),
]


@pytest.mark.parametrize("label,section", _DEP_LABELS)
def test_depreciation_aliases_map_in_cf(label, section):
    assert map_key("cf", label, section) == "depreciation"


@pytest.mark.parametrize("label,statement,section", [
    ("攤銷費用", "cf", "調整項目"),                                    # 仍是 amortization
    ("按攤銷後成本衡量之金融資產", "cf", "調整項目"),
    ("取得按攤銷後成本衡量之金融資產", "cf", "投資活動之現金流量"),
    ("使用權資產折舊費用", "cf", "調整項目"),                          # 相近但不在別名集合
    ("折舊", "cf", "投資活動之現金流量"),                              # 非調整區段
    ("折舊", "cf", "籌資活動之現金流量"),
    ("折舊", "is", "營業費用"),                                        # 非現金流量表
])
def test_depreciation_alias_near_misses_do_not_map(label, statement, section):
    assert map_key(statement, label, section) != "depreciation"


def test_amortization_alias_still_maps():
    assert map_key("cf", "攤銷費用", "調整項目") == "amortization"


# ── 1.5 所得稅符號規則（Spec §6 A2）：無括號詞 → 用 net_income − pretax_income 判斷 ──────────────────

from runtime.tw_equity.fy_income import normalize_sign  # noqa: E402


@pytest.mark.parametrize("tax,ni,pt,expected", [
    (-2945021, 6842729, 9787750, -2945021),   # 3044 形態：成本印正、稅印負（費用）
    (2945021, 6842729, 9787750, -2945021),    # 稅印正數的費用
    (10, 110, 100, 10),                       # 稅利益（淨利 > 稅前）印正數 → 正
    (-10, 110, 100, 10),                      # 稅利益印負數 → 仍取利益的正值
    (40, 61, 100, -40),                       # 差額 39、原值 40：差 1 仟元（容差內）→ 取差額符號（負）
    (40, 160, 100, -40),                      # 差額 +60 與 |40| 不符 → 退回 −|v|
])
def test_normalize_sign_income_tax_by_balance(tax, ni, pt, expected):
    assert normalize_sign("income_tax", "所得稅費用", tax, None, pt, ni) == expected


def test_normalize_sign_income_tax_tolerance_edge_and_fallback():
    assert normalize_sign("income_tax", "所得稅費用", 10, None, 100, 91) == -10    # 差額 −9、相差 1 → 取負
    assert normalize_sign("income_tax", "所得稅費用", 10, None, 100, 111) == 10    # 差額 +11、相差 1 → 取正
    assert normalize_sign("income_tax", "所得稅費用", 10, None, 100, 112) == -10   # 相差 2 → 退回 −|v|
    assert normalize_sign("income_tax", "所得稅費用", 10, None, None, 110) == -10  # 缺稅前 → −|v|
    assert normalize_sign("income_tax", "所得稅費用", 10, None, 100, None) == -10  # 缺淨利 → −|v|
    # 有括號詞時不看帳上關係
    assert normalize_sign("income_tax", "所得稅(費用)利益", -40, None, 100, 160) == -40
    assert normalize_sign("income_tax", "所得稅費用(利益)", -10, None, 100, 60) == 10
    # 有停業單位（2449／2890 型）：淨利−稅前 ＝ −稅＋停業單位損益，|差額| ≠ |稅| → 退回 −|v|
    assert normalize_sign("income_tax", "所得稅費用", -10, None, 100, 150) == -10   # 稅費 10、停業單位 +60
    # 已知限制：稅利益且無括號詞、又有停業單位時，同樣退回 −|v|（判為費用）
    assert normalize_sign("income_tax", "所得稅費用", 10, None, 100, 170) == -10    # 稅利益 10、停業單位 +60


def test_mutation_self_check_income_tax_balance_inputs():
    args = ("income_tax", "所得稅費用", 10, None)
    assert normalize_sign(*args, 100, 110) == 10      # 帶入淨利／稅前：判成利益
    assert normalize_sign(*args, None, None) == -10   # 拿掉輸入（舊行為／退回）：偏離


@pytest.mark.parametrize("sign_tax", [(-40, -30), (40, 30)])
def test_bridge_and_ttm_share_income_tax_rule(sign_tax):
    # 3044／6274／2609 形態：cogs 印正數、稅印負數（無括號詞）→ 兩條路徑都取負值
    led = _ledger(+1, extra={"income_tax": sign_tax})
    comp = next(c for c in _bridges(led)["net_income"].components if c.key == "income_tax")
    assert (comp.current, comp.prior) == (-40, -30)
    assert metrics._h1_normalized(led, "income_tax", "flow_current", "flow_current") == -40
    assert metrics._h1_normalized(led, "income_tax", "flow_prior", "flow_prior") == -30
    assert _bridges(led)["net_income"].residual == pytest.approx(0)


# ── 1.6 淨利 bridge 組成項（Spec §6 A3）────────────────────────────────────────────────────────────


@pytest.mark.parametrize("label,key", [
    ("其他營業收益及費損淨額", "other_operating_net"),
    ("採用權益法認列之關聯企業損益份額", "equity_method_share"),
    ("採用權益法認列之關聯企業及合資損益之份額", "equity_method_share"),
    ("外幣兌換淨益(損)", "fx_gain_loss"),
    ("外幣兌換利益(損失)", "fx_gain_loss"),
    ("其他利益及損失淨額", "other_gains_losses"),
])
def test_is_aliases_map_to_net_income_bridge_components(label, key):
    assert map_key("is", label, "營業外收入及支出") == key


@pytest.mark.parametrize("label", [
    "採用權益法認列之關聯企業之其他綜合損益份額",   # OCI 項，不是損益份額
    "國外營運機構財務報表換算之兌換差額",           # 保持 fx_translation_difference
    "外幣兌換差額",
    "其他利益及損失淨額合計",
])
def test_is_alias_near_misses_do_not_map(label):
    assert map_key("is", label, "營業外收入及支出") not in ("equity_method_share", "fx_gain_loss",
                                                              "other_gains_losses", "other_operating_net")


def test_fx_alias_not_applied_to_cf():
    assert map_key("cf", "外幣兌換淨益(損)", "調整項目") != "fx_gain_loss"


def test_net_income_bridge_includes_new_components_residual_zero():
    extra = {"other_operating_net": (10, 5), "fx_gain_loss": (20, -5), "equity_method_share": (7, 2),
             "other_gains_losses": (3, 1), "net_income": (255, 159), "pretax_income": (295, 189)}
    b = _bridges(_ledger(+1, extra=extra))["net_income"]
    assert b.residual == pytest.approx(0)
    assert {"other_operating_net", "fx_gain_loss"} <= {c.key for c in b.components}
