import json

from agent_runner import run_agent, truncate_with_notice

PASS_THRESHOLD = 70

REQUIRED_KEYS = {
    "business":        ["business_segments", "revenue_drivers", "insufficient_data"],
    "risk":            ["risks", "top_3", "insufficient_data"],
    "mdna":            ["performance_drivers", "mgmt_tone", "insufficient_data"],
    "governance":      ["audit_opinion", "exec_compensation", "insufficient_data"],
    "financial":       ["metrics", "quality_flags", "trend_summary", "insufficient_data"],
    "fn_revenue":      ["revenue_recognition", "insufficient_data"],
    "fn_segment":      ["segments", "insufficient_data"],
    "fn_receivables":  ["securitization", "debt_structure", "insufficient_data"],
    "fn_assets":       ["goodwill", "inventory", "insufficient_data"],
    "fn_risk":         ["contingencies", "insufficient_data"],
    "fn_pension":      ["funded_status", "assumptions", "insufficient_data"],
    "fn_compensation": ["sbc", "insufficient_data"],
    "fn_tax":          ["effective_rate", "deferred_tax", "insufficient_data"],
    "fn_combined":     ["revenue_recognition", "segments", "debt_structure", "goodwill", "contingencies", "sbc", "effective_rate", "insufficient_data"],
    "terms_glossary":  ["terms", "insufficient_data"],
    "unusual_operations": ["unusual_items", "summary", "insufficient_data"],
    "segment_trend": ["segment_table", "insufficient_data"],
    "three_statement_cross": ["checks", "overall_signals", "insufficient_data"],
    "competitor_mapping": ["named_competitors", "market_position", "disclosure_quality", "mode", "insufficient_data"],
    "supply_chain": ["supply_chain_risks", "overall_risk_level", "trend", "insufficient_data"],
}

HARD_RULES = {
    "fn_revenue": [
        lambda src, out: (
            "revenue recognition" in src.lower()
            and not out.get("revenue_recognition", {}).get("policy")
        ),
    ],
    "financial": [
        lambda src, out: not out.get("metrics", {}),
    ],
    "three_statement_cross": [
        # If financial_summary has real content but overall_signals is empty → fail
        lambda src, out: (
            len(src) > 100 and not out.get("overall_signals")
        ),
    ],
    "competitor_mapping": [
        # If section has real content but named_competitors is empty → skill failed to extract
        lambda src, out: len(src) > 1000 and not out.get("named_competitors"),
    ],
    "supply_chain": [
        lambda src, out: (
            "supply chain" in src.lower()
            and not out.get("supply_chain_risks")
        ),
    ],
}


def _hard_rule_check(task_id, output, source_input) -> str | None:
    for rule in HARD_RULES.get(task_id, []):
        if rule(source_input, output):
            return f"hard rule failed: {task_id}"
    return None


def _schema_score(task_id, output) -> int:
    required = REQUIRED_KEYS.get(task_id, [])
    missing = [k for k in required if k not in output]
    empty = [k for k in required if output.get(k) in ("", None, [])]
    return max(0, 25 - len(missing) * 8 - len(empty) * 4)


def eval_single(task_id, skill_output, source_input) -> dict:
    hard_fail = _hard_rule_check(task_id, skill_output, source_input)
    if hard_fail:
        return {
            "pass": False,
            "total": 0,
            "retry_hint": f"[Hard rule] {hard_fail}",
        }
    schema_score = _schema_score(task_id, skill_output)
    eval_result = run_agent(
        "analyst_agent",
        "eval_analysis",
        {
            "skill_name": task_id,
            "skill_output": json.dumps(skill_output, ensure_ascii=False),
            "source_input": truncate_with_notice(source_input or "", 3000),
        },
        task_label=f"eval.{task_id}",
    )
    if "scores" in eval_result:
        eval_result["scores"]["schema_completeness"] = schema_score
        total = eval_result.get("llm_subtotal", 0) + schema_score
        eval_result["total"] = total
        eval_result["pass"] = total >= PASS_THRESHOLD
    return eval_result


def eval_all(results, sections, filing_type: str = "10-K", quarter=None) -> dict:
    """Evaluate all task results, return dict of task_id -> eval_result."""
    source_map = {
        "business":        sections.get("item1_current", ""),
        "risk":            sections.get("item1a_current", ""),
        "mdna":            sections.get("item7_current", ""),
        "governance":      sections.get("partiii_current", ""),
        "financial":       sections.get("xbrl_data", ""),
        "fn_revenue":      sections.get("fn_revenue", ""),
        "fn_segment":      sections.get("fn_segment", ""),
        "fn_receivables":  sections.get("fn_receivables", ""),
        "fn_assets":       sections.get("fn_assets", ""),
        "fn_risk":         sections.get("fn_risk", ""),
        "fn_pension":      sections.get("fn_pension", ""),
        "fn_compensation": sections.get("fn_compensation", ""),
        "fn_tax":          sections.get("fn_tax", ""),
        "fn_combined":     sections.get("fn_combined", ""),
        "terms_glossary":  sections.get("all_sections_md", ""),
        "unusual_operations": sections.get("item8_footnotes_md", ""),
        "segment_trend":     sections.get("xbrl_data", ""),
        "three_statement_cross": sections.get("xbrl_data", ""),
        "competitor_mapping": sections.get("item1_current", "") or sections.get("item1_prior_as_current", ""),
        "supply_chain":       sections.get("item1a_current", ""),
    }
    # 10-Q: skip governance evaluation and tasks without meaningful input
    skip_tasks = {"governance", "business", "risk"} if filing_type == "10-Q" else set()
    if filing_type == "10-Q":
        skip_tasks |= {"segment_trend"}
    if quarter in ("Q2", "Q3"):
        skip_tasks |= {"terms_glossary", "competitor_mapping", "supply_chain"}

    eval_results = {}
    for task_id, output in results.items():
        if task_id in skip_tasks:
            continue
        if isinstance(output, dict) and "error" not in output:
            source = source_map.get(task_id, "")
            eval_results[task_id] = eval_single(task_id, output, source)
            status = "PASS" if eval_results[task_id].get("pass") else "FAIL"
            score = eval_results[task_id].get("total", "?")
            print(f"    {task_id}: {status} ({score})")
    return eval_results


def get_failed_tasks(eval_results) -> list[dict]:
    """Return list of failed tasks with retry hints."""
    failed = []
    for task_id, ev in eval_results.items():
        if not ev.get("pass", False):
            failed.append({
                "task_id": task_id,
                "retry_hint": ev.get("retry_hint", ""),
            })
    return failed
