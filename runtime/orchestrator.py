import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_runner import run_agent
from eval_runner import eval_all, get_failed_tasks
from pipeline_state import PipelineState
from report_writer import save_report

MAX_RETRIES = 2

PHASE1_TASKS = [
    {"task_id": "business",   "skill": "business_analysis",
     "input_keys": ["item1_current", "item1_prior"]},
    {"task_id": "risk",       "skill": "risk_analysis",
     "input_keys": ["item1a_current", "item1a_prior"]},
    {"task_id": "mdna",       "skill": "mdna_analysis",
     "input_keys": ["item7_current", "item7_prior"]},
    {"task_id": "governance", "skill": "governance_analysis",
     "input_keys": ["partiii_current"]},
    # Footnotes sub-tasks (8 pieces)
    {"task_id": "fn_revenue",      "skill": "footnotes_revenue",
     "input_keys": ["fn_revenue"]},
    {"task_id": "fn_segment",      "skill": "footnotes_segment",
     "input_keys": ["fn_segment"]},
    {"task_id": "fn_receivables",  "skill": "footnotes_receivables",
     "input_keys": ["fn_receivables"]},
    {"task_id": "fn_assets",       "skill": "footnotes_assets",
     "input_keys": ["fn_assets"]},
    {"task_id": "fn_risk",         "skill": "footnotes_risk",
     "input_keys": ["fn_risk"]},
    {"task_id": "fn_pension",      "skill": "footnotes_pension",
     "input_keys": ["fn_pension"]},
    {"task_id": "fn_compensation", "skill": "footnotes_compensation",
     "input_keys": ["fn_compensation"]},
    {"task_id": "fn_tax",          "skill": "footnotes_tax",
     "input_keys": ["fn_tax"]},
    # Glossary
    {"task_id": "terms_glossary",  "skill": "terms_glossary",
     "input_keys": ["all_sections_md"]},
]

FOOTNOTES_TASK_IDS = [
    "fn_revenue", "fn_segment", "fn_receivables", "fn_assets",
    "fn_risk", "fn_pension", "fn_compensation", "fn_tax",
]

KEY_MAP = {
    "item1_current":    "current_section",
    "item1_prior":      "prior_section",
    "item1a_current":   "current_section",
    "item1a_prior":     "prior_section",
    "item7_current":    "current_section",
    "item7_prior":      "prior_section",
    "partiii_current":  "current_section",
    "fn_revenue":       "current_section",
    "fn_segment":       "current_section",
    "fn_receivables":   "current_section",
    "fn_assets":        "current_section",
    "fn_risk":          "current_section",
    "fn_pension":       "current_section",
    "fn_compensation":  "current_section",
    "fn_tax":           "current_section",
    "all_sections_md":  "all_sections_md",
}


def _run_task(task, sections, state, step_prefix, hint=""):
    step_key = f"{step_prefix}.{task['task_id']}"
    cached = state.get_result(step_key)
    if cached is not None:
        print(f"    ✓ {task['task_id']}（快取）")
        return task["task_id"], cached

    state.mark_running(step_key)
    inputs = {
        KEY_MAP[k]: sections.get(k)
        for k in task["input_keys"]
        if k in KEY_MAP
    }
    if hint:
        inputs["retry_hint"] = hint
    result = run_agent("analyst_agent", task["skill"], inputs,
                       task_label=step_key)
    state.mark_done(step_key, result)
    print(f"    ✓ {task['task_id']}")
    return task["task_id"], result


def _run_parallel(tasks, sections, state, step_prefix, hints=None):
    hints = hints or {}
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(
                _run_task, t, sections, state, step_prefix,
                hints.get(t["task_id"], ""),
            ): t
            for t in tasks
        }
        for fut in as_completed(futures):
            task_id, output = fut.result()
            results[task_id] = output
    return results


def _collect_footnotes_summary(results) -> dict:
    """Collect all fn_* results into a single summary dict for financial agent."""
    summary = {}
    for tid in FOOTNOTES_TASK_IDS:
        if tid in results and isinstance(results[tid], dict):
            summary[tid] = results[tid]
    return summary


def _run_financial(sections, footnotes_summary, state, step_key, hint=""):
    cached = state.get_result(step_key)
    if cached is not None:
        print(f"    ✓ financial（快取）")
        return "financial", cached

    state.mark_running(step_key)
    inputs = {
        "xbrl_json":         sections.get("xbrl_data", ""),
        "fs_md":             sections.get("item8_fs", ""),
        "footnotes_summary": json.dumps(footnotes_summary, ensure_ascii=False),
    }
    if hint:
        inputs["retry_hint"] = hint
    result = run_agent("analyst_agent", "financial_analysis", inputs,
                       task_label=step_key)
    state.mark_done(step_key, result)
    print(f"    ✓ financial")
    return "financial", result


def run_pipeline(ticker, sections, prior_sections=None, state=None):
    if state is None:
        state = PipelineState(ticker, sections.get("_year", 0),
                              prior_sections.get("_year") if prior_sections else None)

    # Merge prior year sections into current for cross-year comparison
    if prior_sections:
        sections["item1_prior"] = prior_sections.get("item1_current", "")
        sections["item1a_prior"] = prior_sections.get("item1a_current", "")
        sections["item7_prior"] = prior_sections.get("item7_current", "")

    # Phase 1: all agents in parallel (business/risk/mdna/governance + 8 footnotes)
    print("\n[Phase 1] business / risk / mdna / governance / footnotes x8")
    results = _run_parallel(PHASE1_TASKS, sections, state, "phase1")

    # Phase 2: financial (needs footnotes summary)
    print("\n[Phase 2] financial（三層 input）")
    fn_summary = _collect_footnotes_summary(results)
    _, fin = _run_financial(sections, fn_summary,
                            state, "phase2.financial")
    results["financial"] = fin

    # Phase 3: unusual_operations (needs footnotes + financial)
    print("\n[Phase 3] unusual_operations")
    uo_key = "phase3.unusual_operations"
    cached_uo = state.get_result(uo_key)
    if cached_uo is not None:
        results["unusual_operations"] = cached_uo
        print("    \u2713 unusual_operations（快取）")
    else:
        state.mark_running(uo_key)
        fn_summary = _collect_footnotes_summary(results)
        results["unusual_operations"] = run_agent(
            "analyst_agent", "unusual_operations", {
                "footnotes_summary": json.dumps(fn_summary, ensure_ascii=False),
                "financial_summary": json.dumps(results.get("financial", {}), ensure_ascii=False),
                "item8_footnotes_md": sections.get("item8_footnotes_md", ""),
                "business_summary": json.dumps(results.get("business", {}), ensure_ascii=False),
            },
            task_label=uo_key,
        )
        state.mark_done(uo_key, results["unusual_operations"])
        print("    \u2713 unusual_operations")

    # Eval loop
    eval_results = {}
    for attempt in range(1, MAX_RETRIES + 1):
        eval_step = f"eval_round{attempt}"
        # Check if this eval round is fully cached
        all_cached = all(
            state.is_done(f"{eval_step}.{t['task_id']}")
            for t in PHASE1_TASKS
        ) and state.is_done(f"{eval_step}.financial")

        if all_cached:
            print(f"\n[Eval {attempt}/{MAX_RETRIES}]（快取）")
            eval_results = {}
            for t in PHASE1_TASKS:
                ev = state.get_result(f"{eval_step}.{t['task_id']}")
                if ev:
                    eval_results[t["task_id"]] = ev
            fin_ev = state.get_result(f"{eval_step}.financial")
            if fin_ev:
                eval_results["financial"] = fin_ev
        else:
            print(f"\n[Eval {attempt}/{MAX_RETRIES}]")
            eval_results = eval_all(results, sections)
            # Save each eval result
            for tid, ev in eval_results.items():
                state.mark_eval(f"{eval_step}.{tid}", ev)

        failed = get_failed_tasks(eval_results)
        if not failed:
            print("    全部通過！")
            break
        if attempt == MAX_RETRIES:
            for f in failed:
                results[f["task_id"]]["low_confidence"] = True
            print(f"    {len(failed)} 個任務標記為 low_confidence")
            break

        # Retry failed tasks — use retry step prefix so results don't conflict
        retry_prefix = f"retry{attempt}"
        p1_failed = [f for f in failed if f["task_id"] != "financial"]
        fin_failed = next(
            (f for f in failed if f["task_id"] == "financial"), None
        )
        if p1_failed:
            retry_tasks = [
                t for t in PHASE1_TASKS
                if t["task_id"] in {f["task_id"] for f in p1_failed}
            ]
            hints = {f["task_id"]: f["retry_hint"] for f in p1_failed}
            print(f"    重試：{[t['task_id'] for t in retry_tasks]}")
            retried = _run_parallel(retry_tasks, sections, state, retry_prefix, hints)
            results.update(retried)
        if fin_failed:
            print("    重試：financial")
            fn_summary = _collect_footnotes_summary(results)
            _, fin = _run_financial(
                sections, fn_summary,
                state, f"{retry_prefix}.financial",
                hint=fin_failed["retry_hint"],
            )
            results["financial"] = fin

    # Prior year analysis
    prior_results = None
    if prior_sections:
        print("\n[前年度分析]")
        prior_results = _run_parallel(PHASE1_TASKS, prior_sections, state, "prior.phase1")
        prior_fn_summary = _collect_footnotes_summary(prior_results)
        _, prior_fin = _run_financial(
            prior_sections, prior_fn_summary,
            state, "prior.phase2.financial",
        )
        prior_results["financial"] = prior_fin

    # Synthesis
    print("\n[Synthesis]")
    synth_cross_key = "synthesis.cross_year"
    cached_cross = state.get_result(synth_cross_key)
    if cached_cross is not None:
        comparator = cached_cross
        print("    ✓ cross_year_compare（快取）")
    else:
        state.mark_running(synth_cross_key)
        comparator = run_agent(
            "analyst_agent",
            "cross_year_compare",
            {
                "current_analysis": json.dumps(results, ensure_ascii=False),
                "prior_analysis": json.dumps(prior_results, ensure_ascii=False)
                if prior_results
                else None,
            },
            task_label=synth_cross_key,
        )
        state.mark_done(synth_cross_key, comparator)
        print("    ✓ cross_year_compare")

    synth_insight_key = "synthesis.insight"
    cached_insight = state.get_result(synth_insight_key)
    if cached_insight is not None:
        insight = cached_insight
        print("    ✓ insight_synthesis（快取）")
    else:
        state.mark_running(synth_insight_key)
        insight = run_agent(
            "analyst_agent",
            "insight_synthesis",
            {
                "analysis_results": json.dumps(results, ensure_ascii=False),
                "comparator_result": json.dumps(comparator, ensure_ascii=False),
            },
            task_label=synth_insight_key,
        )
        state.mark_done(synth_insight_key, insight)
        print("    ✓ insight_synthesis")

    # Phase 5: completeness_check
    print("\n[Phase 5] completeness_check")
    cc_key = "phase5.completeness"
    cached_cc = state.get_result(cc_key)
    if cached_cc is not None:
        completeness = cached_cc
        print("    \u2713 completeness_check（快取）")
    else:
        state.mark_running(cc_key)
        eval_summary = {
            tid: {"total": r.get("total", 0), "pass": r.get("pass", False)}
            for tid, r in eval_results.items()
        }
        completeness = run_agent(
            "analyst_agent", "completeness_check", {
                "all_results": json.dumps(
                    {**results, "comparator": comparator, "insight": insight},
                    ensure_ascii=False,
                ),
                "eval_summary": json.dumps(eval_summary, ensure_ascii=False),
            },
            task_label=cc_key,
        )
        state.mark_done(cc_key, completeness)
        grade = completeness.get("overall_grade", "?")
        ready = completeness.get("ready_to_publish", False)
        print(f"    \u2713 grade={grade}  ready={ready}")

    synthesis = {"comparator": comparator, "insight": insight, "completeness": completeness}

    report_path = save_report(
        ticker, results, eval_results, synthesis,
        quarterly=sections.get("_quarterly", []),
    )

    print("  [State] Pipeline 完成（state 保留供 --only 使用）")

    return report_path
