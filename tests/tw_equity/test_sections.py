"""build_sections 單元測試（契約：Spec §2.5）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))  # agent_runner 為頂層模組

from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.pdf_doc import Page, PdfDoc  # noqa: E402
from runtime.tw_equity.sections import build_sections  # noqa: E402
from runtime.tw_equity.tables import TablesBundle  # noqa: E402

WHITELIST = {
    "ar_letter", "ar_business", "ar_market", "ar_mdna", "ar_risk",
    "fs_note_related", "fs_note_contingent", "fs_note_disclosure",
    "fs_audit_kam", "tables_json",
}
AR_KEYS = ["ar_letter", "ar_business", "ar_market", "ar_mdna", "ar_risk"]
FS_KEYS = ["fs_note_related", "fs_note_contingent", "fs_note_disclosure", "fs_audit_kam"]


def _doc(n: int = 3, text: str = "內容") -> PdfDoc:
    return PdfDoc(path=Path("x.pdf"), pages=[Page(i, f"{text}{i}", []) for i in range(1, n + 1)])


def _bundle() -> TablesBundle:
    return TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None,
        cost_detail_opex=None, consolidated_key_lines={"營業收入": [1.5, 2.0]},
        parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=["T1"], unit_notes={"T1": "新台幣仟元"},
    )


def _full(doc_keys, rng=PageRange(1, 2)):
    return {k: rng for k in doc_keys}


def test_full_input_keys_equal_whitelist():
    r = build_sections(_doc(), _full(AR_KEYS), _doc(), _full(FS_KEYS), _doc(), {}, bundle=_bundle())
    assert set(r) == WHITELIST
    assert r["ar_letter"] == "內容1\f內容2"


def test_missing_anchor_gives_empty_string():
    ar_a = _full(AR_KEYS)
    ar_a["ar_risk"] = None
    del ar_a["ar_market"]
    r = build_sections(_doc(), ar_a, _doc(), {}, _doc(), {}, bundle=_bundle())
    assert set(r) == WHITELIST
    assert r["ar_risk"] == "" and r["ar_market"] == ""
    assert r["fs_audit_kam"] == ""


def test_long_text_truncated_by_truncate_with_notice():
    from agent_runner import truncate_with_notice

    big = _doc(1, "字" * 13000)
    r = build_sections(big, {"ar_letter": PageRange(1, 1)}, _doc(), {}, _doc(), {}, bundle=_bundle())
    assert r["ar_letter"] == truncate_with_notice(big.text_of(1, 1), 12000)
    assert "截斷提示" in r["ar_letter"]


def test_tables_json_not_truncated_by_max_chars():
    b = _bundle()
    r = build_sections(_doc(), {}, _doc(), {}, _doc(), {}, bundle=b, max_chars={"tables_json": 5})
    assert r["tables_json"] == json.dumps(b.to_dict(), ensure_ascii=False)
    assert len(r["tables_json"]) > 5


def test_max_chars_on_missing_anchor_key_stays_empty():
    r = build_sections(_doc(), {"ar_letter": None}, _doc(), {}, _doc(), {},
                       bundle=_bundle(), max_chars={"ar_letter": 3})
    assert r["ar_letter"] == ""
