"""金控（group == "fh"）三表 schema：canonical key、區段標題、勾稽規格（純資料，不含計算）。

Spec 2026-10-09-tw-equity-fh-schema §2.2／§2.3／§2.4。別名以 §0.4 F3–F5 原文起手。
本檔不 import statements（statements 於工作包 1.2 import 本檔，避免循環），
故自帶與 `statements._norm_label` 等價的 `norm_label`；別名表的 key 為已正規化字串。
"""

from __future__ import annotations

import re
import unicodedata


def norm_label(s: str) -> str:
    """NFKC、去全部空白、`－—–` 統一為 `-`（與 statements._norm_label 等價）。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    return s.replace("－", "-").replace("—", "-").replace("–", "-")


def _hdrs(*names: str) -> frozenset[str]:
    return frozenset(norm_label(n) for n in names)


def _build(spec: dict[str, tuple[str, ...]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, aliases in spec.items():
        for a in aliases:
            n = norm_label(a)
            if n in out and out[n] != key:
                raise ValueError(f"別名 {a!r} 同時對應 {out[n]} 與 {key}")
            out[n] = key
    return out


# ── BS（F3；2881 另有項目置於末段） ───────────────────────────────────────────

_FH_BS_KEYS = _build({
    "cash": ("現金及約當現金－淨額", "現金及約當現金"),
    "due_from_central_bank": ("存放央行及拆借金融同業", "存放央行及拆借金融同業-淨額"),
    "fvtpl_assets": ("透過損益按公允價值衡量之金融資產",),
    "fvoci_assets": ("透過其他綜合損益按公允價值衡量之金融資產",),
    "amortized_cost_assets": ("按攤銷後成本衡量之債務工具投資", "按攤銷後成本衡量之債務工具投資-淨額"),
    "reverse_repo": ("附賣回票券及債券投資",),
    "receivables": ("應收款項－淨額", "應收款項"),
    "loans_net": ("貼現及放款－淨額", "貼現及放款"),
    "insurance_contract_assets": ("保險合約資產及再保險合約資產",),
    "equity_method_investments": ("採用權益法之投資", "採用權益法之投資-淨額", "採用權益法之股權投資", "採用權益法之股權投資-淨額"),
    "investment_property": ("投資性不動產", "投資性不動產-淨額"),
    "ppe": ("不動產及設備", "不動產、廠房及設備", "不動產及設備-淨額"),
    "total_assets": ("資產總計", "資產合計"),
    "due_to_central_bank": ("央行及金融同業存款",),
    "fvtpl_liabilities": ("透過損益按公允價值衡量之金融負債",),
    "repo": ("附買回票券及債券負債",),
    "commercial_paper": ("應付商業本票", "應付商業本票-淨額"),
    "payables": ("應付款項",),
    "deposits": ("存款及匯款",),
    "bonds_payable": ("應付債券",),
    "other_borrowings": ("其他借款",),
    "provisions": ("負債準備",),
    "insurance_contract_liabilities": ("保險合約負債及再保險合約負債",),
    "total_liabilities": ("負債總計", "負債合計"),
    "share_capital": ("股本合計",),
    "capital_surplus": ("資本公積",),
    "retained_earnings": ("保留盈餘合計",),
    "equity_parent": ("歸屬於母公司業主之權益總計", "歸屬於母公司業主之權益合計", "歸屬於本公司業主之權益合計", "歸屬於本公司業主之權益總計"),
    "nci": ("非控制權益",),
    "total_equity": ("權益總計", "權益合計"),
    "total_liabilities_and_equity": ("負債及權益總計", "負債及權益合計", "負債與權益總計", "負債與權益合計"),
    # Spec §2.2 未列、但 F3 2886 原文有、契約要求皆有對照者（最小必要集外新增）
    "current_tax_assets": ("本期所得稅資產",),
    "right_of_use_assets": ("使用權資產", "使用權資產-淨額"),
    "intangible_assets": ("無形資產", "無形資產-淨額"),
    "deferred_tax_assets": ("遞延所得稅資產",),
    "other_financial_assets": ("其他金融資產", "其他金融資產-淨額"),
    "other_assets": ("其他資產", "其他資產-淨額"),
    "central_bank_borrowings": ("央行及同業融資",),
    "current_tax_liabilities": ("本期所得稅負債",),
    "other_financial_liabilities": ("其他金融負債",),
    "lease_liabilities": ("租賃負債",),
    "deferred_tax_liabilities": ("遞延所得稅負債",),
    "other_liabilities": ("其他負債",),
    "common_stock": ("普通股股本",),
    "legal_reserve": ("法定盈餘公積",),
    "special_reserve": ("特別盈餘公積",),
    "unappropriated_earnings": ("未分配盈餘",),
    "other_equity": ("其他權益",),
    # F3 末句：2881 另有
    "preferred_stock": ("特別股股本",),
    "stock_dividend_pending": ("待分配股票股利",),
    "assets_held_for_sale": ("待出售資產", "待出售資產-淨額"),
    # 1.5 收斂：6 家 H1 BS 實際列名新增 key（別名補齊，不改勾稽）
    "hedging_assets": ("避險之金融資產",),
    "hedging_liabilities": ("避險之金融負債",),
    "restricted_assets": ("受限制資產-淨額", "受限制資產"),
    "preferred_stock_liability": ("特別股負債",),
    "treasury_stock": ("庫藏股票",),
    "liabilities_held_for_sale": ("與待出售資產直接相關之負債",),
})

# ── IS（F4；`減：` 前綴由 statements 解析時移除，此處兩種寫法皆收） ─────────────

_FH_IS_KEYS = _build({
    "interest_income": ("利息收入",),
    "interest_expense": ("利息費用", "減：利息費用"),
    "net_interest_income": ("利息淨收益",),
    "fee_income_net": ("手續費及佣金淨收益",),
    "insurance_service_result": ("保險服務結果",),
    "fvtpl_gain": ("透過損益按公允價值衡量之金融資產及負債損益", "透過損益按公允價值衡量之金融資產及負債(損失)利益", "透過損益按公允價值衡量之金融資產及負債利益(損失)"),
    "fx_gain": ("兌換損益", "兌換(損失)利益", "兌換利益(損失)"),
    "equity_method_share": (
        "採用權益法認列之關聯企業及合資損益之份額", "權益法份額", "採用權益法之關聯企業及合資損益之份額",
        "採用權益法認列關聯企業及合資損益之份額", "採用權益法認列關聯企業及合資利益之份額",
        "採用權益法認列之關聯企業損益之份額",
    ),
    "non_interest_income": ("利息以外淨收益", "利息以外淨收益合計", "利息以外淨損益"),
    "net_revenue": ("淨收益",),
    "provision": ("呆帳費用、承諾及保證責任準備提存", "呆帳、承諾及保證責任準備提存"),
    "insurance_other_cost": ("保險其他營業成本",),
    "insurance_reserve_change": ("保險負債準備淨變動",),
    "employee_benefits": ("員工福利費用",),
    "depreciation_amortization": ("折舊及攤銷費用",),
    "other_ga": ("其他業務及管理費用",),
    "total_opex": ("營業費用合計", "營業費用小計", "營業費用"),
    "pretax_income": (
        "繼續營業單位稅前淨利", "繼續營業單位稅前淨利(淨損)", "稅前損益", "稅前淨利",
        "繼續營業單位稅前損益", "稅前淨利(損)", "繼續營業單位稅前淨利(損)",
    ),
    "income_tax": ("所得稅費用", "所得稅費用(利益)", "所得稅(費用)利益", "所得稅利益(費用)"),
    "net_income": ("本期稅後淨利", "本期稅後淨利(淨損)", "本期淨利", "本期淨利(淨損)", "本期淨利(損)"),
    "net_income_parent": ("母公司業主",),
    "net_income_nci": ("非控制權益",),
    "eps_basic": ("基本每股盈餘", "基本每股盈餘(虧損)", "基本及稀釋每股盈餘", "基本每股盈餘(虧損)(單位:新台幣元)", "基本每股盈餘(單位:新台幣元)"),
    "eps_diluted": ("稀釋每股盈餘(虧損)", "稀釋每股盈餘(虧損)(單位:新台幣元)", "稀釋每股盈餘(單位:新台幣元)"),
    # F4 利息以外淨收益各組成（無合計列時加總代替，見 FH_NON_INTEREST_COMPONENT_KEYS）
    "investment_property_gain": ("投資性不動產損益", "投資性不動產利益"),
    "fvoci_realized_gain": ("透過其他綜合損益按公允價值衡量之金融資產已實現損益", "透過其他綜合損益按公允價值衡量之金融資產已實現利益"),
    "derecognition_gain": ("除列按攤銷後成本衡量之金融資產損益", "除列按攤銷後成本衡量之金融資產淨損益"),
    "impairment_loss": (
        "資產減損", "資產減損損失", "資產減損迴轉利益", "資產減損(損失)迴轉利益", "資產減損迴轉利益(損失)",
        "資產減損損失及迴轉利益淨額",
    ),
    "separate_account_result": ("分離帳戶保險商品資產淨損益",),
    "insurance_finance_result": ("保險財務收益或費用",),
    "reinsurance_finance_result": ("所持有之再保險合約財務收益或費用",),
    "other_non_interest": ("其他利息以外淨損益",),
    # 1.5 收斂：各家「其他利息以外淨收益」區段的個別列（同 key 只取首列，故各自獨立 key；併入 FH_NON_INTEREST_COMPONENT_KEYS）
    "npl_sale_gain": ("出售不良債權淨利益",),
    "advisory_income": ("顧問服務收入",),
    "misc_net_gain": ("其他什項淨損益", "其他什項淨利益(損失)"),
    "lottery_levy": ("彩券回饋金",),
})

# ── CF：僅金控特有鍵；cfo／cfi／cff 等沿用鍵由 statements 與工業 CF 表合併 ─────

FH_CF_EXTRA_KEYS: dict[str, str] = _build({
    "provision_cf": (
        "呆帳費用提列數", "呆帳費用提列數(迴轉數)", "呆帳費用、承諾及保證責任準備提存",
        "預期信用減損損失/呆帳費用、承諾及保證責任準備提存(轉列收入)數",
    ),
    "loans_change": ("貼現及放款增加", "貼現及放款減少", "貼現及放款(增加)減少", "貼現及放款減少(增加)", "貼現及放款增加(減少)"),
    "deposits_change": ("存款及匯款增加", "存款及匯款減少", "存款及匯款增加(減少)", "存款及匯款(減少)增加"),
})

# FH_CHECK_SPECS 用到、但由 statements 的工業 CF 表提供的沿用鍵
FH_CF_INHERITED_KEYS: tuple[str, ...] = (
    "cfo", "cfi", "cff", "fx_effect", "net_change_in_cash",
    "cash_beginning", "cash_ending", "cash_per_bs_in_cf", "pretax_income_cf",
)

# 1.5 收斂：6 家 H1 CF 實際列名中、statements 沿用的工業 CF 表（_CF_KEYS）對不到的別名（金控自帶，覆蓋於工業表之上）
_FH_CF_ALIAS_KEYS: dict[str, str] = _build({
    "pretax_income_cf": ("稅前淨利(損)", "本期稅前淨利(淨損)", "繼續營業單位稅前損益", "繼續營業單位稅前淨利(損)"),
    "cfo": ("營業活動之淨現金(流出)流入", "營業活動之淨現金流(出)入", "營業活動之淨現金流入(流出)"),
    "fx_effect": ("匯率及購買力變動對現金及約當現金之影響", "匯率變動之影響"),
    "cash_beginning": ("期初現金及約當現金餘額(重編後)",),
    "equity_method_share_adj": (
        "採用權益法認列之關聯企業及合資利益之份額", "採用權益法認列關聯企業及合資損益之份額",
        "採用權益法認列之關聯企業及合資損失(利益)之份額", "採用權益法認列之關聯企業損益之份額",
    ),
})

FH_CANONICAL_KEYS: dict[str, dict[str, str]] = {
    "bs": _FH_BS_KEYS,
    "is": _FH_IS_KEYS,
    "cf": {**FH_CF_EXTRA_KEYS, **_FH_CF_ALIAS_KEYS},
}

# 選填：該公司無此列（非保險金控）時以 0 計；其餘缺列 → passed=None
FH_OPTIONAL_KEYS: frozenset[str] = frozenset({"insurance_other_cost"})

# 費用類：勾稽時不論印正數或括號，一律取絕對值後相減（計算在 1.3）。
# insurance_other_cost 不在此列：保險其他營業成本可為淨回升（印正值），依報表原號相加（Spec §2.4 修訂）
FH_EXPENSE_KEYS: frozenset[str] = frozenset(
    {"interest_expense", "provision", "total_opex"}
)

# 無 non_interest_income 合計列時，以這些組成項加總代替（Spec §2.4、F4）
FH_NON_INTEREST_COMPONENT_KEYS: tuple[str, ...] = (
    "fee_income_net", "insurance_service_result", "fvtpl_gain", "investment_property_gain",
    "fvoci_realized_gain", "derecognition_gain", "fx_gain", "impairment_loss",
    "equity_method_share", "separate_account_result", "insurance_finance_result",
    "reinsurance_finance_result", "other_non_interest",
    "npl_sale_gain", "advisory_income", "misc_net_gain", "lottery_levy",
)

# 金控 TTM（Spec §6.5）：consolidated 的 key；parent_only 只算 net_income_parent
FH_TTM_KEYS: tuple[str, ...] = (
    "net_interest_income", "non_interest_income", "net_revenue", "provision", "total_opex",
    "pretax_income", "income_tax", "net_income", "net_income_parent",
)

# ── 區段標題 ─────────────────────────────────────────────────────────────────

FH_SECTION_HEADERS: dict[str, frozenset[str]] = {
    "bs": _hdrs("資產", "負債", "權益", "歸屬於母公司業主之權益", "歸屬母公司業主之權益"),
    "is": _hdrs(
        "利息以外淨收益", "營業費用", "其他綜合損益", "不重分類至損益之項目",
        "後續可能重分類至損益之項目", "淨利歸屬於:", "綜合損益總額歸屬於:",
    ),
    "cf": _hdrs(
        "營業活動之現金流量", "調整項目", "收益費損項目",
        "與營業活動相關之資產/負債變動數", "與營業活動相關之資產之淨變動",
        "與營業活動相關之負債之淨變動", "投資活動之現金流量", "籌資活動之現金流量",
        "現金及約當現金之組成", "期末現金及約當現金之調節",
    ),
}

# ── 勾稽 ─────────────────────────────────────────────────────────────────────

# (name, lhs keys, rhs keys)；順序依 Spec §2.4 表。lhs 逐項相加，但屬 FH_EXPENSE_KEYS 的
# key 改為減去其絕對值；insurance_other_cost 依原號相加，缺列以 0 計（見 FH_OPTIONAL_KEYS）；
# is_net_income 的 income_tax 沿用工業符號規則（相加）。
FH_CHECK_SPECS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("bs_assets_eq_liab_equity", ("total_assets",), ("total_liabilities_and_equity",)),
    ("bs_liab_equity_sum", ("total_liabilities", "total_equity"), ("total_liabilities_and_equity",)),
    ("is_net_interest", ("interest_income", "interest_expense"), ("net_interest_income",)),
    ("is_net_revenue", ("net_interest_income", "non_interest_income"), ("net_revenue",)),
    ("is_pretax", ("net_revenue", "provision", "insurance_other_cost", "total_opex"), ("pretax_income",)),
    ("is_net_income", ("pretax_income", "income_tax"), ("net_income",)),
    ("cf_net_change", ("cfo", "cfi", "cff", "fx_effect"), ("net_change_in_cash",)),
    ("cf_ending", ("cash_beginning", "net_change_in_cash"), ("cash_ending",)),
    ("cf_pretax_eq_is", ("pretax_income_cf",), ("pretax_income",)),
]
