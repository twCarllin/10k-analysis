"""metrics.py — 帳本衍生指標登錄表與 bridge 變動歸因（Spec 2026-10-09-tw-equity-metrics §1–§2，無 LLM）。

符號慣例沿用帳本：費用／流出為負數，公式用加法；比率 ×100。
所有指標一律期末值（不做平均）；任一輸入 None → None、分母 0 → None，不 raise。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from runtime.tw_equity.fy_income import FyIncome, normalize_sign
from runtime.tw_equity.statements import StatementLedger

_Vals = dict[str, float]


def _div(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


def _pct(a: float, b: float) -> float | None:
    r = _div(a, b)
    return None if r is None else r * 100


# ── 資料模型（§1.1） ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetricSpec:
    key: str
    name: str
    formula: str
    inputs: tuple[str, ...]
    unit: str                                   # "仟元" | "%" | "天" | "x" | "元"
    fn: Callable[[_Vals], float | None]
    optional_inputs: bool = False               # True：缺的輸入視為 0，全缺才 None


@dataclass
class MetricResult:
    key: str
    name: str
    formula: str
    unit: str
    period: str                                 # "current" | "prior"
    value: float | None
    inputs: dict[str, float | None]

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "formula": self.formula, "unit": self.unit,
                "period": self.period, "value": self.value, "inputs": dict(self.inputs)}


@dataclass
class BridgeComponent:
    key: str
    name: str
    current: float | None
    prior: float | None
    delta: float | None
    share: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "current": self.current, "prior": self.prior,
                "delta": self.delta, "share": self.share}


@dataclass
class BridgeResult:
    target: str
    name: str
    target_current: float | None
    target_prior: float | None
    target_delta: float | None
    components: list[BridgeComponent]
    residual: float | None
    top_drivers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "name": self.name, "target_current": self.target_current,
                "target_prior": self.target_prior, "target_delta": self.target_delta,
                "components": [c.to_dict() for c in self.components],
                "residual": self.residual, "top_drivers": list(self.top_drivers)}


TTM_KEYS = ("revenue", "cogs", "gross_profit", "total_opex", "operating_income", "nonoperating_total",
            "pretax_income", "income_tax", "net_income")


@dataclass
class TtmView:
    """TTM vs FY 視圖（Spec §3.2）。status 為 "unavailable" 時 reason 為一句原因、其餘欄為空。"""
    status: str                                 # "ok" | "unavailable"
    reason: str = ""
    period_ttm: str | None = None
    period_fy: str | None = None
    assurance: str = "mixed"
    source_page: int | None = None
    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: list[MetricResult] = field(default_factory=list)
    bridges: list[BridgeResult] = field(default_factory=list)

    def get(self, key: str, period: str = "ttm") -> float | None:
        for m in self.metrics:
            if m.key == key and m.period == period:
                return m.value
        return None

    def to_dict(self) -> dict[str, Any]:
        index: dict[str, dict[str, float | None]] = {}
        for m in self.metrics:
            index.setdefault(m.key, {})[m.period] = m.value
        return {"status": self.status, "reason": self.reason, "period_ttm": self.period_ttm,
                "period_fy": self.period_fy, "assurance": self.assurance, "source_page": self.source_page,
                "values": {k: dict(v) for k, v in self.values.items()},
                "metrics": [m.to_dict() for m in self.metrics],
                "bridges": [b.to_dict() for b in self.bridges], "index": index}


@dataclass
class MetricsPack:
    period_current: str
    period_prior: str
    metrics: list[MetricResult] = field(default_factory=list)
    bridges: list[BridgeResult] = field(default_factory=list)
    basis: str = "other"
    days: dict[str, int | None] = field(default_factory=lambda: {"current": None, "prior": None})
    assurance: str | None = None
    periods: dict[str, str | None] = field(default_factory=dict)
    ttm: TtmView | None = None

    def get(self, key: str, period: str = "current") -> float | None:
        for m in self.metrics:
            if m.key == key and m.period == period:
                return m.value
        return None

    def to_dict(self) -> dict[str, Any]:
        index: dict[str, dict[str, float | None]] = {}
        for m in self.metrics:
            index.setdefault(m.key, {})[m.period] = m.value
        return {"period_current": self.period_current, "period_prior": self.period_prior,
                "metrics": [m.to_dict() for m in self.metrics],
                "bridges": [b.to_dict() for b in self.bridges], "index": index,
                "basis": self.basis, "days": dict(self.days), "assurance": self.assurance,
                "periods": dict(self.periods),
                "ttm_vs_fy": None if self.ttm is None else self.ttm.to_dict()}


# ── 指標登錄表（§1.2；順序固定） ─────────────────────────────────────────────

_IBD_KEYS = ("short_term_borrowings", "long_term_borrowings_current", "long_term_borrowings",
             "bonds_payable", "lease_liabilities_current", "lease_liabilities_noncurrent")

METRIC_SPECS: list[MetricSpec] = [
    MetricSpec("fcf", "自由現金流", "cfo + capex", ("cfo", "capex"), "仟元",
               lambda v: v["cfo"] + v["capex"]),
    MetricSpec("fcf_margin", "自由現金流率", "fcf / revenue * 100", ("fcf", "revenue"), "%",
               lambda v: _pct(v["fcf"], v["revenue"])),
    MetricSpec("gross_margin", "毛利率", "gross_profit / revenue * 100", ("gross_profit", "revenue"), "%",
               lambda v: _pct(v["gross_profit"], v["revenue"])),
    MetricSpec("operating_margin", "營業利益率", "operating_income / revenue * 100",
               ("operating_income", "revenue"), "%", lambda v: _pct(v["operating_income"], v["revenue"])),
    MetricSpec("net_margin", "淨利率", "net_income / revenue * 100", ("net_income", "revenue"), "%",
               lambda v: _pct(v["net_income"], v["revenue"])),
    MetricSpec("ebitda", "EBITDA", "operating_income + depreciation + amortization",
               ("operating_income", "depreciation", "amortization"), "仟元",
               lambda v: v["operating_income"] + v["depreciation"] + v["amortization"]),
    MetricSpec("ebitda_margin", "EBITDA 率", "ebitda / revenue * 100", ("ebitda", "revenue"), "%",
               lambda v: _pct(v["ebitda"], v["revenue"])),
    MetricSpec("cfo_to_net_income", "營業現金流／淨利", "cfo / net_income", ("cfo", "net_income"), "x",
               lambda v: _div(v["cfo"], v["net_income"])),
    MetricSpec("capex_to_depreciation", "資本支出／折舊", "abs(capex) / depreciation",
               ("capex", "depreciation"), "x", lambda v: _div(abs(v["capex"]), v["depreciation"])),
    MetricSpec("capex_to_revenue", "資本支出率", "abs(capex) / revenue * 100", ("capex", "revenue"), "%",
               lambda v: _pct(abs(v["capex"]), v["revenue"])),
    MetricSpec("dso", "應收帳款天數（期末）",
               "(accounts_receivable + accounts_receivable_related) / revenue * days",
               ("accounts_receivable", "accounts_receivable_related", "revenue", "days"), "天",
               lambda v: _div((v["accounts_receivable"] + v["accounts_receivable_related"]) * v["days"], v["revenue"])),
    MetricSpec("dio", "存貨天數（期末）", "inventories / abs(cogs) * days", ("inventories", "cogs", "days"), "天",
               lambda v: _div(v["inventories"] * v["days"], abs(v["cogs"]))),
    MetricSpec("dpo", "應付帳款天數（期末）", "accounts_payable / abs(cogs) * days",
               ("accounts_payable", "cogs", "days"), "天",
               lambda v: _div(v["accounts_payable"] * v["days"], abs(v["cogs"]))),
    MetricSpec("ccc", "現金轉換循環", "dso + dio - dpo", ("dso", "dio", "dpo"), "天",
               lambda v: v["dso"] + v["dio"] - v["dpo"]),
    MetricSpec("current_ratio", "流動比率", "total_current_assets / total_current_liabilities * 100",
               ("total_current_assets", "total_current_liabilities"), "%",
               lambda v: _pct(v["total_current_assets"], v["total_current_liabilities"])),
    MetricSpec("quick_ratio", "速動比率", "(total_current_assets - inventories) / total_current_liabilities * 100",
               ("total_current_assets", "inventories", "total_current_liabilities"), "%",
               lambda v: _pct(v["total_current_assets"] - v["inventories"], v["total_current_liabilities"])),
    MetricSpec("interest_bearing_debt", "有息負債", " + ".join(_IBD_KEYS) + "（缺 key 視為 0）",
               _IBD_KEYS, "仟元", lambda v: sum(v[k] for k in _IBD_KEYS), optional_inputs=True),
    MetricSpec("net_debt", "淨負債", "interest_bearing_debt - cash", ("interest_bearing_debt", "cash"), "仟元",
               lambda v: v["interest_bearing_debt"] - v["cash"]),
    MetricSpec("debt_to_equity", "有息負債／權益", "interest_bearing_debt / total_equity * 100",
               ("interest_bearing_debt", "total_equity"), "%",
               lambda v: _pct(v["interest_bearing_debt"], v["total_equity"])),
    MetricSpec("liabilities_to_assets", "負債比率", "total_liabilities / total_assets * 100",
               ("total_liabilities", "total_assets"), "%", lambda v: _pct(v["total_liabilities"], v["total_assets"])),
    MetricSpec("interest_coverage", "利息保障倍數", "operating_income / abs(finance_costs)",
               ("operating_income", "finance_costs"), "x",
               lambda v: _div(v["operating_income"], abs(v["finance_costs"]))),
    MetricSpec("roe", "股東權益報酬率（期末）", "net_income_parent / equity_parent * 100",
               ("net_income_parent", "equity_parent"), "%", lambda v: _pct(v["net_income_parent"], v["equity_parent"])),
    MetricSpec("roa", "資產報酬率（期末）", "net_income / total_assets * 100", ("net_income", "total_assets"), "%",
               lambda v: _pct(v["net_income"], v["total_assets"])),
    MetricSpec("asset_turnover", "總資產週轉率（期末）", "revenue / total_assets", ("revenue", "total_assets"), "x",
               lambda v: _div(v["revenue"], v["total_assets"])),
    MetricSpec("rd_intensity", "研發費用率", "abs(rd_expenses) / revenue * 100", ("rd_expenses", "revenue"), "%",
               lambda v: _pct(abs(v["rd_expenses"]), v["revenue"])),
    MetricSpec("opex_ratio", "營業費用率", "abs(total_opex) / revenue * 100", ("total_opex", "revenue"), "%",
               lambda v: _pct(abs(v["total_opex"]), v["revenue"])),
    MetricSpec("effective_tax_rate", "有效稅率", "abs(income_tax) / pretax_income * 100",
               ("income_tax", "pretax_income"), "%", lambda v: _pct(abs(v["income_tax"]), v["pretax_income"])),
    MetricSpec("dividend_payout", "現金股利支付率", "abs(dividends_paid) / net_income_parent * 100",
               ("dividends_paid", "net_income_parent"), "%",
               lambda v: _pct(abs(v["dividends_paid"]), v["net_income_parent"])),
    MetricSpec("cash_to_assets", "現金占總資產", "cash / total_assets * 100", ("cash", "total_assets"), "%",
               lambda v: _pct(v["cash"], v["total_assets"])),
    MetricSpec("working_capital", "營運資金", "total_current_assets - total_current_liabilities",
               ("total_current_assets", "total_current_liabilities"), "仟元",
               lambda v: v["total_current_assets"] - v["total_current_liabilities"]),
]

_METRIC_NAMES = {s.key: s.name for s in METRIC_SPECS}


# ── Bridge 登錄表（§1.3） ────────────────────────────────────────────────────


@dataclass(frozen=True)
class BridgeSpec:
    target: str
    name: str
    components: tuple[str, ...]


BRIDGE_SPECS: list[BridgeSpec] = [
    BridgeSpec("fcf", "自由現金流變動", ("cfo", "capex")),
    BridgeSpec("cfo", "營業現金流變動（間接法）", (
        "pretax_income_cf", "depreciation", "amortization", "change_receivables", "change_receivables_related",
        "change_inventories", "change_payables", "change_other_payables", "change_contract_liabilities",
        "change_other_receivables", "change_other_current_assets", "change_other_current_liabilities",
        "change_notes_receivable", "change_notes_payable", "interest_paid", "income_tax_paid",
        "finance_costs_adj", "interest_income_adj", "dividend_income_adj", "fvtpl_gain_adj", "unrealized_fx_gain",
        "impairment_loss_receivables", "ppe_disposal_loss_adj", "equity_method_share_adj",
        "impairment_reversal_nonfinancial", "lease_modification_loss", "bond_buyback_gain",
        "change_net_defined_benefit")),
    BridgeSpec("net_income", "淨利變動", (
        "revenue", "cogs", "selling_expenses", "admin_expenses", "rd_expenses", "interest_income", "other_income",
        "other_gains_losses", "finance_costs", "equity_method_share", "income_tax")),
    BridgeSpec("operating_income", "營業利益變動", ("revenue", "cogs", "total_opex")),
    BridgeSpec("net_change_in_cash", "現金變動", ("cfo", "cfi", "cff", "fx_effect")),
    BridgeSpec("cfi", "投資現金流變動", (
        "capex", "ppe_disposal_proceeds", "intangible_purchase", "prepaid_equipment_increase", "fvtpl_purchase",
        "fvtpl_disposal_proceeds", "fvoci_disposal_proceeds", "other_noncurrent_assets_increase",
        "change_refundable_deposits", "dividends_received", "interest_received")),
    BridgeSpec("cff", "籌資現金流變動", (
        "short_term_borrowings_increase", "short_term_borrowings_decrease", "long_term_borrowings_proceeds",
        "long_term_borrowings_repayment", "bonds_issued", "bonds_repaid", "lease_principal_repayment",
        "dividends_paid", "dividends_paid_to_nci", "employee_stock_option_exercised",
        "guarantee_deposits_received_increase")),
    BridgeSpec("total_assets", "總資產變動", (
        "cash", "accounts_receivable", "inventories", "ppe", "prepaid_equipment", "other_noncurrent_assets",
        "fvtpl_current", "fvoci_noncurrent", "right_of_use_assets", "deferred_tax_assets", "other_current_assets",
        "other_receivables", "accounts_receivable_related", "notes_receivable", "equity_method_investments",
        "intangible_assets", "refundable_deposits")),
]

_PERIODS = ("current", "prior")


# ── 計算（§2.1、§2.2） ───────────────────────────────────────────────────────


def _ledger_value(ledger: StatementLedger, key: str, period: str, bs_prior_tag: str = "bs_prior_same") -> float | None:
    """帳本第一個相符列的該期值（走 `value_at`；IS／CF 用 flow_*、BS 用 bs_*）；列存在但為 `-` → 0.0；無該列 → None。"""
    for r in ledger.rows:
        if r.key == key:
            if r.statement == "bs":
                tag = "bs_current" if period == "current" else bs_prior_tag
            else:
                tag = "flow_current" if period == "current" else "flow_prior"
            return ledger.value_at(key, tag)
    return None


def _days_value(ledger: StatementLedger, period: str) -> float | None:
    d = ledger.days.get(period)
    if d is None and not ledger.column_periods.get("is"):
        return 365.0  # 舊帳本／合成帳本：退回舊行為
    return d


def _label_of(ledger: StatementLedger, key: str) -> str:
    """帳本第一個相符列的 label；無則指標名；再無則 key。"""
    for r in ledger.rows:
        if r.key == key:
            return r.label
    return _METRIC_NAMES.get(key, key)


def _spec_value(spec: MetricSpec, inputs: dict[str, float | None]) -> float | None:
    if spec.optional_inputs:
        return None if all(v is None for v in inputs.values()) else spec.fn(
            {k: (0.0 if v is None else v) for k, v in inputs.items()})
    return None if any(v is None for v in inputs.values()) else spec.fn(inputs)  # type: ignore[arg-type]


def compute_metrics(ledger: StatementLedger | None, fy_income: FyIncome | None = None) -> MetricsPack | None:
    """依 METRIC_SPECS 對兩期各算一次；再填 bridges。ledger None → None。H1 帳本另填 TTM 視圖（§3.2）。"""
    if ledger is None:
        return None
    pack = MetricsPack(period_current=ledger.period_current, period_prior=ledger.period_prior,
                       basis=ledger.basis, days=dict(ledger.days), assurance=ledger.assurance,
                       periods=dict(ledger.periods))
    computed: dict[str, dict[str, float | None]] = {"current": {}, "prior": {}}
    for spec in METRIC_SPECS:
        for period in _PERIODS:
            done = computed[period]
            inputs: dict[str, float | None] = {
                k: (_days_value(ledger, period) if k == "days"
                    else done[k] if k in done else _ledger_value(ledger, k, period))
                for k in spec.inputs
            }
            value = _spec_value(spec, inputs)
            done[spec.key] = value
            pack.metrics.append(MetricResult(spec.key, spec.name, spec.formula, spec.unit, period, value, inputs))
    pack.bridges = compute_bridges(ledger, pack)
    pack.ttm = compute_ttm(ledger, fy_income)
    return pack


def _value(ledger: StatementLedger, pack: MetricsPack, key: str, period: str,
           bs_prior_tag: str = "bs_prior_same") -> float | None:
    if key in _METRIC_NAMES:
        return pack.get(key, period)
    return _ledger_value(ledger, key, period, bs_prior_tag)


def _build_bridge(target: str, name: str, components: tuple[str, ...],
                  get: Callable[[str, str], float | None],
                  label_of: Callable[[str], str]) -> BridgeResult:
    """target 與 components 的 get(key, "cur"／"pri") 變動；|delta| 降序（None 殿後）；殘差＝target_delta − Σ非 None delta。"""
    t_cur, t_pri = get(target, "cur"), get(target, "pri")
    t_delta = None if t_cur is None or t_pri is None else t_cur - t_pri
    comps: list[BridgeComponent] = []
    for key in components:
        cur, pri = get(key, "cur"), get(key, "pri")
        delta = None if cur is None or pri is None else cur - pri
        share = None if (delta is None or not t_delta) else delta / t_delta
        comps.append(BridgeComponent(key, label_of(key), cur, pri, delta, share))
    known = [c for c in comps if c.delta is not None]
    unknown = [c for c in comps if c.delta is None]
    known.sort(key=lambda c: -abs(c.delta))  # type: ignore[arg-type]
    ordered = known + unknown
    residual = None if t_delta is None else t_delta - sum(c.delta for c in known)  # type: ignore[misc]
    return BridgeResult(target, name, t_cur, t_pri, t_delta, ordered, residual, [c.key for c in known[:3]])


def compute_bridges(ledger: StatementLedger, pack: MetricsPack) -> list[BridgeResult]:
    """每個 BridgeSpec：target 與 components 的本期−上期變動；|delta| 降序（None 殿後）；殘差＝target_delta − Σ非 None delta。"""
    out: list[BridgeResult] = []
    for spec in BRIDGE_SPECS:
        tag = "bs_prior_fy_end" if spec.target == "total_assets" else "bs_prior_same"

        def get(key: str, which: str, tag: str = tag) -> float | None:
            return _value(ledger, pack, key, "current" if which == "cur" else "prior", tag)

        out.append(_build_bridge(spec.target, spec.name, spec.components, get,
                                 lambda k: _label_of(ledger, k)))
    return out


# ── TTM 視圖（§3.2；Spec §2.7 第 4、6 點） ───────────────────────────────────

_TTM_BRIDGES = (BridgeSpec("operating_income", "營業利益變動", ("revenue", "cogs", "total_opex")),
                BridgeSpec("net_income", "淨利變動",
                           ("revenue", "cogs", "total_opex", "nonoperating_total", "income_tax")))


def _h1_normalized(ledger: StatementLedger, key: str, tag: str, cogs_tag: str,
                   source_key: str | None = None) -> float | None:
    """帳本 H1 值依 §2.4 正規化（與 FY 同一規則）；source_key 為實際取值的帳本 key（淨利代用）。"""
    src = source_key or key
    row = next((r for r in ledger.rows if r.key == src), None)
    if row is None:
        return None
    return normalize_sign(key, row.label, ledger.value_at(src, tag),
                          cogs_raw=ledger.value_at("cogs", cogs_tag))


def _ttm_unavailable_reason(ledger: StatementLedger, fy: FyIncome | None) -> str | None:
    if ledger.basis != "H1":
        return "ledger_not_h1"
    if fy is None:
        return "fy_income_missing"
    if not fy.usable:
        return "fy_income_unusable"
    prior = ledger.periods.get("flow_prior")
    if prior is None or not prior[:3].isdigit() or fy.roc_year != int(prior[:3]):
        return "fy_year_mismatch"
    if "仟元" not in ledger.unit and "千元" not in ledger.unit:
        return "unit_mismatch"
    return None


def compute_ttm(ledger: StatementLedger, fy: FyIncome | None) -> TtmView | None:
    """FY 帳本 → None；H1 但條件不成立 → status "unavailable"；否則 TTM = FY + H1 本期 − H1 上期。"""
    if ledger.basis == "FY":
        return None
    reason = _ttm_unavailable_reason(ledger, fy)
    if reason is not None:
        return TtmView(status="unavailable", reason=reason)
    assert fy is not None
    parent = fy.net_income_basis == "parent"
    values: dict[str, dict[str, Any]] = {}
    for k in TTM_KEYS:
        src = "net_income_parent" if (k == "net_income" and parent) else None
        f = fy.normalized(k, "current")
        cur = _h1_normalized(ledger, k, "flow_current", "flow_current", src)
        pri = _h1_normalized(ledger, k, "flow_prior", "flow_prior", src)
        ttm = None if f is None or cur is None or pri is None else f + cur - pri
        values[k] = {"fy": f, "h1_current": cur, "h1_prior": pri, "ttm": ttm}
        if src:
            values[k]["basis"] = "parent"

    bs_keys = {r.key for r in ledger.rows if r.statement == "bs"}
    bs_tag = {"ttm": "bs_current", "fy": "bs_prior_fy_end"}

    def raw(key: str, period: str) -> float | None:
        if key in TTM_KEYS:
            return values[key][period]
        if key in bs_keys:
            return ledger.value_at(key, bs_tag[period])
        return None  # CF／非 TTM 損益 key 一律 None

    view = TtmView(status="ok", period_ttm=(ledger.periods.get("flow_current") or "").split("~")[-1] or None,
                   period_fy=str(fy.roc_year), source_page=fy.page, values=values)
    computed: dict[str, dict[str, float | None]] = {"ttm": {}, "fy": {}}
    for spec in METRIC_SPECS:
        for period in ("ttm", "fy"):
            done = computed[period]
            inputs = {k: (365.0 if k == "days" else done[k] if k in done else raw(k, period))
                      for k in spec.inputs}
            value = _spec_value(spec, inputs)
            done[spec.key] = value
            view.metrics.append(MetricResult(spec.key, spec.name, spec.formula, spec.unit, period, value, inputs))

    def get(key: str, which: str) -> float | None:
        period = "ttm" if which == "cur" else "fy"
        return computed[period][key] if key in computed[period] else raw(key, period)

    view.bridges = [_build_bridge(b.target, b.name, b.components, get,
                                  lambda k: _label_of(ledger, k)) for b in _TTM_BRIDGES]
    return view
