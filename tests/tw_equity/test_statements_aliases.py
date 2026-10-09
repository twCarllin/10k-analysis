"""別名擴充（fs-generalize item 2.3，Spec §4、F11）。

契約 row：
  A1: map_key("is","利息費用") 非 None 且為 finance_costs（IS 財務成本別名）；CF 端為 finance_costs_adj
  A2: map_key("bs","負債與權益總計") == total_liabilities_and_equity
  A3: map_key("is","營業淨利") == operating_income
  A4: map_key("cf","匯率變動對現金及約當現金之影響") == fx_effect
  A5: map_key("bs","應付帳款-關係人") != accounts_payable
  A6: [邊界] 3653 年度 22/22（擁有者為 test_statements_h1_rows；此處只寬鬆檢查）
  （驗收輸出 all_pass_files>=26 需 tw_report/ PDF，不進 pytest，由 fs_acceptance CLI 驗）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections  # noqa: E402
from runtime.tw_equity.statements import extract_statements, map_key  # noqa: E402


def test_interest_expense_maps_to_finance_costs() -> None:
    assert map_key("is", "利息費用", None) == "finance_costs"
    assert map_key("cf", "利息費用", None) == "finance_costs_adj"


def test_total_liabilities_and_equity_alias() -> None:
    assert map_key("bs", "負債與權益總計", None) == "total_liabilities_and_equity"


def test_operating_net_income_alias() -> None:
    assert map_key("is", "營業淨利", None) == "operating_income"


def test_fx_effect_alias() -> None:
    assert map_key("cf", "匯率變動對現金及約當現金之影響", None) == "fx_effect"


def test_related_party_payable_not_merged_into_accounts_payable() -> None:
    assert map_key("bs", "應付帳款-關係人", None) != "accounts_payable"


def test_3653_annual_checks_still_all_pass() -> None:
    doc = pdf_doc.from_json(json.loads((ROOT / "tests/fixtures/tw_equity/fs_3653_pages.json").read_text(encoding="utf-8")))
    led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))
    assert all(c.passed is True for c in led.checks)


# ── Task 3（Spec §8.1.5、§8.2） ───────────────────────────────────────────────

from runtime.tw_equity.statements import IS_SECTION_HEADERS, parse_statement_lines  # noqa: E402


def _is_rows(labels: list[str]):
    lines = [(1, 6 + i, f"{lb} 1,000 100 900 100 1,000 100 900 100") for i, lb in enumerate(labels)]
    rows, _, _ = parse_statement_lines(lines, "is", section_headers=IS_SECTION_HEADERS)
    return rows


def test_sales_revenue_alias_only_without_main_revenue_row() -> None:
    both = _is_rows(["營業收入", "銷貨收入"])
    assert [(r.label, r.key) for r in both] == [("營業收入", "revenue"), ("銷貨收入", None)]
    for variant in ("銷貨收入", "銷貨收入-淨額", "銷貨收入淨額"):
        assert _is_rows([variant])[0].key == "revenue", variant


def test_continuing_ops_net_income_alias_only_without_main_row() -> None:
    both = _is_rows(["本期淨利", "繼續營業單位本期淨利"])
    assert [r.key for r in both] == ["net_income", None]
    assert _is_rows(["繼續營業單位本期淨利"])[0].key == "net_income"


def test_nonoperating_section_total_label_maps_to_nonoperating_total() -> None:
    assert map_key("is", "合計", "營業外收入及支出") == "nonoperating_total"
    assert map_key("is", "淨額", "營業外收入及支出") == "nonoperating_total"
    assert map_key("is", "合計", None) is None


def test_revenue_total_becomes_revenue_when_no_main_revenue_row() -> None:
    assert [r.key for r in _is_rows(["銷貨收入", "其他營業收入", "營業收入合計"])] == [None, None, "revenue"]
    assert _is_rows(["營業收入合計"])[0].key == "revenue"
    both = _is_rows(["營業收入", "營業收入合計"])
    assert [r.key for r in both] == ["revenue", "revenue_total"]
