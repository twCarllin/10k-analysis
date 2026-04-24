"""
Usage:
  python main.py <TICKER> <YEAR> [PRIOR_YEAR] [--file PATH] [--clean] [--dry-run]
                 [--only TASK1,TASK2,...] [--filing-type 10-K|10-Q]
                 [--quarter Q1|Q2|Q3]

Examples:
  python main.py HWM 2024 2023
  python main.py HWM 2024 2023 --dry-run
  python main.py HWM 2024 2023 --clean
  python main.py HWM 2024 2023 --only fn_revenue,fn_segment,fn_receivables
  python main.py HWM 2024 --filing-type 10-Q --quarter Q3
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "runtime"))

from data_fetcher import download_filing, get_xbrl_facts, extract_key_metrics, extract_quarterly_metrics
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
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ticker")
    p.add_argument("year", type=int)
    p.add_argument("prior_year", type=int, nargs="?")
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
    args = p.parse_args()
    ticker = args.ticker.upper()
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

    # Initialize state (auto-detects existing checkpoint)
    state = PipelineState(ticker, args.year, args.prior_year,
                          filing_type=filing_type, quarter=quarter)
    if args.clean:
        state.clear()
        state = PipelineState(ticker, args.year, args.prior_year,
                              filing_type=filing_type, quarter=quarter)
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
                    or key.startswith("phase3.") or key.startswith("phase5.")):
                state.invalidate(key)
        state._save()
        print(f"  [State] 重跑：{', '.join(only_tasks)}（+ eval + synthesis）")

    q_label = f" {quarter}" if quarter else ""
    print(f"\n{'='*50}\n  {ticker} {args.year} {filing_type}{q_label}\n{'='*50}")

    xbrl_facts = get_xbrl_facts(ticker)
    xbrl_json = json.dumps(
        extract_key_metrics(xbrl_facts, filing_type=filing_type), ensure_ascii=False
    )
    quarterly = extract_quarterly_metrics(xbrl_facts, num_quarters=5)
    sections = build_sections(ticker, args.year, args.file,
                              filing_type=filing_type, quarter=quarter)
    sections["xbrl_data"] = xbrl_json
    sections["_quarterly"] = quarterly

    prior_sections = None
    if args.prior_year:
        print(f"\n  前年度 sections ({args.prior_year})...")
        prior_sections = build_sections(ticker, args.prior_year,
                                        filing_type=filing_type, quarter=quarter)
        prior_sections["xbrl_data"] = xbrl_json

    run_pipeline(ticker, sections, prior_sections, state=state,
                 filing_type=filing_type, quarter=quarter)


if __name__ == "__main__":
    main()
