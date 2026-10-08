"""tw_pipeline.py — 台股財報 pipeline（1A Spec §2.7；1B-2 Spec §2.6 兩年度）。

Entry point: run_tw_equity_pipeline(ticker, dry_run, base_dir, ocr) -> Path
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from runtime.tw_credit.adapters import AdapterError
from runtime.tw_equity import ocr as ocr_mod
from runtime.tw_equity import pdf_doc
from runtime.tw_equity.cross_year import build_cross_year, ocr_checks
from runtime.tw_equity.doc_anchor import (
    FS_HEADING_ANCHORS,
    GOVERNANCE_HEADING_ANCHORS,
    PARENT_FS_ANCHORS,
    find_annual_report_sections,
    find_heading_sections,
    find_sections,
)
from runtime.tw_equity.inputs import load_inputs
from runtime.tw_equity.report import save_tw_equity_report
from runtime.tw_equity.sections import build_sections
from runtime.tw_equity.tables import TablesBundle, extract_tables
from runtime.tw_equity.tasks import TW_PHASE1_TASKS

log = logging.getLogger(__name__)

_AR_REQUIRED = {
    "ar_letter", "ar_business", "ar_market", "ar_customers",
    "ar_mdna", "ar_fin_position", "ar_fin_performance",
}
_FS_REQUIRED = {"fs_bs", "fs_is"}
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


class _OcrChain:
    """OCR 鏈：Mistral 為主，其 AdapterError 時改 DI；兩者皆失敗拋 AdapterError。

    供應商於首次呼叫時才建構（設定缺漏同樣視為該 provider 失敗）。
    """

    def __call__(self, path: Path, pages: list[int]) -> dict:
        try:
            return ocr_mod.MistralPageOcr()(path, pages)
        except AdapterError as m_exc:
            mistral_reason = str(m_exc)
        try:
            return ocr_mod.DiPageOcr()(path, pages)
        except AdapterError as d_exc:
            raise AdapterError(
                f"OCR 失敗：Mistral：{mistral_reason}；Azure DI：{d_exc}"
            ) from d_exc


def _build_ocr() -> pdf_doc.OcrFn:
    """OCR 鏈建構點（測試於此注入假 OCR）。"""
    return _OcrChain()


@dataclass
class YearResult:
    bundle: TablesBundle
    sections: dict
    anchors_summary: dict
    skill_results: dict
    eval_results: dict
    skipped_tasks: list[str]
    garbled_pages: list[int] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    ocr_checks: list[dict] = field(default_factory=list)


def _analyze_year(
    *,
    ar_path: Path,
    fs_path: Path | None,
    ps_path: Path | None,
    roc_year: int,
    ocr_fn,
    ar_required: set[str],
    label: str = "tw-equity",
) -> YearResult:
    """Phase 2–7：載入、錨定、抽表、組段、跑 skill、eval loop。"""
    kw = {"ocr": ocr_fn} if ocr_fn is not None else {}

    print(f"[{label} Phase 2] load pdf")
    ar = pdf_doc.load_pdf(ar_path, **kw)
    fs = pdf_doc.load_pdf(fs_path, **kw) if fs_path else None
    ps = pdf_doc.load_pdf(ps_path, **kw) if ps_path else None

    print(f"[{label} Phase 3] find sections")
    ar_anchors = find_annual_report_sections(ar, required=ar_required)
    gov_anchors = find_heading_sections(ar, GOVERNANCE_HEADING_ANCHORS, required=set())
    fs_anchors = (find_heading_sections(fs, FS_HEADING_ANCHORS, required=_FS_REQUIRED)
                  if fs is not None else None)
    ps_anchors = (find_sections(ps, PARENT_FS_ANCHORS, required=_PS_REQUIRED,
                                order=list(PARENT_FS_ANCHORS))
                  if ps is not None else None)

    print(f"[{label} Phase 4] extract tables")
    bundle = extract_tables(ar, ar_anchors, fs, fs_anchors, ps, ps_anchors,
                            roc_year=roc_year, gov_anchors=gov_anchors)

    print(f"[{label} Phase 5] build sections")
    empty = pdf_doc.PdfDoc(path=Path(""), pages=[])
    sections = build_sections(
        ar, ar_anchors,
        fs if fs is not None else empty, fs_anchors or {},
        ps if ps is not None else empty, ps_anchors or {},
        bundle=bundle,
        gov_anchors=gov_anchors,
    )

    print(f"[{label} Phase 6] run skills")
    skipped_tasks: list[str] = []
    active: list[dict] = []
    for task in TW_PHASE1_TASKS:
        if task["skip_if_empty"] and not any(
            sections.get(k, "") for k in task["skip_if_empty"]
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

    print(f"[{label} Phase 7] eval loop")
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

    return YearResult(
        bundle=bundle,
        sections=sections,
        anchors_summary={**ar_anchors, **gov_anchors, **(fs_anchors or {}), **(ps_anchors or {})},
        skill_results=skill_results,
        eval_results=eval_results,
        skipped_tasks=skipped_tasks,
        garbled_pages=list(ar.garbled_pages),
        ocr_pages=list(ar.ocr_pages),
        ocr_checks=ocr_checks(ar, bundle, {**ar_anchors, **gov_anchors}),
    )


def run_tw_equity_pipeline(
    ticker: str,
    *,
    dry_run: bool = False,
    base_dir: Path | None = None,
    ocr: bool = False,
) -> Path:
    print(f"\n{'=' * 50}")
    print(f"  TW Equity Pipeline: {ticker}  (dry_run={dry_run})")
    print(f"{'=' * 50}")

    if dry_run:
        from agent_runner import set_dry_run
        set_dry_run(True)

    print("[tw-equity Phase 1] load inputs")
    inputs = load_inputs(ticker, base_dir=base_dir)
    ocr_fn = _build_ocr() if ocr else None

    current = _analyze_year(
        ar_path=inputs.annual_report_path,
        fs_path=inputs.consolidated_fs_path,
        ps_path=inputs.parent_fs_path,
        roc_year=inputs.roc_year,
        ocr_fn=ocr_fn,
        ar_required=_AR_REQUIRED,
    )

    prior_year: YearResult | None = None
    prior_dict: dict | None = None
    cross_year: dict | None = None
    cross_year_compare: dict | None = None
    if inputs.prior is not None:
        prior_year = _analyze_year(
            ar_path=inputs.prior.annual_report_path,
            fs_path=inputs.prior.consolidated_fs_path,
            ps_path=inputs.prior.parent_fs_path,
            roc_year=inputs.prior.roc_year,
            ocr_fn=ocr_fn,
            ar_required=set(),
            label="tw-equity prior",
        )
        print("[tw-equity Phase 7] cross year")
        cross_year = build_cross_year(
            current.bundle, prior_year.bundle,
            current_roc=inputs.roc_year, prior_roc=inputs.prior.roc_year,
        )
        try:
            from agent_runner import run_agent
            cross_year_compare = run_agent(
                "analyst_agent", "cross_year_compare",
                {
                    "current_analysis": json.dumps(
                        {**current.skill_results, "_cross_year_tables": cross_year},
                        ensure_ascii=False),
                    "prior_analysis": json.dumps(prior_year.skill_results, ensure_ascii=False),
                },
                task_label="cross_year_compare",
            )
        except Exception as exc:
            log.error("cross_year_compare failed: %s", exc)
            cross_year_compare = {"error": str(exc), "insufficient_data": True}
        prior_dict = {
            "bundle": prior_year.bundle,
            "anchors_summary": prior_year.anchors_summary,
            "skill_results": prior_year.skill_results,
            "skipped_tasks": prior_year.skipped_tasks,
            "garbled_pages": prior_year.garbled_pages,
            "ocr_pages": prior_year.ocr_pages,
            "ocr_checks": prior_year.ocr_checks,
        }

    print("[tw-equity Phase 8] save report")
    out_dir = base_dir / "data" / "output" / ticker if base_dir is not None else None
    report_path = save_tw_equity_report(
        inputs=inputs,
        bundle=current.bundle,
        anchors_summary=current.anchors_summary,
        skill_results=current.skill_results,
        eval_results=current.eval_results,
        skipped_tasks=current.skipped_tasks,
        cross_year_compare=cross_year_compare,
        cross_year=cross_year,
        garbled_pages=current.garbled_pages,
        ocr_pages=current.ocr_pages,
        ocr_checks=current.ocr_checks,
        prior=prior_dict,
        out_dir=out_dir,
    )
    print(f"\n  Report: {report_path}")
    return report_path
