"""
jp_pipeline.py — End-to-end pipeline for Japanese EDINET 有価証券報告書.

Entry point: run_jp_pipeline(ticker, years, skip_skills, dry_run) -> Path

Phase 0   ensure_ticker_map_fresh + ticker_to_edinet + company info
Phase 1   find_filings_local(doc_types={"120"}) → most recent filing
Phase 2   download_filing → ZIP
Phase 3   TA3 extract_five_year_summary + TA4 split_filing_by_ixbrl
Phase 4   Run 7 jp skills via ThreadPoolExecutor (max_workers=4)
Phase 4.5 find_recent_events + jp_extraordinary_event skill for rinji
Phase 5   eval loop (max 2 retries, uses eval_runner)
Phase 6   save_jp_report → markdown + PDF (includes recent events section)

Also provides:
    find_recent_events(edinet_code, months=12) -> list[dict]
    run_jp_event_pipeline(doc_id, dry_run=False) -> Path
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent

log = logging.getLogger(__name__)

# Skills to run (in logical order; parallelised in Phase 4)
JP_SKILLS = [
    "jp_business_analysis",
    "jp_risk_analysis",
    "jp_mdna_analysis",
    "jp_going_concern",
    "jp_strategy",
    "jp_rd_analysis",
    "jp_financial_analysis",
]

# chapter_key from split_filing_by_ixbrl → skill input key
_CHAPTER_TO_SKILL_INPUT = {
    "jp_business_analysis": "business",
    "jp_risk_analysis":     "risk",
    "jp_mdna_analysis":     "mda",
    "jp_going_concern":     "going_concern",
    "jp_strategy":          "strategy",
    "jp_rd_analysis":       "rd",
    "jp_financial_analysis": None,  # uses xbrl_data instead
}


def _get_company_info(jpx_code: str) -> dict:
    """Query ticker_map for company name info."""
    from jp_data_fetcher import DB_PATH
    if not DB_PATH.exists():
        return {"company_name_ja": jpx_code, "company_name_en": ""}
    with duckdb.connect(str(DB_PATH)) as con:
        row = con.execute(
            "SELECT company_name_ja, company_name_en FROM ticker_map WHERE jpx_code = ?",
            [jpx_code],
        ).fetchone()
    if row:
        return {"company_name_ja": row[0] or jpx_code, "company_name_en": row[1] or ""}
    return {"company_name_ja": jpx_code, "company_name_en": ""}


def _run_skill(skill_name: str, inputs: dict) -> tuple[str, dict]:
    """Run a single jp skill via agent_runner. Returns (skill_name, result)."""
    from agent_runner import run_agent
    result = run_agent("analyst_agent", skill_name, inputs, task_label=skill_name)
    return skill_name, result


def find_recent_events(edinet_code: str, months: int = 12) -> list[dict]:
    """Query filings_index for recent hanki (doc_type=160) and rinji (doc_type=180).

    Returns list of filing dicts sorted by submitted_at descending.
    Each dict has: doc_id, doc_type_code, form_code, submitted_at, period_end.
    """
    from jp_data_fetcher import find_filings_local, DB_PATH

    if not DB_PATH.exists():
        log.warning("find_recent_events: master.duckdb not found; returning empty list")
        return []

    since = date.today() - timedelta(days=months * 31)
    filings = find_filings_local(edinet_code, doc_types={"160", "180"})

    # Filter by submitted_at >= since (period_end may be None for rinji)
    result = []
    for f in filings:
        sub = f.get("submitted_at")
        if sub is None:
            continue
        sub_date = sub.date() if isinstance(sub, datetime) else date.fromisoformat(str(sub)[:10])
        if sub_date >= since:
            result.append(f)

    # Sort by submitted_at descending
    result.sort(key=lambda x: str(x.get("submitted_at") or ""), reverse=True)
    return result


def run_jp_event_pipeline(doc_id: str, dry_run: bool = False) -> Path:
    """Run the single-rinji event short report pipeline.

    1. Look up filing metadata from local index (or try downloading directly).
    2. download_filing(doc_id) → ZIP
    3. extract_rinji_event → event dict
    4. Run jp_extraordinary_event skill
    5. save_jp_event_report → short md + pdf

    Returns the Path of the generated Markdown report.
    """
    print(f"\n{'='*50}")
    print(f"  JP Event Pipeline: {doc_id}  (dry_run={dry_run})")
    print(f"{'='*50}")

    from jp_data_fetcher import download_filing, find_filings_local, DB_PATH
    from jp_ixbrl_parser import extract_rinji_event

    # Dry-run mode
    if dry_run:
        from agent_runner import set_dry_run
        set_dry_run(True)

    # Look up metadata
    edinet_code = ""
    if DB_PATH.exists():
        with duckdb.connect(str(DB_PATH)) as con:
            row = con.execute(
                "SELECT edinet_code FROM filings_index WHERE doc_id = ?", [doc_id]
            ).fetchone()
            if row:
                edinet_code = row[0] or ""

    # Download ZIP
    print(f"\n[Event Phase 1] download {doc_id}")
    try:
        zip_path = download_filing(doc_id)
    except Exception as exc:
        print(f"  [FATAL] 無法下載 {doc_id}：{exc}")
        raise
    print(f"  ZIP: {zip_path}")

    # Extract event narrative
    print("\n[Event Phase 2] extract_rinji_event")
    event_data = extract_rinji_event(zip_path)
    print(f"  form_code={event_data['form_code']}  event_type_guess={event_data['event_type_guess']}")
    if event_data["_warnings"]:
        for w in event_data["_warnings"]:
            print(f"  [WARNING] {w}")

    # Run jp_extraordinary_event skill
    print("\n[Event Phase 3] jp_extraordinary_event skill")
    from agent_runner import run_agent
    skill_result = run_agent(
        "analyst_agent",
        "jp_extraordinary_event",
        {
            "narrative": event_data["narrative"],
            "event_type_guess": event_data["event_type_guess"],
            "form_code": event_data["form_code"],
        },
        task_label="jp_extraordinary_event",
    )
    status = "error" if "error" in skill_result else "ok"
    print(f"  [{status}] jp_extraordinary_event")

    # Save report
    print("\n[Event Phase 4] save event report")
    from jp_report_writer import save_jp_event_report
    report_path = save_jp_event_report(
        doc_id=doc_id,
        edinet_code=edinet_code,
        event_data=event_data,
        skill_result=skill_result,
    )

    print(f"\n  Event report: {report_path}")
    return report_path


def run_jp_pipeline(
    ticker: str,
    years: int = 3,
    skip_skills: list[str] | None = None,
    dry_run: bool = False,
) -> Path:
    """
    Run the full Japanese EDINET pipeline for *ticker* (JPX 4-digit code).

    dry_run: skip LLM calls only (use mock outputs). EDINET data fetch
    and iXBRL parsing still run — requires local cache or network access.

    Returns the Path of the generated Markdown report.
    """
    skip_skills = set(skip_skills or [])

    print(f"\n{'='*50}")
    print(f"  JP Pipeline: {ticker}  (years={years}, dry_run={dry_run})")
    print(f"{'='*50}")

    # ── Phase 0: ticker map + edinet code ─────────────────────────────────────
    print("\n[Phase 0] ticker map / EDINET lookup")
    from jp_data_fetcher import ensure_ticker_map_fresh, ticker_to_edinet

    if dry_run:
        # In dry-run, skip heavy network fetches; assume map already built.
        print("  [dry-run] skip ensure_ticker_map_fresh")
    else:
        ensure_ticker_map_fresh()

    edinet_code = ticker_to_edinet(ticker)
    company_info = _get_company_info(ticker)
    company_name_ja = company_info["company_name_ja"]
    print(f"  {ticker} → {edinet_code}  ({company_name_ja})")

    # ── Phase 1: find most recent 有報 ────────────────────────────────────────
    print("\n[Phase 1] find filings")
    from jp_data_fetcher import find_filings_local

    since_date = date.today() - timedelta(days=years * 366)
    filings = find_filings_local(edinet_code, doc_types={"120"}, since=since_date)

    if not filings:
        raise RuntimeError(
            f"No 有報 found for {edinet_code} ({ticker}) since {since_date}. "
            "Run scan_date_range first to populate the local index."
        )

    # filings are sorted period_end DESC; take the most recent
    latest = filings[0]
    doc_id = latest["doc_id"]
    fiscal_year_end = str(latest["period_end"])
    print(f"  Most recent filing: {doc_id}  period_end={fiscal_year_end}")

    # ── Phase 2: download ZIP ─────────────────────────────────────────────────
    print("\n[Phase 2] download filing")
    from jp_data_fetcher import download_filing

    zip_path = download_filing(doc_id)
    print(f"  ZIP: {zip_path}")

    # ── Phase 3: parse XBRL + iXBRL ──────────────────────────────────────────
    print("\n[Phase 3] extract financials + narrative chapters")
    from jp_ixbrl_parser import extract_five_year_summary, split_filing_by_ixbrl

    five_year = extract_five_year_summary(zip_path)
    # Update fiscal_year_end from XBRL (more authoritative)
    fiscal_year_end = five_year.get("fiscal_year_end", fiscal_year_end)
    print(f"  fiscal_year_end={fiscal_year_end}  "
          f"accounting_standard={five_year.get('accounting_standard')}")
    if five_year.get("_warnings"):
        for w in five_year["_warnings"]:
            print(f"  [WARNING] {w}")

    chapters = split_filing_by_ixbrl(zip_path)
    print(f"  chapters extracted: {sorted(chapters.keys())}")

    # ── Phase 4: run 7 skills in parallel ────────────────────────────────────
    print("\n[Phase 4] running jp skills")
    xbrl_json = json.dumps(five_year, ensure_ascii=False)

    def _build_inputs(skill_name: str) -> dict:
        chapter_key = _CHAPTER_TO_SKILL_INPUT.get(skill_name)
        if skill_name == "jp_financial_analysis":
            return {"xbrl_data": xbrl_json}
        if chapter_key is None:
            return {"current_section": ""}
        text = chapters.get(chapter_key, "")
        return {"current_section": text}

    skill_results: dict[str, dict] = {}
    active_skills = [s for s in JP_SKILLS if s not in skip_skills]

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_run_skill, sk, _build_inputs(sk)): sk
            for sk in active_skills
        }
        for future in as_completed(futures):
            sk = futures[future]
            try:
                name, result = future.result()
                skill_results[name] = result
                status = "error" if "error" in result else "ok"
                print(f"  [{status}] {name}")
            except Exception as exc:
                log.error("Skill %s failed: %s", sk, exc)
                skill_results[sk] = {"error": str(exc), "insufficient_data": True}
                print(f"  [error] {sk}: {exc}")

    # ── Phase 4.5: find recent events (hanki + rinji) ────────────────────────
    print("\n[Phase 4.5] find recent events (past 12 months)")
    recent_events: list[dict] = []
    event_skill_results: list[dict] = []

    if not dry_run:
        recent_events = find_recent_events(edinet_code, months=12)
        print(f"  Found {len(recent_events)} recent events (hanki+rinji)")
        for evt in recent_events:
            print(f"  {evt['doc_id']} type={evt['doc_type_code']} form={evt.get('form_code')} "
                  f"sub={evt['submitted_at']}")

        # Dispatch each event by doc_type:
        #   180 (rinji) → jp_extraordinary_event skill on rinji narrative
        #   160 (hanki) → jp_semi_annual_summary skill on hanki mda chapter
        from jp_ixbrl_parser import extract_rinji_event, split_filing_by_ixbrl
        for evt in recent_events:
            doc_type = evt["doc_type_code"]
            try:
                evt_zip = download_filing(evt["doc_id"])
                if doc_type == "180":
                    event_data = extract_rinji_event(evt_zip)
                    _, evt_result = _run_skill(
                        "jp_extraordinary_event",
                        {
                            "narrative": event_data["narrative"],
                            "event_type_guess": event_data["event_type_guess"],
                            "form_code": event_data["form_code"],
                        },
                    )
                    event_skill_results.append({
                        "doc_id": evt["doc_id"],
                        "submitted_at": str(evt.get("submitted_at", "")),
                        "doc_type": "rinji",
                        "event_type_guess": event_data["event_type_guess"],
                        "skill_result": evt_result,
                    })
                    print(f"  [ok] jp_extraordinary_event for {evt['doc_id']}")
                elif doc_type == "160":
                    chapters = split_filing_by_ixbrl(evt_zip)
                    mda_text = chapters.get("mda") or chapters.get("business", "")
                    if not mda_text:
                        log.warning("hanki %s has no mda/business chapter; skip", evt["doc_id"])
                        continue
                    _, evt_result = _run_skill(
                        "jp_semi_annual_summary",
                        {"current_section": mda_text},
                    )
                    event_skill_results.append({
                        "doc_id": evt["doc_id"],
                        "submitted_at": str(evt.get("submitted_at", "")),
                        "doc_type": "hanki",
                        "skill_result": evt_result,
                    })
                    print(f"  [ok] jp_semi_annual_summary for {evt['doc_id']}")
            except Exception as exc:
                log.error("Event analysis failed for %s: %s", evt["doc_id"], exc)
                print(f"  [error] {evt['doc_id']}: {exc}")
    else:
        print("  [dry-run] skip find_recent_events")

    # ── Phase 5: eval loop (max 2 retries) ────────────────────────────────────
    print("\n[Phase 5] eval loop")
    from eval_runner import eval_all, get_failed_tasks

    # Build a sections-like dict that eval_runner can use for jp_* tasks
    # eval_runner will default-pass jp_* since they are not in REQUIRED_KEYS / HARD_RULES
    jp_sections = {
        "jp_business_analysis": chapters.get("business", ""),
        "jp_risk_analysis":     chapters.get("risk", ""),
        "jp_mdna_analysis":     chapters.get("mda", ""),
        "jp_going_concern":     chapters.get("going_concern", ""),
        "jp_strategy":          chapters.get("strategy", ""),
        "jp_rd_analysis":       chapters.get("rd", ""),
        "jp_financial_analysis": xbrl_json,
        # placeholders for eval_all source_map keys (it won't find them but won't crash)
        "item1_current": "",
        "item1a_current": "",
        "item7_current": "",
        "partiii_current": "",
        "xbrl_data": xbrl_json,
        "all_sections_md": "",
        "item8_footnotes_md": "",
        "item8_footnotes_current": "",
    }

    MAX_RETRIES = 2
    eval_results = {}
    for attempt in range(MAX_RETRIES + 1):
        eval_results = eval_all(skill_results, jp_sections)
        failed = get_failed_tasks(eval_results)
        if not failed:
            print(f"  All skills passed eval (attempt {attempt + 1})")
            break
        if attempt < MAX_RETRIES:
            print(f"  Retrying {len(failed)} failed skills (attempt {attempt + 2})")
            for item in failed:
                sk = item["task_id"]
                if sk not in active_skills:
                    log.debug("Skipping retry for non-jp task: %s", sk)
                    continue
                inputs = _build_inputs(sk)
                if item.get("retry_hint"):
                    inputs["retry_hint"] = item["retry_hint"]
                _, result = _run_skill(sk, inputs)
                skill_results[sk] = result
        else:
            print(f"  [WARNING] {len(failed)} skills still failing after {MAX_RETRIES} retries")

    # ── Phase 6: save report ──────────────────────────────────────────────────
    print("\n[Phase 6] save report")
    from jp_report_writer import save_jp_report

    report_path = save_jp_report(
        ticker=ticker,
        edinet_code=edinet_code,
        company_name_ja=company_name_ja,
        fiscal_year_end=fiscal_year_end,
        doc_id=doc_id,
        five_year=five_year,
        skill_results=skill_results,
        eval_results=eval_results,
        recent_events=event_skill_results,
    )

    print(f"\n[State] Pipeline 完成")
    return report_path
