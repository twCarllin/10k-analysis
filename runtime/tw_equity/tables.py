"""tables.py — 年報 / 財報表格解析層（deterministic，無 LLM）。

提供共用解析工具函式與各類比較表 dataclass 及解析函式。
後續 item（2.4 客戶表、3.x 成本表、彙整）將繼續往本檔加入新函式。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.tw_equity.pdf_doc import PdfDoc
    from runtime.tw_equity.fy_income import FyIncome
    from runtime.tw_equity.metrics import MetricsPack
    from runtime.tw_equity.statements import StatementLedger

log = logging.getLogger(__name__)


# ── 內部常數 ──────────────────────────────────────────────────────────────────

# 視為空值的破折號字元集（NFKC 之前先查）
_DASH_CHARS: frozenset[str] = frozenset(["－", "−", "—", "–", "─", "‐"])

# 單位抓取：「單位：新台幣仟元」；停在全形或半形分號 / 逗號 / 右括號 / 換行
_UNIT_RE = re.compile(r"單位[：:]\s*([^\n；;，,）)]+)")


# ── parse_amount ──────────────────────────────────────────────────────────────


def parse_amount(s: str | None) -> float | None:
    """解析金額字串為 float。

    - None / "" → None
    - 破折號類字元（全形含 U+FF0D、半形 "-"）→ None
    - 千分位逗號（全形 "，" 或半形 ","）剝除
    - 括號負數（全形「（）」或半形「()」）→ 負值
    - "9.52" → 9.52
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    # 先在原始字串上查破折號（全形）
    if s in _DASH_CHARS:
        return None
    # NFKC 正規化：全形 → 半形（"－"→"-", "（"→"(", "，"→","）
    s = unicodedata.normalize("NFKC", s).strip()
    # 正規化後若只剩半形破折號
    if s == "-":
        return None
    # 括號 → 負數
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    # 去千分位逗號
    s = s.replace(",", "")
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


# ── find_table ────────────────────────────────────────────────────────────────


def _row_text(row: list[str | None]) -> str:
    """合併列的所有格文字並做 NFKC 正規化（處理 CJK 相容表意字元）。"""
    return unicodedata.normalize("NFKC", " ".join(c or "" for c in row))


def find_table(
    tables: list[list[list[str | None]]],
    *,
    header_keywords: list[str],
    row_keywords: list[str] | None = None,
) -> list[list[str | None]] | None:
    """找第一個符合條件的表格。

    條件：
    1. 任一列的合併文字（NFKC 正規化後）含全部 header_keywords。
    2. 若給 row_keywords：另有某列含任一 row_keywords。

    無匹配 → None。
    """
    # 正規化 keywords 以配合 NFKC
    norm_headers = [unicodedata.normalize("NFKC", kw) for kw in header_keywords]
    norm_rows = (
        [unicodedata.normalize("NFKC", kw) for kw in row_keywords]
        if row_keywords is not None
        else None
    )

    for table in tables:
        # 找 header 列
        header_found = False
        for row in table:
            rt = _row_text(row)
            if all(kw in rt for kw in norm_headers):
                header_found = True
                break
        if not header_found:
            continue
        # 若有 row_keywords，確認有列命中
        if norm_rows is not None:
            row_hit = any(
                any(kw in _row_text(row) for kw in norm_rows)
                for row in table
            )
            if not row_hit:
                continue
        return table
    return None


# ── TwoYearTable dataclass ────────────────────────────────────────────────────


@dataclass
class TwoYearRow:
    label: str
    current: float | None
    prior: float | None
    diff: float | None
    diff_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "current": self.current,
            "prior": self.prior,
            "diff": self.diff,
            "diff_pct": self.diff_pct,
        }


@dataclass
class TwoYearTable:
    unit: str
    current_label: str
    prior_label: str
    rows: list[TwoYearRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "current_label": self.current_label,
            "prior_label": self.prior_label,
            "rows": [r.to_dict() for r in self.rows],
        }


# ── 內部工具 ──────────────────────────────────────────────────────────────────


def _extract_unit(page_text: str) -> str:
    """從頁文字抓「單位：XXX」；抓不到回 'unknown'。"""
    m = _UNIT_RE.search(page_text)
    if m:
        return m.group(1).strip()
    return "unknown"


def _nospace(text: str) -> str:
    """NFKC 正規化並去除所有空白（OCR 表頭常寫成「113 年度」）。"""
    return "".join(unicodedata.normalize("NFKC", text).split())


def _find_header_row_idx(
    table: list[list[str | None]],
    *,
    current_label: str,
    prior_label: str,
) -> int | None:
    """找含 current_label、prior_label 且含「差異」的 header 列索引。"""
    norm_cur = _nospace(current_label)
    norm_pri = _nospace(prior_label)
    norm_diff = "差異"
    for i, row in enumerate(table):
        rt = _nospace(_row_text(row))
        if norm_cur in rt and norm_pri in rt and norm_diff in rt:
            return i
    return None


# ── parse_two_year_table ──────────────────────────────────────────────────────


def parse_two_year_table(
    tables: list[list[list[str | None]]],
    page_text: str,
    *,
    roc_year: int,
) -> TwoYearTable | None:
    """解析財務狀況或財務績效比較表（T7a／T7b 共用）。

    Args:
        tables: pdfplumber extract_tables() 結果。
        page_text: 頁文字（用來抓單位）。
        roc_year: 民國年（例：114）；欄頭須含「{roc_year}年度」與「{roc_year-1}年度」及「差異」。

    Returns:
        TwoYearTable 或 None（表找不到 / 年度不符 / 欄頭缺差異）。
    """
    current_label = f"{roc_year}年度"
    prior_label = f"{roc_year - 1}年度"

    # 找含年度標籤與差異的表
    table = next(
        (t for t in tables
         if _find_header_row_idx(
             t, current_label=current_label, prior_label=prior_label) is not None),
        None,
    )
    if table is None:
        return None

    # 確認 header 列位置
    header_idx = _find_header_row_idx(
        table, current_label=current_label, prior_label=prior_label
    )
    if header_idx is None:
        return None

    header_row = table[header_idx]

    # 取各欄索引（用 NFKC 正規化後比對，處理 CJK 相容表意字元）
    norm_cur = _nospace(current_label)
    norm_pri = _nospace(prior_label)
    cur_col = next(
        (i for i, c in enumerate(header_row)
         if c and norm_cur in _nospace(c)), None
    )
    pri_col = next(
        (i for i, c in enumerate(header_row)
         if c and norm_pri in _nospace(c)), None
    )
    diff_col = next(
        (i for i, c in enumerate(header_row)
         if c and "差異" in unicodedata.normalize("NFKC", c)), None
    )
    if cur_col is None or pri_col is None or diff_col is None:
        return None

    # 差異 % 欄緊接差異金額欄右側
    pct_col = diff_col + 1

    # 提取單位
    unit = _extract_unit(page_text)

    # 跳過 sub-header 列（col 0 為 None 的列）
    data_start = header_idx + 1
    while data_start < len(table) and not table[data_start][0]:
        data_start += 1

    # 解析資料列
    max_col = max(cur_col, pri_col, pct_col)
    rows: list[TwoYearRow] = []
    for row in table[data_start:]:
        if len(row) <= max_col:
            continue
        label = row[0]
        if not label:
            continue
        # 跳過附註長文字列
        if len(label) > 50:
            continue
        rows.append(
            TwoYearRow(
                label=label,
                current=parse_amount(row[cur_col]),
                prior=parse_amount(row[pri_col]),
                diff=parse_amount(row[diff_col]),
                diff_pct=parse_amount(row[pct_col]),
            )
        )

    return TwoYearTable(
        unit=unit,
        current_label=current_label,
        prior_label=prior_label,
        rows=rows,
    )


# ── CustomerTable dataclass ───────────────────────────────────────────────────


@dataclass
class CustomerEntry:
    rank: int | None
    name: str
    amount: float | None
    pct: float | None
    relation: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "name": self.name,
            "amount": self.amount,
            "pct": self.pct,
            "relation": self.relation,
        }


@dataclass
class CustomerYear:
    label: str
    entries: list[CustomerEntry]
    others_pct: float | None
    total: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "entries": [e.to_dict() for e in self.entries],
            "others_pct": self.others_pct,
            "total": self.total,
        }


@dataclass
class CustomerTable:
    kind: str
    unit: str
    years: list[CustomerYear]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "unit": self.unit,
            "years": [y.to_dict() for y in self.years],
        }


# ── parse_customer_table ──────────────────────────────────────────────────────

# 每年佔 4 欄（名稱 / 金額 / 比率 / 關係），起始欄偏移
_CUST_PRIOR_START = 1   # cols 1-4
_CUST_CUR_START = 5     # cols 5-8


def parse_customer_table(
    tables: list[list[list[str | None]]],
    kind: str = "sales",
) -> CustomerTable | None:
    """解析主要進銷貨客戶表（T8），支援左右兩年並排 9 欄版面。

    Args:
        tables: pdfplumber extract_tables() 結果（可跨頁合併）。
        kind: "sales"（銷貨）或 "purchase"（進貨）。

    Returns:
        CustomerTable 或 None（表找不到）。
    """
    if kind == "sales":
        row_kws = ["銷貨"]
    elif kind == "purchase":
        row_kws = ["進貨"]
    else:
        return None

    # 找含「年度」且某列含 kind 關鍵字的表
    table = find_table(tables, header_keywords=["年度"], row_keywords=row_kws)
    if table is None:
        return None

    # Row 0：年度標籤（NFKC 正規化處理 CJK 相容字元）
    row0 = table[0]
    if len(row0) < _CUST_CUR_START + 1:
        return None
    prior_label = unicodedata.normalize("NFKC", row0[_CUST_PRIOR_START] or "").strip()
    current_label = unicodedata.normalize("NFKC", row0[_CUST_CUR_START] or "").strip()

    # 解析資料列（從 row 2 開始，跳過 row 0 年度 / row 1 欄頭）
    prior_entries: list[CustomerEntry] = []
    current_entries: list[CustomerEntry] = []
    prior_others_pct: float | None = None
    current_others_pct: float | None = None
    prior_total: float | None = None
    current_total: float | None = None

    for row in table[2:]:
        if len(row) < _CUST_CUR_START + 4:
            continue
        cell0 = (row[0] or "").strip()
        # NFKC 正規化 name 欄位以做字串比對
        prior_name_raw = unicodedata.normalize("NFKC", row[_CUST_PRIOR_START] or "").strip()
        cur_name_raw = unicodedata.normalize("NFKC", row[_CUST_CUR_START] or "").strip()

        if "其他" in prior_name_raw or "其他" in cur_name_raw:
            prior_others_pct = parse_amount(row[_CUST_PRIOR_START + 2])
            current_others_pct = parse_amount(row[_CUST_CUR_START + 2])
        elif "總計" in prior_name_raw or "總計" in cur_name_raw:
            prior_total = parse_amount(row[_CUST_PRIOR_START + 1])
            current_total = parse_amount(row[_CUST_CUR_START + 1])
        else:
            rank = int(cell0) if cell0.isdigit() else None
            if prior_name_raw:
                prior_entries.append(CustomerEntry(
                    rank=rank,
                    name=prior_name_raw,
                    amount=parse_amount(row[_CUST_PRIOR_START + 1]),
                    pct=parse_amount(row[_CUST_PRIOR_START + 2]),
                    relation=(row[_CUST_PRIOR_START + 3] or "").strip() or None,
                ))
            if cur_name_raw:
                current_entries.append(CustomerEntry(
                    rank=rank,
                    name=cur_name_raw,
                    amount=parse_amount(row[_CUST_CUR_START + 1]),
                    pct=parse_amount(row[_CUST_CUR_START + 2]),
                    relation=(row[_CUST_CUR_START + 3] or "").strip() or None,
                ))

    years = [
        CustomerYear(
            label=prior_label,
            entries=prior_entries,
            others_pct=prior_others_pct,
            total=prior_total,
        ),
        CustomerYear(
            label=current_label,
            entries=current_entries,
            others_pct=current_others_pct,
            total=current_total,
        ),
    ]

    return CustomerTable(kind=kind, unit="unknown", years=years)


# ── CostDetail dataclass ──────────────────────────────────────────────────────


@dataclass
class CostRow:
    label: str
    values: list[float | None]

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "values": self.values}


@dataclass
class CostDetail:
    kind: str
    unit: str
    periods: list[str]
    rows: list[CostRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "unit": self.unit,
            "periods": self.periods,
            "rows": [r.to_dict() for r in self.rows],
        }


# ── 成本明細表查找常數 ────────────────────────────────────────────────────────

_YEAR_HEADER_KW = "年度"          # cogs / mfg 表欄頭含年度標籤
_OPEX_MULTICOLUMN_KW = "推銷費用"  # opex 多欄版面欄頭關鍵字


# ── parse_cost_detail ─────────────────────────────────────────────────────────


def parse_cost_detail(
    tables: list[list[list[str | None]]],
    kind: str = "cogs",
) -> CostDetail | None:
    """解析成本明細表（T1 cogs／T2 mfg／T3 opex）。

    Args:
        tables: pdfplumber extract_tables() 結果（已依錨點篩選頁範圍）。
        kind: "cogs"（營業成本）、"mfg"（製造費用）或 "opex"（營業費用）。

    Returns:
        CostDetail 或 None（表找不到）。
    """
    if kind not in ("cogs", "mfg", "opex"):
        return None

    # opex：先嘗試多欄版面（推銷/管理/研發），再嘗試年度欄版面
    if kind == "opex":
        table = find_table(tables, header_keywords=[_OPEX_MULTICOLUMN_KW])
        header_kw = _OPEX_MULTICOLUMN_KW
        if table is None:
            table = find_table(tables, header_keywords=[_YEAR_HEADER_KW])
            header_kw = _YEAR_HEADER_KW
    else:
        table = find_table(tables, header_keywords=[_YEAR_HEADER_KW])
        header_kw = _YEAR_HEADER_KW

    if table is None:
        return None

    # 找 header 列（含 header_kw 的第一列）
    norm_kw = unicodedata.normalize("NFKC", header_kw)
    header_idx = next(
        (i for i, row in enumerate(table) if norm_kw in _row_text(row)),
        None,
    )
    if header_idx is None:
        return None

    header_row = table[header_idx]
    # 提取期間 / 類別標籤（跳過 col 0 的「項目」欄）
    periods = [
        unicodedata.normalize("NFKC", cell).strip()
        for cell in header_row[1:]
        if cell and cell.strip()
    ]
    if not periods:
        return None

    # 解析資料列
    n_cols = len(periods)
    rows: list[CostRow] = []
    for row in table[header_idx + 1:]:
        if not row or not row[0]:
            continue
        label = unicodedata.normalize("NFKC", row[0]).strip()
        if not label:
            continue
        values = [
            parse_amount(row[c + 1] if c + 1 < len(row) else None)
            for c in range(n_cols)
        ]
        rows.append(CostRow(label=label, values=values))

    return CostDetail(kind=kind, unit="unknown", periods=periods, rows=rows)


# ── parse_key_lines ───────────────────────────────────────────────────────────

# 財務金額 token：括號負數 / 千分位正數（至少一 ,xxx 群組；排除無逗號短整數如年份 114）
_AMOUNT_TOKEN_RE = re.compile(
    r"\([0-9,]+(?:\.[0-9]+)?\)"     # (括號負數)
    r"|[0-9]{1,3}(?:,[0-9]{3})+"    # 千分位正數
)


def parse_key_lines(
    text: str,
    labels: list[str],
) -> dict[str, tuple[float | None, float | None]]:
    """從損益表文字層逐行抓「標籤＋本期＋前期」兩個數字。

    Args:
        text: 含損益科目的頁文字。
        labels: 要抓的科目名稱清單。

    Returns:
        dict，key=label，value=(current, prior)；標籤找不到 → (None, None)。
    """
    norm_text = unicodedata.normalize("NFKC", text)
    lines = norm_text.splitlines()
    result: dict[str, tuple[float | None, float | None]] = {}

    for label in labels:
        norm_label = unicodedata.normalize("NFKC", label)
        current: float | None = None
        prior: float | None = None

        for line in lines:
            if norm_label not in line:
                continue
            # 取標籤後的文字，掃描 amount token
            idx = line.index(norm_label)
            suffix = line[idx + len(norm_label):]
            amounts = [
                v
                for tok in _AMOUNT_TOKEN_RE.findall(suffix)
                if (v := parse_amount(tok)) is not None
            ]
            if not amounts:
                continue  # 標題行／附註行無金額，繼續找下一個命中行
            if len(amounts) >= 2:
                current, prior = amounts[0], amounts[1]
            else:
                current = amounts[0]
            break  # 取第一個含金額的命中行

        result[label] = (current, prior)

    return result


# ── 列文字通道（Spec §2.3.1） ─────────────────────────────────────────────────

_LINE_TOKEN_RE = re.compile(
    r"(?<![\w,.])\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?"
    r"|(?<![\w,.])\(?\d+(?:\.\d+)?%?\)?(?![\d年月日度])"
    r"|(?<!\S)-(?!\S)"
)
_LINE_PAREN_RE = re.compile(r"\(\s*\$?\s*([\d,.%]+)\s*\)")
_ABS_LABELS = frozenset(["營業成本", "營業費用"])


def _norm_line(line: str) -> str:
    s = unicodedata.normalize("NFKC", line)
    s = _LINE_PAREN_RE.sub(r"(\1)", s)
    return s.replace("$", "")


def line_amounts(line: str) -> list[float | None]:
    """由左至右取列內金額 token；括號為負、`-` 為 None、`%` 回傳數字本身。"""
    out: list[float | None] = []
    for tok in _LINE_TOKEN_RE.findall(_norm_line(line)):
        if tok == "-":
            out.append(None)
            continue
        neg = tok.startswith("(")
        v = parse_amount(tok.strip("()%").rstrip("%"))
        out.append(-v if (neg and v is not None) else v)
    return out


def _label_suffix(line: str, label: str) -> str | None:
    """line 去空白後以 label 開頭 → 回 label 之後的（正規化）文字；否則 None。"""
    nline = _norm_line(line)
    nlabel = re.sub(r"\s+", "", _norm_line(label))
    consumed = ""
    for i, ch in enumerate(nline):
        if len(consumed) == len(nlabel):
            return nline[i:]
        if ch.isspace():
            continue
        consumed += ch
        if not nlabel.startswith(consumed):
            return None
    return "" if consumed == nlabel else None


def parse_key_lines_from_lines(
    lines: list[str],
    labels: list[str],
) -> dict[str, tuple[float | None, float | None]]:
    """列通道版 parse_key_lines；支援續行合併（最多 1 列）。找不到 → (None, None)。"""
    result: dict[str, tuple[float | None, float | None]] = {}
    for label in labels:
        value: tuple[float | None, float | None] = (None, None)
        for i, line in enumerate(lines):
            suffix = _label_suffix(line, label)
            if suffix is None:
                continue
            amts = line_amounts(suffix)
            if len(amts) < 2 and label != "營業費用" and i + 1 < len(lines):
                amts = line_amounts(suffix + " " + lines[i + 1])
            if not amts:
                continue
            if len(amts) >= 4:
                value = (amts[0], amts[2])
            elif len(amts) >= 2:
                value = (amts[0], amts[1])
            else:
                value = (amts[0], None)
            break
        if label in _ABS_LABELS:
            value = tuple(None if v is None else abs(v) for v in value)  # type: ignore[assignment]
        result[label] = value
    return result


# ── ExpenseNature dataclass (T4) ─────────────────────────────────────────────

_EXPENSE_NATURE_YEAR_RE = re.compile(r"\d{2,3}年度")
_EXPENSE_NATURE_FIELD_KEYWORDS: list[tuple[str, str]] = [
    ("銷貨成本", "cost_of_sales"),
    ("製造成本", "cost_of_sales"),
    ("營業費用", "opex"),
    ("合計", "total"),
]


@dataclass
class ExpenseNatureRow:
    label: str
    cost_of_sales: list[float | None]
    opex: list[float | None]
    total: list[float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "cost_of_sales": self.cost_of_sales,
            "opex": self.opex,
            "total": self.total,
        }


@dataclass
class ExpenseNature:
    unit: str
    periods: list[str]
    rows: list[ExpenseNatureRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "periods": self.periods,
            "rows": [r.to_dict() for r in self.rows],
        }


def parse_expense_nature(
    tables: list[list[list[str | None]]],
) -> ExpenseNature | None:
    """解析費用性質附註表（T4）。

    Returns:
        ExpenseNature 或 None（表找不到）。
    """
    table = find_table(tables, header_keywords=["銷貨成本"], row_keywords=["員工福利"])
    if table is None:
        return None

    # 找含「銷貨成本」的 header 列
    header_idx = next(
        (i for i, row in enumerate(table) if "銷貨成本" in _row_text(row)),
        None,
    )
    if header_idx is None:
        return None

    header_row = table[header_idx]
    col_map: dict[int, tuple[str, str]] = {}  # col_idx → (period, field_type)
    periods_seen: list[str] = []

    for i, cell in enumerate(header_row):
        if i == 0 or not cell:
            continue
        cell_norm = unicodedata.normalize("NFKC", cell).strip()
        m = _EXPENSE_NATURE_YEAR_RE.search(cell_norm)
        period = m.group(0) if m else None
        field_type = next(
            (ft for kw, ft in _EXPENSE_NATURE_FIELD_KEYWORDS if kw in cell_norm),
            None,
        )
        if period and field_type:
            col_map[i] = (period, field_type)
            if period not in periods_seen:
                periods_seen.append(period)

    if not periods_seen:
        return None

    rows: list[ExpenseNatureRow] = []
    for row in table[header_idx + 1:]:
        if not row or not row[0]:
            continue
        label = unicodedata.normalize("NFKC", row[0]).strip()
        if not label:
            continue
        per_period: dict[str, dict[str, float | None]] = {
            p: {"cost_of_sales": None, "opex": None, "total": None}
            for p in periods_seen
        }
        for col_i, (period, ft) in col_map.items():
            if col_i < len(row):
                per_period[period][ft] = parse_amount(row[col_i])
        rows.append(ExpenseNatureRow(
            label=label,
            cost_of_sales=[per_period[p]["cost_of_sales"] for p in periods_seen],
            opex=[per_period[p]["opex"] for p in periods_seen],
            total=[per_period[p]["total"] for p in periods_seen],
        ))

    return ExpenseNature(unit="unknown", periods=periods_seen, rows=rows)


# ── InventoryNote dataclass (T5) ─────────────────────────────────────────────

_INVENTORY_FIELD_KEYWORDS: list[tuple[str, str]] = [
    ("備抵跌價", "allowance"),  # 須在「成本」前
    ("淨額", "net"),
    ("成本", "cost"),
]
_WRITEDOWN_KW = "存貨跌價損失"


@dataclass
class InventoryRow:
    label: str
    cost: list[float | None]
    allowance: list[float | None]
    net: list[float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "cost": self.cost,
            "allowance": self.allowance,
            "net": self.net,
        }


@dataclass
class InventoryNote:
    unit: str
    periods: list[str]
    rows: list[InventoryRow]
    writedown: list[float | None] | None  # 有跌價損失列 → 各期金額；無 → None

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "periods": self.periods,
            "rows": [r.to_dict() for r in self.rows],
            "writedown": self.writedown,
        }


def parse_inventory_note(
    tables: list[list[list[str | None]]],
) -> InventoryNote | None:
    """解析存貨附註表（T5）。

    另抓「存貨跌價損失（回升利益）」列填入 writedown；無此列 → writedown=None。
    """
    table = find_table(tables, header_keywords=["備抵跌價"], row_keywords=["原料"])
    if table is None:
        return None

    # 找含「備抵跌價」且含「淨額」的 header 列
    header_idx = next(
        (i for i, row in enumerate(table)
         if "備抵跌價" in _row_text(row) and "淨額" in _row_text(row)),
        None,
    )
    if header_idx is None:
        return None

    header_row = table[header_idx]
    col_map: dict[int, tuple[str, str]] = {}
    periods_seen: list[str] = []

    for i, cell in enumerate(header_row):
        if i == 0 or not cell:
            continue
        cell_norm = unicodedata.normalize("NFKC", cell).strip()
        m = _EXPENSE_NATURE_YEAR_RE.search(cell_norm)
        period = m.group(0) if m else None
        field_type = next(
            (ft for kw, ft in _INVENTORY_FIELD_KEYWORDS if kw in cell_norm),
            None,
        )
        if period and field_type:
            col_map[i] = (period, field_type)
            if period not in periods_seen:
                periods_seen.append(period)

    if not periods_seen:
        return None

    inventory_rows: list[InventoryRow] = []
    writedown: list[float | None] | None = None

    for row in table[header_idx + 1:]:
        if not row or not row[0]:
            continue
        label = unicodedata.normalize("NFKC", row[0]).strip()
        if not label:
            continue

        if _WRITEDOWN_KW in label:
            wd: dict[str, float | None] = {p: None for p in periods_seen}
            for col_i, (period, _) in col_map.items():
                if col_i < len(row) and wd[period] is None:
                    val = parse_amount(row[col_i])
                    if val is not None:
                        wd[period] = val
            writedown = [wd[p] for p in periods_seen]
            continue

        per_period: dict[str, dict[str, float | None]] = {
            p: {"cost": None, "allowance": None, "net": None}
            for p in periods_seen
        }
        for col_i, (period, ft) in col_map.items():
            if col_i < len(row):
                per_period[period][ft] = parse_amount(row[col_i])
        inventory_rows.append(InventoryRow(
            label=label,
            cost=[per_period[p]["cost"] for p in periods_seen],
            allowance=[per_period[p]["allowance"] for p in periods_seen],
            net=[per_period[p]["net"] for p in periods_seen],
        ))

    return InventoryNote(
        unit="unknown",
        periods=periods_seen,
        rows=inventory_rows,
        writedown=writedown,
    )


# ── T4／T5 列通道解析（Spec §2.3.1） ──────────────────────────────────────────

_NUM_PAT = r"(?:\(?[\d,]+(?:\.\d+)?\)?|-)"


def _label_amounts_re(n: int) -> "re.Pattern[str]":
    return re.compile(
        r"^(?P<label>[^\d()\-,.%]*?)\s*(?P<nums>" + _NUM_PAT + r"(?:\s+" + _NUM_PAT + r"){" + str(n - 1) + r"})$"
    )


_ROW3_RE = _label_amounts_re(3)
_ROW2_RE = _label_amounts_re(2)
_PERIOD_LINE_RE = re.compile(r"^\d{2,3}年度$")
_DATE_RE = re.compile(r"\d{2,3}年\d{1,2}月\d{1,2}日")
_WRITEDOWN_RE = re.compile(r"淨變現價值而認列之銷貨成本\$?([\d,]+)及\$?([\d,]+)")


def _compact(line: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", line))


def _split_row(line: str, pat: "re.Pattern[str]") -> tuple[str, list[float | None]] | None:
    m = pat.match(_norm_line(line).strip())
    if m is None:
        return None
    label = re.sub(r"\s+", "", m.group("label"))
    return label, [parse_amount(t) for t in m.group("nums").split()]


def parse_expense_nature_lines(lines: list[str]) -> ExpenseNature | None:
    """列通道版 T4 解析；找不到「期別列＋欄頭列」或無資料列 → None。"""
    periods: list[str] = []
    data: dict[str, dict[str, tuple[float | None, ...]]] = {}
    current: str | None = None
    i = 0
    while i < len(lines):
        compact = _compact(lines[i])
        if _PERIOD_LINE_RE.match(compact):
            nxt = _compact(lines[i + 1]) if i + 1 < len(lines) else ""
            if all(k in nxt for k in ("營業成本", "營業費用", "合計")):
                current = compact
                if current not in periods:
                    periods.append(current)
                i += 2
                continue
            current = None
        elif current is not None:
            row = _split_row(lines[i], _ROW3_RE)
            if row is not None:
                data.setdefault(row[0] or "員工福利費用合計", {})[current] = tuple(row[1])
        i += 1
    if not periods or not data:
        return None
    blank: tuple[float | None, ...] = (None, None, None)
    rows = [
        ExpenseNatureRow(
            label=lb,
            cost_of_sales=[per.get(p, blank)[0] for p in periods],
            opex=[per.get(p, blank)[1] for p in periods],
            total=[per.get(p, blank)[2] for p in periods],
        )
        for lb, per in data.items()
    ]
    return ExpenseNature(unit="unknown", periods=periods, rows=rows)


def parse_inventory_note_lines(lines: list[str]) -> InventoryNote | None:
    """列通道版 T5 解析；找不到欄頭（兩個日期）或無資料列 → None。periods 為欄頭日期字串。"""
    headers = [i for i, ln in enumerate(lines) if len(_DATE_RE.findall(_compact(ln))) == 2]
    if not headers:
        return None
    inv_idx = next((i for i, ln in enumerate(lines) if "存貨" in ln), None)
    start = next((h for h in headers if inv_idx is not None and h > inv_idx), headers[0])
    periods = _DATE_RE.findall(_compact(lines[start]))

    rows: list[InventoryRow] = []
    for line in lines[start + 1:]:
        row = _split_row(line, _ROW2_RE)
        if row is None:
            continue
        rows.append(InventoryRow(
            label=row[0] or "合計", cost=[None, None], allowance=[None, None], net=row[1],
        ))
        if not row[0]:
            break
    if not rows:
        return None

    m = _WRITEDOWN_RE.search(_compact("".join(lines[start:])))
    writedown = [parse_amount(m.group(1)), parse_amount(m.group(2))] if m else None
    return InventoryNote(unit="unknown", periods=periods, rows=rows, writedown=writedown)


# ── T9 背書保證／資金貸與（Spec §2.3.3） ───────────────────────────────────────


@dataclass
class GuaranteeRow:
    no: int | None
    guarantor: str
    guaranteed: str
    relation_code: str | None
    single_limit: float | None
    max_balance: float | None
    ending_balance: float | None
    drawn: float | None
    collateral: float | None
    pct_of_net_worth: float | None
    max_limit: float | None
    parent_to_sub: str | None
    sub_to_parent: str | None
    to_china: str | None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class GuaranteesLoans:
    loans_status: str            # "none" | "table" | "unknown"
    guarantees_status: str       # "none" | "table" | "unknown"
    guarantees: list[GuaranteeRow]
    loans_raw: list[str]
    max_pct_of_net_worth: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "loans_status": self.loans_status,
            "guarantees_status": self.guarantees_status,
            "guarantees": [g.to_dict() for g in self.guarantees],
            "loans_raw": list(self.loans_raw),
            "max_pct_of_net_worth": self.max_pct_of_net_worth,
        }


_T9_RELATION_RE = re.compile(r"^\(\d\)$")
_T9_AMOUNT_TOK_RE = re.compile(r"^(?:\(?[\d,]+(?:\.\d+)?%?\)?|-)$")
_T9_ROW_START_RE = re.compile(r"^\d+\s")
_T9_FIELDS = ["single_limit", "max_balance", "ending_balance", "drawn", "collateral",
              "pct_of_net_worth", "max_limit"]


def _t9_status(compact_lines: list[str], subject: str) -> str:
    none_kw = unicodedata.normalize("NFKC", f"{subject}：無")
    table_kw = unicodedata.normalize("NFKC", f"{subject}：請詳附表")
    if any(none_kw in c for c in compact_lines):
        return "none"
    if any(table_kw in c for c in compact_lines):
        return "table"
    return "unknown"


def _t9_parse_row(line: str) -> GuaranteeRow:
    toks = _norm_line(line).split()
    no = int(toks[0])
    i = 1
    names: list[str] = []
    relation: str | None = None
    while i < len(toks):
        if _T9_RELATION_RE.match(toks[i]):
            relation = toks[i]
            i += 1
            break
        if i >= 3 and _T9_AMOUNT_TOK_RE.match(toks[i]):
            break
        names.append(toks[i])
        i += 1
    rest = toks[i:]
    amts = [t for t in rest if _T9_AMOUNT_TOK_RE.match(t)][:len(_T9_FIELDS)]
    flags = [t for t in rest if t in ("Y", "N")][:3]
    vals = {f: (parse_amount(amts[k].rstrip("%")) if k < len(amts) else None)
            for k, f in enumerate(_T9_FIELDS)}
    flags += [None] * (3 - len(flags))  # type: ignore[list-item]
    return GuaranteeRow(
        no=no,
        guarantor=names[0] if names else "",
        guaranteed="".join(names[1:]),
        relation_code=relation,
        parent_to_sub=flags[0], sub_to_parent=flags[1], to_china=flags[2],
        **vals,
    )


def parse_guarantees_loans(lines: list[str]) -> GuaranteesLoans | None:
    """解析背書保證／資金貸與（T9）；兩狀態皆 unknown 且無資料列 → None。"""
    compact_lines = [_compact(ln) for ln in lines]
    loans_status = _t9_status(compact_lines, "資金貸與他人")
    guarantees_status = _t9_status(compact_lines, "為他人背書保證")

    guarantees: list[GuaranteeRow] = []
    loans_raw: list[str] = []
    mode: str | None = None
    i = 0
    while i < len(lines):
        c = compact_lines[i]
        if c == "為他人背書保證":
            mode = "g"
        elif c == "資金貸與他人":
            mode = "l"
        elif mode == "l" and _T9_ROW_START_RE.match(lines[i].strip()):
            loans_raw.append(lines[i].strip())
        elif (mode == "g" and _T9_ROW_START_RE.match(lines[i].strip())
              and len(line_amounts(lines[i])) >= 5):
            row = _t9_parse_row(lines[i])
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if nxt is not None and not line_amounts(nxt) and not nxt.strip().startswith("註"):
                row.guarantor += _compact(nxt)
                i += 1
            guarantees.append(row)
        i += 1

    if loans_status == "unknown" and guarantees_status == "unknown" and not guarantees and not loans_raw:
        return None
    pcts = [g.pct_of_net_worth for g in guarantees if g.pct_of_net_worth is not None]
    return GuaranteesLoans(
        loans_status=loans_status,
        guarantees_status=guarantees_status,
        guarantees=guarantees,
        loans_raw=loans_raw,
        max_pct_of_net_worth=max(pcts) if pcts else None,
    )


# ── T10 股權質押（Spec §2.3.4，table 通道） ────────────────────────────────────


@dataclass
class PledgeRow:
    name: str
    reason: str | None
    date: str | None
    counterparty: str | None
    relation: str | None
    shares: float | None
    holding_pct: float | None
    pledge_pct: float | None
    amount: float | None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class PledgeTable:
    status: str                  # "rows" | "none" | "external_reference" | "unknown"
    rows: list[PledgeRow]
    max_pledge_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rows": [r.to_dict() for r in self.rows],
            "max_pledge_pct": self.max_pledge_pct,
        }


_PLEDGE_MARKER = "股權質押資訊"
_PLEDGE_EXTERNAL_KW = "請參閱公開資訊觀測站"
_PLEDGE_WINDOW = 80


def _cell_text(cell: str | None) -> str | None:
    """去除 cell 內換行；空或 `-` → None。"""
    if cell is None:
        return None
    t = unicodedata.normalize("NFKC", cell).replace("\n", "").strip()
    return None if t in ("", "-") else t


def _cell_num(cell: str | None) -> float | None:
    t = _cell_text(cell)
    return parse_amount(t.rstrip("%")) if t is not None else None


def parse_pledges(
    tables: list[list[list[str | None]]],
    page_text: str,
) -> PledgeTable:
    """解析股權質押資訊（T10）；只看「股權質押資訊」之後的文字。一律回 PledgeTable。"""
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", page_text or ""))
    idx = compact.find(_PLEDGE_MARKER)
    if idx < 0:
        return PledgeTable(status="unknown", rows=[], max_pledge_pct=None)
    after = compact[idx + len(_PLEDGE_MARKER):]

    for table in tables:
        if not table:
            continue
        header = re.sub(r"\s+", "", unicodedata.normalize("NFKC", " ".join(c or "" for c in table[0])))
        if "質押" not in header or "股數" not in header:
            continue
        rows: list[PledgeRow] = []
        for r in table[1:]:
            cells = list(r) + [None] * (9 - len(r))
            name = _cell_text(cells[0])
            if not name:
                continue
            rows.append(PledgeRow(
                name=name, reason=_cell_text(cells[1]), date=_cell_text(cells[2]),
                counterparty=_cell_text(cells[3]), relation=_cell_text(cells[4]),
                shares=_cell_num(cells[5]), holding_pct=_cell_num(cells[6]),
                pledge_pct=_cell_num(cells[7]), amount=_cell_num(cells[8]),
            ))
        pcts = [x.pledge_pct for x in rows if x.pledge_pct is not None]
        return PledgeTable(status="rows", rows=rows, max_pledge_pct=max(pcts) if pcts else None)

    window = after[:_PLEDGE_WINDOW]
    if _PLEDGE_EXTERNAL_KW in window:
        return PledgeTable(status="external_reference", rows=[], max_pledge_pct=None)
    if "無" in window:
        return PledgeTable(status="none", rows=[], max_pledge_pct=None)
    return PledgeTable(status="unknown", rows=[], max_pledge_pct=None)


# ── T10 前十大股東（Spec §2.3.4，table 通道） ──────────────────────────────────


@dataclass
class ShareholderRow:
    name: str
    is_representative: bool
    shares: float | None
    pct: float | None
    spouse_shares: float | None
    spouse_pct: float | None
    nominee_shares: float | None
    nominee_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class TopShareholders:
    rows: list[ShareholderRow]
    relation_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [r.to_dict() for r in self.rows],
            "relation_notes": list(self.relation_notes),
        }


_REP_SPLIT_RE = re.compile(r"\s*代表人[:：]\s*")
_NOTE_LINE_RE = re.compile(r"^\d+\.")


def _relation_notes(page_text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", page_text or "")
    m = re.search(r"註:\s*\d+\.", text)
    if m is None:
        return []
    body = text[m.start():].split(":", 1)[1]
    notes: list[str] = []
    for ln in body.splitlines():
        ln = ln.strip()
        if _NOTE_LINE_RE.match(ln):
            notes.append(ln)
        elif ln and notes:
            break
    return notes


def parse_top_shareholders(
    tables: list[list[list[str | None]]],
    page_text: str,
) -> TopShareholders | None:
    """解析前十大股東表（T10）；無符合表頭的表 → None。"""
    table = None
    for t in tables:
        if not t:
            continue
        header = re.sub(r"\s+", "", unicodedata.normalize("NFKC", " ".join(c or "" for c in t[0])))
        if "本人" in header and "持有股份" in header:
            table = t
            break
    if table is None:
        return None

    def nums(row: list[str | None]) -> tuple[float | None, ...]:
        cells = list(row) + [None] * (7 - len(row))
        return tuple(_cell_num(cells[i]) for i in range(1, 7))

    rows: list[ShareholderRow] = []
    data = table[1:]
    i = 0
    while i < len(data):
        row = data[i]
        i += 1
        name_raw = unicodedata.normalize("NFKC", (row[0] if row else None) or "")
        if not name_raw.strip():
            continue
        if _REP_SPLIT_RE.search(name_raw):
            corp, rep = _REP_SPLIT_RE.split(name_raw, 1)
            corp, rep = corp.replace("\n", "").strip(), rep.replace("\n", "").strip()
            rows.append(ShareholderRow(corp, False, *nums(row)))
            rep_nums = (None,) * 6
            if i < len(data) and not _cell_text(data[i][0] if data[i] else None):
                rep_nums = nums(data[i])
                i += 1
            rows.append(ShareholderRow(rep, True, *rep_nums))
        else:
            rows.append(ShareholderRow(name_raw.replace("\n", "").strip(), False, *nums(row)))
    return TopShareholders(rows=rows, relation_notes=_relation_notes(page_text))


# ── ProductionSalesTable dataclass (T6) ──────────────────────────────────────

_PROD_SALES_COL_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("prod_qty",    ("生產量", "產量")),
    ("prod_value",  ("生產值", "產值", "生產金額")),
    ("sales_qty",   ("銷售量", "銷量")),
    ("sales_value", ("銷售值", "銷售金額")),
]


def _safe_divide(
    numerator: float | None,
    denominator: float | None,
) -> float | None:
    """安全除法；任一為 None 或除數為 0 → None。"""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


@dataclass
class ProductionSalesRow:
    product: str
    prod_qty: float | None
    prod_value: float | None
    sales_qty: float | None
    sales_value: float | None
    implied_unit_cost: float | None
    implied_asp: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "prod_qty": self.prod_qty,
            "prod_value": self.prod_value,
            "sales_qty": self.sales_qty,
            "sales_value": self.sales_value,
            "implied_unit_cost": self.implied_unit_cost,
            "implied_asp": self.implied_asp,
        }


@dataclass
class ProductionSalesTable:
    unit: str
    rows: list[ProductionSalesRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "rows": [r.to_dict() for r in self.rows],
        }


def parse_production_sales(
    tables: list[list[list[str | None]]],
    page_text: str = "",
) -> ProductionSalesTable | None:
    """解析產銷量值表（T6）；錨不到 → None。

    Args:
        tables: pdfplumber extract_tables() 結果。
        page_text: 頁文字（用來抓單位）。

    Returns:
        ProductionSalesTable 或 None（表找不到）。
    """
    table = find_table(tables, header_keywords=["生產量", "銷售量"])
    if table is None:
        table = find_table(tables, header_keywords=["產量", "銷量"])
    if table is None:
        return None

    # 找 header 列（同時含生產與銷售量欄位）
    header_idx = None
    for i, row in enumerate(table):
        rt = _row_text(row)
        prod_hit = any(
            kw in rt for _, kws in _PROD_SALES_COL_MAP[:2] for kw in kws
        )
        sales_hit = any(
            kw in rt for _, kws in _PROD_SALES_COL_MAP[2:] for kw in kws
        )
        if prod_hit and sales_hit:
            header_idx = i
            break
    if header_idx is None:
        return None

    header_row = table[header_idx]
    col_roles: dict[int, str] = {}
    for col_i, cell in enumerate(header_row):
        if not cell:
            continue
        cell_norm = unicodedata.normalize("NFKC", cell).strip()
        for field, keywords in _PROD_SALES_COL_MAP:
            if any(kw in cell_norm for kw in keywords):
                col_roles[col_i] = field
                break

    if not any(role in col_roles.values() for role in ("prod_qty", "sales_qty")):
        return None

    unit = _extract_unit(page_text)
    rows: list[ProductionSalesRow] = []

    for row in table[header_idx + 1:]:
        if not row or not row[0]:
            continue
        product = unicodedata.normalize("NFKC", row[0]).strip()
        if not product:
            continue
        vals: dict[str, float | None] = {
            "prod_qty": None,
            "prod_value": None,
            "sales_qty": None,
            "sales_value": None,
        }
        for col_i, field in col_roles.items():
            if col_i < len(row):
                vals[field] = parse_amount(row[col_i])
        rows.append(ProductionSalesRow(
            product=product,
            prod_qty=vals["prod_qty"],
            prod_value=vals["prod_value"],
            sales_qty=vals["sales_qty"],
            sales_value=vals["sales_value"],
            implied_unit_cost=_safe_divide(vals["prod_value"], vals["prod_qty"]),
            implied_asp=_safe_divide(vals["sales_value"], vals["sales_qty"]),
        ))

    return ProductionSalesTable(unit=unit, rows=rows)


# ── TablesBundle 彙整 ─────────────────────────────────────────────────────────

# missing_tables 固定名稱
_MISS_T1 = "T1"
_MISS_T2 = "T2"
_MISS_T3 = "T3"
_MISS_T4 = "T4"
_MISS_T5 = "T5"
_MISS_T6 = "T6"
_MISS_T7A = "T7a"
_MISS_T7B = "T7b"
_MISS_T8_SALES = "T8_sales"
_MISS_T8_PURCHASE = "T8_purchase"
_MISS_T9 = "T9"
_MISS_T10_PLEDGE = "T10_pledge"
_MISS_T10_TOP10 = "T10_top10"
_MISS_FS_BS = "FS_BS"
_MISS_FS_IS = "FS_IS"
_MISS_FS_CF = "FS_CF"

# 損益關鍵科目標籤（parse_key_lines 用）
_KEY_LINE_LABELS: list[str] = [
    "營業收入", "營業成本", "營業毛利", "營業費用", "營業利益", "本期淨利"
]


def _sum_pct(entries: list["CustomerEntry"]) -> float | None:
    vals = [e.pct for e in entries if e.pct is not None]
    return round(sum(vals), 2) if vals else None


def _concentration(table: "CustomerTable | None") -> list[dict[str, Any]]:
    """T8 衍生集中度：每年度 top1／top3／已列名加總（pct 為 None 不計入；表缺 → []）。"""
    if table is None:
        return []
    out: list[dict[str, Any]] = []
    for y in table.years:
        top1 = y.entries[0].pct if y.entries else None
        out.append({
            "label": y.label,
            "top1_pct": round(top1, 2) if top1 is not None else None,
            "top3_pct": _sum_pct(y.entries[:3]),
            "named_total_pct": _sum_pct(y.entries),
        })
    return out


@dataclass
class TablesBundle:
    fin_position: TwoYearTable | None
    fin_performance: TwoYearTable | None
    customers_sales: CustomerTable | None
    customers_purchase: CustomerTable | None
    production_sales: ProductionSalesTable | None
    expense_nature: ExpenseNature | None
    inventory: InventoryNote | None
    cost_detail_cogs: CostDetail | None
    cost_detail_mfg: CostDetail | None
    cost_detail_opex: CostDetail | None
    consolidated_key_lines: dict
    parent_key_lines: dict
    parent_cost_coverage: float | None       # 個體營業成本 / 合併營業成本
    missing_tables: list[str]                # 固定名稱：T1–T6,T7a,T7b,T8_sales,T8_purchase,T9,T10_pledge,T10_top10,FS_BS,FS_IS,FS_CF
    unit_notes: dict[str, str]
    guarantees_loans: "GuaranteesLoans | None" = None
    pledges: "PledgeTable | None" = None
    top_shareholders: "TopShareholders | None" = None
    statements: "StatementLedger | None" = None
    metrics: "MetricsPack | None" = None            # 階段 2：帳本衍生指標與 bridge
    fy_income: "FyIncome | None" = None             # FY 損益表（年報財務績效比較分析表；TTM 用）
    fy_income_error: str | None = None             # FY 損益表解析例外（`<類型>: <訊息>`）；成功 → None
    fh_notes_error: str | None = None               # 金控附註抽取例外（`<類型>: <訊息>`）；僅 fh 且失敗時 to_dict 輸出
    fh_notes: Any = None                            # 金控附註抽取（FhNotes；僅 group=="fh"）；其餘 None、to_dict 不輸出

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        if self.fh_notes is not None:
            d["fh_notes"] = self.fh_notes.to_dict()
        if self.fh_notes_error is not None:
            d["fh_notes_error"] = self.fh_notes_error
        return d

    def _base_dict(self) -> dict[str, Any]:
        return {
            "fin_position": self.fin_position.to_dict() if self.fin_position else None,
            "fin_performance": self.fin_performance.to_dict() if self.fin_performance else None,
            "customers_sales": self.customers_sales.to_dict() if self.customers_sales else None,
            "customers_purchase": self.customers_purchase.to_dict() if self.customers_purchase else None,
            "production_sales": self.production_sales.to_dict() if self.production_sales else None,
            "expense_nature": self.expense_nature.to_dict() if self.expense_nature else None,
            "inventory": self.inventory.to_dict() if self.inventory else None,
            "cost_detail_cogs": self.cost_detail_cogs.to_dict() if self.cost_detail_cogs else None,
            "cost_detail_mfg": self.cost_detail_mfg.to_dict() if self.cost_detail_mfg else None,
            "cost_detail_opex": self.cost_detail_opex.to_dict() if self.cost_detail_opex else None,
            "consolidated_key_lines": {k: list(v) for k, v in self.consolidated_key_lines.items()},
            "parent_key_lines": {k: list(v) for k, v in self.parent_key_lines.items()},
            "parent_cost_coverage": self.parent_cost_coverage,
            "missing_tables": self.missing_tables,
            "unit_notes": self.unit_notes,
            "concentration": {
                "T8_sales": _concentration(self.customers_sales),
                "T8_purchase": _concentration(self.customers_purchase),
            },
            "guarantees_loans": self.guarantees_loans.to_dict() if self.guarantees_loans else None,
            "pledges": self.pledges.to_dict() if self.pledges else None,
            "top_shareholders": self.top_shareholders.to_dict() if self.top_shareholders else None,
            "statements": self.statements.to_dict() if self.statements else None,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "fy_income": self.fy_income.to_dict() if self.fy_income else None,
            "fy_income_error": self.fy_income_error,
        }


def extract_tables(
    ar: "PdfDoc",
    ar_anchors: dict,
    fs: "PdfDoc | None",
    fs_anchors: "dict | None",
    ps: "PdfDoc | None",
    ps_anchors: "dict | None",
    *,
    roc_year: int,
    gov_anchors: dict | None = None,
    group: str | None = None,
) -> TablesBundle:
    """彙整年報、合併財報、個體財報的所有表格解析結果。

    Args:
        ar: 年報 PdfDoc。
        ar_anchors: 年報錨點 dict（key → PageRange | None）。
        fs: 合併財報 PdfDoc；缺檔時傳 None。
        fs_anchors: 合併財報錨點 dict；fs=None 時傳 None。
        ps: 個體財報 PdfDoc；缺檔時傳 None。
        ps_anchors: 個體財報錨點 dict；ps=None 時傳 None。
        roc_year: 民國年（例：114）。
        gov_anchors: 年報治理錨點 dict（ar_pledge／ar_top10）；None 時兩個 T10 表皆缺。
        group: 公司類別；"fh" 走金控三表 schema，其餘（含 None）走工業流程。

    Returns:
        TablesBundle 彙整結果；缺檔時對應表進 missing_tables，不 raise。
    """
    missing: list[str] = []
    unit_notes: dict[str, str] = {}

    # ── 內部輔助：取頁範圍 tables 與 text ────────────────────────────────────

    def _get_ar(key: str) -> tuple[list, str]:
        pr = ar_anchors.get(key)
        if pr is None:
            return [], ""
        return ar.tables_of(pr.start, pr.end), ar.text_of(pr.start, pr.end)

    def _get_fs(key: str) -> tuple[list | None, str | None]:
        if fs is None or fs_anchors is None:
            return None, None
        pr = fs_anchors.get(key)
        if pr is None:
            return None, None
        return fs.tables_of(pr.start, pr.end), fs.text_of(pr.start, pr.end)

    def _get_ps(key: str) -> tuple[list | None, str | None]:
        if ps is None or ps_anchors is None:
            return None, None
        pr = ps_anchors.get(key)
        if pr is None:
            return None, None
        return ps.tables_of(pr.start, pr.end), ps.text_of(pr.start, pr.end)

    def _get_fs_lines(key: str) -> list[str]:
        if fs is None or fs_anchors is None:
            return []
        pr = fs_anchors.get(key)
        if pr is None:
            return []
        return fs.lines_of(pr.start, pr.end)

    # ── T7a 財務狀況表（年報 ar_fin_position） ────────────────────────────────
    tables_7a, text_7a = _get_ar("ar_fin_position")
    fin_position = parse_two_year_table(tables_7a, text_7a, roc_year=roc_year)
    if fin_position is None:
        missing.append(_MISS_T7A)

    # ── T7b 財務績效表（年報 ar_fin_performance） ─────────────────────────────
    tables_7b, text_7b = _get_ar("ar_fin_performance")
    fin_performance = parse_two_year_table(tables_7b, text_7b, roc_year=roc_year)
    if fin_performance is None:
        missing.append(_MISS_T7B)

    # ── T8 主要進銷貨客戶（年報 ar_customers） ────────────────────────────────
    # 搜尋範圍：ar_market 起頁到 ar_customers 終頁（進貨表可能落在 ar_market 範圍）；ar_market 缺則只用 ar_customers
    pr_cust = ar_anchors.get("ar_customers")
    pr_mkt = ar_anchors.get("ar_market")
    if pr_cust is None:
        tables_cust: list = []
    elif pr_mkt is None:
        tables_cust = ar.tables_of(pr_cust.start, pr_cust.end)
    else:
        tables_cust = ar.tables_of(min(pr_mkt.start, pr_cust.start), pr_cust.end)
    customers_sales = parse_customer_table(tables_cust, kind="sales")
    if customers_sales is None:
        missing.append(_MISS_T8_SALES)
    customers_purchase = parse_customer_table(tables_cust, kind="purchase")
    if customers_purchase is None:
        missing.append(_MISS_T8_PURCHASE)

    # ── T6 產銷量值（年報 ar_production_sales） ───────────────────────────────
    tables_prod, text_prod = _get_ar("ar_production_sales")
    production_sales = parse_production_sales(tables_prod, text_prod)
    if production_sales is None:
        missing.append(_MISS_T6)

    # ── T4 費用性質（合併財報 fs_note_expense_nature） ───────────────────────
    fs_tables_en, _ = _get_fs("fs_note_expense_nature")
    expense_nature = parse_expense_nature_lines(_get_fs_lines("fs_note_expense_nature"))
    if expense_nature is None and fs_tables_en is not None:
        expense_nature = parse_expense_nature(fs_tables_en)
    if expense_nature is None:
        missing.append(_MISS_T4)

    # ── T5 存貨附註（合併財報 fs_note_inventory） ────────────────────────────
    fs_tables_inv, _ = _get_fs("fs_note_inventory")
    inventory = parse_inventory_note_lines(_get_fs_lines("fs_note_inventory"))
    if inventory is None and fs_tables_inv is not None:
        inventory = parse_inventory_note(fs_tables_inv)
    if inventory is None:
        missing.append(_MISS_T5)

    # ── T1 營業成本明細（個體財報 ps_cogs_detail） ────────────────────────────
    ps_tables_cogs, _ = _get_ps("ps_cogs_detail")
    if ps_tables_cogs is None:
        cost_detail_cogs = None
        missing.append(_MISS_T1)
    else:
        cost_detail_cogs = parse_cost_detail(ps_tables_cogs, kind="cogs")
        if cost_detail_cogs is None:
            missing.append(_MISS_T1)

    # ── T2 製造費用明細（個體財報 ps_mfg_overhead） ──────────────────────────
    ps_tables_mfg, _ = _get_ps("ps_mfg_overhead")
    if ps_tables_mfg is None:
        cost_detail_mfg = None
        missing.append(_MISS_T2)
    else:
        cost_detail_mfg = parse_cost_detail(ps_tables_mfg, kind="mfg")
        if cost_detail_mfg is None:
            missing.append(_MISS_T2)

    # ── T3 營業費用明細（個體財報 ps_opex_detail） ────────────────────────────
    ps_tables_opex, _ = _get_ps("ps_opex_detail")
    if ps_tables_opex is None:
        cost_detail_opex = None
        missing.append(_MISS_T3)
    else:
        cost_detail_opex = parse_cost_detail(ps_tables_opex, kind="opex")
        if cost_detail_opex is None:
            missing.append(_MISS_T3)

    # ── consolidated_key_lines（合併損益表 fs_is → 或 ar_fin_performance 備援）
    _, fs_is_text = _get_fs("fs_is")
    consolidated_key_lines = parse_key_lines_from_lines(_get_fs_lines("fs_is"), _KEY_LINE_LABELS)
    if all(v == (None, None) for v in consolidated_key_lines.values()):
        consolidated_key_lines = None  # 列通道無結果 → 退回 table 通道
    if consolidated_key_lines is not None:
        pass
    elif fs_is_text:
        consolidated_key_lines = parse_key_lines(fs_is_text, _KEY_LINE_LABELS)
    else:
        consolidated_key_lines = parse_key_lines(text_7b, _KEY_LINE_LABELS)

    # ── T9 背書保證／資金貸與（合併財報 fs_note_disclosure 列通道） ────────────
    guarantees_loans = parse_guarantees_loans(_get_fs_lines("fs_note_disclosure"))
    if guarantees_loans is None:
        missing.append(_MISS_T9)

    # ── T10 股權質押／前十大股東（年報治理錨點，table 通道） ───────────────────
    pledges: PledgeTable | None = None
    top_shareholders: TopShareholders | None = None
    if gov_anchors is not None:
        pr_p = gov_anchors.get("ar_pledge")
        if pr_p is not None:
            pledges = parse_pledges(
                ar.tables_of(pr_p.start, pr_p.end), ar.text_of(pr_p.start, pr_p.end)
            )
        pr_t = gov_anchors.get("ar_top10")
        if pr_t is not None:
            top_shareholders = parse_top_shareholders(
                ar.tables_of(pr_t.start, pr_t.end), ar.text_of(pr_t.start, pr_t.end)
            )
    if pledges is None or pledges.status == "unknown":
        missing.append(_MISS_T10_PLEDGE)
    if top_shareholders is None:
        missing.append(_MISS_T10_TOP10)

    # ── 合併財報三表帳本（statements.py；函式內 import 避開與 tables 的循環） ──
    from runtime.tw_equity.statements import extract_statements

    statements = extract_statements(fs, fs_anchors, group=group)
    counts = statements.to_dict()["row_counts"] if statements is not None else {}
    for st, name in (("bs", _MISS_FS_BS), ("is", _MISS_FS_IS), ("cf", _MISS_FS_CF)):
        if not counts.get(st):
            missing.append(name)

    # ── 階段 2：指標與 bridge（metrics.py；函式內 import 避開循環） ─────────
    from runtime.tw_equity.fy_income import extract_fy_income
    from runtime.tw_equity.metrics import compute_metrics

    # 單份年報格式異常不中斷 pipeline：FY 損益表改為 None（TTM 不可用），並在終端機與報告警示
    fy_income_error: str | None = None
    try:
        fy_income = extract_fy_income(ar, ar_anchors, roc_year=roc_year, group=group)
    except Exception as e:
        fy_income = None
        fy_income_error = f"{type(e).__name__}: {e}"
        msg = f"[tw-equity 警示] FY 損益表解析失敗：{fy_income_error}；TTM 不可用"
        print(msg)
        log.warning(msg)
    fh_notes = None
    fh_notes_error: str | None = None
    if group == "fh" and fs is not None:
        from runtime.tw_equity.fh_notes import extract_fh_notes

        bs_cur = None
        if statements is not None:
            ci = statements.current_col.get("bs")
            cols = statements.column_periods.get("bs") or []
            bs_cur = cols[ci] if ci is not None and ci < len(cols) else None
        try:
            fh_notes = extract_fh_notes(fs, bs_current_period=bs_cur)
        except Exception as e:
            fh_notes_error = f"{type(e).__name__}: {e}"
            msg = f"[tw-equity 警示] 附註抽取失敗：{fh_notes_error}；附註指標不可用"
            print(msg)
            log.warning(msg)
    metrics_notes = fh_notes
    if fh_notes_error is not None:  # 附註指標走「無附註」的 None 路徑（value None、source.reason）
        from runtime.tw_equity.fh_notes import CarResult, FhNotes

        metrics_notes = FhNotes(group_car=CarResult(value=None, reason="附註抽取失敗"), npl=None)
    metrics = compute_metrics(statements, fy_income=fy_income, group=group, notes=metrics_notes)

    # ── parent_key_lines（個體損益表 ps_is） ─────────────────────────────────
    _, ps_is_text = _get_ps("ps_is")
    if ps_is_text:
        parent_key_lines = parse_key_lines(ps_is_text, _KEY_LINE_LABELS)
    else:
        parent_key_lines = {label: (None, None) for label in _KEY_LINE_LABELS}

    # ── parent_cost_coverage（個體營業成本 / 合併營業成本） ──────────────────
    # 合併優先取 consolidated_key_lines，缺則取 fin_performance 的營業成本列
    cons_cogs_tuple = consolidated_key_lines.get("營業成本", (None, None))
    cons_cogs: float | None = cons_cogs_tuple[0] if cons_cogs_tuple else None
    if cons_cogs is None and fin_performance is not None:
        cogs_row = next(
            (r for r in fin_performance.rows if "營業成本" in r.label), None
        )
        if cogs_row is not None:
            cons_cogs = cogs_row.current
    parent_cogs_tuple = parent_key_lines.get("營業成本", (None, None))
    parent_cogs: float | None = parent_cogs_tuple[0] if parent_cogs_tuple else None
    parent_cost_coverage = _safe_divide(parent_cogs, cons_cogs)

    return TablesBundle(
        fin_position=fin_position,
        fin_performance=fin_performance,
        customers_sales=customers_sales,
        customers_purchase=customers_purchase,
        production_sales=production_sales,
        expense_nature=expense_nature,
        inventory=inventory,
        cost_detail_cogs=cost_detail_cogs,
        cost_detail_mfg=cost_detail_mfg,
        cost_detail_opex=cost_detail_opex,
        consolidated_key_lines=consolidated_key_lines,
        parent_key_lines=parent_key_lines,
        parent_cost_coverage=parent_cost_coverage,
        missing_tables=missing,
        unit_notes=unit_notes,
        guarantees_loans=guarantees_loans,
        pledges=pledges,
        top_shareholders=top_shareholders,
        statements=statements,
        metrics=metrics,
        fy_income=fy_income,
        fy_income_error=fy_income_error,
        fh_notes=fh_notes,
        fh_notes_error=fh_notes_error,
    )
