"""tasks.py — 台股財報 Phase 1 的 skill task 清單（Spec §2.6）。"""

from __future__ import annotations

TW_PHASE1_TASKS = [
    {"task_id": "tw_cost_structure", "skill": "tw_cost_structure",
     "input_keys": ["tables_json", "ar_market"]},
    {"task_id": "tw_financial_analysis", "skill": "tw_financial_analysis",
     "input_keys": ["tables_json", "ar_mdna", "ar_letter"]},
    {"task_id": "tw_footnotes_quality", "skill": "tw_footnotes_quality",
     "input_keys": ["fs_note_related", "fs_note_contingent", "fs_note_disclosure",
                    "fs_audit_kam", "ar_risk"]},
]
