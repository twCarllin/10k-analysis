"""statements.py — 合併財報三表（BS／IS／CF）逐列解析、科目對照與帳本（Spec 2026-10-09-tw-equity-statements §1–§3）。

純確定性、無 LLM。列通道輸入為 `Page.lines`；金額 token 解析重用 `tables.line_amounts`。
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from runtime.tw_equity.fh_schema import (
    FH_CANONICAL_KEYS,
    FH_CHECK_SPECS,
    FH_EXPENSE_KEYS,
    FH_NON_INTEREST_COMPONENT_KEYS,
    FH_OPTIONAL_KEYS,
    FH_SECTION_HEADERS,
)
from runtime.tw_equity.tables import _norm_line, line_amounts, parse_amount  # noqa: F401

if TYPE_CHECKING:
    from runtime.tw_equity.doc_anchor import PageRange
    from runtime.tw_equity.pdf_doc import Page, PdfDoc


# ── 資料模型（Spec §1） ───────────────────────────────────────────────────────


@dataclass
class StatementRow:
    statement: str            # "bs" | "is" | "cf"
    section: str | None       # 最近一個群組標題（去 note、NFKC 去空白），無則 None
    label: str                # 科目原文（續行已合併、附註已剝除）
    key: str | None           # 標準代號；對不到 → None
    note: str | None          # 附註 token 原文
    current: float | None
    prior: float | None
    current_pct: float | None  # 只 bs／is；cf 固定 None
    prior_pct: float | None
    page: int                 # 來源頁（1-indexed）
    line_idx: int             # 該頁 lines 索引（續行取首列）
    # 以下為泛化新欄（Spec 2026-10-09-tw-equity-fs-generalize §1.1），皆有預設值以向後相容
    code: str | None = None   # 剝除的會計代碼原文（`1100`、`A21200`），無 → None
    columns: list[float | None] = field(default_factory=list)  # 該列全部期間欄金額（不含 %）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CrossCheck:
    name: str
    period: str               # "current" | "prior"
    lhs: float | None
    rhs: float | None
    passed: bool | None       # 任一邊 None → None（無法勾稽）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PERIOD_TAGS = ("flow_current", "flow_prior", "bs_current", "bs_prior_same", "bs_prior_fy_end")


@dataclass
class StatementLedger:
    unit: str
    period_current: str
    period_prior: str
    rows: list[StatementRow]
    checks: list[CrossCheck]
    unmapped_labels: list[str]
    # 以下為泛化新欄（Spec 2026-10-09-tw-equity-fs-generalize §1.2），皆有預設值以向後相容
    column_periods: dict[str, list[str]] = field(
        default_factory=lambda: {"bs": [], "is": [], "cf": []}
    )  # 每張表的欄位期間標籤；解析不到 → 空 list
    current_col: dict[str, int | None] = field(
        default_factory=lambda: {"bs": None, "is": None, "cf": None}
    )  # current 取自 column_periods 的哪一欄
    prior_col: dict[str, int | None] = field(
        default_factory=lambda: {"bs": None, "is": None, "cf": None}
    )
    parse_warnings: list[str] = field(default_factory=list)
    # 期間模型（Spec 2026-10-09-tw-equity-period-model §1.1）
    basis: str = "other"  # "H1" | "FY" | "other"
    periods: dict[str, str | None] = field(default_factory=lambda: dict.fromkeys(_PERIOD_TAGS))
    days: dict[str, int | None] = field(default_factory=lambda: {"current": None, "prior": None})
    assurance: str | None = None  # "reviewed" | "audited" | None
    schema: str = "industrial"  # "industrial" | "fh"（fh-schema Spec §2.5）

    def get(
        self, key: str, statement: str | None = None
    ) -> tuple[float | None, float | None]:
        """第一個 key 相符的列 → (current, prior)；無 → (None, None)。"""
        for r in self.rows:
            if r.key == key and (statement is None or r.statement == statement):
                return (r.current, r.prior)
        return (None, None)

    def value_at(self, key: str, tag: str) -> float | None:
        """第一個 key 相符列在 `tag` 期間欄的值（Spec §1.2）；不相容／無標籤／欄不存在／無列 → None。"""
        row = next((r for r in self.rows if r.key == key), None)
        if row is None or tag not in _PERIOD_TAGS:
            return None
        is_bs_tag = tag.startswith("bs_")
        if (row.statement == "bs") != is_bs_tag:
            return None
        if not row.columns:  # 舊帳本／合成帳本：退回 current／prior
            v = row.current if tag in ("flow_current", "bs_current") else row.prior
            return 0.0 if v is None else v
        label = self.periods.get(tag)
        cols = self.column_periods.get(row.statement, [])
        if label is None or label not in cols:
            return None
        i = cols.index(label)
        if i >= len(row.columns):
            return None
        v = row.columns[i]
        return 0.0 if v is None else v

    def to_dict(self) -> dict[str, Any]:
        counts = {"bs": 0, "is": 0, "cf": 0}
        for r in self.rows:
            counts[r.statement] = counts.get(r.statement, 0) + 1
        return {
            "unit": self.unit,
            "period_current": self.period_current,
            "period_prior": self.period_prior,
            "rows": [r.to_dict() for r in self.rows],
            "checks": [c.to_dict() for c in self.checks],
            "unmapped_labels": list(self.unmapped_labels),
            "row_counts": counts,
            "column_periods": {k: list(v) for k, v in self.column_periods.items()},
            "current_col": dict(self.current_col),
            "prior_col": dict(self.prior_col),
            "parse_warnings": list(self.parse_warnings),
            "basis": self.basis,
            "periods": dict(self.periods),
            "days": dict(self.days),
            "assurance": self.assurance,
            "schema": self.schema,
        }


# ── 正規化與常數 ──────────────────────────────────────────────────────────────

_CN_NUM = "一二三四五六七八九十"
# 附註欄 token：`六(一)`、`(二十六)及七`、`四及六.1`、`四、六.21及七`、`六.20、六.21、`（結尾頓號＝跨列）
_NOTE_UNIT = rf"[{_CN_NUM}]+(?:\.\d+|\([{_CN_NUM}]+\))*"
_NOTE_PAREN = rf"\([{_CN_NUM}]+\)"
_NOTE_SUFFIXED = rf"[{_CN_NUM}]+(?:\.\d+|\([{_CN_NUM}]+\))+"
_NOTE_MORE = rf"(?:[及、](?:{_NOTE_UNIT}|{_NOTE_PAREN}))"
_NOTE_RE = re.compile(
    rf"^(?:(?:{_NOTE_PAREN}|{_NOTE_SUFFIXED}){_NOTE_MORE}*|{_NOTE_UNIT}{_NOTE_MORE}+)、?$"
)
# 續行開頭的「及七」「及七(二)」片段
_NOTE_CONT_RE = re.compile(rf"^及[{_CN_NUM}]+(?:\([{_CN_NUM}]+\))*$")
# 科目後的單獨中文數字附註（如「預付設備款 七」「重大之期後事項 十一」）；僅在 label 之後才算 note
_NOTE_BARE_RE = re.compile(rf"^[{_CN_NUM}]+$")
# 科目後黏著、無括號包裹的附註（尾端）：`營業成本六(九)(三十五)及七`、`營業收入六(二十三)、七及十四`、`營業收入(四)/(六).23`
_GLUE_ITEM = rf"(?:[{_CN_NUM}]+(?:\([{_CN_NUM}]+\))*(?:\.\d+)*|\([{_CN_NUM}]+\)(?:\.\d+)*)"
_GLUE_NOTE_RE = re.compile(rf"(?<![{_CN_NUM}.\d])({_GLUE_ITEM}(?:[及、/]{_GLUE_ITEM})*)$")
_PERIOD_RE = re.compile(r"(\d{2,3})年.*?(\d{2,3})年")
_DATE_LINE_RE = re.compile(r"^(?:民國)?\d{2,3}年\d{1,2}月\d{1,2}日")
_UNIT_RE = re.compile(r"單位[:：](.+?)(?:\(|$)")
# 單位（Spec §2.3）：`單位：新台幣千元`、`(金額均以新臺幣千元為單位)`、`(金額除每股盈餘外，均以…為單位)`
_UNIT_CCY_RE = re.compile(r"(?:單位[:：]|均以)(新[台臺]幣|美金|人民幣)(仟元|千元|百萬元|萬元|元)")
_CN_DIGITS = "〇零一二三四五六七八九十"
# 純期間續列（`至6月30日 至6月30日`、中文數字 `至六月三十日`、CF 的 `附註 至6月30日`）
_END_ONLY_RE = re.compile(rf"^(?:附註)?至[\d{_CN_DIGITS}]+月")
_HEADER_TOP_LINES = 5  # 頁首這幾列內且無金額者視為公司名／表名／日期／單位列
# 會計代碼（F2）：`1100`、`130X`、`11XX`；CF 的 `A10000`、`AAAA`；與科目黏在一起的 `A21200利息收入`
_CODE_STD_RE = re.compile(r"^[0-9][0-9Xx]{3}$")  # 含 `11xx`／`1xxx` 小寫 x 的合計列代碼
_CODE_ALPHA_RE = re.compile(r"^(?:[A-Z]\d{4,5}|[A-Z]{4})$")
_CODE_GLUE_RE = re.compile(r"^([A-Z]{1,4}\d{0,6}|\d{4})(?=[\u4e00-\u9fff])")
_RIGHT_CODE_RE = re.compile(r"^[23][0-9Xx]{3}$")  # 並排頁右半（負債／權益）的代碼
_CF_RIGHT_CODE_RE = re.compile(r"^[B-E](?:\d{5}|[B-E]{3})$")  # 並排 CF 右半（投資／籌資／匯率／期末）的代碼（3017）
# 金控（group == "fh"）專用（fh-schema Spec §2.1）：5 位數代碼；右半 `2xxxx`／`3xxxx`；`減：` 前綴
_FH_CODE_RE = re.compile(r"^(?:\d{5}|\d[Xx]{4})$")  # `4xxxx`＝無實碼的合計列（如 `4xxxx 淨收益`）
_FH_CODE_GLUE_RE = re.compile(r"^(\d{5}|\d[Xx]{4})(?=[\u4e00-\u9fff])")
# 並排頁左半附註換行後的殘片黏在右半單邊列首：`(十四)及八)負債總計`
_FH_LEAD_NOTE_FRAG_RE = re.compile(r"^(?:\([一二三四五六七八九十廿卅〇]+\))?(?:[及、]?[一二三四五六七八九十廿卅〇]+\))+")
# 金控 IS 歸屬區段標題變體：`淨利(淨損)歸屬於`、`淨利(損)歸屬於`、`本期稅後淨利(損失)歸屬於`…
_FH_SPLIT_SEC_NOISE_RE = re.compile(r"\((?:淨損|損失|損)\)|本期稅後|本期")
_FH_RIGHT_CODE_RE = re.compile(r"^[23](?:\d{4}|[0-9Xx]{3})$")  # 5 位數；亦容許工業 4 位數（fh 為工業的超集）
_FH_LESS_PREFIX_RE = re.compile(r"^減[:：]")
# 金控並排 BS 的左右半各自有「股本：」「保留盈餘：」無金額標題（FH_SECTION_HEADERS 未列），否則會與下一列科目合併
_FH_EXTRA_SECTION_HEADERS: dict[str, frozenset[str]] = {
    "bs": frozenset({"股本", "保留盈餘"}),
}
_FH_DANGLING_NOTE_RE = re.compile(r"\(附註?$")  # 並排頁右半附註被切在續行：`…金融負債(附`

_TITLE_KW = {"bs": "資產負債表", "is": "綜合損益表", "cf": "現金流量表"}
_FS_ANCHOR_KEY = {"bs": "fs_bs", "is": "fs_is", "cf": "fs_cf"}


def _norm_label(s: str) -> str:
    """NFKC、去全部空白、`－—–` 統一為 `-`。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    return s.replace("－", "-").replace("—", "-").replace("–", "-")


def _hdrs(*names: str) -> frozenset[str]:
    return frozenset(_norm_label(n) for n in names)


BS_SECTION_HEADERS = _hdrs(
    "資產", "負債", "流動資產", "非流動資產", "流動負債", "非流動負債", "權益",
    "歸屬於母公司業主之權益", "歸屬母公司業主之權益", "股本", "資本公積", "保留盈餘", "其他權益",
)
IS_SECTION_HEADERS = _hdrs(
    "營業費用", "營業外收入及支出", "其他綜合損益", "不重分類至損益之項目",
    "後續可能重分類至損益之項目", "淨利歸屬於:", "綜合損益總額歸屬於:",
)
CF_SECTION_HEADERS = _hdrs(
    "營業活動之現金流量", "調整項目", "收益費損項目",
    "與營業活動相關之資產/負債變動數", "與營業活動相關之資產之淨變動",
    "與營業活動相關之負債之淨變動", "投資活動之現金流量", "籌資活動之現金流量",
    "現金及約當現金之組成", "期末現金及約當現金之調節",  # 現金調節區塊（§8.3.4），其下的 `資產負債表帳列…` 列不與標題合併
)
SECTION_HEADERS = {
    "bs": BS_SECTION_HEADERS,
    "is": IS_SECTION_HEADERS,
    "cf": CF_SECTION_HEADERS,
}


# ── 科目對照表（Spec §3） ─────────────────────────────────────────────────────


def _build(spec: dict[str, tuple[str, ...]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, aliases in spec.items():
        for a in aliases:
            out[_norm_label(a)] = key
    return out


_BS_KEYS = _build({
    "cash": ("現金及約當現金",),
    "fvtpl_current": ("透過損益按公允價值衡量之金融資產-流動",),
    "notes_receivable": ("應收票據淨額", "應收票據"),
    "accounts_receivable": ("應收帳款淨額", "應收帳款"),
    "accounts_receivable_related": ("應收帳款-關係人淨額", "應收帳款-關係人"),
    "other_receivables_related": ("其他應收款-關係人",),
    "accounts_payable_related": ("應付帳款-關係人",),
    "other_payables_related": ("其他應付款-關係人",),
    "prepayments": ("預付款項",),
    "other_receivables": ("其他應收款",),
    "inventories": ("存貨",),
    "other_current_assets": ("其他流動資產",),
    "total_current_assets": ("流動資產合計", "流動資產總計"),
    "fvoci_noncurrent": ("透過其他綜合損益按公允價值衡量之金融資產-非流動",),
    "equity_method_investments": ("採用權益法之投資",),
    "ppe": ("不動產、廠房及設備",),
    "right_of_use_assets": ("使用權資產",),
    "intangible_assets": ("無形資產",),
    "deferred_tax_assets": ("遞延所得稅資產",),
    "prepaid_equipment": ("預付設備款",),
    "refundable_deposits": ("存出保證金",),
    "other_noncurrent_assets": ("其他非流動資產-其他", "其他非流動資產"),
    "total_noncurrent_assets": ("非流動資產合計", "非流動資產總計"),
    "total_assets": ("資產總計",),
    "short_term_borrowings": ("短期借款",),
    "contract_liabilities_current": ("合約負債-流動",),
    "notes_payable": ("應付票據",),
    "accounts_payable": ("應付帳款",),
    "other_payables": ("其他應付款",),
    "current_tax_liabilities": ("本期所得稅負債",),
    "lease_liabilities_current": ("租賃負債-流動",),
    "long_term_borrowings_current": (
        "一年或一營業週期內到期長期負債", "一年內到期長期借款", "一年內到期之長期借款",
    ),
    "other_current_liabilities": ("其他流動負債-其他", "其他流動負債"),
    "total_current_liabilities": ("流動負債合計", "流動負債總計"),
    "bonds_payable": ("應付公司債",),
    "long_term_borrowings": ("長期借款",),
    "deferred_tax_liabilities": ("遞延所得稅負債",),
    "lease_liabilities_noncurrent": ("租賃負債-非流動",),
    "net_defined_benefit_liabilities": ("淨確定福利負債-非流動",),
    "guarantee_deposits_received": ("存入保證金",),
    "total_noncurrent_liabilities": ("非流動負債合計", "非流動負債總計"),
    "total_liabilities": ("負債總計", "負債合計"),
    "common_stock": ("普通股股本",),
    "advance_receipts_for_stock": ("預收股本",),
    "capital_surplus": ("資本公積", "資本公積總計"),
    "legal_reserve": ("法定盈餘公積",),
    "special_reserve": ("特別盈餘公積",),
    "unappropriated_earnings": ("未分配盈餘",),
    "other_equity": ("其他權益", "其他權益總計"),
    "retained_earnings": ("保留盈餘總計", "保留盈餘合計"),
    "equity_parent": (
        "歸屬於母公司業主之權益合計", "母公司業主權益總計", "母公司業主之權益總計", "母公司業主之權益合計",
        "歸屬母公司業主之權益合計", "本公司業主之權益總計",
    ),
    "noncontrolling_interests": ("非控制權益",),
    "total_equity": ("權益總計", "權益合計"),
    "total_liabilities_and_equity": ("負債及權益總計", "負債與權益總計"),
})

_IS_KEYS = _build({
    "revenue": ("營業收入", "營業收入淨額"),
    "revenue_total": ("營業收入合計",),  # 含其他營業收入；毛利勾稽優先取此列
    "cogs": ("營業成本", "銷貨成本", "營業(成本)"),
    "gross_profit": ("營業毛利", "營業毛利(損)"),
    "gross_profit_net": ("營業毛利淨額", "營業毛利(損)淨額", "已實現營業毛利", "已實現營業毛利淨額"),  # 扣除未實現銷貨損益後；營業利益由此起算
    "selling_expenses": ("推銷費用", "行銷費用", "推銷(費用)"),
    "admin_expenses": ("管理費用", "管理(費用)"),
    "rd_expenses": ("研究發展費用", "研究發展(費用)"),
    "total_opex": ("營業費用合計", "營業(費用)合計"),
    "other_operating_net": ("其他收益及費損淨額", "其他營業收益及費損淨額"),  # 位於營業費用之後、營業利益之前者屬營業項目
    "operating_income": (
        "營業利益", "營業淨利", "營業利益(損失)", "營業淨利(損)", "營業利益(損)",
    ),
    "interest_income": ("利息收入",),
    "other_income": ("其他收入",),
    "other_gains_losses": ("其他利益及損失",),
    "finance_costs": ("財務成本", "利息費用", "財務(成本)"),
    "equity_method_share": ("採用權益法認列之關聯企業及合資損益之份額",),
    "nonoperating_total": ("營業外收入及支出合計", "營業外收入及(支出)合計"),
    "pretax_income": (
        "稅前淨利", "稅前淨利(損)", "繼續營業單位稅前淨利", "繼續營業部門稅前淨利",
    ),
    "income_tax": (
        "所得稅費用", "所得稅費用(利益)", "所得稅(費用)利益", "減:所得稅費用", "減:所得稅費用(利益)",
    ),
    "net_income": (
        "本期淨利", "本期淨利(損)", "本期淨利(淨損)", "本年度淨利", "淨利",
    ),
    "oci": (
        "其他綜合損益(淨額)", "其他綜合損益", "本期其他綜合損益(稅後淨額)", "本期其他綜合損益",
        "本期其他綜合損益(淨額)", "本期其他綜合(損)益", "其他綜合損益合計", "其他綜合(損)益合計",
        "本期其他綜合利益(損失)之稅後淨額",
    ),
    "total_comprehensive_income": ("本期綜合損益總額", "本期綜合(損)益總額"),
    "remeasurement_defined_benefit": ("確定福利計畫之再衡量數",),
    "fvoci_equity_gain_loss": ("透過其他綜合損益按公允價值衡量之權益工具投資未實現評價損益",),
    "oci_tax_nonreclass": ("與不重分類之項目相關之所得稅",),
    "oci_nonreclass_total": ("不重分類至損益之項目總額",),
    "fx_translation_difference": ("國外營運機構財務報表換算之兌換差額",),
    "oci_reclass_total": ("後續可能重分類至損益之項目總額",),
    "eps_basic": ("基本每股盈餘",),
    "eps_diluted": ("稀釋每股盈餘",),
})

_CF_KEYS = _build({
    "pretax_income_cf": (
        "本期稅前淨利", "稅前淨利", "本期稅前淨利(損)", "本期稅前淨利(淨損)", "繼續營業單位稅前淨利",
    ),
    "fvtpl_gain_adj": ("透過損益按公允價值衡量之金融資產利益",),
    "ppe_disposal_loss_adj": ("處分不動產、廠房及設備之損失(利益)",),
    "lease_modification_loss": ("租賃修改損失",),
    "equity_method_share_adj": ("採用權益法認列之關聯企業及合資損益之份額",),
    "impairment_reversal_nonfinancial": ("非金融資產減損迴轉利益",),
    "unrealized_fx_gain": ("未實現外幣兌換淨利益",),
    "bond_buyback_gain": ("買回公司債利益",),
    "change_net_defined_benefit": ("淨確定福利負債-非流動",),
    "fvtpl_purchase": ("取得透過損益按公允價值衡量之金融資產",),
    "fvtpl_disposal_proceeds": ("處分透過損益按公允價值衡量之金融資產",),
    "fvoci_disposal_proceeds": ("處分透過其他綜合損益按公允價值衡量之金融資產",),
    "change_refundable_deposits": ("存出保證金減少(增加)",),
    "other_noncurrent_assets_increase": ("其他非流動資產增加",),
    "guarantee_deposits_received_increase": ("存入保證金增加",),
    "dividends_paid_to_nci": ("子公司發放予非控制權益之現金股利",),
    "employee_stock_option_exercised": ("員工執行認股權",),
    "depreciation": ("折舊費用",),
    "amortization": ("攤銷費用",),
    "share_based_comp": ("股份基礎給付酬勞成本",),
    "impairment_loss_receivables": ("預期信用減損損失(迴轉利益)", "預期信用減損損失"),
    "finance_costs_adj": ("財務成本", "利息費用"),
    "interest_income_adj": ("利息收入",),
    "dividend_income_adj": ("股利收入",),
    "change_notes_receivable": ("應收票據",),
    "change_receivables": ("應收帳款",),
    "change_receivables_related": ("應收帳款-關係人",),
    "change_other_receivables": ("其他應收款",),
    "change_inventories": ("存貨",),
    "change_other_current_assets": ("其他流動資產",),
    "change_contract_liabilities": ("合約負債",),
    "change_notes_payable": ("應付票據",),
    "change_payables": ("應付帳款",),
    "change_other_payables": ("其他應付款",),
    "change_other_current_liabilities": ("其他流動負債",),
    "cash_from_operations_before_tax": (
        "營運產生之現金流入", "營運產生之現金流入(流出)", "營運產生之現金流入(出)",
        "營運產生之現金流(出)入", "營運產生之淨現金流入", "營運產生之現金流出",
    ),
    "interest_paid": ("支付之利息",),
    "income_tax_paid": ("支付之所得稅", "支付所得稅", "退還(支付)之所得稅"),
    "cfo": (
        "營業活動之淨現金流入", "營業活動之淨現金流入(流出)", "營業活動之淨現金流出",
        "營業活動之淨現金流入(出)", "營業活動之淨現金流(出)入", "營運活動之淨現金(流出)流入",
    ),
    "capex": ("取得不動產、廠房及設備",),
    "ppe_disposal_proceeds": ("處分不動產、廠房及設備價款",),
    "intangible_purchase": ("購置無形資產", "取得無形資產"),
    "prepaid_equipment_increase": ("預付設備款增加",),
    "dividends_received": ("收取之股利",),
    "interest_received": ("收取之利息",),
    "cfi": (
        "投資活動之淨現金流出", "投資活動之淨現金流入", "投資活動之淨現金流入(流出)",
        "投資活動之淨現金流入(出)", "投資活動之淨現金流(出)入", "投資活動之淨現金(流出)流入",
        "投資活動之淨現金流(出)",
    ),
    "short_term_borrowings_increase": ("短期借款增加",),
    "short_term_borrowings_decrease": ("短期借款減少",),
    "long_term_borrowings_proceeds": ("舉借長期借款",),
    "long_term_borrowings_repayment": ("償還長期借款",),
    "lease_principal_repayment": ("租賃負債本金償還", "租賃本金償還"),
    "bonds_issued": ("發行應付公司債",),
    "bonds_repaid": ("應付公司債償還",),
    "dividends_paid": ("發放現金股利",),
    "cff": (
        "籌資活動之淨現金流入(流出)", "籌資活動之淨現金流入", "籌資活動之淨現金流出",
        "籌資活動之淨現金流入(出)", "籌資活動之淨現金(流出)流入",
    ),
    "fx_effect": (
        "匯率變動對現金及約當現金影響數", "匯率變動對現金及約當現金之影響", "匯率影響數",
        "匯率影響對現金及約當現金之影響",
    ),
    "net_change_in_cash": (
        "本期現金及約當現金增加(減少)數", "本期現金及約當現金增加數", "本期現金及約當現金減少數",
        "現金及約當現金增加數", "現金及約當現金淨減少數", "現金及約當現金淨增加",
        "現金及約當現金淨增加數", "現金及約當現金淨增加(減少)", "現金及約當現金淨(減少)增加",
        "現金及約當現金增加(減少)數", "本期現金及約當現金淨增加(減少)數",
        "本期現金及約當現金(減少)增加數", "現金及約當現金淨(減少)增加數",
        "本期現金及約當現金淨增加數", "現金及約當現金淨減少",
    ),
    "cash_beginning": ("期初現金及約當現金餘額",),
    "cash_ending": ("期末現金及約當現金餘額",),
    "cash_per_bs_in_cf": ("資產負債表帳列之現金及約當現金", "合併資產負債表帳列之現金及約當現金"),
})

CANONICAL_KEYS: dict[str, dict[str, str]] = {
    "bs": _BS_KEYS,
    "is": _IS_KEYS,
    "cf": _CF_KEYS,
}

_IS_SPLIT_LABELS = {
    "母公司業主": ("net_income_parent", "tci_parent"),
    "非控制權益": ("net_income_nci", "tci_nci"),
    "合計": ("net_income_attrib_total", "tci_attrib_total"),
}


# 條件式別名（Spec §8.2）：同表沒有主科目列時才對照；label → (key, 主科目的 key 集合)
_CONDITIONAL_IS_ALIASES: dict[str, tuple[str, frozenset[str]]] = {
    **{
        _norm_label(a): ("revenue", frozenset({"revenue", "revenue_total"}))
        for a in ("銷貨收入", "銷貨收入-淨額", "銷貨收入淨額")
    },
    _norm_label("繼續營業單位本期淨利"): ("net_income", frozenset({"net_income"})),
}


def _apply_conditional_aliases(rows: list["StatementRow"]) -> None:
    """IS 條件式別名：同表已有主科目列 → 維持 key=None；否則補上對照。"""
    present = {r.key for r in rows if r.key is not None}
    for r in rows:
        if r.statement == "is" and r.key is None:
            hit = _CONDITIONAL_IS_ALIASES.get(_norm_label(r.label))
            if hit and not (hit[1] & present):
                r.key = hit[0]
    if "revenue" not in {r.key for r in rows}:  # 只有 `營業收入合計`（無 `營業收入`）→ 它就是 revenue（§8.2）
        for r in rows:
            if r.statement == "is" and r.key == "revenue_total":
                r.key = "revenue"
                break


_IS_SECTION_TOTAL_LABELS = frozenset({"合計", "淨額"})


_FH_KEYS: dict[str, dict[str, str]] = {
    "bs": FH_CANONICAL_KEYS["bs"],
    "is": FH_CANONICAL_KEYS["is"],
    "cf": {**_CF_KEYS, **FH_CANONICAL_KEYS["cf"]},  # 金控 CF＝沿用工業 CF 鍵＋金控特有 3 鍵
}


def map_key(
    statement: str, label: str, section: str | None, schema: str = "industrial"
) -> str | None:
    """label → 標準代號；對不到 → None。IS 的母公司業主／非控制權益依 section 分流。

    schema == "fh" → 金控對照表，且對照前移除 `減：` 前綴；其餘值一律走工業全域表（行為不變）。
    """
    nl = _norm_label(label)
    if schema == "fh":
        nl = _FH_LESS_PREFIX_RE.sub("", nl)
    if statement == "is" and nl in _IS_SECTION_TOTAL_LABELS and "營業外" in (section or ""):
        return "nonoperating_total"  # 營業外收入及支出區塊自己的小計（只寫「合計」「淨額」）
    if statement == "is" and nl == "合計" and "營業費用" in (section or ""):
        return "total_opex"  # 營業費用區塊自己的小計（2330 只寫「合計」）
    split_labels = _IS_SPLIT_LABELS
    if schema == "fh":  # 金控：「本公司業主」＝母公司業主；區段標題去掉 `(淨損)`／`本期稅後` 等變體字樣
        split_labels = {**_IS_SPLIT_LABELS, "本公司業主": _IS_SPLIT_LABELS["母公司業主"]}
        section = _FH_SPLIT_SEC_NOISE_RE.sub("", section) if section else section
    if statement == "is" and nl in split_labels:
        sec = section or ""
        if "淨利歸屬於" in sec:
            return split_labels[nl][0]
        if "綜合損益總額歸屬於" in sec:
            return split_labels[nl][1]
        return None
    if schema == "fh":
        return _FH_KEYS.get(statement, {}).get(nl)
    return CANONICAL_KEYS.get(statement, {}).get(nl)


# ── 表頭偵測與期間欄（Spec 2026-10-09-tw-equity-fs-generalize §2.1） ────────────

_HEADER_ZONE_MAX = 14  # 表頭區最多掃這幾列
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_CN_DIGIT_RUN_RE = re.compile(rf"[{_CN_DIGITS}]+(?=[年月日季])")
# 期間記號，依出現順序掃描（alternation 次序即優先序）
_PERIOD_TOKEN_RE = re.compile(
    r"(?P<mrange>(?P<my>\d{2,3})年(?P<m1>\d{1,2})月至(?P<m2>\d{1,2})月(?!\d{1,2}日))"  # 115年4月至6月
    r"|(?P<date>(?P<y>\d{2,3})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日)"               # 115年6月30日
    r"|(?P<drange>(?P<ry>\d{2,3})\.(?P<rm1>\d{1,2})\.(?P<rd1>\d{1,2})[〜~]\d{2,3}\.(?P<rm2>\d{1,2})\.(?P<rd2>\d{1,2}))"  # 115.4.1〜115.6.30
    r"|(?P<dot>(?P<dy>\d{2,3})\.(?P<dm>\d{1,2})\.(?P<dd>\d{1,2}))"              # 115.6.30
    r"|(?P<end>至(?P<em>\d{1,2})月(?P<ed>\d{1,2})日)"                              # 至6月30日
    r"|(?P<qtr>(?P<qy>\d{2,3})年第(?P<qn>[1-4])季)"                               # 115年第2季
    r"|(?P<half>(?P<hy>\d{2,3})年上半年度?)"                                       # 115年上半年度
    r"|(?P<year>(?P<yy>\d{2,3})年度)"                                              # 114年度
)


_END_DATES_ONLY_RE = re.compile(r"^[^\d]*(?:\d{1,2}月\d{1,2}日)+$")  # 允許列首的「代」「代碼項目」等欄名


@dataclass
class StatementHeader:
    periods: list[str]        # 欄位期間標籤（並排頁只取左半）；解析不到 → []
    has_pct: bool             # 表頭是否有 `%` 欄標題（有 → 每欄 2 個 token）
    side_by_side: bool        # 左右並排頁（期間數 2n 且含「資產」「負債」）
    skip_idx: frozenset[int]  # 該頁表頭區內應跳過的列索引（期間列、`民國…` 標題列）

    @property
    def n(self) -> int:
        return len(self.periods)


def _cn_to_int(s: str) -> int:
    """中文數字 → int：`一一五`→115（逐位）、`三十一`→31、`十二`→12。"""
    d = {"〇": 0, "零": 0, **{c: i for i, c in enumerate("一二三四五六七八九", start=1)}}
    if "十" in s:
        left, right = s.split("十", 1)
        return (d[left] if left else 1) * 10 + (d[right] if right else 0)
    return int("".join(str(d[c]) for c in s))


def _arabize(cmp: str) -> str:
    """年／月／日前的中文數字改阿拉伯數字（`一一五年六月三十日`→`115年6月30日`）。"""
    return _CN_DIGIT_RUN_RE.sub(lambda m: str(_cn_to_int(m.group(0))), cmp)


def _point(y: int, m: int, d: int) -> str:
    return f"{y:03d}-{m:02d}-{d:02d}"


def _period(y: int, m1: int, d1: int, m2: int, d2: int) -> str:
    return f"{_point(y, m1, d1)}~{_point(y, m2, d2)}"


def _month_end(roc_year: int, month: int) -> int:
    return calendar.monthrange(roc_year + 1911, month)[1]


def _periods_from_text(text: str) -> list[str]:
    """表頭區合併文字（已 NFKC、去空白、中文數字轉阿拉伯）→ 期間標籤清單；無法確定 → []。"""
    seq: list[tuple[str, Any]] = []  # (種類, 值)；full＝自帶起訖的完整期間標籤
    for m in _PERIOD_TOKEN_RE.finditer(text):
        if m.group("mrange"):
            y, m1, m2 = int(m.group("my")), int(m.group("m1")), int(m.group("m2"))
            seq.append(("full", _period(y, m1, 1, m2, _month_end(y, m2))))
        elif m.group("drange"):
            seq.append(("full", _period(int(m.group("ry")), int(m.group("rm1")), int(m.group("rd1")),
                                        int(m.group("rm2")), int(m.group("rd2")))))
        elif m.group("date"):
            seq.append(("date", (int(m.group("y")), int(m.group("m")), int(m.group("d")))))
        elif m.group("dot"):
            seq.append(("date", (int(m.group("dy")), int(m.group("dm")), int(m.group("dd")))))
        elif m.group("end"):
            seq.append(("end", (int(m.group("em")), int(m.group("ed")))))
        elif m.group("qtr"):
            y, q = int(m.group("qy")), int(m.group("qn"))
            seq.append(("full", _period(y, 3 * q - 2, 1, 3 * q, _month_end(y, 3 * q))))
        elif m.group("half"):
            y = int(m.group("hy"))
            seq.append(("full", _period(y, 1, 1, 6, 30)))
        else:
            y = int(m.group("yy"))
            seq.append(("full", _period(y, 1, 1, 12, 31)))
    dates = [v for k, v in seq if k == "date"]
    ends = [v for k, v in seq if k == "end"]
    if not ends:
        # 時點日期與自帶起訖項目依出現順序輸出
        return [_point(*v) if k == "date" else v for k, v in seq if k in ("date", "full")]
    if len(ends) != len(dates):
        return []  # 起訖無法配對 → 不猜
    # 起日與「至…」依出現順序一對一配（IS 兩列、或同列內嵌皆適用）
    return [_period(y, m1, d1, *e) for (y, m1, d1), e in zip(dates, ends)]


_DOT_DATE_LINE_RE = re.compile(r"^\d{2,3}\.\d{1,2}\.\d{1,2}(?: \d{2,3}\.\d{1,2}\.\d{1,2})*$")


def _fh_reorder_two_line_periods(periods: list[str]) -> list[str]:
    """金控雙行表頭：第一行是上年（`114年…（追溯適用後）`）、第二行才是本年，但資料欄序為本年在前。

    期間依年份非遞減（先上年後本年，且至少兩個年份）時，改回資料欄序：
    本年與上年數量相等 → 兩兩交錯（本年_i、上年_i）；本年只有 1 欄（BS）→ 本年置首；其餘維持原樣。
    """
    years = [int(p[:3]) for p in periods]
    if len(set(years)) < 2 or years != sorted(years):
        return periods
    newest = max(years)
    new = [p for p, y in zip(periods, years) if y == newest]
    old = [p for p, y in zip(periods, years) if y != newest]
    if len(new) == len(old):
        return [x for pair in zip(new, old) for x in pair]
    if len(new) == 1:
        return new + old
    return periods


def detect_header(lines: list[str], fh: bool = False) -> StatementHeader:
    """單頁表頭偵測：掃頁首至第一個資料列（含千分位金額或 `$`）為止，最多 14 列。

    含「民國」的列是表題（`民國115年…`），不當欄標題；其餘列合併後抽期間。
    fh=True（金控）：整列皆 `115.6.30 114.12.31 …` 點分日期時以 `|` 分隔各日期，
    避免去空白後 `114.1.1` 與下一個 `115.6.30` 黏成 `114.1.1115.6.30`（並排頁左右兩半各 4 欄）。
    """
    texts: list[str] = []
    skip: set[int] = set()
    all_text: list[str] = []
    end_dates: list[tuple[str, str]] = []
    for idx, raw in enumerate(lines[:_HEADER_ZONE_MAX]):
        cmp = _norm_label(raw)
        if _AMOUNT_RE.search(cmp) or "$" in cmp:
            break
        if fh and _DOT_DATE_LINE_RE.match(unicodedata.normalize("NFKC", raw).strip()):
            cmp = "|".join(unicodedata.normalize("NFKC", raw).split())
        all_text.append(cmp)
        if "民國" in cmp:
            skip.add(idx)
            continue
        ar = _arabize(cmp)
        if _END_DATES_ONLY_RE.match(ar):  # 起日列只寫「…日至」、迄日另起一列：`6月30日6月30日…`
            end_dates.extend(re.findall(r"(\d{1,2})月(\d{1,2})日", ar))
            skip.add(idx)
            continue
        if _PERIOD_TOKEN_RE.search(ar):
            skip.add(idx)
            texts.append(ar)
    periods = _periods_from_text("".join(texts))
    if fh and len(texts) >= 2:
        periods = _fh_reorder_two_line_periods(periods)
    joined = "".join(all_text)
    if end_dates and len(end_dates) == len(periods) and "日至" in joined and all("~" not in p for p in periods):
        periods = [
            _period(int(p[:3]), int(p[4:6]), int(p[7:9]), int(em), int(ed))
            for p, (em, ed) in zip(periods, end_dates)
        ]
    side = False
    n = len(periods)
    if n >= 2 and n % 2 == 0 and periods[: n // 2] == periods[n // 2:] \
            and (("資產" in joined and "負債" in joined) or joined.count("代碼") >= 2):
        side = True
        periods = periods[: n // 2]
    return StatementHeader(
        periods=periods,
        has_pct="%" in joined,
        side_by_side=side,
        skip_idx=frozenset(skip),
    )


def select_cols(statement: str, periods: list[str]) -> tuple[int | None, int | None]:
    """§1.3 選欄規則 → (current_col, prior_col)；對應 `periods` 的索引。"""
    if not periods:
        return (None, None)
    if len(periods) == 1:
        return (0, None)
    if statement == "bs":
        cur_year = int(periods[0][:3])
        for i, lab in enumerate(periods):
            if i > 0 and lab.endswith("-12-31") and int(lab[:3]) == cur_year - 1:
                return (0, i)
        return (0, 1)
    if statement == "is" and len(periods) == 4:
        ytd = [i for i, lab in enumerate(periods) if "-01-01~" in lab]
        if len(ytd) == 2:
            ytd.sort(key=lambda i: int(periods[i][:3]), reverse=True)  # 依年序：新 → 舊
            return (ytd[0], ytd[1])
    return (0, 1)


def _page_headers(lines: list[tuple[int, int, str]], fh: bool = False) -> dict[int, StatementHeader]:
    """依頁分組，每頁重新偵測表頭。"""
    by_page: dict[int, list[str]] = {}
    for page, _idx, text in lines:
        by_page.setdefault(page, []).append(text)
    return {page: detect_header(texts, fh) for page, texts in by_page.items()}


def detect_unit(lines: list[str]) -> str:
    """單位（§2.3）：幣別＋單位詞；比對不到則退回舊的 `單位：…` 寫法，皆無 → ""。"""
    for t in lines:
        cmp = _norm_label(t)
        m = _UNIT_CCY_RE.search(cmp)
        if m:
            return m.group(1) + m.group(2)
    for t in lines:
        m = _UNIT_RE.search(_norm_label(t))
        if m:
            return m.group(1)
    return ""


# ── 列解析（Spec §2.1） ───────────────────────────────────────────────────────


def _is_header(text: str, section_headers: frozenset[str]) -> bool:
    # 群組標題可帶結尾冒號（F8：`流動資產：`）→ 比對前去掉結尾 `:`
    return (
        text in section_headers
        or text.rstrip(":") in section_headers
        or text.rstrip(":").endswith("歸屬於")
    )


def _is_skip(cmp: str) -> bool:
    return (
        not cmp
        or cmp.startswith("~")
        or "(續次頁)" in cmp
        or cmp.startswith("後附合併財務報表附註")
        or cmp.startswith(("董事長", "經理人", "會計主管"))  # 頁尾簽名列
        or cmp.startswith("單位:")
        or "附註金額" in cmp  # 欄位標題列（資產 附註 金額 % 金額 %）
        or ("金額%" in cmp and not any(c.isdigit() for c in cmp))  # 並排頁欄位標題列
        # F7 表頭／雜訊列：`代碼金額%…`、`金額%…`、`項目…`、`(接次頁)`、`(承前頁)`、純期間續列（`至6月30日…`）
        or cmp.startswith(("代碼", "金額%", "項目"))
        or "(接次頁)" in cmp
        or "(承前頁)" in cmp
        or _END_ONLY_RE.match(cmp) is not None
    )


def _split_line(text: str, fh: bool = False) -> tuple[str, str, str | None, list[float | None]]:
    """→ (label, note, code, amounts)；label／note 已去空白，code 為剝除的會計代碼（F2）。

    fh=True（金控）另剝 5 位數代碼（列首 token 或黏著於中文前）；fh=False 行為不變。

    label 之後的單獨中文數字 token（`七`、`十一`）亦視為 note。
    """
    label_toks: list[str] = []
    note_toks: list[str] = []
    amt_toks: list[str] = []
    toks = _norm_line(text).split()
    code: str | None = None
    if toks:
        if len(toks) > 1 and (
            _CODE_STD_RE.match(toks[0]) or _CODE_ALPHA_RE.match(toks[0])
            or (fh and _FH_CODE_RE.match(toks[0]))
        ):
            code, toks = toks[0], toks[1:]
        else:
            m = (fh and _FH_CODE_GLUE_RE.match(toks[0])) or _CODE_GLUE_RE.match(toks[0])
            if m:
                code, toks[0] = m.group(1), toks[0][m.end():]
    for tok in toks:
        if not amt_toks and (
            _NOTE_RE.match(tok)
            or _NOTE_CONT_RE.match(tok)
            or (label_toks and _NOTE_BARE_RE.match(tok))
        ):
            note_toks.append(tok)
        elif not amt_toks and not line_amounts(tok):
            label_toks.append(tok)
        else:
            amt_toks.append(tok)
    amounts = line_amounts(" ".join(amt_toks)) if amt_toks else []
    label = _norm_label("".join(label_toks))
    note = "".join(note_toks)
    if amounts:
        label, glued = _strip_glued_note(label)
        note = glued + note
    return label, note, code, amounts


def _strip_glued_note(label: str) -> tuple[str, str]:
    """label 尾端黏著的附註 → (label, note)（§8.3.1）；剝後 label 須非空、且不以「及」「、」結尾，否則原樣。"""
    m = _GLUE_NOTE_RE.search(label)
    if m and m.start() > 0 and not label[: m.start()].endswith(("及", "、")):
        return label[: m.start()], m.group(1)
    return label, ""


def _strip_note_parens(label: str, final: bool = False) -> str:
    """移除成對（含巢狀）的 `(附註…)`（F3）。final=True 時，未閉合的 `(附註…` 自該處截到尾端。"""
    out = label
    while True:
        i = out.find("(附註")
        if i < 0:
            return out
        depth, end = 0, None
        for j in range(i, len(out)):
            if out[j] == "(":
                depth += 1
            elif out[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end is None:
            return out[:i] if final else out
        out = out[:i] + out[end:]


def _distribute(
    statement: str, amounts: list[float | None]
) -> tuple[float | None, float | None, float | None, float | None] | None:
    """金額 token 分配 → (current, current_pct, prior, prior_pct)；無金額 → None。"""
    n = len(amounts)
    if statement == "cf":
        if n >= 2:
            return (amounts[0], None, amounts[1], None)
        if n == 1:
            return (amounts[0], None, None, None)
        return None
    if n >= 4:
        return (amounts[0], amounts[1], amounts[2], amounts[3])
    if n == 3:
        return (amounts[0], None, amounts[2], None)
    if n == 2:
        return (amounts[0], None, amounts[1], None)
    return None


def _columns(
    statement: str, n: int, amounts: list[float | None]
) -> tuple[list[float | None], list[float | None] | None, int] | None:
    """金額 token 分配（§2.2）→ (columns, pcts, warn_k)；warn_k＝無法確定時的 token 數（0＝正常）；無金額（視為無資料列）→ None。

    token 數＝2n → (金額, %) 成對；＝n → 全為金額；其餘：n≤2（含未偵測）沿用舊規則，n>2 無法確定 → warn。
    """
    k = len(amounts)
    if k == 0:
        return None
    if n >= 1 and k == 2 * n:
        return amounts[0::2], (None if statement == "cf" else amounts[1::2]), 0
    if n >= 1 and k == n:
        return list(amounts), None, 0
    if n <= 2:
        d = _distribute(statement, amounts)
        if d is None:
            return None
        cur, cur_pct, pri, pri_pct = d
        return [cur, pri], [cur_pct, pri_pct], 0
    if k < 2:
        return None
    return [None] * n, None, k


def _tok_amount_count(tok: str, fh: bool = False) -> int:
    if _CODE_STD_RE.match(tok) or _NOTE_RE.match(tok) or _NOTE_CONT_RE.match(tok):
        return 0
    if fh and _FH_CODE_RE.match(tok):
        return 0
    return len(line_amounts(tok))


def _is_right_label(toks: list[str], fh: bool = False) -> bool:
    """並排頁無代碼的單邊列：科目含負債／權益（權益法、權益工具除外）→ 右半。"""
    label = "".join(t for t in toks if _tok_amount_count(t, fh) == 0)
    label = label.replace("權益法", "").replace("權益工具", "")
    return "負債" in label or "權益" in label


def _split_sides(text: str, h: int, fh: bool = False, cf: bool = False) -> tuple[str, str]:
    """並排頁一列 → (左半文字, 右半文字)（§2.2）；h＝單邊金額 token 數。

    切點：右半代碼 token（`^[23]\\d{3}$`；cf＝True 為 `B／C／D／E` 開頭代碼）為主；無代碼 → 左半金額 token 達 h 為界；
    單邊列（總計列、標題）依科目名判左右。
    """
    toks = _norm_line(text).split()
    right_code_re = _CF_RIGHT_CODE_RE if cf else _FH_RIGHT_CODE_RE if fh else _RIGHT_CODE_RE
    for j, t in enumerate(toks):
        if right_code_re.match(t):
            return " ".join(toks[:j]), " ".join(toks[j:])
    if cf and toks and _CODE_ALPHA_RE.match(toks[0]):
        return " ".join(toks), ""  # 並排 CF 左半 A 碼列、同列右半空白（`A32125 合約負債(減少) …`）
    counts = [_tok_amount_count(t, fh) for t in toks]
    total = sum(counts)
    if total >= h > 0:
        acc, cut = 0, len(toks)
        for i, c in enumerate(counts):
            acc += c
            if acc >= h:
                cut = i + 1
                break
        head, rest = toks[:cut], toks[cut:]
        if total == h and _is_right_label(head, fh):
            return "", " ".join(head)
        return " ".join(head), " ".join(rest)
    if total == 0:
        colon = [i for i, t in enumerate(toks) if t.endswith(":") or t.endswith("：")]
        if len(colon) >= 2:
            return " ".join(toks[: colon[0] + 1]), " ".join(toks[colon[0] + 1:])
        if (
            not fh and len(toks) >= 3 and colon == [len(toks) - 1] and _CODE_STD_RE.match(toks[0])
            and not right_code_re.match(toks[0])
        ):
            # 左半帶代碼科目（金額在下一列）＋右半區段標題：`1536 按攤銷後…-非流動 歸屬母公司業主之權益：`（3008）
            return " ".join(toks[:-1]), toks[-1]
    if _is_right_label(toks, fh):
        return "", " ".join(toks)
    return " ".join(toks), ""


def _make_entry(
    statement: str,
    section_headers: frozenset[str],
    n: int,
    page: int,
    idx: int,
    text: str,
    fh: bool = False,
) -> tuple | None:
    """單一（半）列 → (page, idx, label, note, code, cols)；備忘／雜訊列 → None。"""
    label, note, code, amounts = _split_line(text, fh)
    label = _strip_note_parens(label)
    cols = _columns(statement, n, amounts)
    is_hdr = _is_header(label, section_headers)
    if cols is None and code is None and note and _NOTE_BARE_RE.match(note) and not is_hdr:
        return None  # 僅帶單獨數字附註、無金額的備忘列（重大或有負債 九）
    if cols is None and idx < _HEADER_TOP_LINES and not is_hdr:
        return None
    if cols is None and code is None and (
        not label or label.startswith("(") or label.count(")") > label.count("(")
    ):
        return None  # 附註殘片（`(二)及(二十三))`、`六)及七)`）：屬上一列，不另成列
    return (page, idx, label, note, code, cols)


def _row_of(
    statement: str, section: str | None, label: str, note: str | None, page: int, idx: int,
    code: str | None, columns: list[float | None], pcts: list[float | None] | None,
    ci: int | None, pi: int | None, schema: str,
) -> StatementRow:
    return StatementRow(
        statement=statement,
        section=section,
        label=label,
        key=map_key(statement, label, section, schema) if label else None,
        note=note,
        current=columns[ci] if ci is not None and ci < len(columns) else None,
        prior=columns[pi] if pi is not None and pi < len(columns) else None,
        current_pct=pcts[ci] if pcts and ci is not None and ci < len(pcts) else None,
        prior_pct=pcts[pi] if pcts and pi is not None and pi < len(pcts) else None,
        page=page,
        line_idx=idx,
        code=code,
        columns=list(columns),
    )


def _pos(r: StatementRow) -> tuple[int, int]:
    return (r.page, r.line_idx)


def _subtotal_label(
    rows: list[StatementRow], heads: list[tuple[tuple[int, int], str]], pos: tuple[int, int],
    value: float | None, statement: str, schema: str,
) -> tuple[str, str] | None:
    """pos 所在區段的 `區段合計` → (label, section)：須有 canonical key，且 value＝區段內已解析列本期加總。"""
    before = [h for h in heads if h[0] < pos]
    if value is None or not before:
        return None
    head_pos, section = before[-1]
    label = f"{section}合計"
    if map_key(statement, label, section, schema) is None:
        return None
    vals = [r.current for r in rows if r.label and head_pos < _pos(r) < pos and r.current is not None]
    if not vals:
        return None
    total, tol = sum(vals), len(vals)  # 容差：每列 1 單位四捨五入
    if abs(total - value) <= tol or abs(abs(total) - abs(value)) <= tol:
        return label, section
    return None


def _resolve_unlabeled(
    pending: list[tuple[int, StatementRow]],
    stream_rows: list[list[StatementRow]],
    stream_heads: list[list[tuple[tuple[int, int], str]]],
    statement: str,
    schema: str,
) -> None:
    """PDF 未印科目名的小計列（2382、3008）：金額＝所在區段加總 → 補 `區段合計` 科目名；不符者丟棄。

    並排頁（兩條 stream）另處理右半無名小計被切到左半的兩型：
    ①本側不符、另一側相符 → 歸另一側；②前一列帶代碼、其金額＝另一側區段加總（3008 p5 1517）
    → 前一列改取本列金額，原金額成為另一側的區段合計。
    """
    def place(s: int, row: StatementRow, label: str, section: str) -> None:
        row.label, row.section = label, section
        row.key = map_key(statement, label, section, schema)
        target = stream_rows[s]
        k = sum(1 for r in target if _pos(r) < _pos(row))
        target.insert(k, row)

    for s, row in sorted(pending, key=lambda t: _pos(t[1])):
        pos = _pos(row)
        hit = _subtotal_label(stream_rows[s], stream_heads[s], pos, row.current, statement, schema)
        if hit:
            place(s, row, *hit)
            continue
        if len(stream_rows) < 2:
            continue
        o = 1 - s
        hit = _subtotal_label(stream_rows[o], stream_heads[o], pos, row.current, statement, schema)
        if hit:
            place(o, row, *hit)
            continue
        prev = [r for r in stream_rows[s] if r.label and _pos(r) < pos]
        if not prev or prev[-1].code is None:
            continue
        p = prev[-1]
        hit = _subtotal_label(stream_rows[o], stream_heads[o], _pos(p), p.current, statement, schema)
        if not hit:
            continue
        moved = StatementRow(**{**asdict(p), "label": "", "key": None, "note": None, "code": None})
        for f in ("current", "prior", "current_pct", "prior_pct", "columns"):
            setattr(p, f, getattr(row, f))
        place(o, moved, *hit)


def parse_statement_lines(
    lines: list[tuple[int, int, str]],
    statement: str,
    *,
    section_headers: frozenset[str],
    warnings: list[str] | None = None,
    schema: str = "industrial",
) -> tuple[list[StatementRow], str, str]:
    """逐列解析單張報表 → (rows, period_current, period_prior)；解析警告 append 到 `warnings`。"""
    rows: list[StatementRow] = []
    period = ("", "")
    fh = schema == "fh"

    # 每頁重新偵測表頭；首個解析得出期間的頁決定 period（取 §1.3 的 current／prior 欄之年）
    headers = _page_headers(lines, fh)
    stmt_hdr: StatementHeader | None = None
    for hdr in headers.values():
        if hdr.periods and stmt_hdr is None:
            stmt_hdr = hdr
        ci, pi = select_cols(statement, hdr.periods)
        if ci is not None and pi is not None:
            period = (hdr.periods[ci][:3], hdr.periods[pi][:3])
            break
    n = stmt_hdr.n if stmt_hdr else 0
    ci, pi = select_cols(statement, stmt_hdr.periods) if stmt_hdr else (None, None)
    if not stmt_hdr:
        ci, pi = 0, 1
    side = statement in ("bs", "cf") and stmt_hdr is not None and stmt_hdr.side_by_side
    half = (2 * n if stmt_hdr.has_pct else n) if side else 0

    # 預處理：每列 → 各 stream 的 entry；跳過列與期間列為 None（並排頁分左右兩條 stream）
    streams: list[list[tuple | None]] = [[], []] if side else [[]]
    for page, idx, text in lines:
        cmp = _norm_label(_norm_line(text))
        skipped = _is_skip(cmp) or idx in headers[page].skip_idx
        if not skipped:
            m = _PERIOD_RE.search(cmp) if "年" in cmp else None
            if m:
                if not period[0]:
                    period = (m.group(1), m.group(2))
                skipped = True
            elif _DATE_LINE_RE.match(cmp):  # 單一日期列（非期間列）
                skipped = True
        if skipped:
            for st in streams:
                st.append(None)
            continue
        segs = [text]
        if side:
            segs = list(_split_sides(text, half, fh, cf=statement == "cf"))
        for st, seg in zip(streams, segs):
            if seg.strip():
                st.append(_make_entry(statement, section_headers, n, page, idx, seg, fh))

    stream_rows: list[list[StatementRow]] = []
    stream_heads: list[list[tuple[tuple[int, int], str]]] = []  # 各 stream 的區段標題 (位置, section)
    pending: list[tuple[int, StatementRow]] = []  # 無科目名、無代碼的金額列 (stream, row)，待加總驗證
    for s_i, parsed in enumerate(streams):
        s_rows: list[StatementRow] = []
        heads: list[tuple[tuple[int, int], str]] = []
        stream_rows.append(s_rows)
        stream_heads.append(heads)
        section: str | None = None
        i = 0
        while i < len(parsed):
            item = parsed[i]
            i += 1
            if item is None:
                continue
            page, idx, label, note, code, cols = item
            if cols is None:
                if _is_header(label, section_headers):
                    section = label if label in section_headers else label.rstrip(":")
                    heads.append(((page, idx), section))
                    continue
                nxt = parsed[i] if i < len(parsed) else None
                if nxt is None or nxt[5] is None or nxt[4] is not None:
                    continue  # 尾列：下一列無金額（或自帶代碼＝另一筆）或不存在 → 丟棄
                label = label + nxt[2]
                note = note + nxt[3]
                code = code or nxt[4]
                cols = nxt[5]
                i += 1
            if fh and side and code is not None:
                # 並排頁（僅 side）左半科目名換行後、續行落在金額之後（`12150 …金融資 <金額> ` ／下一列 `產(附註…`）：
                # 下一筆無代碼無金額、且再下一筆不是「以它為前綴」的帶金額列 → 續行，併入科目名
                nxt = parsed[i] if i < len(parsed) else None
                nn = parsed[i + 1] if i + 1 < len(parsed) else None
                if (
                    nxt is not None and nxt[4] is None and nxt[5] is None and nxt[2]
                    and not _is_header(nxt[2], section_headers)
                    and (nn is None or nn[4] is not None or nn[5] is None)
                ):
                    label = label + nxt[2]
                    i += 1
            label = _strip_note_parens(label, final=True)
            if fh:
                label = _FH_DANGLING_NOTE_RE.sub("", label)
                label = _FH_LEAD_NOTE_FRAG_RE.sub("", label)
            label, glued = _strip_glued_note(label)  # 跨列合併後才完整的黏著附註
            note = glued + note
            columns, pcts, warn_k = cols
            if not label and code is None:
                # 無科目名、無代碼：頁碼等殘列丟棄；非金控的金額列可能是 PDF 未印科目名的小計列，待加總驗證
                if not fh and not warn_k:
                    pending.append((s_i, _row_of(statement, section, "", None, page, idx, None,
                                                 columns, pcts, ci, pi, schema)))
                continue
            if warn_k and warnings is not None:
                warnings.append(f"{statement} p{page} {label}: {warn_k} tokens")
            s_rows.append(_row_of(statement, section, label, note or None, page, idx, code,
                                  columns, pcts, ci, pi, schema))
    _resolve_unlabeled(pending, stream_rows, stream_heads, statement, schema)
    for s_rows in stream_rows:
        rows.extend(s_rows)
    if statement == "is" and not fh:
        _apply_conditional_aliases(rows)
    return rows, period[0], period[1]


# ── 篩頁（Spec §2.2） ─────────────────────────────────────────────────────────


_CONT_MARKS = ("(承前頁)", "(續前頁)", "(續)")


def _is_continuation(head: str, title_kw: str) -> bool:
    """續頁（§2.4）：頁首含承前／續前／續標記，且不含其他兩張表的表名、也不含權益變動表。"""
    if not any(m in head for m in _CONT_MARKS):
        return False
    others = [kw for kw in _TITLE_KW.values() if kw != title_kw]
    head = head.replace("資產負債表帳列", "")  # CF 現金調節列（`合併資產負債表帳列之現金…`）不是 BS 表名
    return not any(kw in head for kw in others) and "權益變動表" not in head


_OCR_CODE_RE = re.compile(r"^(\d{4}|[A-H]\d{5})(?!\S)")
_OCR_CF_KW = ("營業活動之現金流量", "投資活動之現金流量", "籌資活動之現金流量", "期末現金及約當現金餘額")
_OCR_MIN_SCORE = 3


def _ocr_statement_of(page: "Page") -> str | None:
    """OCR 頁依內容辨認表別（表名列遺失或讀錯時用）：列首 4 位數代碼首碼 1–3 計 bs、4–9 計 is，
    `[A-H]` 加 5 位數計 cf；含 CF 區段關鍵字者 cf 加權。最高分 ≥3 才歸表；權益變動表的短碼（A1／B1）不計分。"""
    score = {"bs": 0, "is": 0, "cf": 0}
    for ln in page.lines:
        m = _OCR_CODE_RE.match(ln)
        if m:
            code = m.group(1)
            score["cf" if code[0].isalpha() else "bs" if code[0] in "123" else "is"] += 1
    text = _norm_label(page.text or "")
    if any(kw in text for kw in _OCR_CF_KW):
        score["cf"] += _OCR_MIN_SCORE
    best = max(score, key=lambda k: score[k])
    return best if score[best] >= _OCR_MIN_SCORE else None


def ocr_statement_pages(doc: "PdfDoc", statement: str) -> list[int]:
    """OCR 頁中依內容辨認為 statement 的頁（首段連續頁；ocr_pages 為空 → []）。"""
    pages_by_no = {p.number: p for p in doc.pages}
    out: list[int] = []
    for n in sorted(getattr(doc, "ocr_pages", None) or []):
        if n in pages_by_no and _ocr_statement_of(pages_by_no[n]) == statement:
            if out and n != out[-1] + 1:
                break
            out.append(n)
    return out


def statement_pages(doc: "PdfDoc", rng: "PageRange | None", title_kw: str) -> list[int]:
    """範圍內頁首 5 列含 title_kw 的連續頁（§2.4 由 3 列放寬），含承前頁續頁；首個不符頁即停。"""
    if rng is None:
        return []
    out: list[int] = []
    for p in doc.pages:
        if not (rng.start <= p.number <= rng.end):
            continue
        head = _norm_label(" ".join(p.lines[:5]))
        if title_kw in head:
            out.append(p.number)
        elif out and _is_continuation(head, title_kw):
            out.append(p.number)
        elif out:
            break
    return out


# ── 勾稽（1.3 實作） ──────────────────────────────────────────────────────────


_CHECK_TOLERANCE = 2  # 仟元

# 費用項正負號慣例不一（3653 帶括號、2059 為正）：勾稽時一律視為減項（Spec §3）；row 原值不改號
# 所得稅例外：label 含「利益」且原值為負＝稅利益，淨利勾稽改加（見 run_cross_checks.side）
_EXPENSE_KEYS = frozenset({"cogs", "total_opex", "income_tax"})

# 同 key 出現多列時取最後一列（先出現的是未扣除未實現損益／其他營業項目前的小計）
_LAST_WINS_KEYS = frozenset({"gross_profit_net", "operating_income"})

# 勾稽項目的候選 key（依序取第一個有列者）：毛利淨額（扣未實現銷貨損益）只作為營業利益的起點
_KEY_CANDIDATES: dict[tuple[str, str], tuple[str, ...]] = {
    ("is_gross_profit", "revenue"): ("revenue_total", "revenue"),
    ("is_gross_profit", "gross_profit"): ("gross_profit", "gross_profit_net"),
    ("is_operating_income", "gross_profit"): ("gross_profit_net", "gross_profit"),
    ("cf_ending_eq_bs_cash", "cash_ending"): ("cash_per_bs_in_cf", "cash_ending"),  # CF 內的現金調節列
}

# (name, lhs 項目, rhs 項目)；lhs／rhs 為 key 的加總清單。順序固定依 Spec §2.4 表。
_CHECK_SPECS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("bs_assets_eq_liab_equity", ("total_assets",), ("total_liabilities_and_equity",)),
    ("bs_assets_sum", ("total_current_assets", "total_noncurrent_assets"), ("total_assets",)),
    ("bs_liab_equity_sum", ("total_liabilities", "total_equity"), ("total_liabilities_and_equity",)),
    ("is_gross_profit", ("revenue", "cogs"), ("gross_profit",)),
    ("is_operating_income", ("gross_profit", "total_opex"), ("operating_income",)),
    ("is_pretax", ("operating_income", "nonoperating_total"), ("pretax_income",)),
    ("is_net_income", ("pretax_income", "income_tax"), ("net_income",)),
    ("cf_net_change", ("cfo", "cfi", "cff", "fx_effect"), ("net_change_in_cash",)),
    ("cf_ending", ("cash_beginning", "net_change_in_cash"), ("cash_ending",)),
    ("cf_ending_eq_bs_cash", ("cash_ending",), ("cash",)),
    ("cf_pretax_eq_is", ("pretax_income_cf",), ("pretax_income",)),
]


_FH_NON_INTEREST_FALLBACK_WARNING = "無「利息以外淨收益」合計列，以各組成項加總代替（is_net_revenue 勾稽）"


def _run_fh_cross_checks(rows: list[StatementRow], warnings: list[str] | None) -> list[CrossCheck]:
    """金控勾稽（fh-schema Spec §2.4）：9 項 × (current, prior)。

    費用類（FH_EXPENSE_KEYS）一律 −|v|；insurance_other_cost 缺列以 0 計，其餘缺列 → passed=None；
    income_tax 沿用工業符號規則；無 non_interest_income 列 → 以組成項加總代替並寫 warnings。
    """
    first: dict[str, StatementRow] = {}
    for r in rows:
        if r.key is not None and r.key not in first:
            first[r.key] = r

    def val(k: str, idx: int) -> float | None:
        row = first.get(k)
        return None if row is None else (row.current if idx == 0 else row.prior)

    def side(keys: tuple[str, ...], idx: int) -> float | None:
        total = 0.0
        for k in keys:
            if k == "non_interest_income" and k not in first:
                parts = [v for c in FH_NON_INTEREST_COMPONENT_KEYS if (v := val(c, idx)) is not None]
                if not parts:
                    return None
                if warnings is not None and _FH_NON_INTEREST_FALLBACK_WARNING not in warnings:
                    warnings.append(_FH_NON_INTEREST_FALLBACK_WARNING)
                total += sum(parts)
                continue
            if k not in first and k in FH_OPTIONAL_KEYS:
                continue
            v = val(k, idx)
            if v is None:
                return None
            if k == "income_tax":
                lab = _norm_label(first[k].label)
                total += v if "(費用)" in lab else -v if "(利益)" in lab else -abs(v)
            elif k in FH_EXPENSE_KEYS:
                total += -abs(v)
            else:
                total += v
        return total

    out: list[CrossCheck] = []
    for name, lhs_keys, rhs_keys in FH_CHECK_SPECS:
        for idx, period in enumerate(("current", "prior")):
            lhs, rhs = side(lhs_keys, idx), side(rhs_keys, idx)
            passed = None if lhs is None or rhs is None else abs(lhs - rhs) <= _CHECK_TOLERANCE
            out.append(CrossCheck(name=name, period=period, lhs=lhs, rhs=rhs, passed=passed))
    return out


def run_cross_checks(
    rows: list[StatementRow],
    column_periods: dict[str, list[str]] | None = None,
    *,
    schema: str = "industrial",
    warnings: list[str] | None = None,
) -> list[CrossCheck]:
    """Spec §2.4 勾稽：11 項 × (current, prior)，name 為主序；任一輸入 None → passed=None。

    schema == "fh" → 改走金控 9 項（_run_fh_cross_checks）。
    """
    if schema == "fh":
        return _run_fh_cross_checks(rows, warnings)
    first: dict[str, StatementRow] = {}
    for r in rows:
        if r.key is not None and (r.key not in first or r.key in _LAST_WINS_KEYS):
            first[r.key] = r

    def side(keys: tuple[str, ...], idx: int, check: str = "") -> float | None:
        total = 0.0
        for k in keys:
            row = next(
                (first[c] for c in _KEY_CANDIDATES.get((check, k), (k,)) if c in first), None
            )
            v = None if row is None else (row.current if idx == 0 else row.prior)
            if v is None:
                return None
            if k == "income_tax":
                # Spec §8.1.4：括號內的詞＝負值時的意義。`(費用)` → 淨利＝稅前＋原值；`(利益)` → 稅前−原值；其餘 → 稅前−|原值|
                lab = _norm_label(row.label)
                total += v if "(費用)" in lab else -v if "(利益)" in lab else -abs(v)
            elif k in _EXPENSE_KEYS:
                total += -abs(v)
            else:
                total += v
        return total

    def bs_cash_at(end_label: str) -> float | None:
        """BS 現金在指定時點欄的值；找不到對應欄 → None（呼叫端退回 prior 欄）。"""
        row = first.get("cash")
        bs_cols = (column_periods or {}).get("bs", [])
        if row is None or end_label not in bs_cols:
            return None
        i = bs_cols.index(end_label)
        return row.columns[i] if i < len(row.columns) else None

    # 營業費用之後、營業利益之前的「其他收益及費損淨額」是營業項目，有則計入營業利益勾稽
    other_op = first.get("other_operating_net")
    op_row = first.get("operating_income")
    if other_op is not None and op_row is not None and rows.index(other_op) > rows.index(op_row):
        other_op = None

    out: list[CrossCheck] = []
    for name, lhs_keys, rhs_keys in _CHECK_SPECS:
        for idx, period in enumerate(("current", "prior")):
            lhs, rhs = side(lhs_keys, idx, name), side(rhs_keys, idx, name)
            if name == "is_operating_income" and lhs is not None and other_op is not None:
                v = other_op.current if idx == 0 else other_op.prior
                lhs = None if v is None else lhs + v
            if name == "cf_ending_eq_bs_cash" and idx == 1:
                # 半年報 CF 前期欄的期末是去年同期末（114-06-30），BS prior 是上年度末：依 CF 前期欄的期末日取 BS 同日欄
                cf_cols = (column_periods or {}).get("cf", [])
                if len(cf_cols) > 1 and "~" in cf_cols[1]:
                    same_day = bs_cash_at(cf_cols[1].split("~")[1])
                    if same_day is not None:
                        rhs = same_day
            passed = None if lhs is None or rhs is None else abs(lhs - rhs) <= _CHECK_TOLERANCE
            out.append(CrossCheck(name=name, period=period, lhs=lhs, rhs=rhs, passed=passed))
    return out


# ── 入口（Spec §2.3） ─────────────────────────────────────────────────────────


def _label_dates(label: str | None):
    """"115-01-01~115-06-30" → ((115,1,1),(115,6,30))；單日 "115-06-30" → (None,(115,6,30))；無法解析 → None。"""
    if not label:
        return None
    parts = label.split("~")
    try:
        pts = [tuple(int(x) for x in p.split("-")) for p in parts]
    except ValueError:
        return None
    if any(len(t) != 3 for t in pts) or len(pts) > 2:
        return None
    return (pts[0], pts[1]) if len(pts) == 2 else (None, pts[0])


def _col_label(cols: list[str], idx: int | None) -> str | None:
    return cols[idx] if idx is not None and 0 <= idx < len(cols) else None


def _flow_labels(column_periods, current_col, prior_col) -> tuple[str | None, str | None]:
    for st in ("is", "cf"):
        cur = _col_label(column_periods.get(st, []), current_col.get(st))
        if cur:
            return cur, _col_label(column_periods.get(st, []), prior_col.get(st))
    return None, None


def _basis_of(flow_current: str | None) -> str:
    dates = _label_dates(flow_current)
    if not dates or dates[0] is None:
        return "other"
    (y1, m1, d1), (y2, m2, d2) = dates
    if y1 == y2 and (m1, d1) == (1, 1):
        if (m2, d2) == (6, 30):
            return "H1"
        if (m2, d2) == (12, 31):
            return "FY"
    return "other"


def _days_between(label: str | None) -> int | None:
    dates = _label_dates(label)
    if not dates or dates[0] is None:
        return None
    try:
        a = date(dates[0][0] + 1911, dates[0][1], dates[0][2])
        b = date(dates[1][0] + 1911, dates[1][1], dates[1][2])
    except ValueError:
        return None
    return (b - a).days + 1


def _periods_of(column_periods, current_col, prior_col) -> dict[str, str | None]:
    out: dict[str, str | None] = dict.fromkeys(_PERIOD_TAGS)
    fc, fp = _flow_labels(column_periods, current_col, prior_col)
    out["flow_current"], out["flow_prior"] = fc, fp
    bs = column_periods.get("bs", [])
    out["bs_current"] = _col_label(bs, current_col.get("bs"))
    cur_end = _label_dates(out["bs_current"] or fc)
    fp_dates = _label_dates(fp)
    if fp_dates:
        py, pm, pd = fp_dates[1]
        for lab in bs:
            d = _label_dates(lab)
            if d and d[0] is None and d[1] == (py, pm, pd):
                out["bs_prior_same"] = lab
                break
    if cur_end:
        target = (cur_end[1][0] - 1, 12, 31)
        for lab in bs:
            d = _label_dates(lab)
            if d and d[0] is None and d[1] == target:
                out["bs_prior_fy_end"] = lab
                break
    return out


def _assurance_of(fs: "PdfDoc") -> str | None:
    text = "\f".join(p.text or "" for p in fs.pages[:5])
    hits = [(text.find(w), v) for w, v in (("核閱報告", "reviewed"), ("查核報告", "audited")) if w in text]
    return min(hits)[1] if hits else None


def extract_statements(
    fs: "PdfDoc | None", fs_anchors: dict | None, *, group: str | None = None
) -> StatementLedger | None:
    """三表篩頁→解析→對照→帳本；fs／fs_anchors 為 None 或三表皆 0 列 → None。

    group == "fh" → 金控 schema（FH_CANONICAL_KEYS／FH_SECTION_HEADERS、5 位數代碼、`減：`）；
    其他值（含 None）走工業流程，行為不變。fh 帳本的 checks 走 FH_CHECK_SPECS（9 項）。
    """
    if fs is None or fs_anchors is None:
        return None
    schema = "fh" if group == "fh" else "industrial"
    section_map = (
        {st: FH_SECTION_HEADERS[st] | _FH_EXTRA_SECTION_HEADERS.get(st, frozenset()) for st in FH_SECTION_HEADERS}
        if schema == "fh" else SECTION_HEADERS
    )
    pages_by_no = {p.number: p for p in fs.pages}
    rows: list[StatementRow] = []
    periods: dict[str, tuple[str, str]] = {}
    column_periods: dict[str, list[str]] = {"bs": [], "is": [], "cf": []}
    current_col: dict[str, int | None] = {"bs": None, "is": None, "cf": None}
    prior_col: dict[str, int | None] = {"bs": None, "is": None, "cf": None}
    parse_warnings: list[str] = []
    unit = ""
    for st in ("bs", "is", "cf"):
        pages = statement_pages(fs, fs_anchors.get(_FS_ANCHOR_KEY[st]), _TITLE_KW[st])
        if not pages:  # 表名比對無頁 → OCR 頁改依內容辨認（2330／3711 圖片頁表名遺失或讀錯）
            pages = ocr_statement_pages(fs, st)
        if not pages:
            continue
        triples = [
            (n, i, t) for n in pages for i, t in enumerate(pages_by_no[n].lines)
        ]
        if not unit:
            unit = detect_unit(pages_by_no[pages[0]].lines)
        for n in pages:  # 首個解析得出期間的頁代表該表欄位期間
            hdr = detect_header(pages_by_no[n].lines, schema == "fh")
            if hdr.periods:
                column_periods[st] = hdr.periods
                current_col[st], prior_col[st] = select_cols(st, hdr.periods)
                break
        st_rows, pc, pp = parse_statement_lines(
            triples, st, section_headers=section_map[st], warnings=parse_warnings, schema=schema
        )
        periods[st] = (pc, pp)
        rows.extend(st_rows)
    if not rows:
        return None
    pc, pp = "", ""
    for st in ("bs", "is", "cf"):
        if periods.get(st, ("", ""))[0]:
            pc, pp = periods[st]
            break
    flow_cur, flow_pri = _flow_labels(column_periods, current_col, prior_col)
    unmapped: list[str] = []
    for r in rows:
        if r.key is None and r.label not in unmapped:
            unmapped.append(r.label)
    return StatementLedger(
        unit=unit,
        period_current=pc,
        period_prior=pp,
        rows=rows,
        checks=run_cross_checks(rows, column_periods, schema=schema, warnings=parse_warnings),
        unmapped_labels=unmapped,
        column_periods=column_periods,
        current_col=current_col,
        prior_col=prior_col,
        parse_warnings=parse_warnings,
        basis=_basis_of(flow_cur),
        periods=_periods_of(column_periods, current_col, prior_col),
        days={"current": _days_between(flow_cur), "prior": _days_between(flow_pri)},
        assurance=_assurance_of(fs),
        schema=schema,
    )
