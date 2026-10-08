"""statements.py — 合併財報三表（BS／IS／CF）逐列解析、科目對照與帳本（Spec 2026-10-09-tw-equity-statements §1–§3）。

純確定性、無 LLM。列通道輸入為 `Page.lines`；金額 token 解析重用 `tables.line_amounts`。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from runtime.tw_equity.tables import _norm_line, line_amounts, parse_amount  # noqa: F401

if TYPE_CHECKING:
    from runtime.tw_equity.doc_anchor import PageRange
    from runtime.tw_equity.pdf_doc import PdfDoc


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


@dataclass
class StatementLedger:
    unit: str
    period_current: str
    period_prior: str
    rows: list[StatementRow]
    checks: list[CrossCheck]
    unmapped_labels: list[str]

    def get(
        self, key: str, statement: str | None = None
    ) -> tuple[float | None, float | None]:
        """第一個 key 相符的列 → (current, prior)；無 → (None, None)。"""
        for r in self.rows:
            if r.key == key and (statement is None or r.statement == statement):
                return (r.current, r.prior)
        return (None, None)

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
        }


# ── 正規化與常數 ──────────────────────────────────────────────────────────────

_CN_NUM = "一二三四五六七八九十"
_NOTE_RE = re.compile(
    rf"^(?:[{_CN_NUM}]+(?:\([{_CN_NUM}]+\))+|\([{_CN_NUM}]+\))"
    rf"(?:及[{_CN_NUM}]+(?:\([{_CN_NUM}]+\))*)*$"
)
# 續行開頭的「及七」「及七(二)」片段
_NOTE_CONT_RE = re.compile(rf"^及[{_CN_NUM}]+(?:\([{_CN_NUM}]+\))*$")
# 科目後的單獨中文數字附註（如「預付設備款 七」「重大之期後事項 十一」）；僅在 label 之後才算 note
_NOTE_BARE_RE = re.compile(rf"^[{_CN_NUM}]+$")
_PERIOD_RE = re.compile(r"(\d{2,3})年.*?(\d{2,3})年")
_DATE_LINE_RE = re.compile(r"^(?:民國)?\d{2,3}年\d{1,2}月\d{1,2}日")
_UNIT_RE = re.compile(r"單位[:：](.+?)(?:\(|$)")
_HEADER_TOP_LINES = 5  # 頁首這幾列內且無金額者視為公司名／表名／日期／單位列

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
    "歸屬於母公司業主之權益", "股本", "資本公積", "保留盈餘", "其他權益",
)
IS_SECTION_HEADERS = _hdrs(
    "營業費用", "營業外收入及支出", "其他綜合損益", "不重分類至損益之項目",
    "後續可能重分類至損益之項目", "淨利歸屬於:", "綜合損益總額歸屬於:",
)
CF_SECTION_HEADERS = _hdrs(
    "營業活動之現金流量", "調整項目", "收益費損項目",
    "與營業活動相關之資產/負債變動數", "與營業活動相關之資產之淨變動",
    "與營業活動相關之負債之淨變動", "投資活動之現金流量", "籌資活動之現金流量",
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
    "other_receivables": ("其他應收款",),
    "inventories": ("存貨",),
    "other_current_assets": ("其他流動資產",),
    "total_current_assets": ("流動資產合計",),
    "fvoci_noncurrent": ("透過其他綜合損益按公允價值衡量之金融資產-非流動",),
    "equity_method_investments": ("採用權益法之投資",),
    "ppe": ("不動產、廠房及設備",),
    "right_of_use_assets": ("使用權資產",),
    "intangible_assets": ("無形資產",),
    "deferred_tax_assets": ("遞延所得稅資產",),
    "prepaid_equipment": ("預付設備款",),
    "refundable_deposits": ("存出保證金",),
    "other_noncurrent_assets": ("其他非流動資產-其他", "其他非流動資產"),
    "total_noncurrent_assets": ("非流動資產合計",),
    "total_assets": ("資產總計",),
    "short_term_borrowings": ("短期借款",),
    "contract_liabilities_current": ("合約負債-流動",),
    "notes_payable": ("應付票據",),
    "accounts_payable": ("應付帳款",),
    "other_payables": ("其他應付款",),
    "current_tax_liabilities": ("本期所得稅負債",),
    "lease_liabilities_current": ("租賃負債-流動",),
    "long_term_borrowings_current": ("一年或一營業週期內到期長期負債", "一年內到期長期借款"),
    "other_current_liabilities": ("其他流動負債-其他", "其他流動負債"),
    "total_current_liabilities": ("流動負債合計",),
    "bonds_payable": ("應付公司債",),
    "long_term_borrowings": ("長期借款",),
    "deferred_tax_liabilities": ("遞延所得稅負債",),
    "lease_liabilities_noncurrent": ("租賃負債-非流動",),
    "net_defined_benefit_liabilities": ("淨確定福利負債-非流動",),
    "guarantee_deposits_received": ("存入保證金",),
    "total_noncurrent_liabilities": ("非流動負債合計",),
    "total_liabilities": ("負債總計",),
    "common_stock": ("普通股股本",),
    "advance_receipts_for_stock": ("預收股本",),
    "capital_surplus": ("資本公積",),
    "legal_reserve": ("法定盈餘公積",),
    "special_reserve": ("特別盈餘公積",),
    "unappropriated_earnings": ("未分配盈餘",),
    "other_equity": ("其他權益",),
    "equity_parent": ("歸屬於母公司業主之權益合計",),
    "noncontrolling_interests": ("非控制權益",),
    "total_equity": ("權益總計",),
    "total_liabilities_and_equity": ("負債及權益總計",),
})

_IS_KEYS = _build({
    "revenue": ("營業收入",),
    "cogs": ("營業成本",),
    "gross_profit": ("營業毛利",),
    "selling_expenses": ("推銷費用",),
    "admin_expenses": ("管理費用",),
    "rd_expenses": ("研究發展費用",),
    "total_opex": ("營業費用合計",),
    "operating_income": ("營業利益",),
    "interest_income": ("利息收入",),
    "other_income": ("其他收入",),
    "other_gains_losses": ("其他利益及損失",),
    "finance_costs": ("財務成本",),
    "equity_method_share": ("採用權益法認列之關聯企業及合資損益之份額",),
    "nonoperating_total": ("營業外收入及支出合計",),
    "pretax_income": ("稅前淨利",),
    "income_tax": ("所得稅費用",),
    "net_income": ("本期淨利",),
    "oci": ("其他綜合損益(淨額)", "其他綜合損益"),
    "total_comprehensive_income": ("本期綜合損益總額",),
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
    "pretax_income_cf": ("本期稅前淨利",),
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
    "impairment_loss_receivables": ("預期信用減損損失(迴轉利益)",),
    "finance_costs_adj": ("財務成本",),
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
    "cash_from_operations_before_tax": ("營運產生之現金流入", "營運產生之現金流入(流出)"),
    "interest_paid": ("支付之利息",),
    "income_tax_paid": ("支付之所得稅",),
    "cfo": ("營業活動之淨現金流入", "營業活動之淨現金流入(流出)", "營業活動之淨現金流出"),
    "capex": ("取得不動產、廠房及設備",),
    "ppe_disposal_proceeds": ("處分不動產、廠房及設備價款",),
    "intangible_purchase": ("購置無形資產",),
    "prepaid_equipment_increase": ("預付設備款增加",),
    "dividends_received": ("收取之股利",),
    "interest_received": ("收取之利息",),
    "cfi": ("投資活動之淨現金流出", "投資活動之淨現金流入", "投資活動之淨現金流入(流出)"),
    "short_term_borrowings_increase": ("短期借款增加",),
    "short_term_borrowings_decrease": ("短期借款減少",),
    "long_term_borrowings_proceeds": ("舉借長期借款",),
    "long_term_borrowings_repayment": ("償還長期借款",),
    "lease_principal_repayment": ("租賃負債本金償還",),
    "bonds_issued": ("發行應付公司債",),
    "bonds_repaid": ("應付公司債償還",),
    "dividends_paid": ("發放現金股利",),
    "cff": ("籌資活動之淨現金流入(流出)", "籌資活動之淨現金流入", "籌資活動之淨現金流出"),
    "fx_effect": ("匯率變動對現金及約當現金影響數",),
    "net_change_in_cash": (
        "本期現金及約當現金增加(減少)數", "本期現金及約當現金增加數", "本期現金及約當現金減少數",
    ),
    "cash_beginning": ("期初現金及約當現金餘額",),
    "cash_ending": ("期末現金及約當現金餘額",),
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


def map_key(statement: str, label: str, section: str | None) -> str | None:
    """label → 標準代號；對不到 → None。IS 的母公司業主／非控制權益依 section 分流。"""
    nl = _norm_label(label)
    if statement == "is" and nl in _IS_SPLIT_LABELS:
        sec = section or ""
        if "淨利歸屬於" in sec:
            return _IS_SPLIT_LABELS[nl][0]
        if "綜合損益總額歸屬於" in sec:
            return _IS_SPLIT_LABELS[nl][1]
        return None
    return CANONICAL_KEYS.get(statement, {}).get(nl)


# ── 列解析（Spec §2.1） ───────────────────────────────────────────────────────


def _is_header(text: str, section_headers: frozenset[str]) -> bool:
    return text in section_headers or text.rstrip(":").endswith("歸屬於")


def _is_skip(cmp: str) -> bool:
    return (
        not cmp
        or cmp.startswith("~")
        or "(續次頁)" in cmp
        or cmp.startswith("後附合併財務報表附註")
        or cmp.startswith("董事長")
        or cmp.startswith("單位:")
        or "附註金額" in cmp  # 欄位標題列（資產 附註 金額 % 金額 %）
    )


def _split_line(text: str) -> tuple[str, str, list[float | None]]:
    """→ (label, note, amounts)；label／note 已去空白。

    label 之後的單獨中文數字 token（`七`、`十一`）亦視為 note。
    """
    label_toks: list[str] = []
    note_toks: list[str] = []
    amt_toks: list[str] = []
    for tok in _norm_line(text).split():
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
    return _norm_label("".join(label_toks)), "".join(note_toks), amounts


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


def parse_statement_lines(
    lines: list[tuple[int, int, str]],
    statement: str,
    *,
    section_headers: frozenset[str],
) -> tuple[list[StatementRow], str, str]:
    """逐列解析單張報表 → (rows, period_current, period_prior)。"""
    rows: list[StatementRow] = []
    period = ("", "")
    section: str | None = None

    # 預處理：每列 → (page, idx, label, note, dist)；跳過列與期間列為 None
    parsed: list[tuple[int, int, str, str, Any] | None] = []
    for page, idx, text in lines:
        cmp = _norm_label(_norm_line(text))
        if _is_skip(cmp):
            parsed.append(None)
            continue
        m = _PERIOD_RE.search(cmp) if "年" in cmp else None
        if m:
            if not period[0]:
                period = (m.group(1), m.group(2))
            parsed.append(None)
            continue
        if _DATE_LINE_RE.match(cmp):  # 單一日期列（非期間列）
            parsed.append(None)
            continue
        label, note, amounts = _split_line(text)
        dist = _distribute(statement, amounts)
        if dist is None and note and _NOTE_BARE_RE.match(note) and not _is_header(label, section_headers):
            parsed.append(None)  # 僅帶單獨數字附註、無金額的備忘列（重大或有負債 九）
            continue
        if dist is None and idx < _HEADER_TOP_LINES and not _is_header(label, section_headers):
            parsed.append(None)
            continue
        parsed.append((page, idx, label, note, dist))

    i = 0
    while i < len(parsed):
        item = parsed[i]
        i += 1
        if item is None:
            continue
        page, idx, label, note, dist = item
        if dist is None:
            if _is_header(label, section_headers):
                section = label
                continue
            nxt = parsed[i] if i < len(parsed) else None
            if nxt is None or nxt[4] is None:
                continue  # 尾列：下一列無金額或不存在 → 丟棄
            label = label + nxt[2]
            note = note + nxt[3]
            dist = nxt[4]
            i += 1
        cur, cur_pct, pri, pri_pct = dist
        rows.append(StatementRow(
            statement=statement,
            section=section,
            label=label,
            key=map_key(statement, label, section),
            note=note or None,
            current=cur,
            prior=pri,
            current_pct=cur_pct,
            prior_pct=pri_pct,
            page=page,
            line_idx=idx,
        ))
    return rows, period[0], period[1]


# ── 篩頁（Spec §2.2） ─────────────────────────────────────────────────────────


def statement_pages(doc: "PdfDoc", rng: "PageRange | None", title_kw: str) -> list[int]:
    """範圍內頁首 3 列含 title_kw 的連續頁；首個不符頁即停。"""
    if rng is None:
        return []
    out: list[int] = []
    for p in doc.pages:
        if not (rng.start <= p.number <= rng.end):
            continue
        head = _norm_label(" ".join(p.lines[:3]))
        if title_kw in head:
            out.append(p.number)
        elif out:
            break
    return out


# ── 勾稽（1.3 實作） ──────────────────────────────────────────────────────────


_CHECK_TOLERANCE = 2  # 仟元

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


def run_cross_checks(rows: list[StatementRow]) -> list[CrossCheck]:
    """Spec §2.4 勾稽：11 項 × (current, prior)，name 為主序；任一輸入 None → passed=None。"""
    first: dict[str, StatementRow] = {}
    for r in rows:
        if r.key is not None and r.key not in first:
            first[r.key] = r

    def side(keys: tuple[str, ...], idx: int) -> float | None:
        total = 0.0
        for k in keys:
            row = first.get(k)
            v = None if row is None else (row.current if idx == 0 else row.prior)
            if v is None:
                return None
            total += v
        return total

    out: list[CrossCheck] = []
    for name, lhs_keys, rhs_keys in _CHECK_SPECS:
        for idx, period in enumerate(("current", "prior")):
            lhs, rhs = side(lhs_keys, idx), side(rhs_keys, idx)
            passed = None if lhs is None or rhs is None else abs(lhs - rhs) <= _CHECK_TOLERANCE
            out.append(CrossCheck(name=name, period=period, lhs=lhs, rhs=rhs, passed=passed))
    return out


# ── 入口（Spec §2.3） ─────────────────────────────────────────────────────────


def extract_statements(
    fs: "PdfDoc | None", fs_anchors: dict | None
) -> StatementLedger | None:
    """三表篩頁→解析→對照→帳本；fs／fs_anchors 為 None 或三表皆 0 列 → None。"""
    if fs is None or fs_anchors is None:
        return None
    pages_by_no = {p.number: p for p in fs.pages}
    rows: list[StatementRow] = []
    periods: dict[str, tuple[str, str]] = {}
    unit = ""
    for st in ("bs", "is", "cf"):
        pages = statement_pages(fs, fs_anchors.get(_FS_ANCHOR_KEY[st]), _TITLE_KW[st])
        if not pages:
            continue
        triples = [
            (n, i, t) for n in pages for i, t in enumerate(pages_by_no[n].lines)
        ]
        if not unit:
            for t in pages_by_no[pages[0]].lines:
                m = _UNIT_RE.search(_norm_label(t))
                if m:
                    unit = m.group(1)
                    break
        st_rows, pc, pp = parse_statement_lines(
            triples, st, section_headers=SECTION_HEADERS[st]
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
    unmapped: list[str] = []
    for r in rows:
        if r.key is None and r.label not in unmapped:
            unmapped.append(r.label)
    return StatementLedger(
        unit=unit,
        period_current=pc,
        period_prior=pp,
        rows=rows,
        checks=run_cross_checks(rows),
        unmapped_labels=unmapped,
    )
