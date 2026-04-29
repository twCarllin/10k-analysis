import json
from datetime import datetime
from pathlib import Path

import markdown
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from weasyprint import HTML

BASE_DIR = Path(__file__).resolve().parent.parent

_REPORT_CSS = (BASE_DIR / "runtime" / "report.css").read_text()
_FONT_DIR = BASE_DIR / "runtime" / "fonts"

def _build_pdf_css() -> str:
    """Build CSS with @font-face for embedded Chinese fonts."""
    font_regular = _FONT_DIR / "NotoSansTC-Regular.otf"
    font_bold = _FONT_DIR / "NotoSansTC-Bold.otf"
    # Also support .ttf variant
    if not font_regular.exists():
        font_regular = _FONT_DIR / "NotoSansTC-Regular.ttf"
    font_css = ""
    if font_regular.exists():
        font_css += f"""
@font-face {{
    font-family: "Noto Sans TC";
    src: url("file://{font_regular.resolve()}");
    font-weight: normal;
}}
"""
    if font_bold.exists():
        font_css += f"""
@font-face {{
    font-family: "Noto Sans TC";
    src: url("file://{font_bold.resolve()}");
    font-weight: bold;
}}
"""
    # Replace body font-family to prioritize Noto Sans TC
    css = _REPORT_CSS.replace(
        '"Helvetica Neue", Arial, "PingFang TC", "Microsoft JhengHei", sans-serif',
        '"Noto Sans TC", "Helvetica Neue", Arial, sans-serif',
    )
    return font_css + css

PDF_CSS = _build_pdf_css()

# Chart style
rcParams.update({
    "font.family": ["Noto Sans TC", "Heiti TC", "PingFang HK", "Arial Unicode MS", "sans-serif"],
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
})


TONE_MAP = {
    # 激烈用詞 → 中性
    "惡化": "下降",
    "暴增": "快速增加",
    "暴跌": "快速下降",
    "崩盤": "下滑",
    "崩跌": "下滑",
    "警訊": "需留意",
    "危機": "需留意",
    "嚴重": "明顯",
    "大幅": "",  # 完全移除
    # metric 名稱（XBRL concept 格式 → 人類可讀）
    "OperatingIncomeLoss": "Operating Income",  # 必須在 OperatingIncome 之前
    "OperatingIncome": "Operating Income",
    "GrossProfit": "Gross Profit",
    "NetIncomeLoss": "Net Income",  # 必須在 NetIncome 之前
    "NetIncome": "Net Income",
    "OperatingCashFlow": "Operating Cash Flow",
    "CapEx": "Capital Expenditure",
    "LongTermDebt": "Long-term Debt",
    "SharesOutstanding": "Shares Outstanding",
}


def tone_filter(text):
    """套用於 LLM 動態輸出文字，不套用於寫死 markdown 結構或 enum value。"""
    if not isinstance(text, str):
        return text
    for old, new in TONE_MAP.items():
        text = text.replace(old, new)
    return text


def _fmt_val(val, is_pct=False):
    """Format a number for display."""
    if val is None:
        return "—"
    if is_pct:
        return f"{val:.1f}%"
    if abs(val) >= 1e9:
        return f"${val / 1e9:,.1f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:,.0f}M"
    return f"{val:,.0f}"


def _build_financial_tables(fin, filing_type="10-K", quarter=None,
                            current_year=None, xbrl_metrics=None) -> list[str]:
    """Build markdown tables from financial metrics.

    Falls back to raw XBRL metrics for fields the agent doesn't return
    (e.g. OperatingIncome / NetIncome / OCF / CapEx / LongTermDebt /
    SharesOutstanding), so the trend table can be rendered even when
    the financial agent only emits derived ratios.
    """
    lines = []
    metrics = fin.get("metrics", {})
    xbrl_metrics = xbrl_metrics or {}

    all_years = set()
    for rows in list(metrics.values()) + list(xbrl_metrics.values()):
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and r.get("val") is not None:
                    all_years.add(r["year"])
    if not all_years:
        return lines
    years = sorted(all_years)

    year_labels = {}
    for y in years:
        if filing_type == "10-Q" and quarter and current_year and y == current_year:
            year_labels[y] = f"{y} {quarter}"
        else:
            year_labels[y] = str(y)

    lines.append("### 年度趨勢")

    def val_map(key):
        rows = metrics.get(key) or []
        result = {
            r["year"]: r["val"]
            for r in rows
            if isinstance(r, dict) and r.get("val") is not None
        }
        if result:
            return result
        rows = xbrl_metrics.get(key) or []
        return {
            r["year"]: r["val"]
            for r in rows
            if isinstance(r, dict) and r.get("val") is not None
        }

    rev = val_map("Revenue")
    oi = val_map("OperatingIncome")
    ni = val_map("NetIncome")
    ocf = val_map("OperatingCashFlow")
    capex = val_map("CapEx")
    ltd = val_map("LongTermDebt")
    shares = val_map("SharesOutstanding")

    trend_rows = [
        ("營收", rev, "money"),
        ("營業利益", oi, "money"),
        ("淨利", ni, "money"),
        ("營業現金流", ocf, "money"),
        ("資本支出", capex, "money"),
        ("長期負債", ltd, "money"),
        ("流通股數", shares, "shares"),
    ]

    margin_data = {}
    fcf_data = {}
    capex_ratio_data = {}
    for y in years:
        if rev.get(y) and oi.get(y):
            margin_data[y] = oi[y] / rev[y] * 100
        if ocf.get(y) and rev.get(y):
            fcf_val = ocf[y] - (capex.get(y, 0) or 0)
            fcf_data[y] = fcf_val / rev[y] * 100
        if capex.get(y) and rev.get(y):
            capex_ratio_data[y] = capex[y] / rev[y] * 100

    rev_yoy = {}
    rev_rows = metrics.get("Revenue", [])
    for r in rev_rows:
        if isinstance(r, dict) and r.get("yoy_pct") is not None:
            rev_yoy[r["year"]] = r["yoy_pct"]
    for y in years:
        if y not in rev_yoy and rev.get(y) and rev.get(y - 1):
            rev_yoy[y] = (rev[y] - rev[y - 1]) / rev[y - 1] * 100

    ni_yoy = {}
    for y in years:
        if ni.get(y) and ni.get(y - 1):
            ni_yoy[y] = (ni[y] - ni[y - 1]) / ni[y - 1] * 100

    net_margin = {}
    for y in years:
        if ni.get(y) and rev.get(y):
            net_margin[y] = ni[y] / rev[y] * 100

    trend_rows += [
        ("營收 YoY", rev_yoy, "pct_change"),
        ("淨利 YoY", ni_yoy, "pct_change"),
        ("營業利益率", margin_data, "pct"),
        ("淨利率", net_margin, "pct"),
        ("FCF 轉換率", fcf_data, "pct"),
        ("CapEx/營收", capex_ratio_data, "pct"),
    ]

    header = "| 指標 | " + " | ".join(year_labels[y] for y in years) + " |"
    sep = "|------|" + "|".join("------:" for _ in years) + "|"
    lines.append(header)
    lines.append(sep)

    for label, data, fmt in trend_rows:
        cells = []
        for y in years:
            v = data.get(y)
            if v is None:
                cells.append("—")
            elif fmt == "money":
                cells.append(_fmt_val(v))
            elif fmt == "shares":
                if v >= 1e6:
                    cells.append(f"{v / 1e6:.1f}M")
                else:
                    cells.append(f"{v:,.0f}")
            elif fmt == "pct":
                cells.append(f"{v:.1f}%")
            elif fmt == "pct_change":
                cells.append(f"{v:+.1f}%")
            else:
                cells.append(str(v))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines.append("")

    # Capital allocation
    cap_alloc = fin.get("capital_allocation_order", [])
    if cap_alloc:
        lines.append("### 資本配置優先序")
        for i, item in enumerate(cap_alloc, 1):
            lines.append(f"{i}. {item}")
        lines.append("")

    return lines


def _build_quarterly_chart(quarterly: list[dict], out_dir: Path) -> str | None:
    """Generate quarterly trend line chart. Returns image filename or None."""
    if not quarterly or len(quarterly) < 2:
        return None

    labels = [q["quarter"] for q in quarterly]
    rev_growth = [q.get("rev_growth_yoy") for q in quarterly]
    op_margin = [q.get("op_margin") for q in quarterly]
    net_margin = [q.get("net_margin") for q in quarterly]

    fig, ax = plt.subplots(figsize=(5.5, 2.8))

    x = range(len(labels))
    if any(v is not None for v in rev_growth):
        vals = [v if v is not None else float("nan") for v in rev_growth]
        ax.plot(x, vals, "o-", color="#2980b9", linewidth=2, markersize=5, label="營收成長率 YoY")
    if any(v is not None for v in op_margin):
        vals = [v if v is not None else float("nan") for v in op_margin]
        ax.plot(x, vals, "s-", color="#e67e22", linewidth=2, markersize=5, label="營業利益率")
    if any(v is not None for v in net_margin):
        vals = [v if v is not None else float("nan") for v in net_margin]
        ax.plot(x, vals, "^-", color="#27ae60", linewidth=2, markersize=5, label="淨利率")

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("%")
    ax.legend(loc="upper left", fontsize=7, framealpha=0.8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    chart_name = "quarterly_trend.png"
    chart_path = out_dir / chart_name
    fig.savefig(str(chart_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return chart_name


def save_report(ticker, results, eval_results, synthesis, quarterly=None,
                filing_type="10-K", quarter=None, xbrl_metrics=None,
                prior_year=None) -> Path:
    out_dir = BASE_DIR / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    insight = synthesis.get("insight", {})
    comparator = synthesis.get("comparator", {})
    completeness = synthesis.get("completeness", {})
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    critical_gaps = completeness.get("critical_gaps", [])
    gap_flag = ""

    filing_label = filing_type
    if quarter:
        filing_label += f" {quarter}"
    lines = [
        f"# {ticker} {filing_label} 投資研究報告",
        f"產出時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}{gap_flag}",
        "",
    ]

    # ── Rerate signal (rendered later, after bear case) ──
    rerate = results.get("rerate_signal", {})

    # ── 公司定位 ──
    biz = results.get("business", {})
    if biz.get("company_positioning"):
        lines.append("## 公司定位")
        lines.append(biz["company_positioning"])
        lines.append("")

    # ── Competitor Landscape ──
    comp = results.get("competitor_mapping", {})
    if comp.get("named_competitors"):
        comp_mode = comp.get("mode", "normal")
        if comp_mode == "q1_vs_10k":
            year_label = str(prior_year) if prior_year else ""
            lines.append(f"## Competitor Landscape（基準：{year_label} 10-K）")
        else:
            lines.append("## Competitor Landscape")
        yoy_zh = {"new": "新增", "removed": "移除", "unchanged": "持平", "baseline": "基準"}
        lines.append("| 競爭對手 | Ticker | 市場 | 變化 |")
        lines.append("|---------|--------|------|------|")
        for c in comp["named_competitors"]:
            name = c.get("name", "")
            ticker_val = c.get("ticker", "")
            markets = "、".join(c.get("markets", []))
            status_zh = yoy_zh.get(c.get("yoy_status", ""), c.get("yoy_status", ""))
            lines.append(f"| {name} | {ticker_val} | {markets} | {status_zh} |")
        lines.append("")
        position_zh = {"leader": "領先", "challenger": "挑戰者", "niche": "利基", "follower": "跟隨"}
        pos = position_zh.get(comp.get("market_position", ""), comp.get("market_position", ""))
        evidence = comp.get("market_position_evidence", "")
        lines.append(f"**市場定位**：{pos}")
        if evidence:
            lines.append(f"> {evidence}")
        lines.append("")
        quality_zh = {"high": "高", "medium": "中", "low": "低"}
        q = quality_zh.get(comp.get("disclosure_quality", ""), comp.get("disclosure_quality", ""))
        rationale = comp.get("disclosure_rationale", "")
        lines.append(f"**揭露品質**：{q}（{rationale}）")
        lines.append("")
        if comp_mode == "q1_vs_10k" and comp.get("baseline_note"):
            lines.append(f"*{comp['baseline_note']}*")
            lines.append("")

    # ── 成長敘事 ──
    if biz.get("growth_narrative"):
        lines.append("## 成長敘事")
        lines.append(biz["growth_narrative"])
        lines.append("")

    # ── 終端市場組合 ──
    end_markets = biz.get("end_market_mix", [])
    if end_markets:
        lines.append("### 終端市場組合")
        lines.append("| 市場 | 趨勢 |")
        lines.append("|------|------|")
        trend_zh = {"growing": "成長", "stable": "穩定", "declining": "下滑"}
        for em in end_markets:
            t = trend_zh.get(em.get("trend", ""), em.get("trend", ""))
            lines.append(f"| {em.get('market', '')} | {t} |")
        lines.append("")

    # ── 供應鏈分析 ──
    sc = results.get("supply_chain")
    if sc and not sc.get("insufficient_data", False):
        lines.append("## 供應鏈分析")
        lines.append("")
        risk_zh = {"high": "高", "medium": "中", "low": "低"}
        trend_zh_sc = {"improving": "改善", "stable": "持平", "deteriorating": "惡化"}
        overall_risk = risk_zh.get(sc.get("overall_risk_level", ""), sc.get("overall_risk_level", ""))
        trend_sc = trend_zh_sc.get(sc.get("trend", ""), sc.get("trend", ""))
        lines.append(f"**整體風險：{overall_risk}　趨勢：{trend_sc}**")
        lines.append("")

        # 原物料
        raw_materials = sc.get("raw_materials", [])
        if raw_materials:
            lines.append("### 原物料")
            lines.append("| 原物料 | 用途 | 集中風險 | 地緣風險 |")
            lines.append("|--------|------|----------|----------|")
            conc_zh = {"high": "高", "medium": "中", "low": "低"}
            for rm in raw_materials:
                conc = conc_zh.get(rm.get("source_concentration", ""), rm.get("source_concentration", ""))
                lines.append(f"| {rm.get('material', '')} | {rm.get('usage', '')} | {conc} | {rm.get('geographic_risk', '')} |")
            lines.append("")

        # 主要風險
        sc_risks = sc.get("supply_chain_risks", [])
        if sc_risks:
            lines.append("### 主要風險")
            cat_zh = {
                "concentration": "集中",
                "geopolitical": "地緣",
                "price": "價格",
                "shortage": "短缺",
                "logistics": "物流",
                "regulatory": "法規",
            }
            yoy_zh = {"new": "新增", "escalated": "升級", "stable": "持平", "resolved": "已解"}
            for risk in sc_risks:
                cat = cat_zh.get(risk.get("category", ""), risk.get("category", ""))
                yoy = yoy_zh.get(risk.get("yoy_status", ""), risk.get("yoy_status", ""))
                lines.append(f"- [{cat} / {yoy}] {risk.get('title', '')}：{tone_filter(risk.get('summary', ''))}")
            lines.append("")

        # 跨期變化
        yoy = sc.get("yoy_changes", {})
        improvements = yoy.get("improvements", [])
        deteriorations = yoy.get("deteriorations", [])
        if improvements or deteriorations:
            lines.append("### 跨期變化")
            lines.append("**改善訊號**")
            if improvements:
                for item in improvements:
                    lines.append(f"- {tone_filter(item)}")
            else:
                lines.append("- —")
            lines.append("")
            lines.append("**惡化訊號**")
            if deteriorations:
                for item in deteriorations:
                    lines.append(f"- {tone_filter(item)}")
            else:
                lines.append("- —")
            lines.append("")

        # MD&A 實際影響
        mdna_impact = sc.get("mdna_impact", {})
        impact_desc = mdna_impact.get("impact_description", "") if mdna_impact else ""
        if impact_desc:
            outlook_zh = {"conservative": "保守", "neutral": "中性", "optimistic": "樂觀"}
            mgmt_out = outlook_zh.get(mdna_impact.get("mgmt_outlook", ""), mdna_impact.get("mgmt_outlook", ""))
            lines.append("### MD&A 實際影響")
            lines.append(f"{tone_filter(impact_desc)}（管理層展望：{mgmt_out}）")
            lines.append("")

        # 採購承諾（僅 found == true 時顯示）
        pc = sc.get("purchase_commitments", {})
        if pc.get("found", False):
            lines.append("### 採購承諾")
            total_desc = pc.get("total_commitment_description", "")
            pct = pc.get("commitment_to_revenue_pct", "")
            if pct:
                lines.append(f"{total_desc}（佔 Revenue 約 {pct}）")
            else:
                lines.append(total_desc)
            lines.append("")

    # ── 多頭論點 ──
    lines.append("## 多頭論點（Bull Case）")
    for item in insight.get("bull_case", []):
        lines.append(f"- **{tone_filter(item.get('point', ''))}**")
        if item.get("evidence"):
            lines.append(f"  - 論述：{tone_filter(item['evidence'])}")
    lines.append("")

    # ── 空頭論點 ──
    lines.append("## 空頭論點（Bear Case）")
    for item in insight.get("bear_case", []):
        lines.append(f"- **{tone_filter(item.get('point', ''))}**")
        if item.get("evidence"):
            lines.append(f"  - 論述：{tone_filter(item['evidence'])}")
    lines.append("")

    # ── 風險清單 ──
    risk_result = results.get("risk", {})
    risks = risk_result.get("risks", [])
    if risks and not risk_result.get("insufficient_data", False):
        lines.append("## 風險清單")
        lines.append("")

        # 排序：high → medium → low
        sorted_risks = sorted(
            risks,
            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("importance"), 2)
        )
        for r in sorted_risks:
            icon = {"high": "●", "medium": "○", "low": "·"}.get(r.get("importance"), "·")
            title = r.get("title", "")
            desc = tone_filter(r.get("description", ""))
            lines.append(f"{icon} **{title}**")
            lines.append(f"  {desc}")
            lines.append("")

        # top_3 子段
        top_3 = risk_result.get("top_3", [])
        if top_3:
            lines.append("### 前三大風險")
            for i, t in enumerate(top_3, 1):
                t_title = t.get("title", "")
                t_rationale = tone_filter(t.get("rationale", ""))
                lines.append(f"{i}. **{t_title}**：{t_rationale}")
            lines.append("")

        # delta_summary
        delta = risk_result.get("delta_summary")
        if delta:
            lines.append(f"_{tone_filter(delta)}_")
            lines.append("")

    # ── 評價趨勢判斷 ──
    if rerate and "error" not in rerate:
        lines.append("## 評價趨勢判斷")
        lines.append("")
        rerate_items = [
            ("structure_changing", "營收結構在變"),
            ("quality_changing", "營收品質在變"),
            ("narrative_changing", "敘事在變"),
        ]
        if filing_type == "10-Q":
            rerate_items = [it for it in rerate_items
                            if it[0] != "structure_changing"]
        for key, label in rerate_items:
            cond = rerate.get(key, {})
            result = cond.get("result", False)
            emerging = cond.get("emerging", False)
            if result:
                icon = "🟢"
            elif emerging:
                icon = "🟡"
            else:
                icon = "🔴"
            rationale = cond.get("rationale", "")
            lines.append(f"### {icon} {label}")
            if rationale:
                lines.append(f"{rationale}")
            lines.append("")

    # ── 關鍵追蹤指標 ──
    lines.append("## 關鍵追蹤指標（未來兩季）")
    for item in insight.get("key_monitorables", []):
        lines.append(f"- {item}")
    lines.append("")

    # ── 10K 洞察 ──
    if insight.get("information_edge"):
        lines.append("## 10K 洞察（Information Edge）")
        for item in insight.get("information_edge", []):
            if isinstance(item, dict):
                lines.append(f"- **{item.get('signal', '')}**")
                if item.get("source"):
                    lines.append(f"  - 來源：{item['source']}")
            else:
                lines.append(f"- {item}")
        lines.append("")

    # ── 財務數據 ──
    fin = results.get("financial", {})
    lines.append("## 財務數據")
    # Extract current year from metrics for column labeling
    _all_yrs = set()
    for _rows in fin.get("metrics", {}).values():
        if isinstance(_rows, list):
            for _r in _rows:
                if _r.get("val") is not None:
                    _all_yrs.add(_r["year"])
    _cur_year = max(_all_yrs) if _all_yrs else None
    lines.extend(_build_financial_tables(fin, filing_type=filing_type,
                                         quarter=quarter, current_year=_cur_year,
                                         xbrl_metrics=xbrl_metrics))

    # ── 季度趨勢 ──
    if quarterly:
        chart_name = _build_quarterly_chart(quarterly or [], out_dir)
        lines.append("### 季度趨勢")
        if chart_name:
            lines.append(f"![季度趨勢]({chart_name})")
            lines.append("")
        # Quarterly data table
        if len(quarterly) >= 2:
            lines.append("| 季度 | 營收 | 營收 YoY | 營業利益率 | 淨利率 |")
            lines.append("|------|-----:|------:|------:|------:|")
            for q in quarterly:
                rev_q = _fmt_val(q.get("revenue")) if q.get("revenue") else "—"
                rev_yoy = f"{q['rev_growth_yoy']:+.1f}%" if q.get("rev_growth_yoy") is not None else "—"
                op_m = f"{q['op_margin']:.1f}%" if q.get("op_margin") is not None else "—"
                ni_m = f"{q['net_margin']:.1f}%" if q.get("net_margin") is not None else "—"
                lines.append(f"| {q.get('quarter', '')} | {rev_q} | {rev_yoy} | {op_m} | {ni_m} |")
            lines.append("")

    # ── 財務趨勢摘要 ──
    if fin.get("trend_summary"):
        lines.append("### 趨勢摘要")
        lines.append(tone_filter(fin["trend_summary"]))
        lines.append("")

    if fin.get("quality_flags"):
        lines.append("### 品質警示")
        for flag in fin["quality_flags"]:
            lines.append(f"- {tone_filter(flag)}")
        lines.append("")

    if fin.get("anomalies"):
        lines.append("### 異常值")
        for a in fin["anomalies"]:
            lines.append(
                f"- **{a.get('year', '')} {tone_filter(a.get('metric', ''))}**："
                f"{tone_filter(a.get('note', ''))}"
            )
        lines.append("")

    # ── 競爭壓力（即時訊號，10-Q 全季）──
    if filing_type == "10-Q":
        lines.append("## 競爭壓力（即時訊號）")
        cp_signals = results.get("mdna", {}).get("competitive_pressure_signals", [])
        if cp_signals:
            severity_zh = {"high": "高", "medium": "中", "low": "低"}
            vs_prior_zh = {"intensifying": "加劇", "stable": "持平", "easing": "緩解"}
            for sig in cp_signals:
                sev = severity_zh.get(sig.get("severity", ""), sig.get("severity", ""))
                vs = sig.get("vs_prior_quarter")
                vs_str = vs_prior_zh.get(vs, "—") if vs else "—"
                summary = tone_filter(sig.get("summary_zh") or sig.get("quote", ""))
                lines.append(
                    f'- [{sev}] **{summary}** — {sig.get("market", "")}（vs 上季：{vs_str}）'
                )
                if sig.get("summary_zh") and sig.get("quote"):
                    lines.append(f'  > "{tone_filter(sig["quote"])}"')
        else:
            lines.append("> 本季 MD&A 無明顯競爭壓力新增揭露。")
        lines.append("")

    # ── 跨年度分析 ──
    lines.append("## 跨年度分析")
    mgmt_cred = comparator.get("mgmt_credibility", "N/A")
    qual_trend = comparator.get("quality_trend", "N/A")
    overall = comparator.get("overall_direction", "N/A")
    lines.append("")
    lines.append("| 維度 | 評估 |")
    lines.append("|------|------|")
    lines.append(f"| 管理層可信度 | {mgmt_cred} |")
    lines.append(f"| 品質趨勢 | {qual_trend} |")
    lines.append(f"| 整體方向 | {overall} |")
    lines.append("")
    if comparator.get("mgmt_credibility_reason"):
        lines.append(f"> {tone_filter(comparator['mgmt_credibility_reason'])}")
        lines.append("")

    # ── 不尋常操作 ──
    uo = results.get("unusual_operations", {})
    unusual_items = uo.get("unusual_items", [])
    lines.append("## 不尋常操作")
    if not unusual_items:
        lines.append("> 未發現不尋常操作，財務處理符合一般揭露規範。")
    else:
        if uo.get("summary"):
            lines.append(tone_filter(uo["summary"]))
            lines.append("")
        for item in unusual_items:
            cls_zh = {"industry_norm": "行業常態", "company_specific": "公司特殊",
                      "hybrid": "混合型"}.get(item.get("classification", ""), item.get("classification", ""))
            inv_zh = {"positive": "正面", "neutral": "中性", "negative": "負面"}.get(
                item.get("investor_interpretation", ""), "")
            lines.append(f"### {item.get('name', '')}")
            lines.append(f"- 分類：{cls_zh}（{tone_filter(item.get('classification_rationale', ''))}）")
            lines.append(f"- 描述：{tone_filter(item.get('description', ''))}")
            if item.get("source_quote"):
                lines.append(f"- 原文：*{item['source_quote']}*")
            lines.append(f"- 財務影響：{tone_filter(item.get('financial_impact', ''))}")
            lines.append(f"- 投資者解讀：**{inv_zh}** — {tone_filter(item.get('investor_note', ''))}")
            lines.append("")
    lines.append("")

    # ── 交叉驗證 ──
    if comparator.get("cross_checks"):
        lines.append("## 交叉驗證")
        for cc in comparator["cross_checks"]:
            dims = ", ".join(cc.get("dimensions", []))
            direction = cc.get("direction", "")
            tag = {"positive": "正面", "negative": "負面", "neutral": "中性"}.get(direction, direction)
            lines.append(f"- **[{tag}]**（{dims}）{tone_filter(cc.get('finding', ''))}")
            if cc.get("implication"):
                lines.append(f"  - 影響：{tone_filter(cc['implication'])}")
        lines.append("")

    # ── 術語表（僅 high importance）──
    glossary = results.get("terms_glossary", {})
    high_terms = [t for t in glossary.get("terms", []) if t.get("importance") == "high"]
    if high_terms:
        lines.append("## 附錄：關鍵術語")
        lines.append("| 術語 | 分類 | 說明 |")
        lines.append("|------|------|------|")
        cat_zh = {"financial": "財務", "industry": "行業", "company_defined": "公司自定",
                  "regulatory": "法規"}
        for t in high_terms:
            cat = cat_zh.get(t.get("category", ""), t.get("category", ""))
            lines.append(f"| {t.get('term', '')} | {cat} | {t.get('explanation', '')} |")
        lines.append("")

    # ── 低信心任務 ──
    low_conf = [
        tid for tid, r in results.items()
        if isinstance(r, dict) and r.get("low_confidence")
    ]
    if low_conf:
        lines.append("## 附錄：低信心任務")
        lines.append(f"以下任務因資料不足或品質未達門檻，結果僅供參考：{', '.join(low_conf)}")
        lines.append("")

    md_text = "\n".join(lines)

    # ── Save Markdown ──
    report_md = out_dir / f"{ticker}_{ts}_report.md"
    report_md.write_text(md_text, encoding="utf-8")

    # ── Save PDF ──
    report_pdf = out_dir / f"{ticker}_{ts}_report.pdf"
    # For PDF: replace relative image paths with file:// URI
    pdf_md = md_text
    chart_file = out_dir / "quarterly_trend.png"
    if chart_file.exists():
        pdf_md = pdf_md.replace(
            "(quarterly_trend.png)",
            f"(file://{chart_file.resolve()})",
        )
    html_body = markdown.markdown(pdf_md, extensions=["tables"])
    html_full = (
        f'<html><head><meta charset="utf-8">'
        f'<style>{PDF_CSS}</style></head>'
        f'<body>{html_body}</body></html>'
    )
    HTML(string=html_full, base_url=str(out_dir)).write_pdf(str(report_pdf))

    # ── Save raw JSON ──
    json_path = out_dir / f"{ticker}_{ts}_raw.json"
    json_path.write_text(
        json.dumps(
            {"results": results, "eval": eval_results, "synthesis": synthesis},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{'='*50}")
    print(f"  報告 (MD)：{report_md}")
    print(f"  報告 (PDF)：{report_pdf}")
    print(f"  原始 JSON：{json_path}")
    print(f"{'='*50}")
    return report_md
