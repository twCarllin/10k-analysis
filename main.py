"""
Usage:
  python main.py <TICKER> <YEAR> [--file PATH] [--clean] [--dry-run]
                 [--only TASK1,TASK2,...] [--filing-type 10-K|10-Q]
                 [--quarter Q1|Q2|Q3] [--prior-year YEAR]

  python main.py <TICKER> --market jp [--years N] [--dry-run]
  python main.py <TICKER> --market jp --tdnet-event-id <DISCLOSURE_ID>
  python main.py <TICKER> --market jp --analyze-call
  python main.py --market jp --tdnet-watch <TICKER>[,TICKER,...] [--since-minutes N] [--dry-run]

Prior period is auto-determined:
  10-K        → prior = 10-K (year - 1)
  10-Q Q1     → prior = 10-K (year - 1)
  10-Q Q2     → prior = 10-Q Q1 (same year)
  10-Q Q3     → prior = 10-Q Q2 (same year)

Examples:
  python main.py HWM 2024                                  # 10-K, auto prior=2023
  python main.py HWM 2024 --dry-run
  python main.py HWM 2024 --clean
  python main.py HWM 2024 --only fn_revenue,fn_segment
  python main.py HWM 2025 --filing-type 10-Q --quarter Q1  # prior=10-K 2024
  python main.py HWM 2025 --filing-type 10-Q --quarter Q2  # prior=10-Q Q1 2025
  python main.py HWM 2024 --prior-year 2022                # override prior year
  python main.py 6315 --market jp --years 3                # JP batch mode
  python main.py 6315 --market jp --tdnet-event-id 20260511_6315_1530  # JP TDNET event
  python main.py 6315 --market jp --analyze-call           # JP logmi call analysis
  python main.py --market jp --tdnet-watch 6315,7203 --since-minutes 30  # watch mode
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "runtime"))

from sec_data_fetcher import download_filing, get_xbrl_facts, extract_key_metrics, extract_quarterly_metrics
from doc_converter import convert_to_markdown
from section_splitter import (
    split_sections,
    validate_sections,
    extract_footnotes,
    extract_fs_tables,
    split_footnotes,
)
from orchestrator import run_pipeline
from pipeline_state import PipelineState


def _determine_prior(year, filing_type, quarter, override=None):
    """Determine prior period for narrative comparison.

    Returns (prior_year, prior_filing_type, prior_quarter).
    """
    if filing_type == "10-K":
        return (override or year - 1), "10-K", None
    # 10-Q
    if quarter == "Q1":
        return (override or year - 1), "10-K", None
    elif quarter == "Q2":
        return (override or year), "10-Q", "Q1"
    elif quarter == "Q3":
        return (override or year), "10-Q", "Q2"


def build_sections(ticker, year, file_path=None, filing_type="10-K",
                   quarter=None) -> dict:
    doc_path = (Path(file_path) if file_path
                else download_filing(ticker, year, filing_type, quarter))
    md_text = convert_to_markdown(doc_path)
    raw = split_sections(md_text, filing_type=filing_type)
    warnings = validate_sections(raw, filing_type=filing_type)
    if warnings:
        for w in warnings:
            print(f"  [WARNING] {w}")

    if filing_type == "10-Q":
        # 10-Q mapping: item1 → Financial Statements, item2 → MD&A
        item_fs = raw.get("item1", "")
        result = {
            "item1_current": "",  # 10-Q has no Business section
            "item1a_current": raw.get("item1a", ""),  # optional in 10-Q
            "item7_current": raw.get("item2", ""),  # Item 2 = MD&A
            "item8_fs": extract_fs_tables(item_fs),
            "partiii_current": "",  # no Part III in 10-Q
            "fn_combined": extract_footnotes(item_fs),  # 10-Q: single combined footnotes task
            "_split_warnings": warnings,
            "_year": year,
        }
    else:
        item8 = raw.get("item8", "")
        fn_subs = split_footnotes(item8)
        item_fs = item8
        result = {
            "item1_current": raw.get("item1", ""),
            "item1a_current": raw.get("item1a", ""),
            "item7_current": raw.get("item7", ""),
            "item8_fs": extract_fs_tables(item8),
            "partiii_current": (
                raw.get("item10", "")
                + "\n"
                + raw.get("item11", "")
                + "\n"
                + raw.get("item13", "")
            ),
            "_split_warnings": warnings,
            "_year": year,
        }

        # Add each footnotes sub-section (10-K only)
        for fn_key, fn_text in fn_subs.items():
            result[fn_key] = fn_text
    # Glossary input: truncated concat of key sections
    from agent_runner import truncate_with_notice
    all_sections_md = (
        truncate_with_notice(result.get("item1_current", ""), 2000) + "\n\n"
        + truncate_with_notice(result.get("item1a_current", ""), 3000) + "\n\n"
        + truncate_with_notice(result.get("item7_current", ""), 4000) + "\n\n"
        + truncate_with_notice(extract_footnotes(item_fs), 3000)
    )
    result["all_sections_md"] = all_sections_md
    # For unusual_operations
    result["item8_footnotes_md"] = truncate_with_notice(extract_footnotes(item_fs), 8000)
    # For supply_chain_analysis (10-K: item8, 10-Q: item_fs)
    result["item8_footnotes_current"] = truncate_with_notice(
        extract_footnotes(item8 if filing_type != "10-Q" else item_fs), 12000
    )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?", default=None)
    p.add_argument("year", nargs="?", type=int, default=None)
    p.add_argument("--market", default="sec", choices=["sec", "jp"],
                   help="Market: sec (US SEC) or jp (EDINET Japanese). Default: sec")
    p.add_argument("--years", type=int, default=3,
                   help="JP pipeline: number of years of filings to consider. Default: 3")
    p.add_argument("--prior-year", type=int, default=None,
                   help="手動覆蓋前期年份（預設自動推算）")
    p.add_argument("--file", default=None)
    p.add_argument("--clean", action="store_true",
                   help="清除 checkpoint 重新開始")
    p.add_argument("--dry-run", action="store_true",
                   help="不發 API，用 mock 結果測試流程")
    p.add_argument("--only", default=None,
                   help="只重跑指定 task（逗號分隔），其餘從快取載入。"
                        "下游 eval + synthesis 自動重跑")
    p.add_argument("--filing-type", default="10-K", choices=["10-K", "10-Q"],
                   help="SEC 申報類型（預設 10-K）")
    p.add_argument("--quarter", default=None, choices=["Q1", "Q2", "Q3"],
                   help="10-Q 季度（10-Q 時必填）")
    p.add_argument("--skip-transcript", action="store_true",
                   help="Skip earnings call transcript scraping")
    p.add_argument("--transcript-quarter", choices=["Q1", "Q2", "Q3", "Q4"], default=None,
                   help="Quarter for transcript scraping (Q1-Q4; Q4 for 10-K annual). Default: derived from --quarter or Q4 for 10-K")
    p.add_argument("--transcript-year", type=int, default=None,
                   help="Year for transcript (default: --year)")
    p.add_argument("--event-doc-id", default=None,
                   help="JP event mode: analyse a single rinji doc_id and produce a short report")
    p.add_argument("--tdnet-watch", default=None, metavar="TICKERS",
                   help="JP watch mode: comma-separated JPX codes to monitor on TDNET, e.g. 6315,7203")
    p.add_argument("--tdnet-event-id", default=None, metavar="DISCLOSURE_ID",
                   help="JP TDNET event mode: analyse a single TDNET disclosure_id")
    p.add_argument("--analyze-call", action="store_true",
                   help="JP logmi mode: fetch latest earnings call transcript for TICKER and analyse")
    p.add_argument("--since-minutes", type=int, default=15,
                   help="Watch mode: look back N minutes for new TDNET disclosures (default: 15)")
    args = p.parse_args()

    # Ticker is optional for watch mode (watchlist is in --tdnet-watch flag)
    ticker = args.ticker.upper() if args.ticker else None
    filing_type = args.filing_type
    quarter = args.quarter

    if filing_type == "10-Q" and not quarter:
        p.error("--quarter is required when --filing-type is 10-Q")
    if filing_type == "10-K" and quarter:
        print("  [WARNING] --quarter is ignored for 10-K filings")
        quarter = None

    # Dry-run mode
    if args.dry_run:
        from agent_runner import set_dry_run
        set_dry_run(True)
        print("  [Mode] dry-run — 不發 API，使用 mock 結果")

    # JP market branch
    if args.market == "jp":
        # --tdnet-watch: watch mode, no positional ticker required
        if args.tdnet_watch:
            watchlist = [t.strip() for t in args.tdnet_watch.split(",") if t.strip()]
            if not watchlist:
                p.error("--tdnet-watch requires at least one JPX code")
            from jp_pipeline import run_tdnet_watch_pipeline
            run_tdnet_watch_pipeline(
                watchlist=watchlist,
                since_minutes=args.since_minutes,
                dry_run=args.dry_run,
            )
            return

        # Remaining JP modes require a ticker
        if ticker is None:
            p.error("ticker is required for JP pipeline (omit only for --tdnet-watch)")

        exclusive_flags = [args.tdnet_event_id, args.analyze_call, args.event_doc_id]
        n_set = sum(1 for f in exclusive_flags if f)
        if n_set > 1:
            p.error("--tdnet-event-id / --analyze-call / --event-doc-id are mutually exclusive")

        if args.tdnet_event_id:
            from jp_pipeline import run_tdnet_event_pipeline
            run_tdnet_event_pipeline(
                disclosure_id=args.tdnet_event_id,
                dry_run=args.dry_run,
            )
        elif args.analyze_call:
            from jp_pipeline import run_logmi_call_pipeline
            run_logmi_call_pipeline(
                jpx_code=ticker,
                dry_run=args.dry_run,
            )
        elif args.event_doc_id:
            from jp_pipeline import run_jp_event_pipeline
            run_jp_event_pipeline(
                doc_id=args.event_doc_id,
                dry_run=args.dry_run,
            )
        else:
            from jp_pipeline import run_jp_pipeline
            run_jp_pipeline(
                ticker=ticker,
                years=args.years,
                dry_run=args.dry_run,
            )
        return

    # SEC branch: ticker and year are both required
    if ticker is None:
        p.error("ticker is required for --market sec")
    if args.year is None:
        p.error("year is required for --market sec")

    # Determine prior period
    prior_year, prior_ft, prior_q = _determine_prior(
        args.year, filing_type, quarter, args.prior_year)

    # Initialize state (auto-detects existing checkpoint)
    state = PipelineState(ticker, args.year, prior_year,
                          filing_type=filing_type, quarter=quarter,
                          prior_filing_type=prior_ft, prior_quarter=prior_q)
    if args.clean:
        state.clear()
        state = PipelineState(ticker, args.year, prior_year,
                              filing_type=filing_type, quarter=quarter,
                              prior_filing_type=prior_ft, prior_quarter=prior_q)
        print("  [State] 已清除 checkpoint，重新開始")

    # --only: invalidate specified tasks + downstream (eval, synthesis)
    if args.only:
        only_tasks = [t.strip() for t in args.only.split(",")]
        for tid in only_tasks:
            for prefix in ["phase1", "prior.phase1", "retry1"]:
                state.invalidate(f"{prefix}.{tid}")
        # Also invalidate financial if any fn_* is rerun (since it depends on footnotes)
        if any(t.startswith("fn_") for t in only_tasks):
            state.invalidate("phase2.financial")
            state.invalidate("prior.phase2.financial")
        # Always invalidate downstream: eval, synthesis, phase3, phase5
        for key in list(state._data["steps"].keys()):
            if (key.startswith("eval_") or key.startswith("synthesis.")
                    or key.startswith("phase3.") or key.startswith("phase3b.")
                    or key.startswith("phase5.")):
                state.invalidate(key)
        state._save()
        print(f"  [State] 重跑：{', '.join(only_tasks)}（+ eval + synthesis）")

    q_label = f" {quarter}" if quarter else ""
    prior_label = f"{prior_ft.replace('-','')}"
    if prior_q:
        prior_label += f" {prior_q}"
    print(f"\n{'='*50}\n  {ticker} {args.year} {filing_type}{q_label}"
          f"  (prior: {prior_year} {prior_label})\n{'='*50}")

    xbrl_facts = get_xbrl_facts(ticker)
    xbrl_json = json.dumps(
        extract_key_metrics(xbrl_facts, filing_type=filing_type), ensure_ascii=False
    )
    quarterly = extract_quarterly_metrics(xbrl_facts, num_quarters=5)
    sections = build_sections(ticker, args.year, args.file,
                              filing_type=filing_type, quarter=quarter)
    sections["xbrl_data"] = xbrl_json
    sections["_quarterly"] = quarterly

    print(f"\n  前期 sections ({prior_year} {prior_label})...")
    prior_sections = build_sections(ticker, prior_year,
                                    filing_type=prior_ft, quarter=prior_q)
    prior_sections["xbrl_data"] = xbrl_json

    # auto-derive transcript quarter / year
    transcript_quarter = args.transcript_quarter
    if transcript_quarter is None:
        transcript_quarter = quarter or "Q4"  # 10-Q uses sanitized quarter; 10-K defaults Q4
    transcript_year = args.transcript_year or args.year

    run_pipeline(ticker, sections, prior_sections, state=state,
                 filing_type=filing_type, quarter=quarter,
                 transcript_quarter=transcript_quarter,
                 transcript_year=transcript_year,
                 skip_transcript=args.skip_transcript,
                 dry_run=args.dry_run)


if __name__ == "__main__":
    main()
