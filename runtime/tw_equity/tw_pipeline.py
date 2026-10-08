"""tw_pipeline.py — 台股財報 Phase 1A pipeline（Spec §2.7）。

Entry point: run_tw_equity_pipeline(ticker, dry_run, base_dir) -> Path
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime.tw_equity import pdf_doc
from runtime.tw_equity.doc_anchor import (
    ANNUAL_REPORT_ANCHORS,
    FS_ANCHORS,
    PARENT_FS_ANCHORS,
    find_sections,
)
from runtime.tw_equity.inputs import load_inputs
from runtime.tw_equity.report import save_tw_equity_report
from runtime.tw_equity.sections import build_sections
from runtime.tw_equity.tables import extract_tables
from runtime.tw_equity.tasks import TW_PHASE1_TASKS

log = logging.getLogger(__name__)

_AR_REQUIRED = {
    "ar_letter", "ar_business", "ar_market", "ar_customers",
    "ar_mdna", "ar_fin_position", "ar_fin_performance",
}
_FS_REQUIRED = {"fs_bs", "fs_is", "fs_note_expense_nature"}
_PS_REQUIRED = {"ps_is", "ps_cogs_detail"}

MAX_RETRIES = 2


def _build_inputs(task: dict, sections: dict) -> dict:
    return {k: sections.get(k, "") for k in task["input_keys"]}


def _run_task(task: dict, inputs: dict) -> tuple[str, dict]:
    from agent_runner import run_agent
    result = run_agent("analyst_agent", task["skill"], inputs, task_label=task["task_id"])
    return task["task_id"], result


def _run_task_safe(task: dict, inputs: dict) -> dict:
    """重試路徑用：例外降級為 {"error": ...}，與 Phase 6 首輪一致。"""
    try:
        return _run_task(task, inputs)[1]
    except Exception as exc:
        log.error("Skill %s retry failed: %s", task["task_id"], exc)
        return {"error": str(exc), "insufficient_data": True}


def run_tw_equity_pipeline(
    ticker: str,
    *,
    dry_run: bool = False,
    base_dir: Path | None = None,
) -> Path:
    print(f"\n{'=' * 50}")
    print(f"  TW Equity Pipeline: {ticker}  (dry_run={dry_run})")
    print(f"{'=' * 50}")

    if dry_run:
        from agent_runner import set_dry_run
        set_dry_run(True)

    print("[tw-equity Phase 1] load inputs")
    inputs = load_inputs(ticker, base_dir=base_dir)

    print("[tw-equity Phase 2] load pdf")
    ar = pdf_doc.load_pdf(inputs.annual_report_path)
    fs = pdf_doc.load_pdf(inputs.consolidated_fs_path) if inputs.consolidated_fs_path else None
    ps = pdf_doc.load_pdf(inputs.parent_fs_path) if inputs.parent_fs_path else None

    print("[tw-equity Phase 3] find sections")
    ar_anchors = find_sections(ar, ANNUAL_REPORT_ANCHORS, required=_AR_REQUIRED,
                               order=list(ANNUAL_REPORT_ANCHORS))
    fs_anchors = (find_sections(fs, FS_ANCHORS, required=_FS_REQUIRED, order=list(FS_ANCHORS))
                  if fs is not None else None)
    ps_anchors = (find_sections(ps, PARENT_FS_ANCHORS, required=_PS_REQUIRED,
                                order=list(PARENT_FS_ANCHORS))
                  if ps is not None else None)

    print("[tw-equity Phase 4] extract tables")
    bundle = extract_tables(ar, ar_anchors, fs, fs_anchors, ps, ps_anchors,
                            roc_year=inputs.roc_year)

    print("[tw-equity Phase 5] build sections")
    empty = pdf_doc.PdfDoc(path=Path(""), pages=[])
    sections = build_sections(
        ar, ar_anchors,
        fs if fs is not None else empty, fs_anchors or {},
        ps if ps is not None else empty, ps_anchors or {},
        bundle=bundle,
    )

    print("[tw-equity Phase 6] run skills")
    skipped_tasks: list[str] = []
    active: list[dict] = []
    for task in TW_PHASE1_TASKS:
        if task["task_id"] == "tw_footnotes_quality" and not any(
            sections.get(k, "") for k in task["input_keys"]
        ):
            skipped_tasks.append(task["task_id"])
            print(f"  [skip] {task['task_id']}（輸入全空）")
            continue
        active.append(task)

    skill_results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_run_task, t, _build_inputs(t, sections)): t for t in active}
        for fut, t in futures.items():
            try:
                name, result = fut.result()
            except Exception as exc:
                log.error("Skill %s failed: %s", t["task_id"], exc)
                name, result = t["task_id"], {"error": str(exc), "insufficient_data": True}
            skill_results[name] = result
            print(f"  [{'error' if 'error' in result else 'ok'}] {name}")

    print("[tw-equity Phase 7] eval loop")
    from eval_runner import eval_all, get_failed_tasks

    eval_sections = {**sections, **{t["task_id"]: sections["tables_json"] for t in TW_PHASE1_TASKS}}
    by_id = {t["task_id"]: t for t in active}
    eval_results: dict = {}
    for attempt in range(MAX_RETRIES + 1):
        eval_results = eval_all(skill_results, eval_sections)
        failed = get_failed_tasks(eval_results)
        if not failed:
            print(f"  All skills passed eval (attempt {attempt + 1})")
            break
        if attempt < MAX_RETRIES:
            print(f"  Retrying {len(failed)} failed skills (attempt {attempt + 2})")
            for item in failed:
                task = by_id.get(item["task_id"])
                if task is None:
                    continue
                task_inputs = _build_inputs(task, sections)
                if item.get("retry_hint"):
                    task_inputs["retry_hint"] = item["retry_hint"]
                skill_results[task["task_id"]] = _run_task_safe(task, task_inputs)
        else:
            print(f"  [WARNING] {len(failed)} skills still failing after {MAX_RETRIES} retries")

    print("[tw-equity Phase 8] save report")
    out_dir = base_dir / "data" / "output" / ticker if base_dir is not None else None
    report_path = save_tw_equity_report(
        inputs=inputs,
        bundle=bundle,
        anchors_summary={**ar_anchors, **(fs_anchors or {}), **(ps_anchors or {})},
        skill_results=skill_results,
        eval_results=eval_results,
        skipped_tasks=skipped_tasks,
        out_dir=out_dir,
    )
    print(f"\n  Report: {report_path}")
    return report_path
