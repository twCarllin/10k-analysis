"""ar_sections.py — 年報章節結構化解析（階段 4a）。

目前提供「財務狀況及財務績效之檢討分析」章的「現金流量」節：`parse_cashflow(doc)`。
輸入年報 `PdfDoc`（只讀 `Page.lines` 與 `Page.tables`），輸出 `CashflowSection`。

status（三個章節共用）：
- parsed：找到章節且解析出結構化內容
- none：找到章節，內容寫「無」或「不適用」
- failed：找到章節但解析不出內容（附 reason）
- not_found：沒找到章節

設計要點（觸發條件都取最窄、可觀察的特徵）：
- 章節標題：行首要有編號前綴，且「現金流量（分析／之檢討與分析）」後直接接空白或行尾；目錄頁不採用。
- 章節終點：下一個同種類、同層級（或更高層級）且編號較大的標題。
- 合併／個體兩組表：組標題行（`…財務報表`，或含合併／個體／子公司字樣的`…現金流量變動分析`）含「合併」或「及子公司」者為合併組；
  只有一張表時不看標題；看不出合併組時取文件順序第一張。
- 表 A／表 B 為一列式表（pdfplumber 表格）；直式兩年比較表（表 A 第 3 種寫法）以「表頭有項目＋≥2 個年度欄＋
  5 或 6 列＋年初＋各項淨流量＝年底」辨識，列角色依列序。
- 算術檢查只用表 A 決定 `arith_ok`；表 B 只記 `arith_diff`。

「重要契約」節：`parse_contracts(doc)`（見該函式 docstring）。
「特別記載事項」章：`parse_special(doc)`（見該函式 docstring）。
"""

from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from runtime.tw_equity.doc_anchor import _TOC_LEADER_RE, _is_toc_page, _norm
from runtime.tw_equity.pdf_doc import PdfDoc

STATUS_PARSED = "parsed"
STATUS_NONE = "none"
STATUS_FAILED = "failed"
STATUS_NOT_FOUND = "not_found"
STATUS_SEE_MOPS = "see_mops"      # 特別記載事項子項：只指向公開資訊觀測站
STATUS_DISCLOSED = "disclosed"    # 特別記載事項子項：有實質內文

ARITH_TOLERANCE = 2.0  # 仟元（同三表勾稽）
_MAX_SECTION_PAGES = 3  # 章節最多跨幾頁（含起頁）

_EXPL_KEYS = ("operating", "investing", "financing")


# ── 資料結構 ────────────────────────────────────────────────────────────────


def _num(v: float | None) -> float | int | None:
    if v is None:
        return None
    return int(v) if float(v) == int(v) else round(float(v), 3)


@dataclass
class CashflowTable:
    """一張現金流量表（表 A 或表 B），金額單位為仟元。"""

    page: int | None = None
    opening_cash: float | None = None
    cfo: float | None = None
    cfi: float | None = None
    cff: float | None = None
    cfi_cff: float | None = None   # 投資及籌資合計（合併欄）
    outflow: float | None = None   # 「全年現金流出量」寫法
    fx: float | None = None
    closing_cash: float | None = None
    remedy_invest: str | None = None
    remedy_finance: str | None = None
    column_headers: list[str] = field(default_factory=list)
    applicable: bool | None = None  # 只有表 B 設定；寫「不適用」→ False
    arith_diff: float | None = None  # 只有表 B 設定：原文剩餘 − 依欄位推算值

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "page": self.page,
            "opening_cash": _num(self.opening_cash),
            "cfo": _num(self.cfo),
            "cfi": _num(self.cfi),
            "cff": _num(self.cff),
            "cfi_cff": _num(self.cfi_cff),
            "outflow": _num(self.outflow),
            "fx": _num(self.fx),
            "closing_cash": _num(self.closing_cash),
            "remedy_invest": self.remedy_invest,
            "remedy_finance": self.remedy_finance,
            "column_headers": list(self.column_headers),
        }
        if self.applicable is not None:
            d["applicable"] = self.applicable
        if self.arith_diff is not None:
            d["arith_diff"] = _num(self.arith_diff)
        return d


def _empty_expl() -> dict[str, str | None]:
    return {k: None for k in _EXPL_KEYS}


@dataclass
class CashflowSection:
    """現金流量節。無表 A → actual=None、arith_ok=None。"""

    status: str
    pages: list[int] = field(default_factory=list)
    reason: str | None = None
    basis_label: str | None = None
    unit_text: str | None = None
    actual: CashflowTable | None = None
    actual_explanations: dict[str, str | None] = field(default_factory=_empty_expl)
    forecast: CashflowTable | None = None
    forecast_explanations: dict[str, str | None] = field(default_factory=_empty_expl)
    arith_ok: bool | None = None
    basis: str | None = None        # 口徑判定（`apply_cashflow_basis` 設定）；未判定 → None
    basis_note: str | None = None   # 口徑判定說明（兩邊數字、只比對一個數字等）

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pages": list(self.pages),
            "reason": self.reason,
            "basis_label": self.basis_label,
            "basis": self.basis,
            "basis_note": self.basis_note,
            "unit_text": self.unit_text,
            "actual": self.actual.to_dict() if self.actual else None,
            "actual_explanations": dict(self.actual_explanations),
            "forecast": self.forecast.to_dict() if self.forecast else None,
            "forecast_explanations": dict(self.forecast_explanations),
            "arith_ok": self.arith_ok,
        }


# ── 金額與列文字工具 ────────────────────────────────────────────────────────


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


_AMOUNT_RE = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


def _amount(cell: Any) -> float | None:
    """單格金額：去 `$` 與空白後整格須是金額（括號為負）；破折號、文字 → None。"""
    if cell is None:
        return None
    t = re.sub(r"\s+", "", _nfkc(str(cell)).replace("$", ""))
    if not _AMOUNT_RE.fullmatch(t):
        return None
    from runtime.tw_equity.tables import parse_amount  # 延遲匯入：tables 之後會反向引用本模組

    return parse_amount(t)


def _tokens(line: str) -> list[str]:
    t = _nfkc(line).replace("$", "")
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    return t.split()


def _line_amounts(line: str) -> list[float]:
    return [v for v in (_amount(t) for t in _tokens(line)) if v is not None]


def _leading_amounts(line: str) -> list[float]:
    out: list[float] = []
    for t in _tokens(line):
        v = _amount(t)
        if v is None:
            break
        out.append(v)
    return out


# ── 標題與章節範圍 ──────────────────────────────────────────────────────────

_HEAD_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+、|\d+(?:[.\-]\d+)*[.、]?)\s*"
    r"(?:現金流量(?:之?檢討與?分析表?|分析|變動分析說明?)?(?:[-－—]\S+)?|(?:現金)?流動性分析)(?=\s|$|[:：])"
)
_CF_CN_TABLE = str.maketrans("壹貳參叁肆伍陸柒捌玖拾", "一二三三四五六七八九十")
_CF_BULLET_RE = re.compile(r"^[\uf000-\uf0ff\s]+")


_CF_BIG_RE = re.compile(r"^[壹貳參叁肆伍陸柒捌玖拾]+(?=、)")


_CF_SIDEBAR_RE = re.compile(r"^(?:[\u4e00-\u9fff]\s+){1,3}(?=(?:[一二三四五六七八九十壹貳參叁肆伍陸柒捌玖拾]+、|\d+(?:[.\-]\d+)*[.、]))")


def _cf_clean_raw(line: str) -> str:
    """去行首私有區符號；去排版側欄殘字（「項 之 三、現金流量」→「三、現金流量」，只在其後緊接章節編號時）；
    每個 token 都重複印兩次的疊印列（「三、 三、 現金流量 現金流量」）還原成單份。"""
    s = _CF_BULLET_RE.sub("", _nfkc(line).strip())
    s = _CF_SIDEBAR_RE.sub("", s)
    toks = s.split()
    if len(toks) >= 4 and len(toks) % 2 == 0 and all(toks[k] == toks[k + 1] for k in range(0, len(toks), 2)):
        s = " ".join(toks[::2])
    return s


def _cf_clean(line: str) -> str:
    """現金流量標題用的列文字：NFKC、去行首私有區項目符號（\uf075）、大寫國字編號（壹貳參…）換成小寫。"""
    s = _cf_clean_raw(line)
    return s.translate(_CF_CN_TABLE) if _CF_BIG_RE.match(s) else s


_PAGE_TAIL_RE = re.compile(r"\s\d{1,3}$")
_PFX_RE = re.compile(
    r"^(?:(?P<cn>[一二三四五六七八九十]+)、"
    r"|(?P<ar>\d+(?:[.\-]\d+)*)(?P<sep>[.、]?)(?=\s*[^\d\s]))"
)
_CN_DIGITS = "一二三四五六七八九十"


def _cn_val(s: str) -> int:
    if s == "十":
        return 10
    if len(s) == 2 and s[0] == "十":
        return 10 + _CN_DIGITS.index(s[1]) + 1
    return _CN_DIGITS.index(s[-1]) + 1 + (10 * (_CN_DIGITS.index(s[0]) + 1) if len(s) == 2 else 0)


def _prefix(line: str) -> tuple[str, tuple[int, ...]] | None:
    """行首章節編號 → (種類, 數字序列)。阿拉伯數字單層須帶「.」或「、」（「114 年」不算編號）。"""
    m = _PFX_RE.match(_nfkc(line).strip())
    if not m:
        return None
    if m.group("cn"):
        return ("cn", (_cn_val(m.group("cn")),))
    parts = tuple(int(x) for x in re.split(r"[.\-]", m.group("ar")))
    if len(parts) == 1 and not m.group("sep"):
        return None
    return ("ar", parts)


def _is_end_heading(line: str, start: tuple[str, tuple[int, ...]]) -> bool:
    p = _prefix(line)
    if p is None or p[0] != start[0] or len(p[1]) > len(start[1]):
        return False
    return p[1] > start[1][: len(p[1])]


_TITLE_RE = re.compile(
    r"^((?:\d+(?:\.\d+)*\s*)?(?:\S*?財務報表|\S*?(?:合併|個體|子公司)\S*?現金流量變動分析))(?=\s|$)"
)
_CONSOL_RE = re.compile(r"合併|及子公司")
_CF_FC_HEAD_RE = re.compile(
    r"^(?:[(（][一二三四五六七八九十]+[)）][、.]?|\d+[.、]|[一二三四五六七八九十]+、)?\s*未來一年度?現金流動性分析")
_MARKER_RE = re.compile(r"未來一年度?現金流動性分析")
_UNIT_RE = re.compile(r"單位[:：]\s*(\S+)")

_UNIT_SUFFIX = (("百萬元", 1000.0), ("佰萬元", 1000.0), ("仟元", 1.0), ("千元", 1.0), ("萬元", 10.0), ("億元", 100000.0), ("元", 0.001))


def _unit_scale(tok: str) -> float | None:
    """單位字串 → 換算成仟元的倍率。限新台幣（「台幣」「臺幣」，或整串只有「仟元／千元／百萬元」）；讀不出 → None。"""
    t = re.split(r"[;；,，]", _norm(tok), maxsplit=1)[0]
    if t in ("仟元", "千元", "百萬元", "佰萬元"):
        t = "新台幣" + t  # 單位列只寫數量級、沒寫幣別：整串只有數量級才視為新台幣（寫了其他幣別字樣的不會相等）
    if "台幣" not in t and "臺幣" not in t:
        return None
    for suf, f in _UNIT_SUFFIX:
        if t.endswith(suf):
            return f
    return None


Seq = list[tuple[int, str]]  # (頁碼, 列文字)


def _heading_candidates(doc: PdfDoc) -> list[tuple[int, int]]:
    """所有非目錄頁中的「現金流量」節標題 → [(頁序, 列序)]。"""
    out: list[tuple[int, int]] = []
    for pi, p in enumerate(doc.pages):
        if _is_toc_page(p.lines):
            continue
        for li, ln in enumerate(p.lines):
            s = _cf_clean(ln)
            if _HEAD_RE.match(s) and not _PAGE_TAIL_RE.search(s):
                out.append((pi, li))
    return out


def _build_seq(doc: PdfDoc, pi: int, li: int) -> tuple[Seq, list[int]]:
    """由標題起到下一個同級標題前的列序列；回傳 (列序列, 涵蓋頁碼)。"""
    pages = doc.pages
    start = _prefix(_cf_clean(pages[pi].lines[li])) or ("cn", (0,))
    # 大寫國字編號（壹貳參…）只在起點標題本身是大寫時才用於終點判定；否則頁首的「伍、…」章名會誤斷小寫編號的節
    big = bool(_CF_BIG_RE.match(_cf_clean_raw(pages[pi].lines[li])))
    first = pages[pi].number
    seq: Seq = []
    covered: list[int] = []
    for pj in range(pi, len(pages)):
        p = pages[pj]
        if p.number > first + _MAX_SECTION_PAGES - 1:
            break
        if pj > pi and (p.number != pages[pj - 1].number + 1 or _is_toc_page(p.lines)):
            break
        covered.append(p.number)
        lines = p.lines[li:] if pj == pi else p.lines
        for k, ln in enumerate(lines):
            if not (pj == pi and k == 0) and _is_end_heading(_cf_clean(ln) if big else ln, start):
                return seq, covered
            seq.append((p.number, ln))
    return seq, covered


# ── 表格辨識 ────────────────────────────────────────────────────────────────

_NUM_ROLES = ("opening_cash", "cfo", "cfi", "cff", "cfi_cff", "outflow", "fx", "closing_cash")


def _role(text: str) -> str | None:
    """欄位表頭（已去空白、NFKC）→ 角色。補救措施欄看「投資計」「理財／籌資／融資計」。"""
    if re.search(r"投資計", text):
        return "remedy_invest"
    if re.search(r"(?:理財|籌資|融資)計", text):
        return "remedy_finance"
    if re.search(r"期初現金|年初現金", text):
        return "opening_cash"
    if "剩餘" in text:
        return "closing_cash"
    if re.search(r"投資及(?:籌資|融資|理財)", text):
        return "cfi_cff"
    if "營業活動" in text:
        return "cfo"
    if "投資活動" in text:
        return "cfi"
    if re.search(r"(?:籌資|融資|理財)活動", text):
        return "cff"
    if "匯率" in text:
        return "fx"
    if "現金流出" in text:
        return "outflow"
    # 文字層字型損壞、關鍵詞缺字時的備援：只認「出量」（流出量）與「來自」（營業活動來源）
    if "出量" in text:
        return "outflow"
    if re.search(r"流入\(出\)量", text):
        return "outflow_alt"  # 3702 的「全年現金流入(出)量」是含營業的淨變動：只在採用後算術成立時才當 outflow（_parse_horizontal）
    if "來自" in text:
        return "cfo"
    return None


@dataclass
class _Tbl:
    kind: str  # "A"（一列式表 A）／"B"（一列式表 B）／"V"（直式兩年比較表，歸為實際）
    page: int
    vals: dict[str, float | None]
    remedy_invest: str | None = None
    remedy_finance: str | None = None
    headers: list[str] = field(default_factory=list)
    loc: int | None = None
    title: str | None = None
    scale: float | None = None
    out_cols: tuple[str, ...] = ()  # 表頭欄名含「流出量」的 cfi／cff／cfi_cff 欄（原文是流出量，驗算要轉號）
    outflow_sign: int | None = None  # 表頭寫明公式時：(3) 前是「-」→ -1、「+」→ +1；沒有公式 → None


def _data_row_index(rows: list[list[str]]) -> int | None:
    for i, r in enumerate(rows):
        if sum(1 for c in r if _amount(c) is not None) >= 3:
            return i
    return None


def _fill_blank_cells(data: list[str], cols: list[int], seq: Seq) -> dict[int, float | None]:
    """表格數字欄有空白儲存格（2330 期初現金）時，找同頁列文字中前導金額與其餘儲存格逐一相等的列補齊。"""
    cells = {c: (_amount(data[c]) if c < len(data) else None) for c in cols}
    blanks = [c for c in cols if cells[c] is None and (c >= len(data) or not str(data[c] or "").strip())]
    if not blanks:
        return cells
    for _, ln in seq:
        la = _leading_amounts(ln)
        if len(la) != len(cols):
            continue
        if all(cells[c] is None or cells[c] == la[k] for k, c in enumerate(cols)):
            for k, c in enumerate(cols):
                if c in blanks:
                    cells[c] = la[k]
            break
    return cells


def _parse_horizontal(rows: list[list[str]], page: int, seq: Seq) -> _Tbl | None:
    di = _data_row_index(rows)
    if not di:
        return None
    head = rows[:di]
    htext = "".join(_norm(c) for r in head for c in r)
    if not (re.search(r"期初現金|年初現金", htext) and "剩餘" in htext):
        return None
    data = rows[di]
    n = len(data)
    coltxt = ["".join(_norm(r[c]) for r in head if c < len(r)) for c in range(n)]
    roles: dict[str, int] = {}
    for c in range(n):
        role = _role(coltxt[c])
        if role and role not in roles:
            roles[role] = c
    num_cols = sorted(roles[r] for r in (*_NUM_ROLES, "outflow_alt") if r in roles)
    if len(num_cols) < 3:
        return None
    raw_cells = {c: _amount(data[c]) for c in num_cols}
    cells = _fill_blank_cells(data, num_cols, seq)
    vals = {r: (cells[roles[r]] if r in roles else None) for r in _NUM_ROLES}
    fm = re.search(r"\(1\)\+\(2\)([+-])\(3\)", htext)  # 表頭公式（_norm 已 NFKC，全形＋－已轉半形）
    sign = None if not fm else (-1 if fm.group(1) == "-" else 1)
    if ("outflow_alt" in roles and vals["outflow"] is None and vals["cfi_cff"] is None
            and (vals["cfi"] is None or vals["cff"] is None)):
        # 備援角色：採用後（當 outflow 代入）算術成立才採用；不成立 → 該欄留 None（不當 0）。
        # 有「投資及籌資」合併欄或投資、籌資兩欄都有時，驗算用不到 outflow → 不採用（審查 Task 3 修正輪 🟡1）
        alt = cells[roles["outflow_alt"]]
        d = _arith_diff({**vals, "outflow": alt}, sign)
        if d is not None and abs(d) <= ARITH_TOLERANCE:
            vals["outflow"] = alt

    def _txt(c: int | None) -> str | None:
        if c is None or c >= n:
            return None
        return str(data[c]).strip() or None

    inv, fin = _txt(roles.get("remedy_invest")), _txt(roles.get("remedy_finance"))
    ri, rf = roles.get("remedy_invest"), roles.get("remedy_finance")
    if fin is None and inv is not None and ri is not None and rf is not None and rf == ri + 1:
        fin = inv  # 合併儲存格：「無」橫跨投資、理財兩欄
    headers = []
    for c in range(n):
        parts = [_norm(r[c]) for r in head if c < len(r) and _norm(r[c])]
        if parts:
            headers.append("／".join(parts))
    # 表 B 的流量欄與剩餘欄表頭帶「預計」；表 A 只有補救措施欄會寫「預計」（2603），不能看整列表頭
    is_b = any("預計" in coltxt[roles[r]] for r in ("cfo", "closing_cash", "outflow", "outflow_alt", "cfi_cff") if r in roles)
    t = _Tbl("B" if is_b else "A", page, vals, inv, fin, headers)
    t.outflow_sign = sign
    t.out_cols = tuple(r for r in ("cfi", "cff", "cfi_cff") if r in roles and "流出量" in coltxt[roles[r]])
    t.loc = _locate(seq, [v for v in raw_cells.values() if v is not None])
    return t


def _parse_vertical(rows: list[list[str]], page: int, seq: Seq) -> _Tbl | None:
    """直式兩年比較表：表頭首欄含「項目」、≥2 個「NNN年」欄；5 或 6 列且 年初＋中間各列＝最後一列。"""
    if len(rows) < 2 or "項目" not in _norm(rows[0][0]):
        return None
    years = {
        c: int(m.group(1))
        for c, cell in enumerate(rows[0])
        if (m := re.fullmatch(r"(\d{2,4})年", _norm(cell)))
    }
    if len(years) < 2:
        return None
    col = max(years, key=lambda c: years[c])
    body = rows[1:]
    if len(body) not in (5, 6):
        return None
    vals = [_amount(r[col]) if col < len(r) else None for r in body]
    if any(v is None for v in vals):
        return None
    if abs(vals[0] + sum(vals[1:-1]) - vals[-1]) > ARITH_TOLERANCE:
        return None
    names = ["opening_cash", "cfo", "cfi", "cff"] + (["fx"] if len(body) == 6 else []) + ["closing_cash"]
    out = {r: None for r in _NUM_ROLES}
    out.update(dict(zip(names, vals)))
    headers = [_norm(c) for c in rows[0] if _norm(c)]
    t = _Tbl("V", page, out, None, None, headers)
    t.loc = _locate(seq, [_amount(c) for c in body[0][1:] if _amount(c) is not None])
    return t


_VL_LABELS = (
    ("opening_cash", re.compile(r"^期初現金(?:及約當現金)?餘額$")),
    ("cfo", re.compile(r"^營業活動(?:之?(?:淨)?現金流量)?$")),
    ("cfi", re.compile(r"^投資活動(?:之?(?:淨)?現金流量)?$")),
    ("cff", re.compile(r"^(?:籌資|融資)活動(?:之?(?:淨)?現金流量)?$")),
    ("fx", re.compile(r"^匯率(?:變動|影響數?)(?:對現金之影響)?$")),
    ("net", re.compile(r"^本期(?:現金)?(?:及約當現金)?增\(減\)(?:數|額)?$")),
    ("closing_cash", re.compile(r"^期末現金(?:及約當現金)?餘額$")),
)


def _parse_vertical_labeled(rows: list[list[str]], page: int, seq: Seq) -> _Tbl | None:
    """直式年度比較表（列標籤式）：前 4 列內有 ≥2 個「NNN年度?」欄；其後各列首欄標籤依序為
    期初現金餘額、營業活動、投資活動、籌資活動、（匯率變動）、（本期增減數）、期末現金餘額。取最新年度欄，
    期初＋各流量＝期末（本期增減數若有須等於期末－期初），否則 None。"""
    years: dict[int, int] = {}
    hdr_end = 0
    for ri, r in enumerate(rows[:4]):
        for c, cell in enumerate(r):
            m = re.fullmatch(r"(\d{2,4})年度?", _norm(cell))
            if m:
                years[c] = int(m.group(1))
                hdr_end = ri + 1
    if len(years) < 2:
        return None
    col = max(years, key=lambda c: years[c])
    found: dict[str, tuple[float, list[float]]] = {}
    order: list[str] = []
    for r in rows[hdr_end:]:
        label = _norm(r[0]) if r and r[0] else ""
        key = next((k for k, rx in _VL_LABELS if rx.match(label)), None)
        if key is None:
            continue
        v = _amount(r[col]) if col < len(r) else None
        if v is None or key in found:
            return None
        found[key] = (v, [a for a in (_amount(c) for c in r[1:]) if a is not None])
        order.append(key)
    if order != [k for k, _ in _VL_LABELS if k in found]:
        return None
    if not all(k in found for k in ("opening_cash", "cfo", "cfi", "cff", "closing_cash")):
        return None
    v = {k: x[0] for k, x in found.items()}
    flows = v["cfo"] + v["cfi"] + v["cff"] + v.get("fx", 0.0)
    if abs(v["opening_cash"] + flows - v["closing_cash"]) > ARITH_TOLERANCE:
        return None
    if "net" in v and abs(v["net"] - (v["closing_cash"] - v["opening_cash"])) > ARITH_TOLERANCE:
        return None
    out = {r: v.get(r) for r in _NUM_ROLES}
    t = _Tbl("V", page, out, None, None, [_norm(c) for r in rows[:hdr_end] for c in r if _norm(c)])
    t.loc = _locate(seq, found["opening_cash"][1])
    return t


def _locate(seq: Seq, amts: list[float]) -> int | None:
    """表格數字列在列序列中的位置：第一個金額依序含全部 amts 的列。"""
    if len(amts) < 2:
        return None
    for i, (_, ln) in enumerate(seq):
        it = iter(_line_amounts(ln))
        if all(a in it for a in amts):
            return i
    return None


# ── 文字列退回解析（pdfplumber 沒抓到表格時）────────────────────────────────

_CF_STOP_RE = re.compile(r"^(?:[(（][一二三四五六七八九十]+[)）]|[一二三四五六七八九十]+、|\d+\.\s*\S|註)")
_CF_ZONE_MAX = 8
_CF_FORMULA_RE = re.compile(r"\(?1\)?\+\(?2\)?([+-])\(?3\)?")
_CF_REMEDY_TAIL = 2


class _TextFail(Exception):
    """文字列退回解析遇到對不上的列：整節 failed，不猜。"""


def _text_layout(zone: str, n: int) -> list[str]:
    """表頭文字（已 NFKC、去空白）＋前導金額數 n → 數字欄角色序列（固定順序：期初、營業、流量欄、匯率、剩餘）。
    必須有 期初／營業活動（可斷字：「營業活」「來自營業」）／剩餘（或年底／期末現金、或「現金餘額」出現兩次以上）；
    流量欄：表頭有「現金流出（量）」→ 1 欄 outflow；其餘扣掉期初、營業、剩餘、匯率後，剩 1 欄 → 投資及籌資合計，剩 2 欄 → 投資、籌資。
    表頭寫了與該欄數矛盾的字樣（合計欄寫法卻有 2 欄、投資與籌資兩欄卻只剩 1 欄）或其他情形 → _TextFail。"""
    opening = bool(re.search(r"期初|年初", zone))
    cfo = bool(re.search(r"(?<!非)(?:來自營業|營業活)|來自營|業活動", zone))
    closing = bool(re.search(r"剩餘|年底現金|期末現金|\(不足\)數", zone)) or zone.count("現金餘額") >= 2
    if not (opening and cfo and closing):
        raise _TextFail("表頭缺期初／營業活動／剩餘")
    fx = "匯率" in zone
    outflow = bool(re.search(r"現金流出|流出量|流入\(出\)量", zone))
    combo = bool(re.search(r"投資(?:及|和)(?:籌資|融資|理財)|非營業|其他活動", zone))
    cfi = bool(re.search(r"投資活|來自投資", zone)) and not combo
    cff = bool(re.search(r"(?:籌資|融資|理財)活", zone))
    extra = n - 3 - (1 if fx else 0)
    if outflow and extra == 1 and not combo and not (cfi and cff):
        mid = ["outflow"]
    elif extra == 1 and not outflow and not (cfi and cff):
        mid = ["cfi_cff"]
    elif extra == 2 and not outflow and not combo:
        mid = ["cfi", "cff"]
    else:
        raise _TextFail(f"數字欄數 {n} 與表頭流量欄寫法對不上")
    return ["opening_cash", "cfo"] + mid + (["fx"] if fx else []) + ["closing_cash"]


_CF_NOTE_MARK_RE = re.compile(r"\(\d\)")  # 表頭欄號「(1)」「(2)」不是金額


def _text_leading(line: str) -> list[str]:
    """列首連續的金額 token（遇到非金額或欄號「(n)」即停）。"""
    out: list[str] = []
    for t in _tokens(line):
        if _CF_NOTE_MARK_RE.fullmatch(t) or _amount(t) is None:
            break
        out.append(t)
    return out


def _text_tables(seq: Seq) -> list[_Tbl]:
    """由列文字解析一列式數字列（表 A／表 B）。

    資料列＝前導 ≥3 個金額的列，且其前（同頁、至多 8 列、不跨章節小標／上一個資料列）的表頭文字含「期初／年初」。
    表頭欄數（角色序列）必須與前導金額數相等，且原文剩餘與推算值差 ≤ 容差，否則 _TextFail。
    """
    out: list[_Tbl] = []
    prev_data = -1
    for i, (pg, ln) in enumerate(seq):
        toks = _text_leading(ln)
        lead = [_amount(t) for t in toks]
        if len(lead) < 3:
            continue
        lo = i
        while lo - 1 > prev_data and i - (lo - 1) <= _CF_ZONE_MAX and seq[lo - 1][0] == pg:
            if _CF_STOP_RE.match(_cf_clean_raw(seq[lo - 1][1])):
                break
            lo -= 1
        prev_data = i
        zone_lines = [t for _, t in seq[lo:i]]
        zone = "".join(_norm(t) for t in zone_lines)
        if not re.search(r"期初|年初", zone):
            continue
        remedy_cols = bool(re.search(r"補救|不足額", zone))
        if remedy_cols and len(lead) >= 6 and lead[-2:] == [0, 0]:
            toks, lead = toks[:-2], lead[:-2]  # 補救措施兩欄寫成「0 0」：不是流量欄
            tail = ["0", "0"]
        else:
            tail = _tokens(ln)[len(toks):]
        roles = _text_layout(zone, len(lead))
        vals: dict[str, float | None] = {r: None for r in _NUM_ROLES}
        vals.update(dict(zip(roles, lead)))
        fm = _CF_FORMULA_RE.search(zone)
        sign = None if not fm else (-1 if fm.group(1) == "-" else 1)
        d = _arith_diff(vals, sign)
        if d is None or abs(d) > ARITH_TOLERANCE:
            raise _TextFail(f"第 {pg} 頁表頭解析後算術不平或欄位不足")
        inv = fin = None
        if len(tail) == _CF_REMEDY_TAIL:
            inv, fin = tail
        elif len(tail) == 1:
            inv = fin = tail[0]
        is_b = bool(re.search(r"預計全年|預計現金剩餘", zone)) or any(
            _MARKER_RE.search(_norm(t)) for _, t in seq[:i])
        t = _Tbl("B" if is_b else "A", pg, vals, inv, fin, [_norm(t) for t in zone_lines if _norm(t)])
        t.outflow_sign = sign
        t.loc = i
        out.append(t)
    return out


# ── 表 A／表 B 子標題判別 ───────────────────────────────────────────────────

_CF_SUB_NUM = r"(?:[●•]\s*)?(?:[(（]\s*[一二三四五六七八九十]+\s*[)）]\s*[、.,]?|\d+(?:[.\-]\d+)*\s*[.、]|[一二三四五六七八九十]+\s*、)"
_CF_SUB_B = (r"(?:(?:預計)?未來一年度?(?:\s*民國\s*\d+\s*年度?)?(?:\s*[(（][^)）]*[)）])?\s*(?:合併|個體)?\s*現金流(?:動性|量)[^\s:：]*?分析"
             r"|預計(?:民國)?\s*\d+\s*年度現金流量變動情形分析)")
_CF_SUB_A = (r"(?:(?:本年度|最近(?:年度|二年度?|兩年度?))(?:\s*[(（][^)）]*[)）])?[^\s現流]{0,8}?"
             r"(?:現金流量|現金流動性|流動性|流量|流動)[^\s:：]{0,12}?(?:變動|分析)|現金流量變動情形分析)")
_CF_SUB_RE = {
    kind: (re.compile(rf"^{_CF_SUB_NUM}\s*{core}"), re.compile(rf"^{core}\s*[:：]?$"))
    for kind, core in (("B", _CF_SUB_B), ("A", _CF_SUB_A))
}


def _cf_sub_kind(line: str) -> str | None:
    """子標題列 → "B"（未來一年）／"A"（本年度、最近年度、最近二年度…）／None（不是子標題）。
    子標題＝行首編號＋關鍵字（編號後可接任何說明），或整列（至多帶冒號）就是關鍵字；句中提到不算。"""
    s = _nfkc(line).strip()
    for kind in ("B", "A"):
        numbered, bare = _CF_SUB_RE[kind]
        if numbered.match(s) or bare.match(s):
            return kind
    return None


def _apply_subheadings(tbls: list["_Tbl"], seq: Seq) -> None:
    """依表格上方最近的子標題判別一列式表 A／表 B（表頭沒寫「預計」的表 B，如 2308）。
    三態：表格位置定不到、上方無可判定的子標題、子標題與表頭「預計」矛盾 → 沿用表頭判別；一節多張表時須每張都判得出才採用，任一張判不出則全部沿用。"""
    cand = [t for t in tbls if t.kind in ("A", "B")]
    decided: dict[int, str] = {}
    for t in cand:
        if t.loc is None:
            continue
        for _, ln in reversed(seq[:t.loc]):
            k = _cf_sub_kind(ln)
            if k:
                if not (k == "A" and t.kind == "B"):  # 表頭寫「預計」卻落在 A 類子標題下：證據互相矛盾，沿用表頭判別
                    decided[id(t)] = k
                break
    if len(cand) >= 2 and len(decided) != len(cand):
        return
    for t in cand:
        if id(t) in decided:
            t.kind = decided[id(t)]


# ── 說明文字 ────────────────────────────────────────────────────────────────

_ITEM_PFX_RE = re.compile(
    r"^(?:[（(]\d+[)）]|\d+[.、．]|[a-zA-Z][.、．]|[（(][一二三四五六七八九十]+[)）]|[-•●・–－—])\s*"
)
_LABEL_START_RE = re.compile(r"^(營業|投資|籌資|融資|理財)活動")
_LABEL_ANY_RE = re.compile(r"投資及(?:籌資|融資|理財)|營業活動|投資活動|(?:籌資|融資|理財)活動")


def _expl_key(label: str) -> str:
    if re.search(r"投資及(?:籌資|融資|理財)", label):
        return "financing"
    if "營業活動" in label:
        return "operating"
    if "投資活動" in label:
        return "investing"
    return "financing"


def _classify_item(s: str) -> tuple[str, str] | None:
    """說明段落起首列 → (key, 去編號後原文)。

    A：去編號後以「營業／投資／籌資／融資／理財活動」起頭。
    B：有編號且「：」前 ≤30 字的標籤含上述活動詞（例：「2. 全年來自營業活動淨現金流量：…」）。
    """
    m = _ITEM_PFX_RE.match(s)
    rest = s[m.end():] if m else s
    nrest = _nfkc(rest)
    ms = _LABEL_START_RE.match(nrest)
    if ms:
        return _expl_key(ms.group(0)), rest
    if m and ":" in nrest[:31]:
        label = nrest.split(":", 1)[0]
        if _LABEL_ANY_RE.search(label):
            return _expl_key(label), rest
    return None


def _is_stop(s: str) -> bool:
    n = _nfkc(s)
    return bool(_ITEM_PFX_RE.match(s)) or n.endswith(":") or n.startswith(("註", "單位"))


def _explanations(lines: list[str]) -> dict[str, str | None]:
    out = _empty_expl()
    cur: list[str] | None = None

    def flush() -> None:
        nonlocal cur
        if cur is not None and out[cur[0]] is None:
            out[cur[0]] = cur[1]
        cur = None

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        item = _classify_item(s)
        if item:
            flush()
            cur = [item[0], item[1].strip()]
        elif cur is not None:
            if _is_stop(s):
                flush()
                continue
            cur[1] += s
        if cur is not None and cur[1].endswith(("。", "；", ";")):
            flush()
    flush()
    return out


# ── 算術 ────────────────────────────────────────────────────────────────────


def _arith_diff(v: dict[str, float | None], outflow_sign: int | None = None,
                out_cols: tuple[str, ...] = ()) -> float | None:
    """原文剩餘 − 推算值。推算＝期初＋營業＋(投資＋籌資 | 投資及籌資 | 流出量)＋匯率。
    流出量：表頭寫明公式（(1)+(2)-(3)）→ 依公式代入帶號值（outflow_sign × 原文值）；
    表頭沒有公式：原文為正 → 減去；原文帶括號／負號 → 視為帶號淨流量加上（兩者皆為 −|流出量|）。
    out_cols（表頭寫「流出量」的 cfi／cff／cfi_cff 欄）：有公式 → outflow_sign × 原文值；沒有公式 → 同流出量規則。
    欄位不足以推算 → None。"""
    def flow(role: str) -> float | None:
        x = v.get(role)
        if x is None or role not in out_cols:
            return x
        return outflow_sign * x if outflow_sign else -abs(x)

    o, c, cfo = v.get("opening_cash"), v.get("closing_cash"), v.get("cfo")
    if o is None or c is None or cfo is None:
        return None
    if v.get("cfi_cff") is not None:
        flows = flow("cfi_cff")
    elif v.get("outflow") is not None:
        flows = outflow_sign * v["outflow"] if outflow_sign else -abs(v["outflow"])
    elif v.get("cfi") is not None and v.get("cff") is not None:
        flows = flow("cfi") + flow("cff")
    else:
        return None
    return c - (o + cfo + flows + (v.get("fx") or 0))


# ── 主流程 ──────────────────────────────────────────────────────────────────


def _pick(tbls: list[_Tbl]) -> _Tbl | None:
    if not tbls:
        return None
    if len(tbls) == 1:
        return tbls[0]
    for t in tbls:
        if t.title and _CONSOL_RE.search(_norm(t.title)):
            return t
    return tbls[0]


def _to_table(t: _Tbl, unit_scale: float) -> CashflowTable:
    def sc(x: float | None) -> float | None:
        return None if x is None else x * unit_scale

    ct = CashflowTable(page=t.page, remedy_invest=t.remedy_invest, remedy_finance=t.remedy_finance,
                       column_headers=t.headers)
    for r in _NUM_ROLES:
        setattr(ct, r, sc(t.vals.get(r)))
    return ct


def _parse_candidate(doc: PdfDoc, pi: int, li: int) -> tuple[CashflowSection, bool]:
    seq, covered = _build_seq(doc, pi, li)
    start_page = doc.pages[pi].number
    page_set = {start_page}

    # 組標題（略過章節標題本身）
    titles: list[tuple[int, str]] = []
    for i, (_, ln) in enumerate(seq):
        m = _TITLE_RE.match(_nfkc(ln).strip()) if i > 0 else None
        if m:
            titles.append((i, m.group(1)))

    def region(pos: int) -> tuple[int, int]:
        s = max((i for i, _ in titles if i <= pos), default=0)
        e = min((i for i, _ in titles if i > pos), default=len(seq))
        return s, e

    # 收集表格
    tbls: list[_Tbl] = []
    pnums = set(covered)
    for p in doc.pages:
        if p.number not in pnums:
            continue
        for raw in p.tables:
            rows = [[("" if c is None else str(c)) for c in r] for r in raw if r]
            if not rows:
                continue
            t = (_parse_vertical(rows, p.number, seq) or _parse_horizontal(rows, p.number, seq)
                 or _parse_vertical_labeled(rows, p.number, seq))
            if t is None:
                continue
            if t.loc is not None:
                tl = [i for i, _ in titles if i <= t.loc]
                t.title = next((tt for i, tt in titles if i == max(tl)), None) if tl else None
            tbls.append(t)

    markers = [i for i, (_, ln) in enumerate(seq) if _MARKER_RE.search(_norm(ln))]
    if not tbls:
        try:
            tbls = _text_tables(seq)
        except _TextFail as e:
            return CashflowSection(STATUS_FAILED, [start_page], reason=f"文字列退回解析失敗：{e}"), True
    for t in tbls:
        if t.title is None and t.loc is not None:
            tl = [i for i, _ in titles if i <= t.loc]
            t.title = next((tt for i, tt in titles if i == max(tl)), None) if tl else None
    _apply_subheadings(tbls, seq)
    na_marker = lambda i: "不適用" in _norm(seq[i][1]).split("分析", 1)[-1]  # noqa: E731

    if not tbls:
        if any(na_marker(i) for i in markers):
            sec = CashflowSection(STATUS_NONE, [start_page],
                                  forecast=CashflowTable(page=seq[markers[0]][0], applicable=False))
            return sec, False
        # 只有說明文字、沒有表 A 與表 B（使用者裁示）：至少有一段營業／投資／籌資說明 → parsed，表為 None，只存說明原文。
        # 不算說明的列：含 ≥3 個金額的列（年度比較表的資料列）；切分點：行首（可帶編號）的「未來一年現金流動性分析」，標題列自己提到的不算
        body = [(pg, ln) for pg, ln in seq[1:] if len(_line_amounts(ln)) < 3]
        cut = next((i for i, (_, ln) in enumerate(body) if _CF_FC_HEAD_RE.match(_nfkc(ln).strip())), None)
        act_part = body if cut is None else body[:cut]
        fc_part = [] if cut is None else body[cut + 1:]
        act_ex = _explanations([ln for _, ln in act_part])
        fc_ex = _explanations([ln for _, ln in fc_part])
        if any(v is not None for v in (*act_ex.values(), *fc_ex.values())):
            sec = CashflowSection(STATUS_PARSED, actual_explanations=act_ex, forecast_explanations=fc_ex)
            sec.pages = sorted({start_page} | _pages_of_items(act_part) | _pages_of_items(fc_part))
            return sec, False
        return CashflowSection(STATUS_FAILED, [start_page], reason="找不到現金流量表格"), False

    act = _pick([t for t in tbls if t.kind in ("A", "V")])
    fc = _pick([t for t in tbls if t.kind == "B"])

    # 單位：表格位置之前最近的「單位：」列；位置不明取第一個
    def unit_of(t: _Tbl) -> tuple[float | None, str | None]:
        rng = range(len(seq)) if t.loc is None else range(t.loc)
        hits = [m.group(1) for i in rng if (m := _UNIT_RE.search(_nfkc(seq[i][1])))]
        if not hits:
            return None, None
        tok = hits[0] if t.loc is None else hits[-1]
        return _unit_scale(tok), "單位：" + tok

    chosen = [t for t in (act, fc) if t is not None]
    units = {id(t): unit_of(t) for t in chosen}
    for t in chosen:
        t.scale = units[id(t)][0]
    if any(t.scale is None for t in chosen):
        return CashflowSection(STATUS_FAILED, sorted({t.page for t in chosen} | {start_page}),
                               reason="單位讀不到"), True

    sec = CashflowSection(STATUS_PARSED)
    sec.unit_text = units[id(chosen[0])][1]
    sec.basis_label = (act or fc).title
    ref = act or fc
    rs, re_ = region(ref.loc if ref.loc is not None else 0)

    next_locs = sorted(t.loc for t in tbls if t.loc is not None)

    def nxt(loc: int, limit: int) -> int:
        return min([limit] + [x for x in next_locs if x > loc])

    if act is not None:
        sec.actual = _to_table(act, act.scale)
        d = _arith_diff(sec.actual.__dict__, act.outflow_sign, act.out_cols)
        sec.arith_ok = None if d is None else abs(d) <= ARITH_TOLERANCE
        page_set.add(act.page)
        if act.loc is not None:
            _, aend = region(act.loc)
            mk = [i for i in markers if i > act.loc]
            end = nxt(act.loc, min([aend] + mk))
            sl = seq[act.loc + 1:end]
            sec.actual_explanations = _explanations([ln for _, ln in sl])
            page_set.update(_pages_of_items(sl))

    if fc is not None:
        sec.forecast = _to_table(fc, fc.scale)
        sec.forecast.applicable = True
        sec.forecast.arith_diff = _arith_diff(sec.forecast.__dict__, fc.outflow_sign, fc.out_cols)
        page_set.add(fc.page)
        if fc.loc is not None:
            _, fend = region(fc.loc)
            sl = seq[fc.loc + 1:nxt(fc.loc, fend)]
            sec.forecast_explanations = _explanations([ln for _, ln in sl])
            page_set.update(_pages_of_items(sl))
    else:
        in_reg = [i for i in markers if rs <= i < re_] or markers
        if in_reg:
            m = in_reg[0]
            ft = CashflowTable(page=seq[m][0], applicable=not na_marker(m))
            sec.forecast = ft
            page_set.add(seq[m][0])
            if ft.applicable:
                sl = seq[m + 1:re_ if re_ > m else len(seq)]
                sec.forecast_explanations = _explanations([ln for _, ln in sl])
                page_set.update(_pages_of_items(sl))
        else:
            sec.forecast = CashflowTable(applicable=True)

    sec.pages = sorted(page_set)
    return sec, True


def _pages_of_items(sl: Seq) -> set[int]:
    """說明段落所在頁（只算有被取用成說明項的列所在頁）。"""
    pages: set[int] = set()
    cur = False
    for pg, ln in sl:
        s = ln.strip()
        if not s:
            continue
        if _classify_item(s):
            cur = not s.endswith(("。", "；", ";"))
            pages.add(pg)
        elif cur:
            if _is_stop(s):
                cur = False
            else:
                pages.add(pg)
                cur = not s.endswith(("。", "；", ";"))
    return pages


def parse_cashflow(doc: PdfDoc) -> CashflowSection:
    """解析年報「現金流量」節。

    章節沒找到 → not_found；有多個非目錄候選標題時取第一個有表格的，皆無表格則回第一個候選的結果。
    """
    cands = _heading_candidates(doc)
    if not cands:
        return CashflowSection(STATUS_NOT_FOUND)
    first: CashflowSection | None = None
    for pi, li in cands:
        sec, has_tables = _parse_candidate(doc, pi, li)
        if has_tables:
            return sec
        first = first or sec
    assert first is not None
    return first


# ── 口徑判定（合併／個體）──────────────────────────────────────────────────

BASIS_CONSOLIDATED = "consolidated"
BASIS_NON_CONSOLIDATED = "non_consolidated"
BASIS_UNKNOWN = "unknown"


def _ledger_cash_ends(ledger: Any) -> tuple[float | None, float | None, str | None]:
    """帳本 → (年報年度的期初現金, 年底現金, 無法取值的原因)，單位仟元；缺值 → None（不當 0）。

    - 半年報帳本（basis H1）：現金流量表 `cash_beginning` 本期值＝年報年度年底現金、上期值＝年報年度期初現金。
    - 全年財報帳本（basis FY）：`cash_beginning` 本期＝期初、`cash_ending` 本期＝年底。
    取值走 `StatementLedger.get`（缺值保持 None；`value_at` 缺值回 0.0，不可用）。
    """
    scale = _unit_scale(ledger.unit or "")
    if scale is None:
        return None, None, f"帳本單位「{ledger.unit}」無法換算為仟元"
    if ledger.basis == "H1":
        closing, opening = ledger.get("cash_beginning", "cf")
    elif ledger.basis == "FY":
        opening = ledger.get("cash_beginning", "cf")[0]
        closing = ledger.get("cash_ending", "cf")[0]
    else:
        return None, None, f"帳本期間類型「{ledger.basis}」無法對應年報年度"

    def conv(v: float | None) -> float | None:
        return None if v is None else v * scale

    return conv(opening), conv(closing), None


def cashflow_basis(section: CashflowSection, ledger: Any) -> tuple[str, str | None, list[str]]:
    """口徑判定（Spec §2.1(a)，使用者裁示 Q1）→ (basis, basis_note, compared)。

    比對年報表 A 的 `opening_cash`／`closing_cash` 與合併帳本的期初／年底現金；沒有表 A → 用表 B 的
    `opening_cash`（＝年報年度年底現金）比對年底。可比對的數字（兩邊都有值）全部相差 ≤2 仟元 → consolidated；
    任一不符 → non_consolidated（note 寫兩邊數字）；無帳本、帳本或年報沒有可比數字 → unknown。
    `compared` 列出實際比對的項目（"opening"、"closing"）。
    """
    if ledger is None:
        return BASIS_UNKNOWN, "無合併帳本", []
    a, b = section.actual, section.forecast
    if a is not None:
        ar_open, ar_close, src = a.opening_cash, a.closing_cash, "表A"
    elif b is not None:
        ar_open, ar_close, src = None, b.opening_cash, "表B期初＝年底現金"
    else:
        return BASIS_UNKNOWN, "年報無表A與表B", []
    led_open, led_close, why = _ledger_cash_ends(ledger)
    if why is not None:
        return BASIS_UNKNOWN, why, []
    pairs = [(name, label, x, y) for name, label, x, y in (
        ("opening", "期初", ar_open, led_open), ("closing", "年底", ar_close, led_close))
        if x is not None and y is not None]
    if not pairs:
        return BASIS_UNKNOWN, "帳本或年報沒有可比對的期初／年底現金", []
    compared = [p[0] for p in pairs]
    nums = "；".join(f"{lab}：年報({src}) {x:,.0f}／帳本 {y:,.0f}" for _, lab, x, y in pairs)
    bad = [p for p in pairs if abs(p[2] - p[3]) > ARITH_TOLERANCE]
    if bad:
        return BASIS_NON_CONSOLIDATED, nums, compared
    note = None
    if compared != ["opening", "closing"]:
        note = f"只比對{'年底' if compared == ['closing'] else '期初'}（{nums}）"
    return BASIS_CONSOLIDATED, note, compared


def apply_cashflow_basis(section: CashflowSection, ledger: Any) -> CashflowSection:
    """把 `cashflow_basis` 的結果寫進 `section.basis`／`basis_note`，回傳同一物件。"""
    section.basis, section.basis_note, _ = cashflow_basis(section, ledger)
    return section


# ═══ 重要契約節（item 1.3）═══════════════════════════════════════════════════════

# 設計要點（觸發條件都取最窄、可觀察的特徵；列邊界不確定 → 該頁計入 failed，不產出猜測的列）：
# - 節標題：行首有編號前綴，且整列只有「重要契約」（可接冒號）；目錄頁、帶頁碼的列不採用。
# - 欄位對應看表頭欄名（性質／當事人／日期期間／內容／限制），不看欄序；表頭文字跨列時逐欄串接，
#   表頭下的空白欄（pdfplumber 合併儲存格錯位）併入左邊最近的欄名（同一欄名多個欄只在文字完全相同時併一）。
# - 一列的儲存格被切成多個表格列時：表中有全空白列 → 以全空白列分塊（2317）；沒有 → 依「性質欄有字」起新列，
#   「性質欄空白」的列視為前列的續行（含跨頁）；合併儲存格（性質、內容空白，當事人／期間／限制都有字）→ 新列，
#   性質與內容沿用合併起點。
# - 其餘情形（續行找不到前列、欄位無對應、同欄名兩欄文字不同、位置不明）→ _Uncertain，整頁 failed。
# - 任一列的文字欄含 U+FFFD（文字層缺字）→ 該頁不產出列、計入 failed，reason 寫「文字層缺字」與頁碼（Spec §2.6）。

# 泛化的標題寫法（101 家）：大寫數字「柒、」、括號「(七)」、尾綴「(截至…止)」、同列「：無。」；一律須有編號前綴（無編號的整列「重要契約」不採用）
_CT_HEAD2_RE = re.compile(
    r"^(?:(?:[一二三四五六七八九十]+|[壹貳參肆伍陸柒捌玖拾]+)、|\([一二三四五六七八九十]+\)|\d+(?:[.\-]\d+)*[.、]?)\s*"
    r"重要契約(?:\(截至[^()]{0,20}止\))?(?::\s*(無)[。.]?|[:(]列示截至年報刊印日止.*|:)?$"
)
_CT_PAREN_PFX_RE = re.compile(r"^\(([一二三四五六七八九十]+)\)")
_CROLE_PATTERNS = (
    ("nature", "性質"),
    ("parties", "事人|對象|相對人"),
    ("period", "日期|期間|期限|起[訖迄]"),
    ("restrictions", "限制|條款"),
    ("content", "內容|容"),  # 「容」：文字層缺字時的備援（主要內容 → 主��容）
)
_CTH_FULL = (  # 文字表頭列的單一欄名（整段須完全是欄名，不是含欄名的句子）
    ("nature", r"契約性質|性質"),
    ("parties", r"當事人|他方當事人|相對人|契約對象|對象"),
    ("period", r"契約起[訖迄]日期|起[訖迄]日期|契約期間|契約期限"),
    ("content", r"主要內容|內容"),
    ("restrictions", r"限制條款|限制條件"),
)
_NONE_STMT_RE = re.compile(r"無簽訂(?:性質特殊之)?重要契約|尚無足以影響(?:投資人|股東)權益之重要契約")
_NONE_LINE_RE = re.compile(r"無[。.]?")
_ENTITY_HEAD_RE = re.compile(r"^\((\d{1,2})\)\s*([^\s:;,，。；]{1,20}?)(?:\s*:\s*無\s*)?$")
_ENTITY_NONE_RE = re.compile(r":\s*無\s*$")
_ENTITY_COLON_RE = re.compile(r"^\S{2,30}(?:公司|銀行|證券):(?:\s|$)")  # 「台新國際商業銀行股份有限公司：」（非「(n) 名稱」）的子公司分段標題
_TERM_RE = re.compile(r"(?:公司|Inc\.?|Incorporated|Corporation|Corp\.|Limited|Ltd\.?|LLC|GmbH|Company|L\.P\.)$", re.I)
_CONT_START = ("(", "（", "、", "及", "之", "的", "*", "＊", "註")
_ENUM_RE = re.compile(r"^(?:[(（](\d{1,2})[)）]|(\d{1,2})[.、．])\s*(.*)$")
_SIDE_RE = re.compile(r"^[甲乙丙丁]方[:：]")
_PARTY_SPLIT_RE = re.compile(r"(?:(?<=公司)|(?<=\)))[、及](?!其)")
_PREAMBLE_RE = re.compile(r"^[^()（）]{0,20}?包括[:：]\s*")


class _Uncertain(Exception):
    """列邊界或欄位對應不確定：該頁不產出任何列。"""


@dataclass
class ContractRow:
    """一筆契約。`parties` 一個儲存格多個當事人時拆成 list；`entity` 金控子公司名（非金控 None）。"""

    page: int
    entity: str | None
    nature: str
    parties: list[str]
    period: str
    content: str
    restrictions: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "entity": self.entity,
            "nature": self.nature,
            "parties": list(self.parties),
            "period": self.period,
            "content": self.content,
            "restrictions": self.restrictions,
        }


@dataclass
class ContractsSection:
    """重要契約節。failed 時 `rows` 只含列邊界確定的頁，`reason` 列出不確定的頁。"""

    status: str
    pages: list[int] = field(default_factory=list)
    rows: list[ContractRow] = field(default_factory=list)
    none_entities: list[str] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pages": list(self.pages),
            "rows": [r.to_dict() for r in self.rows],
            "none_entities": list(self.none_entities),
            "reason": self.reason,
        }


def _need_space(a: str, b: str) -> bool:
    return a.isascii() and (a.isalnum() or a in ",.)") and b.isascii() and (b.isalnum() or b == "(")


def _cat(a: str, b: str) -> str:
    return a + (" " if a and b and _need_space(a[-1], b[0]) else "") + b


def _join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        out = _cat(out, ln)
    return out


def _split_parties(lines: list[str]) -> list[str]:
    """當事人儲存格的列 → 當事人 list。

    1. 列首依序編號 1..k（k≥2，「(1)」「1.」）→ 每個編號一個當事人。
    2. 否則逐列累積；累積字串以「公司／Inc.／Ltd.…」結尾且下一列不是接續符（括號、頓號、及、*、註、單獨一個「等」）→ 換人；
       「甲方：」「乙方：」開頭的列 → 換人。
    3. 每個當事人字串：去「…包括：」前導與結尾「等」（只在有前導時）；
       在「公司」或「)」之後的「、」「及」（非「及其」）拆開。
    """
    enum: list[int] = []
    for i, ln in enumerate(lines):
        m = _ENUM_RE.match(ln)
        if m and int(m.group(1) or m.group(2)) == len(enum) + 1:
            enum.append(i)
    if len(enum) >= 2 and enum[0] == 0:
        segs = []
        for a, b in zip(enum, enum[1:] + [len(lines)]):
            segs.append(_join_lines([_ENUM_RE.match(lines[a]).group(3)] + lines[a + 1:b]))  # type: ignore[union-attr]
        return [s for s in segs if s]
    parts: list[str] = []
    cur = ""
    for ln in lines:
        if cur and (_SIDE_RE.match(ln) or (_TERM_RE.search(cur) and not (ln.startswith(_CONT_START) or ln == "等"))):
            parts.append(cur)
            cur = ln
        else:
            cur = _cat(cur, ln)
    if cur:
        parts.append(cur)
    out: list[str] = []
    for p in parts:
        m = _PREAMBLE_RE.match(p)
        if m:
            p = re.sub(r"\s*等$", "", p[m.end():])
        out += [x.strip() for x in _PARTY_SPLIT_RE.split(p) if x.strip()]
    return out


def _cell_lines(cell: str) -> list[str]:
    return [x.strip() for x in cell.split("\n") if x.strip()]


def _contract_header(rows: list[list[str]]) -> tuple[dict[int, str], int, int, set[int]] | None:
    """表頭辨識 → (欄位→角色（含併入的空白欄）, 資料起列, 欄數, 有欄名的欄)。表頭文字跨列時逐欄串接，取最少列數。"""
    nonblank = [i for i, r in enumerate(rows) if any(c.strip() for c in r)]
    for k in range(1, min(5, len(nonblank)) + 1):
        idxs = nonblank[:k]
        ncol = max(len(rows[i]) for i in idxs)
        coltxt = ["".join(_norm(rows[i][c]) for i in idxs if c < len(rows[i])) for c in range(ncol)]
        roles: dict[int, str] = {}
        dup = False
        for c, t in enumerate(coltxt):
            r = next((n for n, pat in _CROLE_PATTERNS if re.search(pat, t)), None) if t else None
            if r is None:
                continue
            if r in roles.values():
                dup = True
                break
            roles[c] = r
        if dup or len(roles) < 4 or "parties" not in roles.values():
            continue
        spans: dict[int, str] = {}
        cur: str | None = None
        for c in range(ncol):
            if c in roles:
                cur = roles[c]
            elif coltxt[c]:
                cur = None  # 有字但認不得的欄名（備註等）
            if cur is not None and (c in roles or not coltxt[c]):
                spans[c] = cur
        return spans, idxs[-1] + 1, ncol, set(roles)
    return None


def _row_cells(row: list[str], spans: dict[int, str], tid: int) -> dict[str, dict[tuple[int, int], list[str]]]:
    out: dict[str, dict[tuple[int, int], list[str]]] = {}
    for c, cell in enumerate(row):
        ls = _cell_lines(cell)
        if not ls:
            continue
        role = spans.get(c)
        if role is None:
            raise _Uncertain(f"第 {c + 1} 欄沒有對應的欄名")
        out.setdefault(role, {})[(tid, c)] = ls
    return out


class _Raw:
    """尚未定稿的一列：role → {(表序, 欄) → 列文字}。同一張表內同欄名的多欄（合併儲存格錯位）定稿時才併。"""

    def __init__(self, page: int, entity: str | None, cells: dict[str, dict[tuple[int, int], list[str]]]) -> None:
        self.page = page
        self.entity = entity
        self.cols: dict[str, dict[tuple[int, int], list[str]]] = {}
        self.add(cells)

    def add(self, cells: dict[str, dict[tuple[int, int], list[str]]]) -> None:
        for role, cs in cells.items():
            for k, ls in cs.items():
                self.cols.setdefault(role, {}).setdefault(k, []).extend(ls)

    def lines(self, role: str) -> list[str]:
        """各表（依序）的文字接起來；同一張表內多欄只在文字完全相同時併成一份，否則不確定。"""
        out: list[str] = []
        by_tid: dict[int, list[list[str]]] = {}
        for (tid, _), ls in sorted(self.cols.get(role, {}).items()):
            by_tid.setdefault(tid, []).append(ls)
        for groups in by_tid.values():
            uniq: list[list[str]] = []
            for ls in groups:
                if not any(_norm("".join(ls)) == _norm("".join(u)) for u in uniq):
                    uniq.append(ls)
            if len(uniq) > 1:
                raise _Uncertain(f"同一欄名有多個欄位且文字不同（{role}）")
            out += uniq[0]
        return out

    def finalize(self) -> ContractRow:
        nature, parties = self.lines("nature"), _split_parties(self.lines("parties"))
        if not nature or not parties:
            raise _Uncertain("性質或當事人空白")
        return ContractRow(
            self.page, self.entity, _join_lines(nature), parties, _join_lines(self.lines("period")),
            _join_lines(self.lines("content")), _join_lines(self.lines("restrictions")),
        )


_FULL_PERIOD_RE = re.compile(r"\d.*[~～\-–—至到]\s*(?:.*\d|迄今|至今)")
_OPEN_PERIOD_RE = re.compile(r"[~～\-–—至到]$")
_PARTY_TAIL_HEADS = ("公司", "股份有限公司", "有限公司", "之", "的", "及", "、")


def _full_period(cell: dict[tuple[int, int], list[str]]) -> bool:
    """期間欄的每個儲存格都是完整的起訖日期（起端有數字、訖端有數字或「迄今」「至今」）。"""
    return all(_FULL_PERIOD_RE.search(_nfkc("".join(ls))) for ls in cell.values())


def _open_period(cell: dict[tuple[int, int], list[str]]) -> bool:
    """期間欄有儲存格以起訖符號結尾（「111.1~」）→ 明確的半截片段。"""
    return any(_OPEN_PERIOD_RE.search(_nfkc("".join(ls)).strip()) for ls in cell.values())


_PARTY_EN_TAIL_RE = re.compile(r"^(?:Ltd|Inc|Incorporated|Corporation|Corp|Co|Limited|LLC|GmbH|Company|L\.P|Pty|S\.A|AG)\b", re.I)


def _party_paren(cell: dict[tuple[int, int], list[str]]) -> bool:
    """當事人欄首行以括號起頭（「(原…」「（株）…」）：可能是斷行殘片，也可能是完整名稱。"""
    return any(ls[0].strip().startswith(("(", "（")) for ls in cell.values())


def _party_tail(cell: dict[tuple[int, int], list[str]]) -> bool:
    """當事人欄首行是上一列當事人名稱的斷行殘片：以中文尾綴詞（「公司」「股份有限公司」…）、英文尾綴（Ltd.、Inc 等）、
    或括號（「(加拿大)」「(原…」）起頭。"""
    return any(
        ls[0].strip().startswith(_PARTY_TAIL_HEADS + ("(", "（")) or _PARTY_EN_TAIL_RE.match(ls[0].strip())
        for ls in cell.values()
    )


_PERIOD_START_RE = re.compile(r"^(?:民國)?\d{2,4}\s*[年./\-]\s*\d{1,2}")


def _period_starts(per_row: list[dict[str, dict[tuple[int, int], list[str]]]]) -> int:
    """一個分塊內新契約的起點數：當事人欄有字（且不是上一個名稱斷行的尾綴殘片）、期間欄以日期起頭的列
    （上一個期間欄以起訖符號結尾的半截片段不算新的起頭）。≥2 → 分塊內是多筆契約。"""
    n = 0
    prev_open = False
    for cells in per_row:
        period, parties = cells.get("period"), cells.get("parties")
        if not period:
            continue
        starts = any(_PERIOD_START_RE.match(_nfkc("".join(ls)).strip()) for ls in period.values())
        tail = parties is None or _party_tail(parties)
        if starts and not tail and not prev_open:
            n += 1
        prev_open = any(_OPEN_PERIOD_RE.search(_nfkc("".join(ls)).strip()) for ls in period.values())
    return n


class _Acc:
    """跨表、跨頁累積的解析狀態。"""

    def __init__(self) -> None:
        self.raws: list[_Raw] = []
        self.cur: int | None = None   # 目前可接續行的列（raws 索引）
        self.src: int | None = None   # 合併儲存格（性質、內容）的起點列
        self.spans: dict[int, str] | None = None
        self.hcols: set[int] = set()  # 表頭有欄名的欄（spans 另含併入的空白欄）
        self.ncol = 0
        self.tid = 0

    def snapshot(self) -> tuple:
        return copy.deepcopy((self.raws, self.cur, self.src))

    def restore(self, snap: tuple) -> None:
        self.raws, self.cur, self.src = copy.deepcopy(snap)
        self.cur = self.src = None  # 失敗後下一頁的續行不得接到失敗頁之前的列

    def feed(self, data: list[list[str]], page: int, entity: str | None) -> None:
        """一張表的資料列 → 列。表中有全空白列 → 以全空白列分塊（一塊一個單位）；否則每個表格列一個單位。"""
        self.tid += 1
        spans = self.spans or {}
        filled = {c for r in data for c, v in enumerate(r) if v.strip()}
        if filled and not filled & self.hcols and len({spans.get(c) for c in filled}) >= 3:
            raise _Uncertain("資料儲存格全落在表頭的空白延伸欄（欄位對位不確定）")
        units: list[tuple[dict[str, dict[tuple[int, int], list[str]]], bool]] = []  # (儲存格, 是否只有性質欄)
        if any(not any(c.strip() for c in r) for r in data):
            block: list[list[str]] = []
            for r in data + [[""]]:
                if any(c.strip() for c in r):
                    block.append(r)
                    continue
                if block:
                    per_row = [_row_cells(br, spans, self.tid) for br in block]
                    if _period_starts(per_row) >= 2:
                        raise _Uncertain("分塊內有多列各自以日期起頭的期間（多筆契約沒有空白列分隔）")
                    merged = _Raw(page, entity, {})
                    for c in per_row:
                        merged.add(c)
                    units.append((merged.cols, False))
                block = []
        else:
            for r in data:
                cells = _row_cells(r, spans, self.tid)
                if cells:
                    only_nature = len(r) > 1 and all(not c.strip() for i, c in enumerate(r) if spans.get(i) != "nature")
                    units.append((cells, only_nature))
        first = True
        for cells, only_nature in units:
            roles = set(cells)
            if "nature" in roles and only_nature:
                self.cur = None  # 跨欄分隔標題（2412「關係企業」）
                first = False
                continue
            merged_row = False
            if ("nature" not in roles and {"parties", "period", "restrictions"} <= roles
                    and _full_period(cells["period"]) and _party_paren(cells["parties"])):
                # 合併儲存格形狀、期間完整、當事人以括號起頭：可能是新契約（「（株）…」）也可能是名稱殘片 → 不猜（審查 Task 3 修正輪 🟡2）
                raise _Uncertain("合併儲存格的當事人以括號起頭，列邊界不明")
            if "nature" not in roles and "content" not in roles and {"parties", "period", "restrictions"} <= roles:
                # 合併儲存格形狀：完整起訖且當事人是完整名稱 → 新列；明確片段（當事人以尾綴詞起頭、或期間以起訖符號結尾）→ 續行；其餘不猜
                if _full_period(cells["period"]) and not _party_tail(cells["parties"]):
                    merged_row = True
                elif not (_party_tail(cells["parties"]) or _open_period(cells["period"])):
                    raise _Uncertain("合併儲存格的列邊界不明")
            elif ("nature" not in roles and {"parties", "content", "period", "restrictions"} <= roles
                  and _full_period(cells["period"]) and not _party_tail(cells["parties"])):
                merged_row = True  # 只有性質是合併儲存格：其餘欄各自完整（內容欄有字）→ 新列，只沿用性質
            if "nature" in roles or merged_row:
                if merged_row:
                    if self.src is None:
                        raise _Uncertain("合併儲存格的列找不到起點")
                    inherit = {k: copy.deepcopy(v) for k, v in self.raws[self.src].cols.items() if k in ("nature", "content")}
                    cells = {**inherit, **cells}
                if ("nature" in roles and not merged_row and "parties" not in roles and self.raws
                        and self.raws[-1].page == page and "".join(_norm(x) for ls in cells.get("period", {}).values() for x in ls) == "同上"):
                    # 當事人是合併儲存格（空白）、期間明寫「同上」→ 與上一列同一當事人（兩個條件缺一不可，否則維持空白 → 定稿時 failed）
                    cells = {**cells, "parties": copy.deepcopy(self.raws[-1].cols.get("parties", {}))}
                    if not cells["parties"]:
                        del cells["parties"]
                self.raws.append(_Raw(page, entity, cells))
                self.cur = len(self.raws) - 1
                if "nature" in roles:
                    self.src = self.cur
            else:
                if self.cur is None:
                    raise _Uncertain("續行找不到前一列" if first else "續行前沒有完整的列")
                self.raws[self.cur].add(cells)
            first = False


def _norm_rows(raw: list[list[str | None]]) -> list[list[str]]:
    return [["" if c is None else str(c) for c in r] for r in raw if r]


def _contract_locate(lines: list[str], rows: list[list[str]]) -> int | None:
    """表格在列文字中的位置：表內第一個有字儲存格的首行，開頭相符的第一列（對不到 → None）。"""
    for r in rows:
        for c in r:
            ls = _cell_lines(c)
            if ls:
                frag = _norm(ls[0])
                if len(frag) < 2:
                    return None
                return next((i for i, ln in enumerate(lines) if _norm(ln).startswith(frag)), None)
    return None


def _text_rows(lines: list[str]) -> tuple[tuple[dict[int, str], int, int, set[int]], list[list[str]]] | None:
    """退回文字列解析：表頭列之後每列須以 2 個以上空白或 tab 切成與表頭相同欄數，否則列邊界不確定。

    回傳 (表頭欄位對應, 資料列)；找不到表頭列或沒有資料列 → None。"""
    cut = lambda ln: re.split(r"\s{2,}|\t", ln.strip())  # noqa: E731
    hi = next((i for i, ln in enumerate(lines) if all(k in _norm(ln) for k in ("性質", "當事人"))), None)
    if hi is None:
        return None
    hdr = _contract_header([cut(lines[hi])])
    if hdr is None:
        return None
    data = []
    for ln in lines[hi + 1:]:
        if not ln.strip():
            continue
        cells = cut(ln)
        if len(cells) != hdr[2]:
            raise _Uncertain("文字列無法切成與表頭相同的欄數")
        data.append(cells)
    return (hdr, data) if data else None


_BIG_NUM_RE = re.compile(r"^[壹貳參肆伍陸柒捌玖拾]+、")


def _ct_clean(line: str) -> str:
    """標題列正規化：NFKC、去行首私有區符號（項目符號字型）、每個詞都連續重複兩遍的文字（「十、 十、 重要契約 重要契約」，2887）只留一份。"""
    s = _nfkc(line).strip().lstrip("".join(ch for ch in _nfkc(line)[:3] if unicodedata.category(ch) == "Co") + " ")
    toks = s.split()
    return " ".join(toks[0::2]) if len(toks) % 2 == 0 and len(toks) >= 4 and toks[0::2] == toks[1::2] else s


def _ct_prefix(line: str) -> tuple[str, tuple[int, ...]] | None:
    """重要契約專用的標題編號：先用通用 `_prefix`，其次括號數字「(七)」→ ("pcn", (7,))。"""
    s = _ct_clean(line)
    m = _CT_PAREN_PFX_RE.match(s)
    return ("pcn", (_cn_val(m.group(1)),)) if m else _prefix(s)


def _ct_is_end(line: str, start: tuple[str, tuple[int, ...]]) -> bool:
    if start[0] != "pcn":
        return _is_end_heading(line, start)
    p = _ct_prefix(line)
    return p is not None and ((p[0] == "pcn" and p[1] > start[1]) or p[0] == "cn")


def _ct_head(lines: list[str], i: int) -> tuple[bool] | None:
    """第 i 列是不是「重要契約」節標題 → (同列是否寫「無」,)；不是 → None。寫法見 `_CT_HEAD2_RE`（一律須有編號前綴）。"""
    m = _CT_HEAD2_RE.match(_ct_clean(lines[i]))
    return None if m is None else (bool(m.group(1)),)


def _contract_end(lines: list[str], lo: int, tables: list, start: tuple[str, tuple[int, ...]]) -> int | None:
    """節終點標題的列序：同種類同層級（或更高）編號較大的標題，或大寫數字章名（「伍、」）。
    與表格儲存格內某一行完全相同的列不算標題（當事人儲存格的「5. GOLD STAR」編號）。"""
    cell_lines = {_norm(x) for t in tables for r in t for c in r if c for x in _cell_lines(str(c))}
    for k in range(lo, len(lines)):
        if _norm(lines[k]) in cell_lines:
            continue
        if _ct_is_end(lines[k], start) or _BIG_NUM_RE.match(_nfkc(lines[k]).strip()):
            return k
    return None


def _contract_headings(p_lines: list[str], lo: int, hi: int, p_tables: list, next_num: int) -> list[tuple[int, str, bool]]:
    """子公司分段標題「(n) 公司名」「(n) 公司名：無」：編號須接續、且該列不是表格儲存格內的列。"""
    cell_lines = {_norm(x) for t in p_tables for r in t for c in r if c for x in _cell_lines(str(c))}
    out: list[tuple[int, str, bool]] = []
    for i in range(lo, hi):
        s = _nfkc(p_lines[i]).strip()
        m = _ENTITY_HEAD_RE.match(s)
        if not m or int(m.group(1)) != next_num + len(out) or _norm(p_lines[i]) in cell_lines:
            continue
        out.append((i, m.group(2).strip(), bool(_ENTITY_NONE_RE.search(s))))
    return out


def _chars_after(rows: list[list[str]], lines: list[str], k: int) -> bool:
    """表格所有儲存格的每一個（非空白）字元，都出現在第 k 列之後的列文字中（表格文字與列文字逐字對不上、loc 為 None 時的位置佐證）。"""
    tc = {ch for r in rows for c in r for ch in c if not ch.isspace()}
    return bool(tc) and tc <= set("".join(lines[k + 1:]))


def _ct_text_header(lines: list[str], lo: int, loc: int | None, rows: list[list[str]]) -> tuple[dict[int, str], int, int, set[int]] | None:
    """表格沒有表頭列，但表格上方（lo 到表格位置之間）有一列文字，空白切開後每一段正好是一個欄名
    （「契約性質 當事人 契約起訖日期 主要內容 限制條款」），且段數＝表格欄數 → 用那一列當表頭（取最靠近表格的一列）。
    表格位置不明（loc 為 None）或表格各列欄數不一 → None。"""
    if loc is None or not rows or len({len(r) for r in rows}) != 1:
        return None
    for k in range(loc - 1, lo - 1, -1):
        toks = _nfkc(lines[k]).split()
        if len(toks) != len(rows[0]) or not all(any(re.fullmatch(pat, _norm(t)) for _, pat in _CTH_FULL) for t in toks):
            continue
        hdr = _contract_header([toks])
        if hdr is not None and hdr[3] == set(range(len(toks))):
            return hdr
    return None


def _parse_contracts_at(doc: PdfDoc, pi: int, li: int) -> ContractsSection:
    pages = doc.pages
    start_pfx = _ct_prefix(pages[pi].lines[li]) or ("cn", (0,))
    acc = _Acc()
    covered: list[int] = []
    failed: list[tuple[int, str]] = []
    none_entities: list[str] = []
    entity: str | None = None
    next_num = 1
    for pj in range(pi, len(pages)):
        p = pages[pj]
        if pj > pi and (p.number != pages[pj - 1].number + 1 or _is_toc_page(p.lines)):
            break
        lo = li + 1 if pj == pi else 0
        end_idx = _contract_end(p.lines, lo, p.tables, start_pfx)
        hi = len(p.lines) if end_idx is None else end_idx
        snap = acc.snapshot()
        accepted = False
        heads = _contract_headings(p.lines, lo, hi, p.tables, next_num)
        try:
            cell_lines = {_norm(x) for t in p.tables for r in t for c in r if c for x in _cell_lines(str(c))}
            if not heads and entity is None and any(
                    _ENTITY_COLON_RE.match(_ct_clean(x)) and _norm(x) not in cell_lines for x in p.lines[lo:hi]):
                raise _Uncertain("有「○○公司：」子公司分段標題但不是「(n) 名稱」寫法，entity 不確定")
            for ti, raw in enumerate(p.tables):
                rows = _norm_rows(raw)
                hdr = _contract_header(rows)
                loc = _contract_locate(p.lines, rows)
                if loc is not None and ((pj == pi and loc <= li) or (end_idx is not None and loc >= end_idx)):
                    continue  # 表在節標題之前或終點標題之後
                if hdr:
                    acc.spans, data_start, acc.ncol, acc.hcols = hdr
                    data = rows[data_start:]
                elif acc.spans is not None and ti == 0 and pj > pi and rows and max(len(r) for r in rows) == acc.ncol:
                    if end_idx == 0 and _chars_after(rows, p.lines, 0):
                        continue  # 終點標題是本頁第一列（其上沒有任何文字列），表格的每個字都出現在標題之後的列文字 → 表在終點之後
                    if end_idx is not None and loc is None:
                        raise _Uncertain("無表頭的表格與終點標題的先後不明")
                    data = rows
                else:
                    th = _ct_text_header(p.lines, lo, loc, rows) if acc.spans is None else None
                    if th is None:
                        continue
                    acc.spans, _, acc.ncol, acc.hcols = th
                    data = rows
                before = [h for h in heads if loc is not None and h[0] < loc]
                if loc is None and heads:
                    raise _Uncertain("子公司標題與表格的先後不明")
                ent = before[-1][1] if before else entity
                acc.feed(data, p.number, ent)
                accepted = True
            if not accepted and pj == pi:
                seg = [_nfkc(x).strip() for x in p.lines[lo:hi]]
                if pj + 1 < len(pages) and end_idx is None and pages[pj + 1].number == p.number + 1:
                    seg += [_nfkc(x).strip() for x in pages[pj + 1].lines]
                has_hdr = any(all(k in _norm(x) for k in ("性質", "當事人")) for x in seg)
                # 單列「無」：seg 內有契約表頭列（限制條款欄換行後的「無」）→ 不算；整句「無簽訂重要契約」不受影響
                none_stmt = any(_NONE_STMT_RE.search(x) for x in seg) or (
                    not has_hdr and any(_NONE_LINE_RE.fullmatch(x) for x in seg))
                if not none_stmt and not (heads and all(h[2] for h in heads)):
                    trows = _text_rows(p.lines[lo:hi])
                    if trows is None:
                        raise _Uncertain("找不到契約表格")
                    acc.spans, acc.ncol, acc.hcols = trows[0][0], trows[0][2], trows[0][3]
                    acc.feed(trows[1], p.number, entity)
                    accepted = True
        except _Uncertain as e:
            acc.restore(snap)
            failed.append((p.number, str(e)))
            accepted = True  # 失敗頁仍是節的一部分（頁碼計入、續頁繼續往後看）
        none_entities += [h[1] for h in heads if h[2]]
        if heads:
            entity, next_num = heads[-1][1], next_num + len(heads)
        if accepted or pj == pi:
            covered.append(p.number)
        else:
            break
        if end_idx is not None:
            break
    rows_out: list[ContractRow] = []
    for raw in acc.raws:
        try:
            rows_out.append(raw.finalize())
        except _Uncertain as e:
            failed.append((raw.page, str(e)))
    garbled = sorted({r.page for r in rows_out if _row_has_garble(r)})  # 文字層缺字（U+FFFD）的頁整頁不產出列
    rows_out = [r for r in rows_out if r.page not in garbled]
    fpages = sorted({n for n, _ in failed} | set(garbled))
    if failed or garbled:
        parts = []
        if failed:
            parts.append("列邊界不確定：" + "；".join(f"第 {n} 頁（{m}）" for n, m in sorted(set(failed))))
        if garbled:
            parts.append("文字層缺字：" + "；".join(f"第 {n} 頁" for n in garbled))
        return ContractsSection(STATUS_FAILED, sorted(set(covered) | set(fpages)), rows_out, none_entities, "；".join(parts))
    if rows_out:
        return ContractsSection(STATUS_PARSED, sorted(set(covered)), rows_out, none_entities)
    return ContractsSection(STATUS_NONE, sorted(set(covered)), [], none_entities)


def _row_has_garble(r: ContractRow) -> bool:
    """文字欄（性質、當事人、期間、內容、限制）含 U+FFFD（文字層缺字）。"""
    return any("\ufffd" in x for x in [r.nature, r.period, r.content, r.restrictions, *r.parties])


def parse_contracts(doc: PdfDoc) -> ContractsSection:
    """解析年報「重要契約」節。

    節標題：行首有編號前綴、整列只有「重要契約」；目錄頁不採用。多個候選時取第一個得出 parsed／none 者，
    否則回第一個候選的 failed；沒有候選 → not_found。
    終點：下一個同種類、同層級（或更高）且編號較大的標題；跨頁續表只接頁碼連續、且有契約表格的頁。
    整節寫「無」「並無簽訂重要契約」→ none。列邊界不確定的頁記入 failed（reason 列頁碼），不產出猜測的列。
    任一列的文字欄含 U+FFFD 的頁同樣記入 failed（reason「文字層缺字」與頁碼），該頁不產出列。
    """
    first: ContractsSection | None = None
    for pi, p in enumerate(doc.pages):
        if _is_toc_page(p.lines):
            continue
        for li, ln in enumerate(p.lines):
            head = _ct_head(p.lines, li)
            if head is None:
                continue
            if head[0]:  # 標題同列寫「：無。」
                return ContractsSection(STATUS_NONE, [p.number])
            sec = _parse_contracts_at(doc, pi, li)
            if sec.status != STATUS_FAILED:
                return sec
            first = first or sec
    return first or ContractsSection(STATUS_NOT_FOUND)


# ═══ 特別記載事項章（item 1.4）═══════════════════════════════════════════════════

# 設計要點（觸發條件都取最窄、可觀察的特徵）：
# - 章名：整列只有「特別記載事項」（可帶大寫數字／阿拉伯編號前綴）；帶頁碼或引導線的目錄列不採用。
# - 章名找不到 → 子項退回：非目錄頁中，行首有編號前綴＋子項關鍵字的標題列，連續 ≤3 頁內出現 ≥2 種子項 → 認定為該章。
#   （只看行首編號後的關鍵字，句中出現的「關係企業」不算；目錄列帶頁碼／引導線，不算標題。）
# - 子項標題列可斷成多列（標題後 ≤2 個無編號列併入判斷）。同一子項出現多次（章扉頁的子項目錄）時，取第一個
#   「標題所在頁有內文」者（2412、1216 的章扉頁）。
# - 子項內文＝標題之後到下一個標題前（可跨頁）；最後一個標題只取到其所在頁底。
# - 第 36 條事項：獨立子項、另立一章（「柒、對股東權益或證券價格有重大影響之事項」）、或寫在「其他必要補充說明事項」內文
#   （1216，主 flow 裁示）三種。

SPECIAL_KEYS = ("affiliates", "private_placement", "other_supplement", "material_events_36")

# 第 36 條事項的標題特徵（比對前去除空白）：第 36 條＋第 2／3 項＋第 2 款（原文有「第二項」「第3 項」「所訂」寫法；
# 雙欄交錯使「第」之後接別欄文字的標題（1101）也算——款字不在（斷行）即可；「第一款」「第三款」等其他款次不算），
# 或「對股東權益或證券價格有重大影響（之）事項」整句標題（句中「…有重大影響者」的內文不含「事項」緊接）。
_SP_36_PAT = r"(?:第(?:三十六|36)條第[二三23]項第(?:[二2]款|(?![一二三四五六七八九十\d]+款))|對股東權益或證券價格有重大影響(?:之)?事項)"
_SP_TITLE_KEYS = (
    ("private_placement", r"私募有價證券(?:及金融債券)?之?辦理情形"),
    ("other_supplement", r"其他必要?補充(?:說明)?(?:事項|(?=[：:\n]|$))"),
    ("material_events_36", _SP_36_PAT),
    ("affiliates", r"關?係企業相關資料"),
)
_SP_TITLE_RES = tuple((k, re.compile(r"[^。：:]{0,40}?" + pat)) for k, pat in _SP_TITLE_KEYS)
_SP_STRIP_RES = {  # 內文去標題：標題結尾詞（第 36 條的標題結尾是「…重大影響之事項」，可接「，亦應逐項載明」）
    "affiliates": re.compile(r"^.*?關?係企業相關資料[：:]?"),
    "private_placement": re.compile(r"^.*?私募有價證券(?:及金融債券)?之?辦理情形[：:]?"),
    "other_supplement": re.compile(r"^.*?其他必要?補充(?:說明)?(?:事項)?[：:]?"),
    "material_events_36": re.compile(r"^.*?重大影響(?:之)?事項(?:[，,]亦應逐項載明)?[：:]?"),
}
_SP_HEAD_RE = re.compile(
    r"^(?:[壹貳參肆伍陸柒捌玖拾一二三四五六七八九十]+\s*[、‧]|\d+(?:[.\-]\d+)*[.、]?)?\s*特別記載事項[：:]?$"
)
_SP_CH36_RE = re.compile(r"^[壹貳參肆伍陸柒捌玖拾]+、\s*對股東權益或證券價格有重大影響之事項[：:]?$")
_SP_FOLIO_RE = re.compile(r"^[-–—]?\s*\d{1,3}(?:\s+\d{1,3})?\s*[-–—]?$")  # 頁碼列（「-111-」「162」「178 179」）
_SP_TOC_TITLE_RE = re.compile(r"[-.·…─—_]{5,}|\s\d{1,3}$")  # 目錄列：引導線或列尾頁碼
_SP_VERT_RE = re.compile(r"^[特別記載事項]\s+(?=\S)")  # 直排章名混入文字層（2886「記 二、…」）
_SP_36_RE = re.compile(r"第(?:三十六|36)條第[二三23]項第[二2]款")
_SP_BIG_PFX_RE = re.compile(r"^[壹貳參肆伍陸柒捌玖拾]+、\s*")
_SP_MIDLINE_RE = re.compile(r"^\S{1,12}\s+(?=[一二三四五六七八九十]+、\s*(?:最近年度|其他必要|私募))")
_SP_LONE_BIG_RE = re.compile(r"^[壹貳參肆伍陸柒捌玖拾]$")
_SP_36_HEAD_RE = re.compile(r"[^。：:]{0,40}?" + _SP_36_PAT)
_SP_MOPS_RE = re.compile(r"公開資訊觀測站")
_SP_SEE_MOPS_MAX = 600  # 超過此字數（去空白）視為實質揭露，不是單純連結
_SP_NONE_RE = re.compile(r"(?:無|不適用)。?$")
_SP_NONE_FIRST_MAX = 200  # 「無」句的長度上限：101 家實測正確的 none 第一句 ≤175 字（私募「，應揭露…：無」）；≥234 字者是整張組織圖等揭露、只是最後一小項寫「無」（2379、6505）


@dataclass
class SpecialItem:
    """特別記載事項的一個子項。找不到 → status=not_found、page／text=None。"""

    status: str
    page: int | None = None
    text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "page": self.page, "text": self.text}


def _empty_special_items() -> dict[str, SpecialItem]:
    return {k: SpecialItem(STATUS_NOT_FOUND) for k in SPECIAL_KEYS}


@dataclass
class SpecialSection:
    """特別記載事項章。至少 1 個子項不是 not_found → parsed；都找不到 → not_found。"""

    status: str
    pages: list[int] = field(default_factory=list)
    chapter_heading: str | None = None
    items: dict[str, SpecialItem] = field(default_factory=_empty_special_items)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pages": list(self.pages),
            "chapter_heading": self.chapter_heading,
            "items": {k: v.to_dict() for k, v in self.items.items()},
            "reason": self.reason,
        }


def _sp_item_status(text: str) -> str:
    """子項內文 → status。順序：第一句結尾為「無」「不適用」→ none（優先於 see_mops；但第一句本身提到觀測站時不算，視為觀測站連結）；
    只有觀測站連結（提到「公開資訊觀測站」且 ≤600 字）→ see_mops；其餘 → disclosed（文字層缺字使「無」變成別的字元時也是 disclosed，已知限制）。"""
    n = re.sub(r"\s+", "", _nfkc(text))
    first = n.split("。", 1)[0] + "。" if "。" in n else n
    mops_only = bool(_SP_MOPS_RE.search(n)) and len(n) <= _SP_SEE_MOPS_MAX
    # 第一句本身提到觀測站（各小項沒有句號、整段成一句，2317 型「(一)…觀測站…(三)…：不適用。」）→ 不是獨立的「無」句
    # 第一句超過長度上限 → 多小項揭露（無句號），結尾的「無」只屬最後一小項，不是整項無
    if _SP_NONE_RE.search(first) and not _SP_MOPS_RE.search(first) and len(first) <= _SP_NONE_FIRST_MAX:
        return STATUS_NONE
    if mops_only:
        return STATUS_SEE_MOPS
    return STATUS_DISCLOSED


def _sp_is_toc_page(lines: list[str]) -> bool:
    return any(_TOC_LEADER_RE.search(_norm(x)) for x in lines)


def _sp_big_36_head(texts: list[str], i: int) -> bool:
    """texts[i] 是「柒、…第三十六條第三項第二款…事項」型的第 36 條事項另立章標題（標題可斷成 ≤5 列（5871 型），之後的列不帶編號）。
    只認大寫數字章號起頭、章號後 ≤40 字內就出現第 36 條款次或「對股東權益或證券價格有重大影響（之）事項」；目錄列（引導線／列尾頁碼）不算。"""
    s = _nfkc(texts[i]).strip()
    m = _SP_BIG_PFX_RE.match(s)
    if m is None or _SP_TOC_TITLE_RE.search(s):
        return False
    win = s[m.end():]
    for nxt in texts[i + 1:i + 5]:
        n = _nfkc(nxt).strip()
        if _prefix(n) is not None or _SP_BIG_PFX_RE.match(n):
            break
        win += n
    return _SP_36_HEAD_RE.match(re.sub(r"\s+", "", win)) is not None


def _sp_title_key(texts: list[str], i: int) -> str | None:
    """texts[i] 是子項標題列 → 子項 key。標題須行首編號（或另立章的大寫數字章名）＋關鍵字；
    標題可斷成多列：之後 ≤2 個無編號列併入判斷。"""
    s = _SP_VERT_RE.sub("", _CF_BULLET_RE.sub("", _nfkc(texts[i]).replace("\u31d0", "一")).strip())  # U+31D0（㇐）是 2207 的「一、」
    if _SP_CH36_RE.match(s) or _sp_big_36_head(texts, i):
        return "material_events_36"
    big = _SP_BIG_PFX_RE.match(s)
    if _prefix(s) is None and big is None and (mid := _SP_MIDLINE_RE.match(s)):
        s = s[mid.end():]  # 雙欄交錯：別欄表格儲存格的殘字（≤12 字）在標題前（4958「有限公司 三、其他必要補充說明事項：無。」）
    if (_prefix(s) is None and big is None) or _SP_TOC_TITLE_RE.search(s):
        return None  # 子項標題以大寫數字編號（2379、3045「壹、關係企業相關資料」）也算，但仍須比對到子項關鍵字
    win = s
    for nxt in ([] if big else texts[i + 1:i + 3]):  # 大寫章號的標題只看本列（「陸、特別記載事項」不能併下一列去配子項關鍵字）
        n = _nfkc(nxt).strip()
        if _prefix(n) is not None or _SP_BIG_PFX_RE.match(n):
            break
        win += "\n" + n
    rest = re.sub(r"^(?:[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]+、|\d+(?:[.\-]\d+)*[.、]?)\s*", "", win)
    rest_nl = re.sub(r"[^\S\n]+", "", rest)  # 保留列尾（「其他必要補充」的標題寫法要看列尾）
    rest = re.sub(r"\s+", "", rest)
    return next((k for k, rx in _SP_TITLE_RES if rx.match(rest_nl if k == "other_supplement" else rest)), None)


def _sp_stream(pages: list, pi: int, li: int) -> list[tuple[int, str]]:
    """由 pages[pi].lines[li] 起的列流（頁碼, 列文字）：略過空列與頁碼列；遇目錄頁、頁碼不連續、
    其他大寫數字章名（「伍、」；章名本身與第 36 條另立章除外）即結束。
    起點是帶大寫章號的章名（「陸、特別記載事項」）時，只有章號大於起點的大寫章名才結束章（子節「貳、關係企業營運概況」
    的章號小於起點，6223 型，不結束）；起點沒有大寫章號時，任何大寫章名都結束。"""
    start = _SP_BIG_PFX_RE.match(_nfkc(pages[pi].lines[li]).strip())
    start_val = _cn_val(start.group(0).rstrip("、 ").translate(_CF_CN_TABLE)) if start else None
    out: list[tuple[int, str]] = []
    for pj in range(pi, len(pages)):
        p = pages[pj]
        if pj > pi and (p.number != pages[pj - 1].number + 1 or _sp_is_toc_page(p.lines)):
            break
        cur = [ln.strip() for ln in (p.lines[li:] if pj == pi else p.lines)]
        cur = [x for x in cur if x and not _SP_FOLIO_RE.match(_nfkc(x))]
        for k, s in enumerate(cur):
            n = _nfkc(s)
            if _SP_LONE_BIG_RE.match(n):
                continue  # 直排章號單獨成列（2002 型「柒」），不是內文
            if _BIG_NUM_RE.match(n) and not _SP_HEAD_RE.match(n) and not _SP_CH36_RE.match(n) and _sp_title_key(cur, k) is None:
                big = _SP_BIG_PFX_RE.match(n)
                # 章號較小的大寫章名只在已讀到子項編號列之後才視為子節（目錄頁上的章名清單沒有子項編號列，不放行）
                nested = start_val is not None and any(_prefix(x) for _, x in out)
                if not nested or _cn_val(big.group(0).rstrip("、 ").translate(_CF_CN_TABLE)) > start_val:
                    return out
            out.append((p.number, s))
    return out


def _sp_items(stream: list[tuple[int, str]]) -> dict[str, SpecialItem]:
    """列流 → 4 個子項。每個子項取第一個「標題所在頁有內文」的標題；內文到下一個標題前，最後一個標題只取到所在頁底。"""
    texts = [t for _, t in stream]
    marks = [(i, k) for i in range(len(stream)) if (k := _sp_title_key(texts, i))]
    items = _empty_special_items()
    def own_body(n: int) -> str:
        i = marks[n][0]
        j = marks[n + 1][0] if n + 1 < len(marks) else len(stream)
        return _sp_body(texts[i:next((x for x in range(i, j) if stream[x][0] != stream[i][0]), j)], marks[n][1])

    def real(body: str) -> bool:  # 實質內文：有句號，或讀得出「無」「觀測站」（目錄頁的內文只有頁尾或下一行標題）
        return "。" in body or _sp_item_status(body) != STATUS_DISCLOSED

    # 子項目錄頁（3443 章扉）：同一頁有 ≥2 種子項的標題在之後的頁還有同種標題，且該頁沒有任何標題帶實質內文 → 該頁的標題不採用
    # （目錄頁最後一個子項的「內文」是頁尾，會被誤當內文）。標題下有實質內文的頁照舊採用第一頁。
    bodies = [own_body(n) for n in range(len(marks))]
    index_pages = {
        pg for pg in {stream[i][0] for i, _ in marks}
        if len({k for i, k in marks if stream[i][0] == pg and any(stream[x][0] > pg and kk == k for x, kk in marks)}) >= 2
        and not any(real(bodies[n]) for n, (i, _) in enumerate(marks) if stream[i][0] == pg)
    }
    for n, (i, key) in enumerate(marks):
        if items[key].status != STATUS_NOT_FOUND:
            continue
        if stream[i][0] in index_pages and any(stream[x][0] > stream[i][0] and kk == key for x, kk in marks):
            continue
        j = marks[n + 1][0] if n + 1 < len(marks) else len(stream)
        own_end = next((x for x in range(i, j) if stream[x][0] != stream[i][0]), j)
        if marks[n + 1:] == []:
            j = own_end
        text = _sp_body(texts[i:j], key)
        if not bodies[n]:
            continue  # 章扉頁的子項目錄：標題所在頁沒有內文
        items[key] = SpecialItem(_sp_item_status(text), stream[i][0], text)
    _sp_36_from_other(items)
    return items


def _sp_body(lines: list[str], key: str) -> str:
    """標題列起的列 → 去標題後的原文。標題結尾詞在 NFKC 後的字串上比對（文字層有 CJK 相容字），
    再依逐字 NFKC 長度對回原文的切點；對不到時，只取標題列之後的列。"""
    lines = [_SP_VERT_RE.sub("", x) for x in lines]
    joined = _join_lines(lines)
    m = _SP_STRIP_RES[key].match(_nfkc(joined))
    if m is None:
        return _join_lines(lines[1:]).strip()
    cut, acc = 0, 0
    while cut < len(joined) and acc < m.end():
        acc += len(_nfkc(joined[cut]))
        cut += 1
    return joined[cut:].strip()


def _sp_36_from_other(items: dict[str, SpecialItem]) -> None:
    """第 36 條事項寫在「其他必要補充說明事項」內文（1216）：沒有獨立標題時，含該條文的那一句另記為第 36 條事項；
    「其他補充」的 status 看扣掉該句後的內文（扣完沒有內文 → 看該句）。"""
    oth = items["other_supplement"]
    if items["material_events_36"].status != STATUS_NOT_FOUND or oth.text is None:
        return
    sents = re.findall(r"[^。]*。|[^。]+$", oth.text)
    hit = next((s for s in sents if _SP_36_RE.search(re.sub(r"\s+", "", _nfkc(s)))), None)
    if hit is None:
        return
    items["material_events_36"] = SpecialItem(_sp_item_status(hit), oth.page, hit)
    rest = "".join(s for s in sents if s is not hit).strip()
    items["other_supplement"] = SpecialItem(_sp_item_status(rest or hit), oth.page, oth.text)


def _sp_pick(cands: list[tuple[list[int], str | None, dict[str, SpecialItem]]]) -> tuple[list[int], str | None, dict[str, SpecialItem]] | None:
    """候選中子項找到最多者；同數取最早（目錄頁、章扉頁的候選只讀到少數子項，真章節讀到的較多）。"""
    best = None
    for c in cands:
        if best is None or sum(it.page is not None for it in c[2].values()) > sum(it.page is not None for it in best[2].values()):
            best = c
    return best


def _sp_chapter(doc: PdfDoc) -> tuple[list[int], str | None, dict[str, SpecialItem]] | None:
    pages = doc.pages
    # 1. 章名
    cands = []
    for pi, p in enumerate(pages):
        if _sp_is_toc_page(p.lines):
            continue
        for li, ln in enumerate(p.lines):
            if not _SP_HEAD_RE.match(_nfkc(ln).strip()):
                continue
            stream = _sp_stream(pages, pi, li)
            items = _sp_items(stream)
            found = [it.page for it in items.values() if it.page is not None]
            if found:
                cands.append(([p_.number for p_ in pages if p.number <= p_.number <= max(found)], ln.strip(), items))
    if cands:
        return _sp_pick(cands)
    # 2. 退回：連續 ≤3 頁內出現 ≥2 種子項標題
    keyed: list[tuple[int, int, str]] = []  # (頁序, 列序, key)
    for pi, p in enumerate(pages):
        if _sp_is_toc_page(p.lines):
            continue
        keyed += [(pi, i, k) for i in range(len(p.lines)) if (k := _sp_title_key(p.lines, i))]
    for pi, li, _ in keyed:
        no = pages[pi].number
        if len({k for pj, _, k in keyed if no <= pages[pj].number <= no + _MAX_SECTION_PAGES - 1}) < 2:
            continue
        items = _sp_items(_sp_stream(pages, pi, li))
        found = [it.page for it in items.values() if it.page is not None]
        if found:  # 沒有章名：範圍取子項實際所在頁（起點可能是未判為目錄的子項索引頁，2801 p5）
            cands.append(([p_.number for p_ in pages if min(found) <= p_.number <= max(found)], None, items))
    return _sp_pick(cands)


def parse_special(doc: PdfDoc) -> SpecialSection:
    """解析年報「特別記載事項」章的 4 個固定子項（affiliates／private_placement／other_supplement／material_events_36）。

    定位：先找章名（整列只有「特別記載事項」，可帶編號前綴；目錄頁不採用）；章名後找不到子項、或沒有章名 →
    子項退回（連續 ≤3 頁內有 ≥2 種「行首編號＋關鍵字」的子項標題）。都找不到 → not_found。
    子項 status：只有「公開資訊觀測站」連結（≤600 字）→ see_mops；第一句為「…：無。」「不適用。」→ none；
    其他 → disclosed；找不到 → not_found（page／text 為 None）。text 為去標題後的原文。
    """
    found = _sp_chapter(doc)
    if found is None:
        return SpecialSection(STATUS_NOT_FOUND, reason="找不到特別記載事項章名與子項")
    pages, heading, items = found
    return SpecialSection(STATUS_PARSED, pages, heading, items)
