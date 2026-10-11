"""run 2026-10-11-tw-equity-bridge-residual Task 1：bridge 組成項與別名（1.1 別名、1.2 組成項、1.3 合成項）。"""
import pytest

from runtime.tw_equity import metrics
from runtime.tw_equity.metrics import compute_bridges, compute_metrics
from runtime.tw_equity.statements import StatementLedger, StatementRow, map_key

_PERIODS = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
            "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": "114-12-31"}


def _ledger(rows: list[tuple], statement: str = "is") -> StatementLedger:
    """rows：(key, label, cur, pri)，依序成列；label 為 None 時用 key。值都是帳本原值。"""
    srows = [StatementRow(statement, None, lab or k, k, None, c, p, None, None, 1, i, columns=[c, p])
             for i, (k, lab, c, p) in enumerate(rows)]
    flow = [_PERIODS["flow_current"], _PERIODS["flow_prior"]]
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=srows, checks=[], unmapped_labels=[],
        column_periods={"bs": [], "is": flow if statement == "is" else [], "cf": flow if statement == "cf" else []},
        basis="H1", periods=dict(_PERIODS), days={"current": 181, "prior": 181})


def _bridges(led):
    return {b.target: b for b in compute_bridges(led, compute_metrics(led))}


def _comps(b):
    return {c.key: c for c in b.components}


# ── 1.1 別名 ─────────────────────────────────────────────────────────────────

_NEW_ALIASES = [
    ("預期信用減損迴轉利益", "ecl_operating"), ("預期信用減損利益(損失)", "ecl_operating"),
    ("預期信用(迴轉利益)減損損失", "ecl_operating"), ("預期信用減損損失(迴轉利益)", "ecl_operating"),
    ("預期信用減損損失(回升利益)", "ecl_operating"), ("預期信用減損(迴轉利益)損失", "ecl_operating"),
    ("預期信用減損(損失)利益", "ecl_operating"), ("非投資之預期信用減損損失", "ecl_operating"),
    ("採用權益法之關聯企業及合資損益份額", "equity_method_share"),
    ("採用權益法認列關聯企業及合資損益之份額", "equity_method_share"),
    ("採用權益法認列之關聯企業及合資(損)益之份額", "equity_method_share"),
    ("採用權益法認列之關聯企業損益之份額", "equity_method_share"),
    ("採用權益法認列之關聯企業利益(損失)之份額", "equity_method_share"),
    ("採用權益法認列之關聯企業及合資利益之份額", "equity_method_share"),
    ("採用權益法認列之關聯企業及合資利益(損失)之份額", "equity_method_share"),
    ("採用權益法認列之關聯企業損失份額", "equity_method_share"),
    ("採用權益法之關聯企業損益份額", "equity_method_share"),
    ("採用權益法認列關聯企業損益之份額", "equity_method_share"),
    ("外幣兌換損失", "fx_gain_loss"), ("外幣兌換利益", "fx_gain_loss"),
    ("研發費用", "rd_expenses"), ("管理及總務費用", "admin_expenses"),
    ("停業單位損益", "discontinued_ops"), ("停業單位利益", "discontinued_ops"),
    ("停業單位損失", "discontinued_ops"), ("停業單位淨利", "discontinued_ops"),
    ("停業單位損益合計", "discontinued_ops"),
]


@pytest.mark.parametrize("label,key", _NEW_ALIASES)
def test_new_aliases_map(label, key):
    assert map_key("is", label, "營業費用" if key in ("ecl_operating", "rd_expenses", "admin_expenses")
                   else "營業外收入及支出") == key


@pytest.mark.parametrize("label", [
    "採用權益法認列之關聯企業之其他綜合損益之份額",          # OCI 區段（Spec §2.2 反例）
    "採用權益法認列之關聯企業及合資之其他綜合損益份額",
    "採用權益法認列之關聯企業及合資之其他綜合利益(損失)之份額",
    "採用權益法認列之關聯企業及合資之其他綜合損益之份額-可能重分類至損益之項目",
])
def test_equity_method_oci_not_mapped(label):
    assert map_key("is", label, "不重分類至損益之項目") != "equity_method_share"
    assert map_key("is", label, "後續可能重分類至損益之項目") != "equity_method_share"


@pytest.mark.parametrize("label,not_key", [
    ("國外營運機構財務報表換算之兌換差額", "fx_gain_loss"),          # 兌換差額（OCI）不是兌換損益
    ("報表換算之兌換差額", "fx_gain_loss"),
    ("繼續營業單位淨利", "discontinued_ops"),                          # 繼續營業不是停業
    ("研究發展費用總額", "rd_expenses"),
])
def test_near_miss_labels_not_triggered(label, not_key):
    assert map_key("is", label, "營業外收入及支出") != not_key


def test_cf_ecl_label_unchanged():
    assert map_key("cf", "預期信用減損損失", "調整項目") == "impairment_loss_receivables"


# ── 1.2 組成項 ───────────────────────────────────────────────────────────────

def _base_rows(**over):
    """營收1000/800、成本600/500、毛利400/300、三費 −(50,30,60)/−(40,20,50)、營業利益260/190；
    營業外：利息收入10/8、財務成本−5/−4 → 稅前265/194；稅 −40/−30；淨利 225/164。"""
    r = {"revenue": (1000, 800), "cogs": (-600, -500), "gross_profit": (400, 300),
         "selling_expenses": (-50, -40), "admin_expenses": (-30, -20), "rd_expenses": (-60, -50),
         "total_opex": (-140, -110), "operating_income": (260, 190), "interest_income": (10, 8),
         "finance_costs": (-5, -4), "pretax_income": (265, 194), "income_tax": (-40, -30), "net_income": (225, 164)}
    r.update(over)
    return [(k, None, c, p) for k, (c, p) in r.items() if (c, p) != (None, None)]


def test_operating_income_adds_other_operating_net_and_ecl_after_total_opex():
    rows = [("revenue", None, 1000, 800), ("cogs", None, -600, -500), ("total_opex", None, -140, -110),
            ("other_operating_net", None, 30, -5), ("ecl_operating", None, -20, -10),
            ("operating_income", None, 270, 175)]
    b = _bridges(_ledger(rows))["operating_income"]
    assert {"other_operating_net", "ecl_operating"} <= {c.key for c in b.components}
    assert b.residual == pytest.approx(0)


def test_operating_income_ecl_inside_total_opex_not_double_counted():
    # 反例：預期信用減損列在 total_opex 之前（已含在小計內）→ 不加組成項，殘差仍為 0
    rows = [("revenue", None, 1000, 800), ("cogs", None, -600, -500), ("ecl_operating", None, -20, -10),
            ("total_opex", None, -140, -110), ("operating_income", None, 260, 190)]
    b = _bridges(_ledger(rows))["operating_income"]
    assert "ecl_operating" not in {c.key for c in b.components}
    assert b.residual == pytest.approx(0)


def test_net_income_has_ecl_and_discontinued_components():
    rows = _base_rows(ecl_operating=(-20, -10), operating_income=(240, 180), pretax_income=(245, 184),
                      discontinued_ops=(None, 300), net_income=(205, 454))
    # operating_income 240 ＝ 毛利 400 − 三費 140 − ecl 20；discontinued_ops 本期欄空白 → value_at 以 0 計
    led = _ledger(rows)
    b = _bridges(led)["net_income"]
    comps = _comps(b)
    assert {"ecl_operating", "discontinued_ops"} <= set(comps)
    assert comps["ecl_operating"].delta == -10
    assert comps["discontinued_ops"].delta == -300
    assert b.residual == pytest.approx(0)


def test_discontinued_ops_blank_current_column_is_zero_delta_full():
    led = _ledger(_base_rows(discontinued_ops=(0, 300), net_income=(225, 464)))
    assert _comps(_bridges(led)["net_income"])["discontinued_ops"].delta == -300


def test_fees_missing_uses_total_opex():
    rows = [r for r in _base_rows() if r[0] not in ("selling_expenses", "admin_expenses", "rd_expenses")]
    b = _bridges(_ledger(rows))["net_income"]
    keys = {c.key for c in b.components}
    assert "total_opex" in keys
    assert not keys & {"selling_expenses", "admin_expenses", "rd_expenses"}
    assert b.residual == pytest.approx(0)
    assert _comps(b)["other_opex_residual"].delta == 0  # Σ 扣的是 total_opex，不是三費 → 合成項為 0


def test_fees_present_do_not_use_total_opex():
    keys = {c.key for c in _bridges(_ledger(_base_rows()))["net_income"].components}
    assert "total_opex" not in keys and "selling_expenses" in keys


def test_cogs_total_preferred_over_cogs():
    rows = [r for r in _base_rows() if r[0] != "cogs"]
    rows += [("cogs", None, -500, -400), ("cogs_total", None, -600, -500)]
    comps = _comps(_bridges(_ledger(rows))["net_income"])
    assert (comps["cogs"].current, comps["cogs"].prior, comps["cogs"].delta) == (-600, -500, -100)


def test_cogs_used_when_no_cogs_total():
    comps = _comps(_bridges(_ledger(_base_rows()))["net_income"])
    assert comps["cogs"].current == -600


def test_cogs_total_printed_positive_is_normalized():
    rows = [r for r in _base_rows() if r[0] != "cogs"] + [("cogs_total", None, 600, 500)]
    assert _comps(_bridges(_ledger(rows))["net_income"])["cogs"].delta == -100


def test_single_step_uses_income_and_expense_totals():
    rows = [("income_total", None, 1000, 900), ("expense_total", None, 700, 650), ("pretax_income", None, 300, 250),
            ("income_tax", None, -50, -40), ("discontinued_ops", None, 10, 0), ("net_income", None, 260, 210)]
    b = _bridges(_ledger(rows))["net_income"]
    comps = _comps(b)
    assert set(comps) == {"income_total", "expense_total", "income_tax", "discontinued_ops"}
    assert comps["expense_total"].delta == -50   # 費用類走正規化：支出增加 → 對淨利負貢獻
    assert b.residual == pytest.approx(0)


def test_not_single_step_when_gross_profit_present():
    rows = _base_rows() + [("income_total", None, 1, 1), ("expense_total", None, 1, 1)]
    keys = {c.key for c in _bridges(_ledger(rows))["net_income"].components}
    assert "revenue" in keys and "income_total" not in keys


@pytest.mark.parametrize("label,cur,pri,exp_cur,exp_pri", [
    ("預期信用減損損失", 100, 80, -100, -80),            # 損失：−|v|（正負印法皆同）
    ("預期信用減損損失", -100, -80, -100, -80),
    ("預期信用減損利益(損失)", -100, 50, -100, 50),      # 帶貢獻符號 → 原值
    ("預期信用減損(損失)利益", -100, 50, -100, 50),
    ("預期信用減損損失(迴轉利益)", 100, -50, -100, 50),  # 費用口徑：正＝損失、負＝迴轉 → −v
    ("預期信用(迴轉利益)減損損失", -100, 50, 100, -50),
    ("預期信用減損迴轉利益", -100, -50, 100, 50),        # 只有利益 → +|v|
])
def test_ecl_sign_by_label(label, cur, pri, exp_cur, exp_pri):
    rows = [("revenue", None, 1000, 800), ("ecl_operating", label, cur, pri)]
    c = _comps(_bridges(_ledger(rows))["net_income"])["ecl_operating"]
    assert (c.current, c.prior) == (exp_cur, exp_pri)


def test_mutation_self_check_old_net_income_components_leave_residual(monkeypatch):
    rows = _base_rows(ecl_operating=(-20, -10), operating_income=(240, 180), pretax_income=(245, 184),
                      net_income=(205, 154))
    led = _ledger(rows)
    ok = _bridges(led)["net_income"]
    assert abs(ok.residual) < 1                                   # patch 前：殘差收斂
    old = ("revenue", "cogs", "selling_expenses", "admin_expenses", "rd_expenses", "interest_income", "other_income",
           "other_gains_losses", "finance_costs", "equity_method_share", "income_tax", "other_operating_net",
           "fx_gain_loss")
    monkeypatch.setattr(metrics, "_net_income_components", lambda ledger: old)   # patch：退回舊的固定組成項
    broken = _bridges(led)["net_income"]
    assert abs(broken.residual) >= 10                              # patch 後：ecl 漏掉 → 殘差偏離


def test_mutation_self_check_ecl_inside_total_opex_rule(monkeypatch):
    rows = [("revenue", None, 1000, 800), ("cogs", None, -600, -500), ("ecl_operating", None, -20, -10),
            ("total_opex", None, -140, -110), ("operating_income", None, 260, 190)]
    led = _ledger(rows)
    assert _bridges(led)["operating_income"].residual == pytest.approx(0)       # patch 前
    monkeypatch.setattr(metrics, "_operating_income_components",
                        lambda ledger: ("revenue", "cogs", "total_opex", "ecl_operating"))
    assert _bridges(led)["operating_income"].residual == pytest.approx(10)      # patch 後：重複計 −10 變動


def test_fcf_and_net_change_in_cash_bridges_unchanged():
    rows = [("cfo", None, 500, 400), ("capex", None, -200, -150), ("cfi", None, -300, -250), ("cff", None, -100, -50),
            ("fx_effect", None, 5, 3), ("net_change_in_cash", None, 105, 103)]
    br = _bridges(_ledger(rows, statement="cf"))
    assert [c.key for c in br["fcf"].components] == ["cfo", "capex"]
    assert {c.key: c.delta for c in br["net_change_in_cash"].components} == {"cfo": 100, "cfi": -50, "cff": -50,
                                                                              "fx_effect": 2}
    assert not any(c.synthetic for t in ("fcf", "net_change_in_cash") for c in br[t].components)


# ── 1.3 合成組成項 ───────────────────────────────────────────────────────────

def _synth_rows():
    """未對到 key 的業外列：合計 本期 +30（租金收入 20、處分損失 10 淨）／上期 +12（租金 15、損失 −3）；
    營業費用另有未對到的「其他營業費用」列：本期 −7／上期 −3。"""
    return [("revenue", None, 1000, 800), ("cogs", None, -600, -500), ("gross_profit", None, 400, 300),
            ("selling_expenses", None, -50, -40), ("admin_expenses", None, -30, -20), ("rd_expenses", None, -60, -50),
            ("operating_income", None, 253, 187),                      # 400−140−7 ／ 300−110−3
            ("interest_income", None, 10, 8), ("finance_costs", None, -5, -4),
            ("pretax_income", None, 288, 203),                         # 253+10−5+30 ／ 187+8−4+12
            ("income_tax", None, -40, -30), ("net_income", None, 248, 173)]


def test_synthetic_components_equal_unmatched_rows():
    b = _bridges(_ledger(_synth_rows()))["net_income"]
    comps = _comps(b)
    nonop, opex = comps["other_nonoperating_residual"], comps["other_opex_residual"]
    assert (nonop.current, nonop.prior, nonop.delta) == (30, 12, 18)   # 未對到的業外列合計
    assert (opex.current, opex.prior, opex.delta) == (-7, -3, -4)
    assert nonop.name == "其他營業外收支" and opex.name == "其他營業費用"
    assert b.residual == pytest.approx(0)


def test_synthetic_none_when_subtotal_missing():
    rows = [r for r in _synth_rows() if r[0] != "pretax_income"]
    b = _bridges(_ledger(rows))["net_income"]
    comps = _comps(b)
    assert comps["other_nonoperating_residual"].delta is None
    assert comps["other_nonoperating_residual"].current is None
    assert comps["other_opex_residual"].delta == -4                      # 不影響另一個合成項
    rows = [r for r in _synth_rows() if r[0] != "gross_profit"]
    assert _comps(_bridges(_ledger(rows))["net_income"])["other_opex_residual"].delta is None


def test_synthetic_flag_in_to_dict_only_for_synthetic():
    d = _bridges(_ledger(_synth_rows()))["net_income"].to_dict()
    flags = {c["key"]: c.get("synthetic") for c in d["components"]}
    assert flags["other_opex_residual"] is True and flags["other_nonoperating_residual"] is True
    assert flags["revenue"] is None
    assert {"key", "name", "current", "prior", "delta", "share"} <= set(d["components"][0])


def test_synthetic_zero_when_all_rows_matched():
    comps = _comps(_bridges(_ledger(_base_rows()))["net_income"])
    assert comps["other_opex_residual"].delta == 0 and comps["other_nonoperating_residual"].delta == 0


def test_operating_income_bridge_has_no_synthetic():
    b = _bridges(_ledger(_synth_rows()))["operating_income"]
    assert not any(c.synthetic for c in b.components)


def test_mutation_self_check_synthetic_excludes_matched_detail(monkeypatch):
    led = _ledger(_synth_rows())
    assert _comps(_bridges(led)["net_income"])["other_nonoperating_residual"].delta == 18   # patch 前
    monkeypatch.setattr(metrics, "_NONOP_DETAIL_KEYS", ())          # patch：不扣已對到的業外明細
    d = _comps(_bridges(led)["net_income"])["other_nonoperating_residual"].delta
    assert d != 18                                                   # patch 後：偏離（含利息收入、財務成本的變動）


def test_operating_income_bridge_prefers_cogs_total_mutation_self_check(monkeypatch):
    rows = [("revenue", None, 1000, 800), ("cogs", None, -500, -450), ("cogs_total", None, -600, -500),
            ("total_opex", None, -140, -110), ("operating_income", None, 260, 190)]
    led = _ledger(rows)
    ok = _bridges(led)["operating_income"]
    assert ok.residual == pytest.approx(0)                                  # patch 前：用 cogs_total，殘差 0
    real = metrics._has_row
    monkeypatch.setattr(metrics, "_has_row", lambda l, k: False if k == "cogs_total" else real(l, k))
    broken = _bridges(led)["operating_income"]
    assert broken.residual == pytest.approx(-50)                            # patch 後：退回 cogs，漏掉 50 的成本變動


# ── 審查 🟡-4：補對照式 mutation self-check（三費退回 total_opex、單步式、discontinued_ops） ──────


def test_mutation_self_check_fees_fallback_to_total_opex(monkeypatch):
    rows = [r for r in _base_rows() if r[0] not in ("selling_expenses", "admin_expenses", "rd_expenses")]
    ok = _comps(_bridges(_ledger(rows))["net_income"])
    assert ok["total_opex"].delta == -30 and ok["other_opex_residual"].delta == 0        # patch 前：退回 total_opex 承接 −30
    monkeypatch.setattr(metrics, "_fee_keys", lambda ledger: metrics._FEE_KEYS)          # patch：不退回，仍用三費
    broken = _comps(_bridges(_ledger(rows))["net_income"])
    assert "total_opex" not in broken
    assert broken["other_opex_residual"].delta == pytest.approx(-30)                     # 營業費用 −30 只能落到合成項（歸因失去明細）


def test_mutation_self_check_single_step(monkeypatch):
    rows = [("income_total", None, 1000, 900), ("expense_total", None, 700, 650), ("pretax_income", None, 300, 250),
            ("income_tax", None, -50, -40), ("net_income", None, 250, 210)]
    assert _bridges(_ledger(rows))["net_income"].residual == pytest.approx(0)            # patch 前：單步式組成項，殘差 0
    monkeypatch.setattr(metrics, "_is_single_step", lambda ledger: False)                # patch：不偵測單步式
    broken = _bridges(_ledger(rows))["net_income"]
    assert "income_total" not in {c.key for c in broken.components}
    assert broken.residual == pytest.approx(50)                                           # 收入 +100、支出 −50 全落入殘差


def test_mutation_self_check_discontinued_ops(monkeypatch):
    rows = _base_rows(discontinued_ops=(None, 300), net_income=(225, 464))
    assert _bridges(_ledger(rows))["net_income"].residual == pytest.approx(0)            # patch 前：停業單位列入，殘差 0
    real = metrics._net_income_components
    monkeypatch.setattr(metrics, "_net_income_components",
                        lambda ledger: tuple(k for k in real(ledger) if k != "discontinued_ops"))  # patch：拿掉停業單位
    broken = _bridges(_ledger(rows))["net_income"]
    assert broken.residual == pytest.approx(-300)                                         # 去年停業單位利益 300 全落入殘差
