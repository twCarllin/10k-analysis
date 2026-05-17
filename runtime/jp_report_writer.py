"""
jp_report_writer.py — Render jp pipeline results into Markdown + PDF.

Public API:
    save_jp_report(...) -> Path   # returns markdown path
"""

import json
from datetime import datetime
from pathlib import Path

import markdown
from weasyprint import HTML

# Import shared helpers from existing report_writer (do not copy-paste)
from report_writer import (
    _build_pdf_css,
    tone_filter,
    _escape_md_cell,
    _format_blockquote,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def _edinet_to_jpx(edinet_code: str) -> str:
    """Resolve EDINET code → jpx_code via ticker_map.

    Used to keep rinji event reports filed under the same company subdir as
    other JP reports. Falls back to the EDINET code itself when ticker_map
    has no row (e.g. funds, asset managers without a 4-digit code).
    """
    if not edinet_code:
        return ""
    try:
        import duckdb
        from jp_data_fetcher import DB_PATH
        if not DB_PATH.exists():
            return edinet_code
        with duckdb.connect(str(DB_PATH)) as con:
            row = con.execute(
                "SELECT jpx_code FROM ticker_map WHERE edinet_code = ?",
                [edinet_code],
            ).fetchone()
        return (row[0] if row and row[0] else edinet_code)
    except Exception:
        return edinet_code


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_jpy(value) -> str:
    """Format a JPY value in 億円 if >= 1e9, else 百万円."""
    if value is None:
        return "—"
    v = float(value)
    if abs(v) >= 1e12:
        return f"¥{v / 1e12:,.2f}兆"
    if abs(v) >= 1e8:
        return f"¥{v / 1e8:,.1f}億"
    if abs(v) >= 1e6:
        return f"¥{v / 1e6:,.0f}百万"
    return f"¥{v:,.0f}"


def _fmt_ratio(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}"


def _fmt_pct(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}%"


def _fmt_employees(value) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}"


def _safe_render(v, indent: int = 0) -> str:
    """Render LLM value (scalar / dict / list) as markdown-friendly text."""
    if v is None or v == "":
        return "（未提供）"
    if isinstance(v, dict):
        lines = []
        for k, val in v.items():
            if isinstance(val, (dict, list)):
                lines.append(f"{'  ' * indent}- **{k}**:")
                lines.append(_safe_render(val, indent + 1))
            else:
                lines.append(f"{'  ' * indent}- **{k}**: {val}")
        return "\n".join(lines)
    if isinstance(v, list):
        return "\n".join(_safe_render(item, indent) for item in v)
    return str(v)


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_business(result: dict) -> str:
    """Render Section 1: 公司概況."""
    if result.get("insufficient_data"):
        return "> 資料不足，無法分析。\n"

    parts = []

    positioning = result.get("company_positioning")
    if positioning:
        parts.append(f"{tone_filter(_safe_render(positioning))}\n")

    segments = result.get("business_segments") or []
    if segments:
        parts.append("### 事業部門")
        parts.append("| 部門 | 描述 | 收入比重 |")
        parts.append("|------|------|--------|")
        for seg in segments:
            name = _escape_md_cell(tone_filter(str(seg.get("name", ""))))
            desc = _escape_md_cell(tone_filter(str(seg.get("description", ""))))
            weight = _escape_md_cell(str(seg.get("revenue_weight", "")))
            parts.append(f"| {name} | {desc} | {weight} |")
        parts.append("")

    end_mix = result.get("end_market_mix") or []
    if end_mix:
        parts.append("### 終端市場")
        for m in end_mix:
            mkt = tone_filter(str(m.get("market", "")))
            pct = str(m.get("pct", ""))
            trend = str(m.get("trend", ""))
            line = f"- **{_escape_md_cell(mkt)}**"
            if pct:
                line += f"：{pct}"
            if trend:
                line += f"（趨勢：{trend}）"
            parts.append(line)
        parts.append("")

    geo_mix = result.get("geographic_mix") or []
    if geo_mix:
        parts.append("### 地域分布")
        for g in geo_mix:
            parts.append(f"- {tone_filter(str(g))}")
        parts.append("")

    subsidiaries = result.get("subsidiaries") or []
    if subsidiaries:
        parts.append("### 連結子会社")
        for s in subsidiaries:
            if isinstance(s, dict):
                name = s.get("name", "")
                role = s.get("role", "")
                parts.append(f"- **{tone_filter(str(name))}**：{tone_filter(str(role))}")
            else:
                parts.append(f"- {tone_filter(str(s))}")
        parts.append("")

    return "\n".join(parts) if parts else "> 無相關資料。\n"


def _render_financial_table(five_year: dict) -> str:
    """Render Section 2: 財務數據（5 年表）."""
    summary = five_year.get("five_year_summary", {})
    if not summary:
        return "> 5 年財務 summary 未能抽取。\n"

    # Collect all fiscal years across all metrics
    all_years: set[str] = set()
    for vals in summary.values():
        if isinstance(vals, dict):
            all_years.update(vals.keys())
    years = sorted(all_years)

    if not years:
        return "> 無年度資料。\n"

    parts = []
    currency = five_year.get("currency", "JPY")
    std = five_year.get("accounting_standard", "JGAAP")
    parts.append(f"> 貨幣單位：{currency}  會計準則：{std}")
    parts.append("")

    # Main metrics table (money metrics)
    money_metrics = [
        ("淨銷售額", "net_sales", _fmt_jpy),
        ("普通利益", "ordinary_income", _fmt_jpy),
        ("淨利益", "net_income", _fmt_jpy),
        ("綜合利益", "comprehensive_income", _fmt_jpy),
        ("純資產", "net_assets", _fmt_jpy),
        ("總資產", "total_assets", _fmt_jpy),
        ("營業現金流", "operating_cash_flow", _fmt_jpy),
    ]

    ratio_metrics = [
        ("每股純益（円）", "eps_yen", _fmt_ratio),
        ("每股純資產（円）", "bps_yen", _fmt_ratio),
        ("ROE (%)", "roe_pct", _fmt_pct),
        ("PER (倍)", "per", _fmt_ratio),
        ("自己資本比率 (%)", "equity_ratio_pct", _fmt_pct),
        ("員工人數", "employees", _fmt_employees),
    ]

    # Build year headers (show only last 4 digits of date for brevity)
    year_labels = [y[:4] for y in years]
    header = "| 指標 | " + " | ".join(year_labels) + " |"
    sep = "|------|" + "|".join("------:" for _ in years) + "|"

    parts.append("### 主要財務指標推移")
    parts.append(header)
    parts.append(sep)

    for label, key, fmt_fn in money_metrics:
        vals = summary.get(key, {})
        cells = [fmt_fn(vals.get(y)) for y in years]
        parts.append(f"| {label} | " + " | ".join(cells) + " |")

    parts.append(header)
    parts.append(sep)

    for label, key, fmt_fn in ratio_metrics:
        vals = summary.get(key, {})
        cells = [fmt_fn(vals.get(y)) for y in years]
        parts.append(f"| {label} | " + " | ".join(cells) + " |")

    parts.append("")
    return "\n".join(parts)


def _render_risk(result: dict) -> str:
    """Render Section 3: 風險敘事重點."""
    if result.get("insufficient_data"):
        return "> 資料不足，無法分析。\n"

    parts = []

    top3 = result.get("top_3") or []
    if top3:
        parts.append("### 前三大風險")
        for i, item in enumerate(top3, 1):
            title = tone_filter(str(item.get("title", "")))
            rationale = tone_filter(str(item.get("rationale", "")))
            parts.append(f"{i}. **{_escape_md_cell(title)}**：{_escape_md_cell(rationale)}")
        parts.append("")

    risks = result.get("risks") or []
    if risks:
        parts.append("### 全部風險條目")
        parts.append("| 風險名稱 | 類別 | 重要性 | 描述 |")
        parts.append("|---------|------|--------|------|")
        for r in risks:
            title = _escape_md_cell(tone_filter(str(r.get("title", ""))))
            category = _escape_md_cell(str(r.get("category", "")))
            importance = _escape_md_cell(str(r.get("importance", "")))
            desc = _escape_md_cell(tone_filter(str(r.get("description", ""))))
            parts.append(f"| {title} | {category} | {importance} | {desc} |")
        parts.append("")

    delta = result.get("delta_summary")
    if delta:
        parts.append("### 年度變化")
        parts.append(tone_filter(str(delta)))
        parts.append("")

    return "\n".join(parts) if parts else "> 無相關資料。\n"


def _render_mdna(result: dict) -> str:
    """Render Section 4: 管理層分析 (MD&A)."""
    if result.get("insufficient_data"):
        return "> 資料不足，無法分析。\n"

    parts = []

    drivers = result.get("drivers") or []
    if drivers:
        parts.append("### 業績驅動因子")
        for d in drivers:
            if isinstance(d, dict):
                factor = tone_filter(str(d.get("factor", "")))
                direction = str(d.get("direction", ""))
                parts.append(f"- **{_escape_md_cell(factor)}**（{direction}）")
            else:
                parts.append(f"- {tone_filter(str(d))}")
        parts.append("")

    outlook = result.get("mgmt_outlook")
    commitment = result.get("commitment_strength")
    if outlook or commitment:
        parts.append("### 管理層展望")
        if outlook:
            parts.append(f"**語氣**：{outlook}")
        if commitment:
            parts.append(f"**承諾強度**：{commitment}")
        parts.append("")

    signals = result.get("forward_signals") or []
    if signals:
        parts.append("### 前瞻訊號")
        for s in signals:
            parts.append(f"- {tone_filter(str(s))}")
        parts.append("")

    return "\n".join(parts) if parts else "> 無相關資料。\n"


def _render_strategy(result: dict) -> str:
    """Render Section 5: 經營方針."""
    if result.get("insufficient_data"):
        return "> 資料不足，無法分析。\n"

    parts = []

    vision = result.get("vision")
    if vision:
        parts.append(f"**願景**：{tone_filter(str(vision))}\n")

    targets = result.get("mid_term_targets") or []
    if targets:
        parts.append("### 中長期目標")
        parts.append("| KPI | 目標值 | 期限 |")
        parts.append("|-----|--------|------|")
        for t in targets:
            kpi = _escape_md_cell(tone_filter(str(t.get("kpi", ""))))
            target_val = _escape_md_cell(str(t.get("target_value") or "—"))
            deadline = _escape_md_cell(str(t.get("deadline") or "—"))
            parts.append(f"| {kpi} | {target_val} | {deadline} |")
        parts.append("")

    challenges = result.get("current_challenges") or []
    if challenges:
        parts.append("### 對處すべき課題")
        for c in challenges:
            parts.append(f"- {tone_filter(str(c))}")
        parts.append("")

    action_items = result.get("action_items") or []
    if action_items:
        parts.append("### 具體行動計畫")
        for a in action_items:
            parts.append(f"- {tone_filter(str(a))}")
        parts.append("")

    return "\n".join(parts) if parts else "> 無相關資料。\n"


def _render_rd(result: dict) -> str:
    """Render Section 6: 研發與策略."""
    if result.get("insufficient_data"):
        return "> 資料不足，無法分析。\n"

    parts = []

    themes = result.get("themes") or []
    if themes:
        parts.append("### 研發主題")
        for t in themes:
            parts.append(f"- {tone_filter(str(t))}")
        parts.append("")

    rd_pct = result.get("rd_expense_pct")
    if rd_pct is not None:
        parts.append(f"**研究開発費占比**：{rd_pct}\n")

    projects = result.get("key_projects") or []
    if projects:
        parts.append("### 重要研究項目")
        for p in projects:
            if isinstance(p, dict):
                name = p.get("name") or p.get("title") or ""
                desc = p.get("description") or p.get("detail") or ""
                line = f"**{tone_filter(str(name))}**：{tone_filter(str(desc))}" if name else tone_filter(str(desc))
                parts.append(f"- {line}")
            else:
                parts.append(f"- {tone_filter(str(p))}")
        parts.append("")

    partnerships = result.get("partnerships") or []
    if partnerships:
        parts.append("### 產業合作")
        for p in partnerships:
            if isinstance(p, dict):
                name = p.get("name") or p.get("partner") or ""
                desc = p.get("description") or p.get("detail") or ""
                line = f"**{tone_filter(str(name))}**：{tone_filter(str(desc))}" if name else tone_filter(str(desc))
                parts.append(f"- {line}")
            else:
                parts.append(f"- {tone_filter(str(p))}")
        parts.append("")

    return "\n".join(parts) if parts else "> 無相關資料。\n"


def _render_going_concern(result: dict) -> str:
    """Render Section 7: 持續經營疑義."""
    if result.get("insufficient_data") or not result.get("has_disclosure"):
        return "> 公司未揭露重大持續經營疑義。\n"

    parts = []
    level = result.get("concern_level", "none")
    parts.append(f"**疑義程度**：{level}\n")

    triggers = result.get("triggers") or []
    if triggers:
        parts.append("### 觸發因素")
        for t in triggers:
            parts.append(f"- {tone_filter(str(t))}")
        parts.append("")

    plan = result.get("remediation_plan")
    if plan:
        parts.append("### 對策")
        parts.append(tone_filter(str(plan)))
        parts.append("")

    return "\n".join(parts)


def _render_tdnet_financial_highlights(events: list[dict]) -> str:
    """Render financial highlights from the most recent TDNET earnings_flash.

    Used as a substitute for Section 2 (5-year table) when no yuho is
    available — 決算短信 only carries current period + prior + annual
    forecast, not a full 5-year history.
    """
    # Filter by the disclosure's deterministic `category` field
    # (from classify_tdnet_title), not the LLM-generated event_category
    # which may return Japanese strings like "決算短信".
    flashes = [
        e for e in events
        if e.get("doc_type") == "tdnet" and e.get("category") == "earnings_flash"
    ]
    if not flashes:
        return "> 無 EDINET 有報且無 TDNET 決算短信揭露；財務數據待文件發布後更新。\n"

    # Most recent flash (events are already sorted by date desc upstream)
    flash = flashes[0]
    result = flash.get("skill_result", {})
    sub_date = flash.get("submitted_at", "")[:10]

    parts = [
        f"> 來源：TDNET 決算短信 ({sub_date})；5 年表待 EDINET 有報發布後補上。",
        "",
    ]

    km = result.get("key_metrics") or {}
    label_map = [
        ("revenue", "營收"),
        ("operating_income", "營業利益"),
        ("net_income", "淨利"),
        ("yoy_pct", "YoY"),
        ("annual_forecast", "通期予想"),
    ]
    km_rows = [(label, str(km[k])) for k, label in label_map if km.get(k) is not None]
    if km_rows:
        parts.append("| 項目 | 數值 |")
        parts.append("|---|---|")
        for label, val in km_rows:
            parts.append(f"| {label} | {_escape_md_cell(val)} |")
        parts.append("")

    segs = result.get("segment_notes") or []
    if segs:
        parts.append("**Segment 別業績**")
        for seg in segs:
            if isinstance(seg, dict):
                name = seg.get("name", "")
                perf = seg.get("performance", "")
                if name and perf:
                    parts.append(f"- **{tone_filter(str(name))}**：{tone_filter(str(perf))}")
        parts.append("")

    return "\n".join(parts)


def _render_recent_events(event_skill_results: list[dict]) -> str:
    """Render Section 8: 近期重大事件（過去 12 個月）.

    event_skill_results items carry doc_type ("rinji" | "hanki") so the renderer
    can dispatch to the right schema:
      - rinji → jp_extraordinary_event output (event_category / materiality / ...)
      - hanki → jp_semi_annual_summary output (current_half_performance / ...)
    """
    if not event_skill_results:
        return "> 過去 12 個月無重大事件揭露（半期報 / 臨時報）。\n"

    parts = []
    for item in event_skill_results:
        doc_id = item.get("doc_id", "")
        submitted_at = item.get("submitted_at", "")[:10]
        doc_type = item.get("doc_type", "rinji")
        result = item.get("skill_result", {})

        if result.get("insufficient_data"):
            parts.append(f"### {submitted_at}  {doc_id}  [{doc_type}]")
            parts.append("> 事件資料不足，無法分析。\n")
            continue

        if doc_type == "hanki":
            parts.append(f"### {submitted_at}  {doc_id}  [半期報]")
            performance = result.get("current_half_performance", "")
            if performance:
                parts.append(tone_filter(str(performance)))
                parts.append("")
            for label, key in (
                ("與前期同期比較", "vs_prior_half"),
                ("全年預算進度", "vs_full_year_forecast_progress"),
                ("業績修正", "forecast_revision"),
                ("管理層語氣變化", "mgmt_outlook_change"),
            ):
                val = result.get(key)
                if val:
                    parts.append(f"**{label}**：{tone_filter(str(val))}")
            parts.append("")
            continue

        if doc_type == "tdnet":
            # TDNET disclosure rendering
            category = item.get("category", result.get("event_category", "other"))
            title = item.get("title", "")
            event_summary = result.get("event_summary", "")
            materiality = result.get("materiality", "")
            credit_impact = result.get("credit_impact", "")
            key_metrics = result.get("key_metrics") or {}
            forward_guidance = result.get("forward_guidance")
            pdf_extracted = result.get("pdf_extracted", False)

            header = (
                f"### {submitted_at}  {doc_id}  "
                f"[TDNET/{_escape_md_cell(str(category))}]"
            )
            if pdf_extracted:
                header += "  [PDF 已解析]"
            parts.append(header)
            if title:
                parts.append(f"**標題**：{_escape_md_cell(tone_filter(str(title)))}")
                parts.append("")
            if event_summary:
                parts.append(tone_filter(str(event_summary)))
                parts.append("")
            if materiality or credit_impact:
                row_parts = []
                if materiality:
                    row_parts.append(f"**重要性**：{materiality}")
                if credit_impact:
                    row_parts.append(f"**信用影響**：{credit_impact}")
                parts.append("  ".join(row_parts))
                parts.append("")
            # key_metrics table (render when at least one value is non-null)
            km_labels = [
                ("revenue", "營收"),
                ("operating_income", "營業利益"),
                ("net_income", "淨利"),
                ("yoy_pct", "YoY"),
                ("annual_forecast", "通期預想"),
            ]
            km_rows = [
                (label, _escape_md_cell(str(key_metrics[k])))
                for k, label in km_labels
                if key_metrics.get(k) is not None
            ]
            if km_rows:
                parts.append("| 項目 | 數值 |")
                parts.append("|---|---|")
                for label, val in km_rows:
                    parts.append(f"| {label} | {val} |")
                parts.append("")
            segment_notes = result.get("segment_notes") or []
            if segment_notes:
                parts.append("**Segment 別業績**")
                for seg in segment_notes:
                    if isinstance(seg, dict):
                        name = seg.get("name", "")
                        perf = seg.get("performance", "")
                        if name and perf:
                            parts.append(f"- **{tone_filter(str(name))}**：{tone_filter(str(perf))}")
                        elif name:
                            parts.append(f"- {tone_filter(str(name))}")
                    else:
                        parts.append(f"- {tone_filter(str(seg))}")
                parts.append("")
            if forward_guidance:
                parts.append(f"**業績展望**：{tone_filter(str(forward_guidance))}")
                parts.append("")
            continue

        # Default: rinji rendering
        event_category = result.get("event_category", item.get("event_type_guess", "unknown"))
        summary = result.get("event_summary", "")
        materiality = result.get("materiality", "")
        credit_impact = result.get("credit_impact", "")
        key_terms = result.get("key_terms") or {}
        quote = result.get("verbatim_quote", "")

        parts.append(f"### {submitted_at}  {doc_id}  [{_escape_md_cell(str(event_category))}]")
        if summary:
            parts.append(tone_filter(str(summary)))
            parts.append("")
        if materiality or credit_impact:
            row_parts = []
            if materiality:
                row_parts.append(f"**重要性**：{materiality}")
            if credit_impact:
                row_parts.append(f"**信用影響**：{credit_impact}")
            parts.append("  ".join(row_parts))
            parts.append("")
        if key_terms and isinstance(key_terms, dict):
            details = []
            for k, v in key_terms.items():
                if v:
                    details.append(f"**{_escape_md_cell(str(k))}**：{_escape_md_cell(str(v))}")
            if details:
                parts.append("、".join(details))
                parts.append("")
        if quote:
            parts.append(f"> 原文：{tone_filter(str(quote))}")
            parts.append("")

    return "\n".join(parts) if parts else "> 過去 12 個月無重大事件揭露（半期報 / 臨時報）。\n"


def _render_credit_observations(skill_results: dict) -> str:
    """Render Section 9: 信用觀察點 (synthesized from skills 1-7)."""
    parts = []

    # Derive key observations from risk + financial + going_concern
    risk = skill_results.get("jp_risk_analysis", {})
    fin = skill_results.get("jp_financial_analysis", {})
    concern = skill_results.get("jp_going_concern", {})
    mdna = skill_results.get("jp_mdna_analysis", {})

    # Risk highlights
    top3 = risk.get("top_3") or []
    if top3 and not risk.get("insufficient_data"):
        parts.append("### 主要風險")
        for item in top3:
            title = tone_filter(str(item.get("title", "")))
            parts.append(f"- {_escape_md_cell(title)}")
        parts.append("")

    # Financial health
    overall_health = fin.get("overall_health")
    if overall_health and not fin.get("insufficient_data"):
        parts.append(f"**財務體質**：{overall_health}\n")

    # Going concern
    if not concern.get("insufficient_data") and concern.get("has_disclosure"):
        level = concern.get("concern_level", "none")
        parts.append(f"**持續經營疑義**：{level}\n")
    else:
        parts.append("**持續經營疑義**：無重大疑義揭露\n")

    # Management outlook
    outlook = mdna.get("mgmt_outlook")
    if outlook and not mdna.get("insufficient_data"):
        parts.append(f"**管理層展望**：{outlook}\n")

    # Revenue trend
    rev_trend = fin.get("revenue_trend")
    if rev_trend and not fin.get("insufficient_data"):
        parts.append(f"**營收趨勢**：{tone_filter(_safe_render(rev_trend))}\n")

    return "\n".join(parts) if parts else "> 綜合觀察資料不足。\n"


# ── Main save function ────────────────────────────────────────────────────────

def save_jp_report(
    ticker: str,
    edinet_code: str,
    company_name_ja: str,
    fiscal_year_end: str,
    doc_id: str,
    five_year: dict,
    skill_results: dict[str, dict],
    eval_results: dict | None = None,
    recent_events: list[dict] | None = None,
    fiscal_quarter: str = "Q4",
) -> Path:
    """Render and save the JP investment research report.

    Returns the Path of the Markdown file.
    """
    out_dir = BASE_DIR / "data" / "output" / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Derive fiscal year label from fiscal_year_end (e.g. "2025-03-31" → "2025")
    fy_label = fiscal_year_end[:4] if fiscal_year_end else ""

    # Reconstruct chapters dict for appendix (from five_year warnings & skill data)
    # The chapters are not passed here; we use skill_results to detect which existed.
    # For appendix, we note we don't have raw text here — we skip if not available.
    chapters_available: dict[str, str] = {}

    # Section 2 placeholder when yuho not yet published
    no_edinet = not doc_id

    lines = [
        f"# {company_name_ja}（{ticker}）投資研究報告 — FY{fy_label} {fiscal_quarter}",
        "",
        f"> 公司名稱: {company_name_ja}（証券コード: {ticker}、EDINET: {edinet_code}）",
        f"> 期間: FY{fy_label} {fiscal_quarter}（period_end: {fiscal_year_end}）",
        *(
            [f"> 有報 doc_id: {doc_id}"]
            if doc_id else
            ["> 有報: 尚未提交（EDINET 無對應文件）"]
        ),
        f"> 產出時間: {now_str}",
        "",
    ]

    # When no EDINET filing (e.g. yuho not yet published), skip the seven
    # narrative sections, but keep financial data — pull current-period
    # numbers from any TDNET earnings_flash extracted via PDF.
    if no_edinet:
        # ── Section 1: 財務速報（from TDNET earnings_flash if available）──
        lines.append("## 1. 財務速報")
        lines.append("")
        lines.append(_render_tdnet_financial_highlights(recent_events or []))

        # ── Section 2: 其他重大事件 ────────────────────────────────────────
        # Earnings_flash is fully covered in Section 1; only show the OTHER
        # events here (rinji 股東會/M&A, hanki, share buyback, guidance
        # revisions, etc.). Hide the whole section if nothing left.
        other_events = [
            e for e in (recent_events or [])
            if not (e.get("doc_type") == "tdnet" and e.get("category") == "earnings_flash")
        ]
        if other_events:
            lines.append("## 2. 其他重大事件（過去 12 個月）")
            lines.append("")
            lines.append(_render_recent_events(other_events))
    else:
        # ── Section 1: 公司概況 ───────────────────────────────────────────────
        lines.append("## 1. 公司概況（事業の内容）")
        lines.append("")
        biz = skill_results.get("jp_business_analysis", {})
        lines.append(_render_business(biz))

        # ── Section 2: 財務數據（5 年表）───────────────────────────────────
        lines.append("## 2. 財務數據（5 年表）")
        lines.append("")
        lines.append(_render_financial_table(five_year))
        fin_skill = skill_results.get("jp_financial_analysis", {})
        if not fin_skill.get("insufficient_data"):
            parts = []
            for key in ["revenue_trend", "profitability_trend", "balance_sheet_quality",
                        "cash_generation", "return_metrics"]:
                val = fin_skill.get(key)
                if val:
                    parts.append(f"- **{key.replace('_', ' ').title()}**：{tone_filter(_safe_render(val))}")
            if parts:
                lines.append("### 財務趨勢分析")
                lines.extend(parts)
                lines.append("")

        # ── Section 3: 風險敘事重點 ───────────────────────────────────────────
        lines.append("## 3. 風險敘事重點（事業等のリスク）")
        lines.append("")
        lines.append(_render_risk(skill_results.get("jp_risk_analysis", {})))

        # ── Section 4: 管理層分析 (MD&A) ──────────────────────────────────────
        lines.append("## 4. 管理層分析 (MD&A)")
        lines.append("")
        lines.append(_render_mdna(skill_results.get("jp_mdna_analysis", {})))

        # ── Section 5: 經營方針 ────────────────────────────────────────────────
        lines.append("## 5. 經營方針")
        lines.append("")
        lines.append(_render_strategy(skill_results.get("jp_strategy", {})))

        # ── Section 6: 研發與策略 ─────────────────────────────────────────────
        lines.append("## 6. 研發與策略")
        lines.append("")
        lines.append(_render_rd(skill_results.get("jp_rd_analysis", {})))

        # ── Section 7: 持續經營疑義 ───────────────────────────────────────────
        lines.append("## 7. 持續經營疑義")
        lines.append("")
        lines.append(_render_going_concern(skill_results.get("jp_going_concern", {})))

        # ── Section 8: 近期重大事件（過去 12 個月）────────────────────────────
        lines.append("## 8. 近期重大事件（過去 12 個月）")
        lines.append("")
        lines.append(_render_recent_events(recent_events or []))

        # ── Section 9: 信用觀察點 ─────────────────────────────────────────────
        lines.append("## 9. 信用觀察點")
        lines.append("")
        lines.append(_render_credit_observations(skill_results))

    # ── Appendix ──────────────────────────────────────────────────────────────
    lines.append("## 附錄：原文引用對照")
    lines.append("")
    lines.append("（各 skill 分析依據日文有報原文；以下為各章節首段摘錄）")
    lines.append("")
    # We don't have raw chapters here; leave a placeholder note
    lines.append("*原文詳見 EDINET 有報 ZIP 內 iXBRL HTM 檔案。*")
    lines.append("")

    md_text = "\n".join(lines)

    # ── Save Markdown ──────────────────────────────────────────────────────────
    report_md = out_dir / f"{ticker}_{ts}_jp_report.md"
    report_md.write_text(md_text, encoding="utf-8")

    # ── Save PDF ───────────────────────────────────────────────────────────────
    report_pdf = out_dir / f"{ticker}_{ts}_jp_report.pdf"
    pdf_css = _build_pdf_css()
    html_body = markdown.markdown(md_text, extensions=["tables"])
    html_full = (
        f'<html><head><meta charset="utf-8">'
        f'<style>{pdf_css}</style></head>'
        f'<body>{html_body}</body></html>'
    )
    HTML(string=html_full, base_url=str(out_dir)).write_pdf(str(report_pdf))

    # ── Save raw JSON ──────────────────────────────────────────────────────────
    json_path = out_dir / f"{ticker}_{ts}_raw.json"
    json_path.write_text(
        json.dumps(
            {
                "five_year": five_year,
                "skill_results": skill_results,
                "eval_results": eval_results or {},
                "recent_events": recent_events or [],
            },
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


def save_jp_event_report(
    doc_id: str,
    edinet_code: str,
    event_data: dict,
    skill_result: dict,
) -> Path:
    """Render and save a short event report for a single rinji filing.

    Output filename pattern: {edinet_code}_{doc_id}_event.md + .pdf
    Stored under data/output/{jpx_code}/ when ticker_map resolves the
    edinet_code, otherwise under data/output/{edinet_code}/ as a fallback.

    Returns the Path of the Markdown file.
    """
    company_dir = _edinet_to_jpx(edinet_code) or edinet_code or "unknown"
    out_dir = BASE_DIR / "data" / "output" / company_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    submitted_at = str(event_data.get("submitted_at", ""))[:10]
    event_type = event_data.get("event_type_guess", "unknown")

    lines = [
        f"# 臨時報告書分析：{edinet_code}  {doc_id}",
        "",
        f"> EDINET コード: {edinet_code}",
        f"> 提出日: {submitted_at}",
        f"> 事件類別（推測）: {event_type}",
        f"> doc_id: {doc_id}",
        f"> 產出時間: {now_str}",
        "",
    ]

    if skill_result.get("insufficient_data"):
        lines.append("> 資料不足，無法分析此臨時報告。\n")
    else:
        event_category = skill_result.get("event_category", event_type)
        summary = skill_result.get("event_summary", "")
        materiality = skill_result.get("materiality", "")
        credit_impact = skill_result.get("credit_impact", "")
        key_terms = skill_result.get("key_terms") or {}
        quote = skill_result.get("verbatim_quote", "")

        lines.append(f"## 事件類別：{_escape_md_cell(str(event_category))}")
        lines.append("")
        if summary:
            lines.append("## 事件摘要")
            lines.append("")
            lines.append(tone_filter(str(summary)))
            lines.append("")
        if materiality or credit_impact:
            lines.append("## 評估")
            lines.append("")
            if materiality:
                lines.append(f"**重要性**：{materiality}")
            if credit_impact:
                lines.append(f"**信用影響**：{credit_impact}")
            lines.append("")
        if key_terms and isinstance(key_terms, dict):
            lines.append("## 關鍵條款")
            lines.append("")
            for k, v in key_terms.items():
                if v:
                    lines.append(f"- **{_escape_md_cell(str(k))}**：{_escape_md_cell(str(v))}")
            lines.append("")
        if quote:
            lines.append("## 原文引用")
            lines.append("")
            lines.append(f"> {tone_filter(str(quote))}")
            lines.append("")

    lines.append("## 原始 Narrative")
    lines.append("")
    narrative = event_data.get("narrative", "")
    lines.append(narrative[:2000] + ("…（截斷）" if len(narrative) > 2000 else ""))
    lines.append("")

    md_text = "\n".join(lines)

    report_md = out_dir / f"{edinet_code}_{doc_id}_event.md"
    report_md.write_text(md_text, encoding="utf-8")

    report_pdf = out_dir / f"{edinet_code}_{doc_id}_event.pdf"
    pdf_css = _build_pdf_css()
    html_body = markdown.markdown(md_text, extensions=["tables"])
    html_full = (
        f'<html><head><meta charset="utf-8">'
        f'<style>{pdf_css}</style></head>'
        f'<body>{html_body}</body></html>'
    )
    HTML(string=html_full, base_url=str(out_dir)).write_pdf(str(report_pdf))

    print(f"  Event report (MD)：{report_md}")
    print(f"  Event report (PDF)：{report_pdf}")

    return report_md


def save_tdnet_event_report(
    disclosure: dict,
    skill_result: dict,
    out_dir: "Path | None" = None,
) -> "Path":
    """Render and save a short TDNET event report for a single disclosure.

    Output filename pattern: {jpx_code}_tdnet_{disclosure_id}.md + .pdf
    Stored under data/output/{jpx_code}/ by default.

    Returns the Path of the Markdown file.
    """
    disc_id = disclosure.get("disclosure_id", "unknown")
    jpx_code = disclosure.get("jpx_code") or "unknown"
    if out_dir is None:
        out_dir = BASE_DIR / "data" / "output" / jpx_code
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    jpx_code = disclosure.get("jpx_code", "")
    company_name = disclosure.get("company_name", "")
    title = disclosure.get("title", "")
    category = disclosure.get("category", "other")
    disc_date = str(disclosure.get("disclosure_date", ""))[:10]
    disc_time = str(disclosure.get("disclosure_time", ""))

    lines = [
        f"# TDNET 公告分析：{company_name}（{jpx_code}）",
        "",
        f"> 証券コード: {jpx_code}",
        f"> 公告日時: {disc_date} {disc_time}",
        f"> 分類: {_escape_md_cell(str(category))}",
        f"> disclosure_id: {disc_id}",
        f"> 産出時間: {now_str}",
        "",
    ]

    if title:
        lines.append(f"## 公告標題")
        lines.append("")
        lines.append(_escape_md_cell(tone_filter(str(title))))
        lines.append("")

    if skill_result.get("insufficient_data"):
        lines.append("> 資料不足，無法分析此 TDNET 公告。\n")
    else:
        event_category = skill_result.get("event_category", category)
        event_summary = skill_result.get("event_summary", "")
        materiality = skill_result.get("materiality", "")
        credit_impact = skill_result.get("credit_impact", "")

        lines.append(f"## 事件類別：{_escape_md_cell(str(event_category))}")
        lines.append("")
        if event_summary:
            lines.append("## 事件摘要")
            lines.append("")
            lines.append(tone_filter(str(event_summary)))
            lines.append("")
        if materiality or credit_impact:
            lines.append("## 評估")
            lines.append("")
            if materiality:
                lines.append(f"**重要性**：{materiality}")
            if credit_impact:
                lines.append(f"**信用影響**：{credit_impact}")
            lines.append("")

    md_text = "\n".join(lines)

    report_md = Path(out_dir) / f"{jpx_code}_tdnet_{disc_id}.md"
    report_md.write_text(md_text, encoding="utf-8")

    report_pdf = Path(out_dir) / f"{jpx_code}_tdnet_{disc_id}.pdf"
    pdf_css = _build_pdf_css()
    html_body = markdown.markdown(md_text, extensions=["tables"])
    html_full = (
        f'<html><head><meta charset="utf-8">'
        f'<style>{pdf_css}</style></head>'
        f'<body>{html_body}</body></html>'
    )
    HTML(string=html_full, base_url=str(out_dir)).write_pdf(str(report_pdf))

    print(f"  TDNET event report (MD)：{report_md}")
    print(f"  TDNET event report (PDF)：{report_pdf}")

    return report_md


def save_earnings_call_report(
    transcript: dict,
    skill_result: dict,
    jpx_code: str = "",
    company_name_ja: str = "",
) -> "Path":
    """Render and save a short earnings call report from a logmi transcript.

    Output filename pattern: {jpx_code}_{YYYYMMDD_HHMMSS}_earnings_call.md + .pdf
    Stored under data/output/{jpx_code}/.

    Returns the Path of the Markdown file.
    """
    out_dir = BASE_DIR / "data" / "output" / (jpx_code or "unknown")
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    call_title = transcript.get("title", "法説会")
    call_date = transcript.get("date", "")

    lines = [
        f"# 法說會分析：{company_name_ja}（{jpx_code}）",
        "",
        f"> 証券コード: {jpx_code}",
        f"> 法說會標題: {_escape_md_cell(str(call_title))}",
        f"> 發表日期: {call_date}",
        f"> 産出時間: {now_str}",
        "",
    ]

    if skill_result.get("insufficient_data"):
        lines.append("> 資料不足，無法分析此法說會。\n")
    else:
        meeting_summary = skill_result.get("meeting_summary", "")
        forward_guidance = skill_result.get("forward_guidance") or {}
        qa_signals = skill_result.get("qa_signals") or []
        top_concerns = skill_result.get("top_concerns") or []
        tone_vs_prior = skill_result.get("tone_vs_prior")

        if meeting_summary:
            lines.append("## 會議摘要")
            lines.append("")
            lines.append(tone_filter(str(meeting_summary)))
            lines.append("")

        if forward_guidance:
            lines.append("## 前瞻 Guidance")
            lines.append("")
            summary = forward_guidance.get("summary", "")
            strength = forward_guidance.get("commitment_strength", "")
            if summary:
                lines.append(tone_filter(str(summary)))
                lines.append("")
            if strength:
                lines.append(f"**承諾強度**：{strength}")
                lines.append("")
            key_stmts = forward_guidance.get("key_statements") or []
            for s in key_stmts:
                lines.append(f"- {tone_filter(str(s))}")
            if key_stmts:
                lines.append("")

        if top_concerns:
            lines.append("## 主要關切議題")
            lines.append("")
            lines.append("| 議題 | 摘要 |")
            lines.append("|------|------|")
            for c in top_concerns:
                theme = _escape_md_cell(tone_filter(str(c.get("question_theme", ""))))
                summ = _escape_md_cell(tone_filter(str(c.get("summary", ""))))
                lines.append(f"| {theme} | {summ} |")
            lines.append("")

        if qa_signals:
            lines.append("## Q&A 訊號")
            lines.append("")
            lines.append("| 議題 | 已回答 | 強度 |")
            lines.append("|------|--------|------|")
            for sig in qa_signals:
                theme = _escape_md_cell(str(sig.get("question_theme", "")))
                answered = "是" if sig.get("answered") else "否"
                strength = _escape_md_cell(str(sig.get("response_strength", "")))
                lines.append(f"| {theme} | {answered} | {strength} |")
            lines.append("")

        if tone_vs_prior:
            lines.append("## 與前次基調對比")
            lines.append("")
            lines.append(tone_filter(str(tone_vs_prior)))
            lines.append("")

    md_text = "\n".join(lines)

    report_md = out_dir / f"{jpx_code}_{ts}_earnings_call.md"
    report_md.write_text(md_text, encoding="utf-8")

    report_pdf = out_dir / f"{jpx_code}_{ts}_earnings_call.pdf"
    pdf_css = _build_pdf_css()
    html_body = markdown.markdown(md_text, extensions=["tables"])
    html_full = (
        f'<html><head><meta charset="utf-8">'
        f'<style>{pdf_css}</style></head>'
        f'<body>{html_body}</body></html>'
    )
    HTML(string=html_full, base_url=str(out_dir)).write_pdf(str(report_pdf))

    print(f"  Earnings call report (MD)：{report_md}")
    print(f"  Earnings call report (PDF)：{report_pdf}")

    return report_md
