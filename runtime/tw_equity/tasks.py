"""tasks.py — 台股財報 Phase 1 的 skill task 清單（Spec §2.5／§2.6）。

skip_if_empty：非空且這些 key 全為空字串 → 跳過該 task（記 skipped_tasks）。
"""

from __future__ import annotations

TW_PHASE1_TASKS = [
    {"task_id": "tw_cost_structure", "skill": "tw_cost_structure",
     "input_keys": ["tables_json", "ar_market"], "skip_if_empty": []},
    {"task_id": "tw_financial_analysis", "skill": "tw_financial_analysis",
     "input_keys": ["tables_json", "ar_mdna", "ar_letter"], "skip_if_empty": []},
    {"task_id": "tw_footnotes_quality", "skill": "tw_footnotes_quality",
     "input_keys": ["fs_note_related", "fs_note_contingent", "fs_note_disclosure",
                    "fs_audit_kam", "ar_risk"],
     "skip_if_empty": ["fs_note_related", "fs_note_contingent", "fs_note_disclosure",
                       "fs_audit_kam", "ar_risk"]},
    {"task_id": "tw_kam_analysis", "skill": "tw_kam_analysis",
     "input_keys": ["fs_audit_kam", "tables_json"], "skip_if_empty": ["fs_audit_kam"]},
    {"task_id": "tw_business_analysis", "skill": "tw_business_analysis",
     "input_keys": ["ar_letter", "ar_business", "tables_json"], "skip_if_empty": []},
    {"task_id": "tw_customer_supplier", "skill": "tw_customer_supplier",
     "input_keys": ["tables_json", "ar_market"], "skip_if_empty": []},
    {"task_id": "tw_governance_flags", "skill": "tw_governance_flags",
     "input_keys": ["tables_json", "ar_governance", "ar_capital"],
     "skip_if_empty": ["ar_governance", "ar_capital"]},
]
