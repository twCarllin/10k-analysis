"""fy_income.py — FY 損益表資料結構、符號正規化、勾稽、可用判準（Spec 2026-10-09-tw-equity-period-model §2.1、§2.4–§2.6）。

純確定性、無 LLM。列解析、候選頁、`extract_fy_income` 入口屬後續 item，本檔不含。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from runtime.tw_equity.statements import _norm_label, map_key
from runtime.tw_equity.tables import _norm_line

if TYPE_CHECKING:
    from runtime.tw_equity.pdf_doc import PdfDoc

# 單位原文 → 換算為仟元的倍數（Spec §2.1）；認不出 → None
_SCALE_TABLE: dict[str, float] = {
    "仟元": 1.0,
    "千元": 1.0,
    "百萬元": 1000.0,
    "百萬新台幣": 1000.0,
    "元": 0.001,
}

_TOLERANCE = 1.0  # 勾稽容差：1 仟元（Spec §2.5）

# Spec §2.4 補充別名（key 為 _norm_label 後的科目）；僅在 statements.map_key 對不到時使用
_ALIASES: dict[str, str] = {
    "營業收入總額": "revenue",
    "營業損益": "operating_income",
    "營業淨利(損)": "operating_income",
    "營業損失": "operating_income",
    "營業(損)益": "operating_income",
    "稅前利益": "pretax_income",
    "本期稅前淨利": "pretax_income",
    "稅前損益": "pretax_income",
    "稅後淨利": "net_income",
    "本期稅後淨利": "net_income",
    "本年度淨利": "net_income",
    "營業費用": "total_opex",
    "營業外收入及支出": "nonoperating_total",
    "營業外收入(支出)": "nonoperating_total",
    "營業毛利淨額": "gross_profit_net",
    # §2.7.1 未實現銷貨損益（前綴 減:／加: 已先剝除）
    "未(已)實現銷貨損益": "unrealized_sales_profit",
    "未實現銷貨損益": "unrealized_sales_profit",
    "已實現銷貨損益": "unrealized_sales_profit",
    # §2.7.2 其他營業項目（營業費用之後、營業利益之前）
    "其他收益及費損": "other_operating_net",
    "其他收益及費損淨額": "other_operating_net",
    "其他營業收益及費損淨額": "other_operating_net",
    # §2.7.6 歸屬母公司淨利（net_income 缺列時代用）
    "淨利歸屬於母公司業主": "net_income_parent",
    "本期淨利歸屬於母公司業主": "net_income_parent",
    "歸屬於母公司業主之淨利": "net_income_parent",
}

_PREFIX_RE = re.compile(r"^(?:合併|減:|加:)+")

_REQUIRED_CURRENT = ("revenue", "operating_income", "pretax_income", "net_income")


def scale_for_unit(unit: str) -> float | None:
    """單位原文 → 仟元倍數；認不出 → None。"""
    nu = _norm_label(unit)
    if nu in _SCALE_TABLE:
        return _SCALE_TABLE[nu]
    return _SCALE_TABLE.get(re.sub(r"新[台臺]幣", "", nu))  # `新台幣千元` → `千元`


def normalize_sign(
    key: str | None, label: str, value: float | None, cogs_raw: float | None = None
) -> float | None:
    """Spec §2.4／§2.7 符號正規化：費用為負、收入為正。

    cogs／total_opex 取 -abs；income_tax 依括號詞（(費用)→原值、(利益)→-x）；無括號詞時，
    同頁 cogs 原值為正（`cogs_raw > 0`，表內費用以正數表示）→ -x（負值＝稅利益），否則 -abs；
    unrealized_sales_profit：標籤以 `減` 起頭 → -x（該列是自毛利扣除的項目），否則原值；其餘原值。
    """
    if value is None:
        return None
    if key in ("cogs", "total_opex"):
        return -abs(value)
    if key == "income_tax":
        lab = _norm_label(label)
        if "(費用)" in lab:
            return value
        if "(利益)" in lab:
            return -value
        if cogs_raw is not None and cogs_raw > 0:
            return -value
        return -abs(value)
    if key == "unrealized_sales_profit":
        return -value if _norm_label(label).startswith("減") else value
    return value


def map_fy_label(label: str) -> str | None:
    """Spec §2.4：剝除前綴（合併、減:、加:）→ statements.map_key("is", …, None) → 補充別名；對不到 → None。"""
    nl = _PREFIX_RE.sub("", _norm_label(label))
    return map_key("is", nl, None) or _ALIASES.get(nl)


# ── 列解析（Spec §2.3） ───────────────────────────────────────────────────────

_NOTE_TOKEN_RE = re.compile(r"^(?:說明\d*|\(?註\d*\)?|不適用)$")
_AMOUNT_TOKEN_RE = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?$|^\(?-?\d+(?:\.\d+)?%?\)?$")
_YEAR_MARK_RE = re.compile(r"(\d{2,3})年")


def _token_amount(tok: str) -> float | None:
    """金額 token → 數值；括號或前置 `-` 為負；lone `-` → None。"""
    if tok == "-":
        return None
    neg = tok.startswith("(") or tok.startswith("-")
    v = float(tok.strip("()%").lstrip("-").replace(",", ""))
    v = int(v) if v == int(v) and "." not in tok else v
    return -v if neg else v


_GLUED_NOTE_RE = re.compile(r"\(註\d*\)")


def _resolve_label(toks: list[str]) -> str:
    """科目 token → 科目文字；整串對不到時取「最長的可對照後綴」（左側夾雜 BS 科目或欄名，G8）。"""
    full = "".join(toks)
    if map_fy_label(full) is not None:
        return full
    for i in range(1, len(toks)):
        cand = "".join(toks[i:])
        if map_fy_label(cand) is not None:
            return cand
    return full


def _split_segments(line: str) -> list[tuple[str, list[float | None]]]:
    """一列切成 [(label, amounts)]；金額之後又出現中文科目 → 新段（左右並排，G8）。

    列尾附註（說明N、(註N)、註N、不適用）忽略；首個科目文字之前的金額 token（如 `(1)`）略過。
    """
    segs: list[tuple[str, list[float | None]]] = []
    label: list[str] = []
    amts: list[float | None] = []
    for tok in _norm_line(line).split():
        tok = _GLUED_NOTE_RE.sub("", tok)  # `營業利益(註1)` → `營業利益`
        if not tok or _NOTE_TOKEN_RE.match(tok):
            continue
        if _AMOUNT_TOKEN_RE.match(tok) or tok == "-":
            if label:
                amts.append(_token_amount(tok))
            continue
        if amts:  # 金額之後的科目文字 → 切段
            segs.append((_resolve_label(label), amts))
            label, amts = [], []
        label.append(tok)
    if label:
        segs.append((_resolve_label(label), amts))
    return segs


def _is_amount_only(line: str) -> bool:
    toks = [t for t in _norm_line(line).split() if not _NOTE_TOKEN_RE.match(t)]
    return bool(toks) and all(_AMOUNT_TOKEN_RE.match(t) or t == "-" for t in toks)


def parse_page_rows(
    lines: list[str], roc_year: int, warnings: list[str] | None = None
) -> list[dict]:
    """Spec §2.3：頁文字列 → [{"label","key","current","prior"}]（未乘 scale）。

    表頭＝第一個「科目對照到 IS key 且有 ≥2 個金額」的列之前；其中 `{roc_year}年`／`{roc_year-1}年`
    的先後決定欄序；表頭兩個年度標記之間出現 `%`（或表頭含 `金額 % 金額 %`）→ 每年度佔 2 個 token。
    科目在上一列、金額在下一列者不產生 row，寫入 warnings。
    """
    segs_by_line = [_split_segments(ln) for ln in lines]

    def is_data_seg(seg: tuple[str, list[float | None]]) -> bool:
        return len(seg[1]) >= 2 and map_fy_label(seg[0]) is not None

    first = next((i for i, ss in enumerate(segs_by_line) if any(is_data_seg(s) for s in ss)), None)
    if first is None:
        return []
    header = re.sub(r"\s+", "", "".join(_norm_line(ln) for ln in lines[:first]).replace("％", "%"))
    order: list[int] = []
    pos: list[int] = []
    for m in _YEAR_MARK_RE.finditer(header):
        y = int(m.group(1))
        if y in (roc_year, roc_year - 1) and y not in order:
            order.append(y)
            pos.append(m.start())
    if len(order) < 2:
        return []
    between = header[pos[0]:pos[1]]
    stride = 2 if ("%" in between or "金額%金額%" in header) else 1

    rows: list[dict] = []
    for i in range(first, len(lines)):
        ss = segs_by_line[i]
        for label, amts in ss:
            key = map_fy_label(label)
            if key is None:
                continue
            picked = amts[::stride][:2]
            if len(picked) < 2:
                if not amts and len(ss) == 1 and i + 1 < len(lines) and _is_amount_only(lines[i + 1]):
                    if warnings is not None:
                        warnings.append(f"科目與金額跨列，未解析：{label}")
                continue
            by_year = dict(zip(order, picked))
            rows.append(
                {"label": label, "key": key,
                 "current": by_year.get(roc_year), "prior": by_year.get(roc_year - 1)}
            )
    # §2.7.5：僅取營收列所屬表內的列——營收列之前、且同 key 在營收列（含）之後再出現的列不取（頁首另一張表）
    rev_i = next((i for i, r in enumerate(rows) if r["key"] == "revenue"), None)
    if rev_i is not None:
        later = {r["key"] for r in rows[rev_i:]}
        rows = [r for i, r in enumerate(rows) if i >= rev_i or r["key"] not in later]
    return rows


def _first_row(rows: list[dict], key: str) -> dict | None:
    return next((r for r in rows if r.get("key") == key), None)


def _norm_val(rows: list[dict], key: str, period: str) -> tuple[bool, float | None]:
    """(有此 key 的列, 該期正規化後的值)；income_tax 的無括號詞符號判斷用同期 cogs 原值（§2.7.4）。"""
    row = _first_row(rows, key)
    if row is None:
        return (False, None)
    cogs = _first_row(rows, "cogs")
    cogs_raw = None if cogs is None else cogs.get(period)
    return (True, normalize_sign(key, row["label"], row.get(period), cogs_raw))


def _approx(a: float, b: float) -> bool:
    return abs(a - b) <= _TOLERANCE


def run_fy_checks(rows: list[dict]) -> list[dict]:
    """Spec §2.5／§2.7：gross／operating／net × (current, prior)，共 6 項；無法計算 → passed=None。

    name 形如 `gross_current`、`gross_prior`。lhs／rhs 為正規化後的數值（無法計算時 None）。
    - gross：`revenue+cogs+unrealized_sales_profit == (gross_profit_net 列有則用之，否則 gross_profit)` 或
      `revenue+cogs == gross_profit`，任一成立即 passed（unrealized_sales_profit 缺列／值視為 0）
    - operating：`(gross_profit_net 列有則用之，否則 gross_profit) + total_opex + other_operating_net == operating_income`
    - net：`pretax_income + income_tax == net_income`
    """
    out: list[dict] = []
    for period in ("current", "prior"):
        def v(key: str) -> float | None:
            return _norm_val(rows, key, period)[1]

        has_net, gpn = _norm_val(rows, "gross_profit_net", period)
        gp = v("gross_profit")
        base = gpn if has_net else gp
        unreal = v("unrealized_sales_profit") or 0.0
        other = v("other_operating_net") or 0.0
        rev, cogs = v("revenue"), v("cogs")

        # gross
        cand: list[tuple[float, float]] = []  # (lhs, rhs)
        if rev is not None and cogs is not None:
            if base is not None:
                cand.append((rev + cogs + unreal, base))
            if gp is not None:
                cand.append((rev + cogs, gp))
        if not cand:
            out.append({"name": f"gross_{period}", "lhs": None, "rhs": base if base is not None else gp, "passed": None})
        else:
            ok = next((c for c in cand if _approx(*c)), None)
            lhs, rhs = ok if ok is not None else cand[0]
            out.append({"name": f"gross_{period}", "lhs": lhs, "rhs": rhs, "passed": ok is not None})

        # operating
        opex, op = v("total_opex"), v("operating_income")
        if base is None or opex is None or op is None:
            out.append({"name": f"operating_{period}", "lhs": None, "rhs": op, "passed": None})
        else:
            lhs = base + opex + other
            out.append({"name": f"operating_{period}", "lhs": lhs, "rhs": op, "passed": _approx(lhs, op)})

        # net
        pre, tax, ni = v("pretax_income"), v("income_tax"), v("net_income")
        if pre is None or tax is None or ni is None:
            out.append({"name": f"net_{period}", "lhs": None, "rhs": ni, "passed": None})
        else:
            out.append({"name": f"net_{period}", "lhs": pre + tax, "rhs": ni, "passed": _approx(pre + tax, ni)})
    # 輸出順序：gross／operating／net × (current, prior)
    order = {f"{n}_{p}": i for i, (n, p) in enumerate((n, p) for n in ("gross", "operating", "net") for p in ("current", "prior"))}
    out.sort(key=lambda c: order[c["name"]])
    return out


def compute_usable(
    scale: float | None, basis: str, rows: list[dict], checks: list[dict]
) -> bool:
    """Spec §2.6：scale 非 None、basis 非 parent、本期四個必要列皆非 None、勾稽無 passed=False。"""
    if scale is None or basis == "parent":
        return False
    for key in _REQUIRED_CURRENT:
        row = _first_row(rows, key)
        if row is None or row.get("current") is None:
            return False
    return not any(c["passed"] is False for c in checks)


# ── 入口：候選頁、單位、基準（Spec §2.2、§2.1） ──────────────────────────────

_CORE_KEYS = frozenset({"gross_profit", "operating_income", "pretax_income", "net_income"})
_ANCHOR_KEYS = ("ar_fin_performance", "ar_mdna")
_UNIT_RE = re.compile(r"單位[:：]([^;；%％]*)")
# 單位文字起頭的已知寫法（NFKC、去空白後比對）；對不到 → 原文（scale 為 None）
_UNIT_NAME_RE = re.compile(r"^(?:新[台臺]幣(?:百萬元|仟元|千元|元)|(?:百萬元|仟元|千元|元)|百萬新[台臺]幣)")


def _keyed_segs(line: str) -> list[tuple[str, list[float | None]]]:
    """列內「科目對照到 key 且 ≥2 個金額」的段 → [(key, amounts)]。"""
    out = []
    for label, amts in _split_segments(line):
        key = map_fy_label(label)
        if key is not None and len(amts) >= 2:
            out.append((key, amts))
    return out


def _is_candidate(lines: list[str], roc_year: int) -> bool:
    """Spec §2.2 a/b/c：表頭含兩個年度標記、有 ≥2 金額的營收列、其後 40 列內 ≥2 個核心科目列。"""
    rev_idx = next(
        (i for i, ln in enumerate(lines) if any(k == "revenue" for k, _ in _keyed_segs(ln))), None
    )
    if rev_idx is None:
        return False
    header = re.sub(r"\s+", "", "".join(_norm_line(ln) for ln in lines[:rev_idx]))
    if f"{roc_year}年" not in header or f"{roc_year - 1}年" not in header:
        return False
    core = sum(
        1
        for ln in lines[rev_idx + 1 : rev_idx + 41]
        if any(k in _CORE_KEYS for k, _ in _keyed_segs(ln))
    )
    return core >= 2


def _in_ranges(page_no: int, anchors: dict | None) -> bool:
    for k in _ANCHOR_KEYS:
        r = (anchors or {}).get(k)
        if r is not None and r.start <= page_no <= r.end:
            return True
    return False


def _detect_unit(lines: list[str]) -> str:
    """單位原文；先 NFKC＋去全部空白再比對（`單位：新台幣 千元` → `新台幣千元`）。"""
    for ln in lines:
        m = _UNIT_RE.search(_norm_label(ln))
        if m:
            raw = m.group(1)
            known = _UNIT_NAME_RE.match(raw)
            return known.group(0) if known else raw
    return ""


_NARRATIVE_UNIT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(仟元|千元|百萬元)")


def _narrative_unit(lines: list[str]) -> tuple[str, int]:
    """敘述文字中緊接千分位金額之後的單位（NFKC、去空白；跨列相接）。

    → (單位, 不同 scale 的個數)：恰 1 種 scale → (第一個單位, 1)；多種 → ("", n)；無 → ("", 0)。
    """
    text = re.sub(r"\s+", "", "".join(_norm_line(ln) for ln in lines))
    units = _NARRATIVE_UNIT_RE.findall(text)
    scales = {scale_for_unit(u) for u in units}
    if len(scales) == 1:
        return (units[0], 1)
    return ("", len(scales))


def _detect_basis(lines: list[str]) -> str:
    text = re.sub(r"\s+", "", "".join(_norm_line(ln) for ln in lines))
    if "合併" in text or "及子公司" in text:
        return "consolidated"
    if "個體" in text:
        return "parent"
    return "unknown"

# ── 金控候選頁與欄序（Spec fh-schema §6.2；task 4.2 骨架 C） ─────────────────────

_FH_HEADER_MAX_LEN = 40  # 表頭列去空白後的長度上限（排除含兩個年度字樣的說明散文列）
_FH_AMOUNT_RUN_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_FH_BREAK_RE = re.compile(
    r"就差異金額|重大變動|前後期變動|^(?:說明|註\d*[:：]|單位|\([一二三四五六七八九十]+\)|[一二三四五六七八九十]+、|\d+[.、]|\(\d+\))"
)
_FH_TITLE_MAX_LEN = 40
_FH_TITLE_WINDOW = 5
_FH_CONSOL_KEYS = frozenset({"net_interest_income", "non_interest_income", "insurance_reserve_change", "provision"})


@dataclass(frozen=True)
class FhTable:
    """金控 FY 損益比較表的定位結果（列對照與 FyIncome 由後續 item 在此基礎上做）。

    start／end 為頁內列 index 的半開區間 [start, end)，start 為表頭列；
    current_col／prior_col 為該列「金額 token」中本期／上期的 index（已含 `金額 %` 並排的 stride）。
    """

    page: int
    scope_hint: str       # "consolidated" | "parent_only"（最終 scope 判定屬 item 4.3）
    family: str           # "roc"（114年度）| "west"（2025年度）
    current_col: int
    prior_col: int
    start: int
    end: int
    n_rows: int           # 區段內可辨識的 IS 列數（排序用）


def _fh_marks(norm_line: str, roc_year: int) -> tuple[str, list[int]] | None:
    """表頭列 → (family, 年度依標記出現位置由左至右排序)；兩個標記未同現 → None。"""
    for family, cur in (("roc", roc_year), ("west", roc_year + 1911)):
        found: dict[int, int] = {}
        for y in (cur, cur - 1):
            m = re.search(rf"(?<!\d){y}年", norm_line)
            if m:
                found[y] = m.start()
        if len(found) == 2:
            return family, sorted(found, key=found.__getitem__)
    return None


def _fh_row_kinds(label: str) -> set[str]:
    nl = _PREFIX_RE.sub("", _norm_label(label))
    kinds: set[str] = set()
    if "稅前" in nl:
        kinds.add("pretax")
    if (
        map_key("is", nl, None, schema="fh") == "net_income"
        or re.search(r"(?:本期|本年度|稅後)(?:稅後)?(?:淨利|純益|淨損|\(損\)益|損益)", nl)  # search：容忍左側直排文字黏字（`及及本期(損)益`）
    ):
        kinds.add("net")
    if map_key("is", nl, None, schema="fh") in _FH_CONSOL_KEYS:
        kinds.add("consol")
    if "採權益法" in nl or "採用權益法" in nl:
        kinds.add("equity")
    return kinds


def _fh_tables_in_page(page_no: int, lines: list[str], roc_year: int) -> list[FhTable]:
    nos = [re.sub(r"\s+", "", _norm_line(ln)) for ln in lines]
    headers: list[tuple[int, str, list[int]]] = []  # (列 index, family, 欄序年度)
    for i, nl in enumerate(nos):
        if len(nl) > _FH_HEADER_MAX_LEN or _FH_AMOUNT_RUN_RE.search(nl):
            continue
        mk = _fh_marks(nl, roc_year)
        if mk is not None:
            headers.append((i, mk[0], mk[1]))
    out: list[FhTable] = []
    for h, (start, family, years) in enumerate(headers):
        limit = headers[h + 1][0] if h + 1 < len(headers) else len(lines)
        end = limit
        for j in range(start + 1, limit):
            if _FH_BREAK_RE.search(nos[j]):
                end = j
                break
        kinds: set[str] = set()
        n_rows = 0
        for j in range(start + 1, end):
            for label, amts in _split_segments(lines[j]):
                if len(amts) >= 2:
                    k = _fh_row_kinds(label)
                    kinds |= k
                    n_rows += 1
        if not {"pretax", "net"} <= kinds:
            continue
        cur = roc_year if family == "roc" else roc_year + 1911
        pos = sorted(nos[start].find(f"{y}年") for y in (cur, cur - 1))
        between = nos[start][pos[0] : pos[1]]  # 兩個年度標記之間有 `%`／`金額%金額%` → 每年度佔 2 個金額 token
        stride = 2 if ("%" in between or "金額%金額%" in nos[start]) else 1
        cur_i, prior_i = years.index(cur), years.index(cur - 1)
        scope = _fh_scope_hint(lines, nos, start, h and headers[h - 1][0], kinds)
        out.append(FhTable(page_no, scope, family, cur_i * stride, prior_i * stride, start, end, n_rows))
    return out


def _fh_scope_hint(lines: list[str], nos: list[str], start: int, floor: int, kinds: set[str]) -> str:
    """表題（表頭列＋其前 5 列內最近的短列）含「合併」→ consolidated、含「個體」→ parent_only；
    表題無字樣時依列內容：有權益法列 → parent_only、有利息／保險負債列 → consolidated，其餘 parent_only。"""
    for j in range(start, max(floor, start - _FH_TITLE_WINDOW) - 1, -1):
        t = nos[j]
        if j != start and (len(t) > _FH_TITLE_MAX_LEN or re.search(r"[，。]", t)):
            continue
        if "合併" in t or "及子公司" in t:
            return "consolidated"
        if "個體" in t:
            return "parent_only"
    if "equity" in kinds:
        return "parent_only"
    return "consolidated" if "consol" in kinds else "parent_only"


def fh_candidate_tables(ar: "PdfDoc", ar_anchors: dict | None, roc_year: int) -> list[FhTable]:
    """§6.2：候選表依優先序排列（錨點範圍內優先；合併先於個體；列數多者先；頁碼小者先）。"""
    tables: list[FhTable] = []
    for pg in ar.pages:
        tables.extend(_fh_tables_in_page(pg.number, pg.lines, roc_year))
    pool = [t for t in tables if _in_ranges(t.page, ar_anchors)] or tables
    return sorted(pool, key=lambda t: (t.scope_hint != "consolidated", -t.n_rows, t.page, t.start))


def fh_select_table(ar: "PdfDoc", ar_anchors: dict | None, roc_year: int) -> FhTable | None:
    cands = fh_candidate_tables(ar, ar_anchors, roc_year)
    return cands[0] if cands else None


_FH_PARENT_NI = frozenset(_norm_label(x) for x in ("稅後純益", "本期(損)益", "稅後淨利", "本期淨利"))
_FH_OWNER_RE = re.compile(r"^(.*?(?:淨利|淨損|綜合損益總額)(?:\([^)]*\))?)歸屬於(.+)$")


def _fh_key(label: str, consolidated: bool) -> str | None:
    """Spec §6.3：合併表 → map_key(schema="fh")（含「…歸屬於母公司業主」→ net_income_parent）；個體表只認淨利列。"""
    nl = _norm_label(label)
    if not consolidated:
        return "net_income_parent" if nl in _FH_PARENT_NI else None
    m = _FH_OWNER_RE.match(nl)
    if m:
        return map_key("is", m.group(2), m.group(1) + "歸屬於", schema="fh")
    return map_key("is", nl, None, schema="fh")


def _fh_resolve(label: str, consolidated: bool) -> tuple[str, str | None]:
    """整串對不到時取最長的可對照後綴（容忍左側直排文字黏字，如 `況利息收入`、`及及本期(損)益`）。"""
    key = _fh_key(label, consolidated)
    if key is not None:
        return label, key
    for i in range(1, len(label)):
        key = _fh_key(label[i:], consolidated)
        if key is not None:
            return label[i:], key
    return label, None


def _parse_fh_rows(lines: list[str], tbl: FhTable) -> list[dict]:
    """區段內有 ≥2 個金額 token 的列 → {"label","key","current","prior"}（未乘 scale；費用維持原號）。

    合併表 key 取 FH 對照；個體表只有淨利列有 key（net_income_parent），其餘 key=None、label 保留原文。
    直排殘字等無金額的列忽略。
    """
    consolidated = tbl.scope_hint == "consolidated"
    rows: list[dict] = []
    for ln in lines[tbl.start + 1 : tbl.end]:
        for label, amts in _split_segments(ln):
            need = max(tbl.current_col, tbl.prior_col) + 1
            if len(amts) < need or not label:
                continue
            label, key = _fh_resolve(label, consolidated)
            rows.append({"label": label, "key": key, "current": amts[tbl.current_col], "prior": amts[tbl.prior_col]})
    return rows


def _fh_val(rows: list[dict], key: str, period: str) -> float | None:
    row = _first_row(rows, key)
    return None if row is None else row.get(period)


def run_fh_fy_checks(rows: list[dict]) -> list[dict]:
    """Spec §6.4：合併表 `is_net_income`（pretax＋income_tax＝net_income，所得稅沿用原號）、
    `is_pretax`（net_revenue − |provision| − |insurance_reserve_change| − |total_opex|＝pretax_income，IFRS 4 年報格式）。

    name 形如 `is_net_income_current`；任一項缺值 → lhs None、passed None。
    """
    out: list[dict] = []
    for period in ("current", "prior"):
        def v(key: str) -> float | None:
            return _fh_val(rows, key, period)

        pre, tax, ni = v("pretax_income"), v("income_tax"), v("net_income")
        out.append(_fh_check(f"is_net_income_{period}", None if None in (pre, tax) else pre + tax, ni))
        rev, prov, rsv, opex = v("net_revenue"), v("provision"), v("insurance_reserve_change"), v("total_opex")
        lhs = None if None in (rev, prov, rsv, opex) else rev - abs(prov) - abs(rsv) - abs(opex)
        out.append(_fh_check(f"is_pretax_{period}", lhs, pre))
    return out


def _fh_check(name: str, lhs: float | None, rhs: float | None) -> dict:
    passed = None if lhs is None or rhs is None else _approx(lhs, rhs)
    return {"name": name, "lhs": lhs, "rhs": rhs, "passed": passed}


def compute_fh_usable(scale: float | None, scope: str, rows: list[dict]) -> bool:
    """Spec §6.4：合併 → 本期 net_revenue、pretax_income、net_income 皆有值；個體 → 本期 net_income_parent 有值（另需 scale 可辨識）。"""
    if scale is None:
        return False
    need = ("net_revenue", "pretax_income", "net_income") if scope == "consolidated" else ("net_income_parent",)
    return all(_fh_val(rows, k, "current") is not None for k in need)


def _extract_fh(ar: "PdfDoc", ar_anchors: dict | None, roc_year: int) -> "FyIncome | None":
    """Spec §6.2–§6.4：金控候選表 → 列解析（乘 scale）→ FyIncome(schema="fh")。"""
    tbl = fh_select_table(ar, ar_anchors, roc_year)
    if tbl is None:
        return None
    pg = next(p for p in ar.pages if p.number == tbl.page)
    unit = next(
        (u for u in (_detect_unit([ln]) for ln in reversed(pg.lines[max(0, tbl.start - 6) : tbl.start + 1])) if u), ""
    )
    scale = scale_for_unit(unit) if unit else None
    warns = [] if scale is not None else [f"單位無法辨識：{unit!r}"]
    rows = _parse_fh_rows(pg.lines, tbl)
    if scale is not None:
        for r in rows:
            for f in ("current", "prior"):
                if r[f] is not None:
                    r[f] = r[f] * scale
    return FyIncome(
        roc_year=roc_year, page=tbl.page, unit=unit, scale=scale,
        basis="consolidated" if tbl.scope_hint == "consolidated" else "parent",
        rows=rows, warnings=warns, scope=tbl.scope_hint, schema="fh",
    ).finalize()


def extract_fy_income(
    ar: "PdfDoc", ar_anchors: dict | None, *, roc_year: int, group: str | None = None
) -> "FyIncome | None":
    """Spec §2.1／§2.2：掃全份年報找 FY 損益比較頁並解析；無候選頁 → None。

    group == "fh" → 金控路徑（§6.2）；其他（含 None）行為不變。
    """
    if group == "fh":
        return _extract_fh(ar, ar_anchors, roc_year)
    parsed: list[tuple[int, list[dict], list[str], list[str]]] = []  # (頁碼, rows, lines, warnings)
    for pg in ar.pages:
        if not _is_candidate(pg.lines, roc_year):
            continue
        warns: list[str] = []
        rows = parse_page_rows(pg.lines, roc_year, warns)
        parsed.append((pg.number, rows, pg.lines, warns))
    if not parsed:
        return None
    # §2.7.3：先剔除個體頁（含「個體」且不含「合併」／「及子公司」）；全被剔除才保留原候選
    parsed = [c for c in parsed if _detect_basis(c[2]) != "parent"] or parsed
    pool = [c for c in parsed if _in_ranges(c[0], ar_anchors)] or parsed
    page_no, rows, lines, warns = max(pool, key=lambda c: (len({r["key"] for r in c[1]}), c[0]))

    # §2.4：同頁有其他 revenue 列 → 丟棄 `營業收入總額`
    if any(r["key"] == "revenue" and _norm_label(r["label"]) != "營業收入總額" for r in rows):
        rows = [r for r in rows if _norm_label(r["label"]) != "營業收入總額"]

    # §2.7.5：候選頁沒有單位列 → 往前 1 頁找；仍無 → 敘述中緊接千分位金額之後的單位
    prev = next((p for p in ar.pages if p.number == page_no - 1), None)
    prev_lines = prev.lines if prev is not None else []
    unit = _detect_unit(lines) or _detect_unit(prev_lines)
    if not unit:
        unit, n_units = _narrative_unit(lines + prev_lines)
        if n_units > 1:
            warns.append("敘述中出現多個不同單位，scale 無法判定")
    # §2.7.6：無 net_income 列但有歸屬母公司淨利 → 代用
    net_basis = "total"
    if not any(r["key"] == "net_income" for r in rows):
        proxy = next((r for r in rows if r["key"] == "net_income_parent"), None)
        if proxy is not None:
            rows = rows + [{**proxy, "key": "net_income"}]
            net_basis = "parent"
            warns.append("net_income 以歸屬母公司淨利代用")
    scale = scale_for_unit(unit) if unit else None
    if scale is None:
        warns.append(f"單位無法辨識：{unit!r}")
    else:
        for r in rows:
            for f in ("current", "prior"):
                if r[f] is not None:
                    r[f] = r[f] * scale
    return FyIncome(
        roc_year=roc_year, page=page_no, unit=unit, scale=scale,
        basis=_detect_basis(lines), rows=rows, warnings=warns, net_income_basis=net_basis,
    ).finalize()


@dataclass
class FyIncome:
    roc_year: int
    page: int
    unit: str
    scale: float | None
    basis: str = "unknown"                      # consolidated | parent | unknown
    rows: list[dict] = field(default_factory=list)    # {"label","key","current","prior"}（已乘 scale）
    checks: list[dict] = field(default_factory=list)  # {"name","lhs","rhs","passed"}
    usable: bool = False
    warnings: list[str] = field(default_factory=list)
    net_income_basis: str = "total"                   # "total" | "parent"（§2.7.6）
    scope: str = "consolidated"                       # "consolidated" | "parent_only"（fh-schema §6.4；工業恆 consolidated）
    schema: str = "industrial"                        # "industrial" | "fh"

    def get(self, key: str) -> tuple[float | None, float | None]:
        """第一個相符列的 (current, prior)；無 → (None, None)。"""
        row = _first_row(self.rows, key)
        if row is None:
            return (None, None)
        return (row.get("current"), row.get("prior"))

    def normalized(self, key: str, period: str = "current") -> float | None:
        """第一個相符列在 `period`（"current"／"prior"）的 §2.4／§2.7 正規化值；無列／值為 None → None。

        income_tax 無括號詞時依同頁 cogs 原值（同期）判斷符號；勾稽與 3653 錨比對共用此入口。
        """
        return _norm_val(self.rows, key, period)[1]

    def finalize(self) -> "FyIncome":
        """依 rows 填入 checks 與 usable。"""
        if self.schema == "fh":
            self.checks = run_fh_fy_checks(self.rows) if self.scope == "consolidated" else []
            self.usable = compute_fh_usable(self.scale, self.scope, self.rows)
            return self
        self.checks = run_fy_checks(self.rows)
        self.usable = compute_usable(self.scale, self.basis, self.rows, self.checks)
        return self

    def to_dict(self) -> dict[str, Any]:
        d = self._base_dict()
        if self.schema == "fh":  # 新鍵只在金控輸出；工業 to_dict 與本 run 前逐值相同
            d["scope"] = self.scope
            d["schema"] = self.schema
        return d

    def _base_dict(self) -> dict[str, Any]:
        return {
            "roc_year": self.roc_year,
            "page": self.page,
            "unit": self.unit,
            "scale": self.scale,
            "basis": self.basis,
            "rows": [dict(r) for r in self.rows],
            "checks": [dict(c) for c in self.checks],
            "usable": self.usable,
            "warnings": list(self.warnings),
            "net_income_basis": self.net_income_basis,
        }
