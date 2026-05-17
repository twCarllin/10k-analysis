"""
jp_pipeline.py — End-to-end pipeline for Japanese EDINET 有価証券報告書.

Entry point: run_jp_pipeline(ticker, fiscal_year, fiscal_quarter, dry_run) -> Path

Phase 0   ensure_ticker_map_fresh + ticker_to_edinet + company info
Phase 1   find_filings_local(doc_types={"120"}) → filing matching period_end
Phase 2   download_filing → ZIP
Phase 3   TA3 extract_five_year_summary + TA4 split_filing_by_ixbrl
Phase 4   Run 7 jp skills via ThreadPoolExecutor (max_workers=4)
Phase 4.5 find_recent_events + jp_extraordinary_event skill for rinji
Phase 5   eval loop (max 2 retries, uses eval_runner)
Phase 6   save_jp_report → markdown + PDF (includes recent events section)

Also provides:
    fy_quarter_period_end(year, quarter, fy_end_month=3) -> date
    find_recent_events(edinet_code, months=12) -> list[dict]
    run_jp_event_pipeline(doc_id, dry_run=False) -> Path
"""

import calendar
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent

log = logging.getLogger(__name__)


def _last_day_of_month(year: int, month: int) -> date:
    """Return the last calendar day of the given year/month."""
    return date(year, month, calendar.monthrange(year, month)[1])


def fy_quarter_period_end(
    year: int,
    quarter: str,
    fy_end_month: int = 3,
) -> date:
    """Compute the period_end date for a JP fiscal year + quarter.

    Convention: "FY{year}" means the fiscal year ENDING in calendar year `year`,
    i.e. period_end falls in month `fy_end_month` of `year`.

    Examples (fy_end_month=3, the JP default):
      year=2026, quarter=Q4 → 2026-03-31  (year end)
      year=2026, quarter=Q3 → 2025-12-31
      year=2026, quarter=Q2 → 2025-09-30  (hanki end)
      year=2026, quarter=Q1 → 2025-06-30
    """
    if quarter == "Q4":
        return _last_day_of_month(year, fy_end_month)
    q_offset = {"Q1": 3, "Q2": 6, "Q3": 9}[quarter]
    end_month_raw = fy_end_month + q_offset
    end_month = ((end_month_raw - 1) % 12) + 1
    year_offset = (end_month_raw - 1) // 12
    target_year = year - 1 + year_offset
    return _last_day_of_month(target_year, end_month)

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
    fiscal_year: int,
    fiscal_quarter: str = "Q4",
    fy_end_month: int = 3,
    skip_skills: list[str] | None = None,
    dry_run: bool = False,
) -> Path:
    """
    Run the full Japanese EDINET pipeline for *ticker* (JPX 4-digit code).

    Q4: fetch yuho (doc_type=120) with period_end == fy_quarter_period_end(fiscal_year, "Q4")
        + TDNET earnings flash → full report
    Q2: fetch hanki (doc_type=160) with matching period_end
        + TDNET → mid report (no 5-year table from XBRL)
    Q1/Q3: only TDNET → short report

    In each case, if the EDINET filing has not yet been submitted, the pipeline
    falls back to TDNET-only and prints a placeholder in the report.

    dry_run: skip LLM calls and TDNET auto-scan (use mock outputs).

    Returns the Path of the generated Markdown report.
    """
    skip_skills = set(skip_skills or [])

    print(f"\n{'='*50}")
    print(f"  JP Pipeline: {ticker}  FY{fiscal_year} {fiscal_quarter}  (dry_run={dry_run})")
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

    # ── Phase 1: find the EDINET filing matching (fiscal_year, fiscal_quarter) ──
    print("\n[Phase 1] find filings")
    from jp_data_fetcher import find_filings_local

    target_period_end = fy_quarter_period_end(fiscal_year, fiscal_quarter, fy_end_month)
    print(f"  target period_end={target_period_end}  quarter={fiscal_quarter}")

    # Q4 = 有報 (120); Q2 = 半期報 (160); Q1/Q3 = no EDINET filing
    if fiscal_quarter == "Q4":
        edinet_doc_types = {"120"}
    elif fiscal_quarter == "Q2":
        edinet_doc_types = {"160"}
    else:
        edinet_doc_types = set()

    doc_id = ""
    fiscal_year_end = str(target_period_end)
    has_edinet_filing = False
    zip_path = None

    if edinet_doc_types:
        filings = find_filings_local(edinet_code, doc_types=edinet_doc_types,
                                     since=target_period_end - timedelta(days=30))
        # Filter to exact period_end match (allow ±30 days tolerance)
        tolerance = timedelta(days=30)
        matched = [
            f for f in filings
            if f.get("period_end") and
            abs((date.fromisoformat(str(f["period_end"])[:10]) - target_period_end).days) <= 30
        ]
        if matched:
            latest = matched[0]
            doc_id = latest["doc_id"]
            fiscal_year_end = str(latest["period_end"])[:10]
            has_edinet_filing = True
            print(f"  Filing found: {doc_id}  period_end={fiscal_year_end}")
        else:
            print(f"  [INFO] No EDINET filing found for period_end~{target_period_end}; "
                  "will use TDNET-only path with placeholder")
    else:
        print(f"  [INFO] Q1/Q3 has no EDINET yuho/hanki; using TDNET-only path")

    # ── Phase 2: download ZIP (only if EDINET filing found) ───────────────────
    from jp_data_fetcher import download_filing

    if has_edinet_filing:
        print("\n[Phase 2] download filing")
        zip_path = download_filing(doc_id)
        print(f"  ZIP: {zip_path}")
    else:
        print("\n[Phase 2] skip (no EDINET filing)")

    # ── Phase 3: parse XBRL + iXBRL ──────────────────────────────────────────
    five_year: dict = {}
    chapters: dict = {}

    if has_edinet_filing and zip_path is not None:
        print("\n[Phase 3] extract financials + narrative chapters")
        from jp_ixbrl_parser import extract_five_year_summary, split_filing_by_ixbrl

        if fiscal_quarter == "Q4":
            five_year = extract_five_year_summary(zip_path)
            # Update fiscal_year_end from XBRL (more authoritative)
            fiscal_year_end = five_year.get("fiscal_year_end", fiscal_year_end)
            print(f"  fiscal_year_end={fiscal_year_end}  "
                  f"accounting_standard={five_year.get('accounting_standard')}")
            if five_year.get("_warnings"):
                for w in five_year["_warnings"]:
                    print(f"  [WARNING] {w}")
        else:
            print("  [INFO] Q2 hanki: skipping 5-year XBRL extract (not in hanki)")

        chapters = split_filing_by_ixbrl(zip_path)
        print(f"  chapters extracted: {sorted(chapters.keys())}")
    else:
        print("\n[Phase 3] skip (no EDINET filing)")

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

    # ── Phase 4.5b: TDNET recent disclosures ────────────────────────────────
    # Auto-scan TDNET for quarter_end + 14..75 day window (skip in dry-run)
    print("\n[Phase 4.5b] find recent TDNET disclosures")
    if not dry_run:
        from jp_tdnet_scraper import scan_tdnet_range, find_tdnet_local
        tdnet_scan_start = target_period_end + timedelta(days=14)
        tdnet_scan_end = target_period_end + timedelta(days=75)
        # Clamp to today
        if tdnet_scan_end > date.today():
            tdnet_scan_end = date.today()
        if tdnet_scan_start <= tdnet_scan_end:
            print(f"  [auto-scan] TDNET {tdnet_scan_start} ~ {tdnet_scan_end}")
            scan_tdnet_range(tdnet_scan_start, tdnet_scan_end)

        tdnet_since = target_period_end + timedelta(days=14)
        tdnet_hits = find_tdnet_local(jpx_code=ticker, since=tdnet_since)
        # Limit to 30 entries to avoid bloating Section 8
        tdnet_hits = tdnet_hits[:30]
        print(f"  Found {len(tdnet_hits)} TDNET disclosures in past 30 days")

        for hit in tdnet_hits:
            disc_id = hit["disclosure_id"]
            try:
                _, tdnet_result = _run_skill("jp_tdnet_event", {
                    "title": hit.get("title", ""),
                    "category": hit.get("category", "other"),
                    "company_name": hit.get("company_name", ""),
                    "is_amendment": hit.get("is_amendment", False),
                })
                event_skill_results.append({
                    "doc_id": disc_id,
                    "submitted_at": str(hit.get("disclosure_date", "")),
                    "doc_type": "tdnet",
                    "category": hit.get("category", "other"),
                    "title": hit.get("title", ""),
                    "skill_result": tdnet_result,
                })
                print(f"  [ok] jp_tdnet_event for {disc_id}")
            except Exception as exc:
                log.error("TDNET event analysis failed for %s: %s", disc_id, exc)
                print(f"  [error] {disc_id}: {exc}")
    else:
        print("  [dry-run] skip find_tdnet_local")

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
        fiscal_quarter=fiscal_quarter,
        doc_id=doc_id,
        five_year=five_year,
        skill_results=skill_results,
        eval_results=eval_results,
        recent_events=event_skill_results,
    )

    print(f"\n[State] Pipeline 完成")
    return report_path


def run_tdnet_watch_pipeline(
    watchlist: list,
    since_minutes: int = 15,
    dry_run: bool = False,
) -> list:
    """Scan TDNET for recent disclosures and produce event reports for watched tickers.

    Phases:
      1. scan_tdnet_range(today) — ensure latest page is in DB.
      2. For each ticker in watchlist:
           hits = find_tdnet_local(jpx_code=ticker, since_minutes window)
           For each hit (skip if output file already exists — dedup):
               run jp_tdnet_event skill
               save_tdnet_event_report -> data/output/{jpx}_tdnet_{disclosure_id}.md

    Returns list of Paths of generated report files.
    """
    from datetime import timedelta

    print(f"\n{'='*50}")
    print(f"  JP TDNET Watch Pipeline: {watchlist}  "
          f"since_minutes={since_minutes}  dry_run={dry_run}")
    print(f"{'='*50}")

    if dry_run:
        from agent_runner import set_dry_run
        set_dry_run(True)

    today = date.today()
    since_dt = datetime.now() - timedelta(minutes=since_minutes)
    since_date = since_dt.date()

    # Phase 1: refresh today's TDNET index (skip in dry-run)
    if not dry_run:
        print(f"\n[Watch Phase 1] scan_tdnet_range({today})")
        from jp_tdnet_scraper import scan_tdnet_range
        scan_tdnet_range(today, today)
    else:
        print("\n[Watch Phase 1] [dry-run] skip scan_tdnet_range")

    # Phase 2: dispatch for each ticker
    from jp_tdnet_scraper import find_tdnet_local
    from jp_report_writer import save_tdnet_event_report

    out_dir = BASE_DIR / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_paths: list = []
    errors: list = []

    for jpx_code in watchlist:
        print(f"\n[Watch Phase 2] ticker={jpx_code}")
        try:
            hits = find_tdnet_local(jpx_code=jpx_code, since=since_date)
            # Filter to since_minutes window using disclosure_time
            hits_in_window = []
            for h in hits:
                # disclosure_date + disclosure_time form the full timestamp
                try:
                    disc_date = str(h.get("disclosure_date", ""))[:10]
                    disc_time = str(h.get("disclosure_time", "00:00"))
                    disc_dt_str = f"{disc_date} {disc_time}"
                    disc_dt = datetime.strptime(disc_dt_str, "%Y-%m-%d %H:%M")
                    if disc_dt >= since_dt:
                        hits_in_window.append(h)
                except (ValueError, TypeError):
                    # If parsing fails, include conservatively
                    hits_in_window.append(h)

            print(f"  Found {len(hits_in_window)} disclosures in last {since_minutes} min")

            for hit in hits_in_window:
                disc_id = hit["disclosure_id"]

                # Dedup: skip if PDF (last step) already exists
                out_pdf = out_dir / f"{jpx_code}_tdnet_{disc_id}.pdf"
                if out_pdf.exists():
                    log.debug("Watch dedup: skipping %s (report already exists)", disc_id)
                    print(f"  [skip] {disc_id} (已處理)")
                    continue

                print(f"  Processing {disc_id}: {hit.get('title', '')[:60]}")
                try:
                    skill_result = _run_skill("jp_tdnet_event", {
                        "title": hit.get("title", ""),
                        "category": hit.get("category", "other"),
                        "company_name": hit.get("company_name", ""),
                        "is_amendment": hit.get("is_amendment", False),
                    })[1]
                    path = save_tdnet_event_report(
                        disclosure=hit,
                        skill_result=skill_result,
                        out_dir=out_dir,
                    )
                    report_paths.append(path)
                    print(f"  [ok] {disc_id} -> {path.name}")
                except Exception as exc:
                    log.error("TDNET event failed for %s: %s", disc_id, exc)
                    errors.append((jpx_code, disc_id, str(exc)))
                    print(f"  [error] {disc_id}: {exc}")

        except Exception as exc:
            log.error("Watch pipeline failed for %s: %s", jpx_code, exc)
            errors.append((jpx_code, "", str(exc)))
            print(f"  [error] ticker={jpx_code}: {exc}")

    # Summary
    print(f"\n{'='*50}")
    print(f"  Watch完成: {len(report_paths)} 份報告")
    if errors:
        print(f"  失敗 {len(errors)} 件：{errors}")
    print(f"{'='*50}")

    return report_paths


def run_logmi_call_pipeline(jpx_code: str, dry_run: bool = False) -> "Path":
    """Fetch latest logmi earnings call transcript for jpx_code and run jp_earnings_call skill.

    Phases:
      1. Look up company_name_ja from ticker_map.
      2. scrape_logmi_transcript(jpx_code, company_name_ja) — requires Stagehand (not run in dry-run).
      3. parse_logmi_transcript.
      4. Run jp_earnings_call skill.
      5. save_earnings_call_report -> short md + pdf.

    Note: Stagehand is not actually invoked in dry-run mode.
    Returns the Path of the generated Markdown report.
    """
    print(f"\n{'='*50}")
    print(f"  JP Logmi Call Pipeline: {jpx_code}  (dry_run={dry_run})")
    print(f"{'='*50}")

    if dry_run:
        from agent_runner import set_dry_run
        set_dry_run(True)

    company_info = _get_company_info(jpx_code)
    company_name_ja = company_info.get("company_name_ja", jpx_code)
    print(f"  {jpx_code}  company={company_name_ja}")

    if dry_run:
        print("\n[Call Phase 1] [dry-run] skip logmi Stagehand scrape")
        transcript_dict = {
            "title": f"[dry-run] {company_name_ja} 決算説明会",
            "date": date.today().isoformat(),
            "presentation": "[dry-run] presentation placeholder",
            "qa": [],
        }
    else:
        print("\n[Call Phase 1] scrape_logmi_transcript")
        import asyncio
        from transcript_scraper.logmi_scraper import scrape_logmi_transcript
        from transcript_scraper.logmi_parser import parse_logmi_transcript

        raw = asyncio.run(
            scrape_logmi_transcript(jpx_code=jpx_code, company_name_ja=company_name_ja)
        )
        if raw is None:
            raise RuntimeError(f"logmi: transcript not found for {jpx_code} ({company_name_ja})")

        print(f"  Scraped: {raw.get('title', '')} ({raw.get('date', '')})")
        transcript_dict = parse_logmi_transcript(
            raw_text=raw.get("raw_text", ""),
            speakers=raw.get("speakers", []),
        )
        transcript_dict.update({
            "title": raw.get("title", ""),
            "date": raw.get("date", ""),
        })

    print("\n[Call Phase 2] jp_earnings_call skill")
    skill_result = _run_skill("jp_earnings_call", {"transcript": transcript_dict})[1]
    status = "error" if "error" in skill_result else "ok"
    print(f"  [{status}] jp_earnings_call")

    print("\n[Call Phase 3] save_earnings_call_report")
    from jp_report_writer import save_earnings_call_report
    report_path = save_earnings_call_report(
        transcript=transcript_dict,
        skill_result=skill_result,
        jpx_code=jpx_code,
        company_name_ja=company_name_ja,
    )
    print(f"\n  Earnings call report: {report_path}")
    return report_path
