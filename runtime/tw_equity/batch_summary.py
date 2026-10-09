"""batch_summary.py — 跨公司排名表與紅旗清單（工作包 F；run 2026-10-09-tw-equity-batch-runner）。

只讀 batch.run_company 的每家記錄（不讀 PDF），輸出 summary.json／summary.md／summary.html。
金額單位：帳本皆為新台幣仟元；排名表金額欄換算為百萬元。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

UNSUPPORTED_GROUPS: dict[str, str] = {}  # fh 已支援（fh-schema Spec §8.2）；保留表結構供日後新類別


def _metric(rec: dict, key: str, period: str = "current") -> float | None:
    return ((rec.get("metrics") or {}).get(key) or {}).get(period)


def _value(rec: dict, key: str, period: str = "current") -> float | None:
    return ((rec.get("values") or {}).get(key) or {}).get(period)


def _ttm(rec: dict, key: str) -> float | None:
    t = rec.get("ttm") or {}
    if t.get("status") != "ok":
        return None
    return ((t.get("values") or {}).get(key) or {}).get("ttm")


def _mn(v: float | None) -> float | None:
    return None if v is None else v / 1000.0


# 排名欄：(key, 標題, 單位, 取值函式)；金額欄為百萬元
RANK_COLUMNS: list[tuple[str, str, str, Callable[[dict], float | None]]] = [
    ("revenue", "營收", "百萬元", lambda r: _mn(_value(r, "revenue"))),
    ("gross_margin", "毛利率", "%", lambda r: _metric(r, "gross_margin")),
    ("operating_margin", "營業利益率", "%", lambda r: _metric(r, "operating_margin")),
    ("net_margin", "淨利率", "%", lambda r: _metric(r, "net_margin")),
    ("fcf", "FCF", "百萬元", lambda r: _mn(_metric(r, "fcf"))),
    ("fcf_margin", "FCF 率", "%", lambda r: _metric(r, "fcf_margin")),
    ("roe", "ROE", "%", lambda r: _metric(r, "roe")),
    ("current_ratio", "流動比率", "%", lambda r: _metric(r, "current_ratio")),
    ("debt_to_equity", "有息負債／權益", "%", lambda r: _metric(r, "debt_to_equity")),
    ("ccc", "CCC", "天", lambda r: _metric(r, "ccc")),
    ("ttm_revenue", "TTM 營收", "百萬元", lambda r: _mn(_ttm(r, "revenue"))),
    ("ttm_net_income", "TTM 淨利", "百萬元", lambda r: _mn(_ttm(r, "net_income"))),
]


# 金控排名欄（fh-schema Spec §8.2）：取值同工業欄的 (key, 標題, 單位, 取值函式) 形狀。
# group_car 期間與 TTM scope 另存於列（group_car_period／ttm_scope），由 render 標註。
def _fh_ttm(rec: dict) -> float | None:
    t = rec.get("ttm") or {}
    key = "net_income_parent" if t.get("scope") == "parent_only" else "net_income"
    return _mn(_ttm(rec, key))


FH_RANK_COLUMNS: list[tuple[str, str, str, Callable[[dict], float | None]]] = [
    ("net_revenue", "淨收益", "百萬元", lambda r: _mn(_value(r, "net_revenue"))),
    ("roe", "ROE", "%", lambda r: _metric(r, "roe")),
    ("roa", "ROA", "%", lambda r: _metric(r, "roa")),
    ("cost_income_ratio", "成本收入比", "%", lambda r: _metric(r, "cost_income_ratio")),
    ("credit_cost", "信用成本", "%", lambda r: _metric(r, "credit_cost")),
    ("npl_ratio", "逾放比", "%", lambda r: _metric(r, "npl_ratio")),
    ("coverage_ratio", "覆蓋率", "%", lambda r: _metric(r, "coverage_ratio")),
    ("equity_to_assets", "權益／資產", "%", lambda r: _metric(r, "equity_to_assets")),
    ("loan_to_deposit", "放款／存款", "%", lambda r: _metric(r, "loan_to_deposit")),
    ("group_car", "集團 CAR", "%", lambda r: _metric(r, "group_car")),
    ("ttm_net_income", "TTM 淨利", "百萬元", _fh_ttm),
]
FH_NOTE = ("金控 H1 指標未年化；TTM 為 FY＋本期 H1－上年同期 H1，其中 FY 為 IFRS 4、H1 為 IFRS 17（混用），"
           "數字不可直接與 FY 比較。集團 CAR 為最新可得期，期間見括號。")
FH_IFRS17_NOTE = "FY 為 IFRS 4、H1 為 IFRS 17"


def _is_fh(r: dict) -> bool:
    return r.get("schema") == "fh" or r.get("group") == "fh"


def _fh_row(r: dict, base: dict) -> dict:
    src = (((r.get("metrics") or {}).get("group_car") or {}).get("source") or {}).get("current") or {}
    t = r.get("ttm") or {}
    return {**base, "fs_period": r.get("fs_period"), "basis": r.get("basis"),
            "values": {k: f(r) for k, _, _, f in FH_RANK_COLUMNS},
            "group_car_period": src.get("period"),
            "ttm_scope": t.get("scope"),
            "ttm_label": "歸母" if t.get("scope") == "parent_only" else None,
            "ifrs17_break": bool(r.get("ifrs17_break"))}


def _yoy(cur: float | None, prior: float | None) -> float | None:
    if cur is None or prior is None or prior <= 0:
        return None
    return (cur - prior) / prior * 100


def _r1(r: dict) -> str | None:
    v = _metric(r, "fcf")
    return None if v is None or v >= 0 else f"FCF {_mn(v):,.0f} 百萬元"


def _r2(r: dict) -> str | None:
    ni, cfo = _value(r, "net_income"), _value(r, "cfo")
    if ni is None or cfo is None or ni <= 0 or cfo / ni >= 0.5:
        return None
    return f"CFO／淨利 {cfo / ni:.2f}"


def _below(key: str, limit: float, label: str, unit: str) -> Callable[[dict], str | None]:
    def f(r: dict) -> str | None:
        v = _metric(r, key)
        return None if v is None or v >= limit else f"{label} {v:,.1f}{unit}"
    return f


def _r4(r: dict) -> str | None:
    v = _metric(r, "liabilities_to_assets")
    return None if v is None or v <= 70 else f"負債比率 {v:.1f}%"


def _r6(r: dict) -> str | None:
    y = _yoy(_value(r, "revenue"), _value(r, "revenue", "prior"))
    return None if y is None or y >= -20 else f"營收 YoY {y:.1f}%"


def _r7(r: dict) -> str | None:
    c, p = _metric(r, "gross_margin"), _metric(r, "gross_margin", "prior")
    if c is None or p is None or c - p >= -5:
        return None
    return f"毛利率 {p:.1f}% → {c:.1f}%（{c - p:+.1f} 個百分點）"


def _r8(r: dict) -> str | None:
    hits = []
    for key, label in (("dso", "DSO"), ("dio", "DIO")):
        c, p = _metric(r, key), _metric(r, key, "prior")
        y = _yoy(c, p)
        if y is not None and y > 30:
            hits.append(f"{label} {p:.0f} → {c:.0f} 天（{y:+.0f}%）")
    return "；".join(hits) or None


def _q1(r: dict) -> str | None:
    hits = []
    c = r.get("checks")
    if c is not None and (c["failed"] > 0 or c["none"] > 0):
        hits.append(f"勾稽未全過（失敗 {c['failed']}、無法勾稽 {c['none']}）")
    t = r.get("ttm")
    if t is not None and t.get("status") == "unavailable":
        hits.append(f"TTM 不可用：{t.get('reason') or '未記原因'}")
    return "；".join(hits) or None


# 紅旗規則表（單一枚舉點）：(id, 規則說明, 判定函式 → 命中時回數值說明，否則 None)
FLAG_RULES: list[tuple[str, str, Callable[[dict], str | None]]] = [
    ("R1", "FCF < 0", _r1),
    ("R2", "淨利 > 0 且 CFO／淨利 < 0.5", _r2),
    ("R3", "流動比率 < 100%", _below("current_ratio", 100, "流動比率", "%")),
    ("R4", "負債比率 > 70%", _r4),
    ("R5", "利息保障倍數 < 3", _below("interest_coverage", 3, "利息保障倍數", "x")),
    ("R6", "營收較上年同期 < -20%", _r6),
    ("R7", "毛利率較上年同期下降 > 5 個百分點", _r7),
    ("R8", "DSO 或 DIO 較上年同期增加 > 30%", _r8),
    ("Q1", "資料品質：勾稽未全過或 TTM 不可用", _q1),
]


def build_summary(records: list[dict]) -> dict[str, Any]:
    rows, flags, unsupported, failed, fh_rows = [], [], [], [], []
    for r in records:
        base = {"ticker": r["ticker"], "company_name": r.get("company_name"), "group": r.get("group")}
        if r.get("status") == "error":
            failed.append({**base, "error": r.get("error")})
            continue
        if _is_fh(r):
            fh_rows.append(_fh_row(r, base))
            continue
        if r.get("group") in UNSUPPORTED_GROUPS:
            unsupported.append({**base, "reason": UNSUPPORTED_GROUPS[r["group"]]})
            continue
        rows.append({**base, "fs_period": r.get("fs_period"), "basis": r.get("basis"),
                     "values": {k: f(r) for k, _, _, f in RANK_COLUMNS}})
        for rid, desc, fn in FLAG_RULES:
            detail = fn(r)
            if detail is not None:
                flags.append({**base, "rule": rid, "rule_desc": desc, "detail": detail})
    return {
        "columns": [{"key": k, "title": t, "unit": u} for k, t, u, _ in RANK_COLUMNS],
        "rules": [{"id": i, "desc": d} for i, d, _ in FLAG_RULES],
        "rows": rows, "flags": flags, "unsupported": unsupported, "failed": failed,
        "fh_ranking": fh_rows,
        "fh_columns": [{"key": k, "title": t, "unit": u} for k, t, u, _ in FH_RANK_COLUMNS],
    }


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return ""
    return f"{v:,.0f}" if unit in ("百萬元", "天") else f"{v:,.1f}"


def _fh_cell(row: dict, c: dict) -> str:
    v = row["values"][c["key"]]
    if v is None:
        txt = "不可得"
    else:
        txt = f"{v:,.0f}" if c["unit"] == "百萬元" else f"{v:,.2f}"  # 金控比率 2 位（逾放比等 0.1 級數）
    if c["key"] == "group_car" and v is not None and row.get("group_car_period"):
        txt += f"（{row['group_car_period']}）"
    if c["key"] == "ttm_net_income" and v is not None and row.get("ttm_label"):
        txt += f"（{row['ttm_label']}）"
    return txt


def _fh_md(s: dict) -> list[str]:
    cols = s["fh_columns"]
    L = ["", "## 金控", "", FH_NOTE, "",
         "| 代號 | 公司 | 期間 | " + " | ".join(f"{c['title']}（{c['unit']}）" for c in cols) + " | IFRS 17 |",
         "|---|---|---|" + "---:|" * len(cols) + "---|"]
    for r in s["fh_ranking"]:
        mark = "斷層" if r["ifrs17_break"] else "否"
        L.append(f"| {r['ticker']} | {r['company_name'] or ''} | {r['fs_period'] or ''} | "
                 + " | ".join(_fh_cell(r, c) for c in cols) + f" | {mark} |")
    L += [f"- {r['ticker']} {r['company_name'] or ''}：{FH_IFRS17_NOTE}" for r in s["fh_ranking"] if r["ifrs17_break"]]
    return L


def render_md(s: dict) -> str:
    cols = s["columns"]
    L = ["# tw-equity 跨公司摘要", "",
         f"排名 {len(s['rows'])} 家；紅旗 {len(s['flags'])} 筆；未支援 {len(s['unsupported'])} 家；失敗 {len(s['failed'])} 家。",
         "金額單位百萬元（新台幣）；期間欄為各家財報期間（H1＝半年報本期，FY＝年度）。", "",
         "## 排名表", "",
         "| 代號 | 公司 | 期間 | " + " | ".join(f"{c['title']}（{c['unit']}）" for c in cols) + " |",
         "|---|---|---|" + "---:|" * len(cols)]
    for r in s["rows"]:
        L.append(f"| {r['ticker']} | {r['company_name'] or ''} | {r['fs_period'] or ''} | "
                 + " | ".join(_fmt(r["values"][c["key"]], c["unit"]) for c in cols) + " |")
    L += ["", "## 紅旗清單", "", "| 代號 | 公司 | 規則 | 說明 | 數值 |", "|---|---|---|---|---|"]
    L += [f"| {f['ticker']} | {f['company_name'] or ''} | {f['rule']} | {f['rule_desc']} | {f['detail']} |"
          for f in s["flags"]]
    if s.get("fh_ranking"):
        L += _fh_md(s)
    L += ["", "## 未支援", ""] + [f"- {u['ticker']} {u['company_name'] or ''}：{u['reason']}" for u in s["unsupported"]]
    L += ["", "## 失敗", ""] + [f"- {x['ticker']} {x['company_name'] or ''}：{x['error']}" for x in s["failed"]]
    return "\n".join(L) + "\n"


_HTML = """<title>台股跨公司財報摘要</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
/* 版面：頁首摘要 → 紅旗（依規則篩選）→ 可排序排名表 → 未支援／失敗 */
:root {
  --bg: #f4f6f5; --surface: #ffffff; --fg: #1b2420; --muted: #5d6a63; --line: #dbe1dd;
  --accent: #1d6b58; --accent-soft: #e2efea; --neg: #b3261e; --flag: #9a4f00; --flag-soft: #fbefe2;
  --font-body: "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif;
  --font-data: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #121715; --surface: #1a211e; --fg: #e3e9e6; --muted: #98a59e; --line: #2d3732;
  --accent: #6cc4aa; --accent-soft: #1f332c; --neg: #f08b82; --flag: #f0b46e; --flag-soft: #33281b; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #121715; --surface: #1a211e; --fg: #e3e9e6; --muted: #98a59e; --line: #2d3732;
  --accent: #6cc4aa; --accent-soft: #1f332c; --neg: #f08b82; --flag: #f0b46e; --flag-soft: #33281b; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font: 14px/1.55 var(--font-body); margin: 0; }
main { max-width: 1280px; margin: 0 auto; padding: 24px 16px 48px; display: grid; gap: 28px; }
h1 { font-size: 1.5rem; margin: 0; text-wrap: balance; }
h2 { font-size: 1.05rem; margin: 0 0 10px; }
.sub { color: var(--muted); margin: 4px 0 0; }
.stats { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-top: 12px; }
.stats b { font: 600 1.25rem var(--font-data); color: var(--accent); margin-right: 4px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { font: inherit; font-size: 12px; border: 1px solid var(--line); background: var(--surface); color: var(--fg);
  border-radius: 999px; padding: 3px 10px; cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--flag-soft); border-color: var(--flag); color: var(--flag); }
.chip:focus-visible, th button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.scroll { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
td.num { text-align: right; font-family: var(--font-data); font-size: 13px; }
td.neg { color: var(--neg); }
th { position: sticky; top: 0; background: var(--surface); font-size: 12px; color: var(--muted); font-weight: 600; }
th button { all: unset; cursor: pointer; }
th .u { display: block; font-weight: 400; font-size: 11px; }
tr:last-child td { border-bottom: 0; }
.rule { font: 600 12px var(--font-data); color: var(--flag); background: var(--flag-soft); border-radius: 4px; padding: 1px 6px; }
.tag { font-size: 11px; color: var(--muted); }
ul { margin: 0; padding-left: 18px; }
</style>
<main>
  <header>
    <h1>台股跨公司財報摘要</h1>
    <p class="sub">本地解析三表帳本與年報 FY 損益表，數字皆由程式計算。金額單位：新台幣百萬元。</p>
    <div class="stats" id="stats"></div>
  </header>
  <section>
    <h2>紅旗清單</h2>
    <div class="chips" id="chips"></div>
    <div class="scroll"><table><thead><tr><th>代號</th><th>公司</th><th>規則</th><th>說明</th><th>數值</th></tr></thead>
      <tbody id="flags"></tbody></table></div>
  </section>
  <section>
    <h2>排名表</h2>
    <div class="scroll"><table><thead><tr id="rank-head"></tr></thead><tbody id="rank-body"></tbody></table></div>
  </section>
  <section><h2>未支援</h2><ul id="unsupported"></ul></section>
  <section><h2>失敗</h2><ul id="failed"></ul></section>
</main>
<script>
const S = __DATA__;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (v, u) => v == null ? "" : v.toLocaleString("zh-TW", {maximumFractionDigits: (u === "百萬元" || u === "天") ? 0 : 1,
  minimumFractionDigits: (u === "百萬元" || u === "天") ? 0 : 1});
document.getElementById("stats").innerHTML = [["排名", S.rows.length, "家"], ["紅旗", S.flags.length, "筆"],
  ["未支援", S.unsupported.length, "家"], ["失敗", S.failed.length, "家"]]
  .map(([k, n, u]) => `<span><b>${n}</b>${u} ${k}</span>`).join("");
let active = null;
function renderFlags() {
  document.getElementById("chips").innerHTML = [`<button class="chip" id="chip-all" aria-pressed="${active === null}">全部</button>`]
    .concat(S.rules.map(r => {
      const n = S.flags.filter(f => f.rule === r.id).length;
      return `<button class="chip" id="chip-${r.id}" data-rule="${r.id}" aria-pressed="${active === r.id}" title="${esc(r.desc)}">${r.id} ${esc(r.desc)}（${n}）</button>`;
    })).join("");
  const list = S.flags.filter(f => active === null || f.rule === active);
  document.getElementById("flags").innerHTML = list.map(f => `<tr><td>${esc(f.ticker)}</td><td>${esc(f.company_name)}</td>
    <td><span class="rule">${esc(f.rule)}</span></td><td>${esc(f.rule_desc)}</td><td>${esc(f.detail)}</td></tr>`).join("")
    || `<tr><td colspan="5" class="tag">此規則無命中</td></tr>`;
}
document.getElementById("chips").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  active = b.dataset.rule ?? null; renderFlags();
});
let sortKey = "revenue", sortDir = -1;
function renderRank() {
  document.getElementById("rank-head").innerHTML = `<th>代號</th><th>公司</th><th>期間</th>` + S.columns.map(c =>
    `<th><button data-key="${c.key}">${esc(c.title)}${sortKey === c.key ? (sortDir < 0 ? " ▼" : " ▲") : ""}<span class="u">${esc(c.unit)}</span></button></th>`).join("");
  const rows = [...S.rows].sort((a, b) => {
    const x = a.values[sortKey], y = b.values[sortKey];
    if (x == null) return 1; if (y == null) return -1; return (x - y) * sortDir;
  });
  document.getElementById("rank-body").innerHTML = rows.map(r => `<tr><td>${esc(r.ticker)}</td><td>${esc(r.company_name)}</td>
    <td class="tag">${esc(r.fs_period)}</td>` + S.columns.map(c => { const v = r.values[c.key];
      return `<td class="num${v != null && v < 0 ? " neg" : ""}">${fmt(v, c.unit)}</td>`; }).join("") + `</tr>`).join("");
}
document.getElementById("rank-head").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  if (sortKey === b.dataset.key) sortDir = -sortDir; else { sortKey = b.dataset.key; sortDir = -1; }
  renderRank();
});
document.getElementById("unsupported").innerHTML = S.unsupported.map(u => `<li>${esc(u.ticker)} ${esc(u.company_name)}：${esc(u.reason)}</li>`).join("") || "<li>無</li>";
document.getElementById("failed").innerHTML = S.failed.map(x => `<li>${esc(x.ticker)} ${esc(x.company_name)}：${esc(x.error)}</li>`).join("") || "<li>無</li>";
renderFlags(); renderRank();
</script>
"""


_FH_HTML_SECTION = """  <section id="fh-section">
    <h2>金控</h2>
    <p class="sub">__NOTE__</p>
    <div class="scroll"><table><thead><tr id="fh-head"></tr></thead><tbody id="fh-body"></tbody></table></div>
    <ul id="fh-notes"></ul>
  </section>
"""
_FH_HTML_JS = """const FH_NOTE = __IFRS17__;
document.getElementById("fh-head").innerHTML = `<th>代號</th><th>公司</th><th>期間</th>` + S.fh_columns.map(c =>
  `<th>${esc(c.title)}<span class="u">${esc(c.unit)}</span></th>`).join("") + `<th>IFRS 17</th>`;
document.getElementById("fh-body").innerHTML = S.fh_ranking.map(r => `<tr><td>${esc(r.ticker)}</td><td>${esc(r.company_name)}</td>
  <td class="tag">${esc(r.fs_period)}</td>` + S.fh_columns.map(c => { const v = r.values[c.key];
    if (v == null) return `<td class="num tag">不可得</td>`;
    let t = c.unit === "百萬元" ? fmt(v, c.unit) : v.toLocaleString("zh-TW", {minimumFractionDigits: 2, maximumFractionDigits: 2});
    if (c.key === "group_car" && r.group_car_period) t += `（${esc(r.group_car_period)}）`;
    if (c.key === "ttm_net_income" && r.ttm_label) t += `（${esc(r.ttm_label)}）`;
    return `<td class="num${v < 0 ? " neg" : ""}">${t}</td>`; }).join("") + `<td class="tag">${r.ifrs17_break ? "斷層" : "否"}</td></tr>`).join("");
document.getElementById("fh-notes").innerHTML = S.fh_ranking.filter(r => r.ifrs17_break)
  .map(r => `<li>${esc(r.ticker)} ${esc(r.company_name)}：${esc(FH_NOTE)}</li>`).join("");
"""


def render_html(s: dict) -> str:
    if not s.get("fh_ranking"):  # 無金控 → 與本功能前逐字相同（資料也不帶 fh_* 鍵）
        data = json.dumps({k: v for k, v in s.items() if not k.startswith("fh_")}, ensure_ascii=False).replace("</", "<\\/")
        return _HTML.replace("__DATA__", data)
    data = json.dumps(s, ensure_ascii=False).replace("</", "<\\/")
    html = _HTML.replace("__DATA__", data)
    html = html.replace("  <section><h2>未支援</h2>",
                        _FH_HTML_SECTION.replace("__NOTE__", FH_NOTE) + "  <section><h2>未支援</h2>", 1)
    return html.replace("renderFlags(); renderRank();",
                        _FH_HTML_JS.replace("__IFRS17__", json.dumps(FH_IFRS17_NOTE, ensure_ascii=False))
                        + "renderFlags(); renderRank();", 1)


def write_summary(summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_md(summary), encoding="utf-8")
    (out_dir / "summary.html").write_text(render_html(summary), encoding="utf-8")
