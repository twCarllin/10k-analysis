"""test_sections_tasks_1b1.py — build_sections 治理 key 與 TW_PHASE1_TASKS（item 4.3，Spec §2.4／§2.5）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))  # agent_runner 為頂層模組

from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.pdf_doc import Page, PdfDoc  # noqa: E402
from runtime.tw_equity.sections import build_sections  # noqa: E402
from runtime.tw_equity.tables import TablesBundle  # noqa: E402
from runtime.tw_equity.tasks import TW_PHASE1_TASKS  # noqa: E402


def _doc(n: int = 3, text: str = "內容") -> PdfDoc:
    return PdfDoc(path=Path("x.pdf"), pages=[Page(i, f"{text}{i}", []) for i in range(1, n + 1)])


def _bundle() -> TablesBundle:
    return TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None,
        cost_detail_opex=None, consolidated_key_lines={}, parent_key_lines={},
        parent_cost_coverage=None, missing_tables=[], unit_notes={},
    )


def _build(ar: PdfDoc, gov: dict | None) -> dict[str, str]:
    return build_sections(ar, {}, _doc(), {}, _doc(), {}, bundle=_bundle(), gov_anchors=gov)


_BASE_KEYS = {
    "ar_letter", "ar_business", "ar_market", "ar_mdna", "ar_risk",
    "fs_note_related", "fs_note_contingent", "fs_note_disclosure",
    "fs_audit_kam", "tables_json",
}


def test_gov_anchors_give_range_text_and_keyset() -> None:
    r = _build(_doc(), {"ar_governance": PageRange(1, 2), "ar_capital": PageRange(3, 3)})
    assert set(r) == _BASE_KEYS | {"ar_governance", "ar_capital"}
    assert r["ar_governance"] == "內容1\f內容2"
    assert r["ar_capital"] == "內容3"


def test_gov_anchors_none_gives_empty_strings() -> None:
    r = _build(_doc(), None)
    assert set(r) == _BASE_KEYS | {"ar_governance", "ar_capital"}
    assert r["ar_governance"] == "" and r["ar_capital"] == ""


def test_long_governance_truncated_by_truncate_with_notice() -> None:
    from agent_runner import truncate_with_notice

    big = _doc(1, "字" * 13000)
    r = _build(big, {"ar_governance": PageRange(1, 1)})
    assert r["ar_governance"] == truncate_with_notice(big.text_of(1, 1), 12000)
    assert "截斷提示" in r["ar_governance"]


def test_governance_anchor_missing_is_empty_not_truncated() -> None:
    r = build_sections(_doc(1, "字" * 13000), {}, _doc(), {}, _doc(), {}, bundle=_bundle(),
                       gov_anchors={"ar_governance": None}, max_chars={"ar_governance": 3})
    assert r["ar_governance"] == ""


def test_tasks_seven_with_spec_input_keys_and_skip_if_empty() -> None:
    by_id = {t["task_id"]: t for t in TW_PHASE1_TASKS}
    assert len(TW_PHASE1_TASKS) == 7 and len(by_id) == 7
    assert all("skip_if_empty" in t for t in TW_PHASE1_TASKS)
    assert by_id["tw_cost_structure"]["skip_if_empty"] == []
    assert by_id["tw_financial_analysis"]["skip_if_empty"] == []
    fq = by_id["tw_footnotes_quality"]
    assert fq["skip_if_empty"] == fq["input_keys"]
    assert (by_id["tw_kam_analysis"]["input_keys"], by_id["tw_kam_analysis"]["skip_if_empty"]) == (
        ["fs_audit_kam", "tables_json"], ["fs_audit_kam"])
    assert (by_id["tw_business_analysis"]["input_keys"],
            by_id["tw_business_analysis"]["skip_if_empty"]) == (
        ["ar_letter", "ar_business", "tables_json"], [])
    assert (by_id["tw_customer_supplier"]["input_keys"],
            by_id["tw_customer_supplier"]["skip_if_empty"]) == (["tables_json", "ar_market"], [])
    assert (by_id["tw_governance_flags"]["input_keys"],
            by_id["tw_governance_flags"]["skip_if_empty"]) == (
        ["tables_json", "ar_governance", "ar_capital"], ["ar_governance", "ar_capital"])
