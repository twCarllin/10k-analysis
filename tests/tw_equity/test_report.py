"""save_tw_equity_report 單元測試（契約：Spec §2.8、task item 4.3）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))  # report_writer 為頂層模組

import pytest  # noqa: E402

from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.inputs import TwEquityInputs  # noqa: E402
from runtime.tw_equity.report import save_tw_equity_report  # noqa: E402
from runtime.tw_equity.tables import (  # noqa: E402
    CostDetail, CostRow, CustomerEntry, CustomerTable, CustomerYear,
    ExpenseNature, ExpenseNatureRow, GuaranteeRow, GuaranteesLoans, InventoryNote,
    InventoryRow, PledgeRow, PledgeTable, ShareholderRow, TablesBundle, TopShareholders,
    TwoYearRow, TwoYearTable,
)

FIXTURE = json.loads(
    (ROOT / "tests/fixtures/tw_equity/report_skill_results.json").read_text(encoding="utf-8")
)
FULL = FIXTURE["full"]
PARTIAL = FIXTURE["partial"]
NO_RETURN = "（skill 未回傳）"
NO_COVERAGE = "無法計算（缺個體／合併營業成本）"


def _inputs() -> TwEquityInputs:
    return TwEquityInputs(
        ticker="3653", company_name="健策", fiscal_year=2025,
        annual_report_path=Path("x.pdf"), consolidated_fs_path=None, parent_fs_path=None,
    )


def _two_year(label: str) -> TwoYearTable:
    return TwoYearTable("新台幣仟元", "114年度", "113年度",
                        [TwoYearRow(label, 1000.0, 800.0, 200.0, 25.0)])


def _cost(kind: str, label: str) -> CostDetail:
    return CostDetail(kind, "新台幣仟元", ["114年度"], [CostRow(label, [123.0])])


def _full_bundle() -> TablesBundle:
    cust = CustomerTable("sales", "unknown", [
        CustomerYear("113年度", [CustomerEntry(1, "客戶甲", 500.0, 10.0, "無")], 5.0, 5000.0),
        CustomerYear("114年度", [CustomerEntry(1, "客戶甲", 600.0, 12.0, "無")], 6.0, 5000.0),
    ])
    return TablesBundle(
        fin_position=_two_year("T7A列"), fin_performance=_two_year("T7B列"),
        customers_sales=cust, customers_purchase=cust,
        production_sales=None,
        expense_nature=ExpenseNature("仟元", ["114年度"], [
            ExpenseNatureRow("T4列", [1.0], [2.0], [3.0])]),
        inventory=InventoryNote("仟元", ["114年度"], [
            InventoryRow("T5列", [10.0], [-1.0], [9.0])], [4.0]),
        cost_detail_cogs=_cost("cogs", "T1列"), cost_detail_mfg=_cost("mfg", "T2列"),
        cost_detail_opex=_cost("opex", "T3列"),
        consolidated_key_lines={}, parent_key_lines={},
        parent_cost_coverage=0.85, missing_tables=[], unit_notes={},
        guarantees_loans=GuaranteesLoans("none", "table", [GuaranteeRow(
            1, "T9保證人", "T9被保人", "(2)", 100.0, 90.0, 80.0, 70.0, None, 5.5, 200.0,
            "Y", "N", "N")], [], 5.5),
        pledges=PledgeTable("rows", [PledgeRow(
            "T10質押人", "借款", "114.01.01", "銀行", "無", 1000.0, 10.0, 35.0, 5000.0)], 35.0),
        top_shareholders=TopShareholders(
            [ShareholderRow("T10股東", False, 9000.0, 20.0, None, None, None, None)], []),
    )


def _missing_bundle(coverage=None) -> TablesBundle:
    return TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=coverage,
        missing_tables=["T1", "T4", "T8_sales"], unit_notes={},
    )


def _run(tmp_path, bundle, skill_results, anchors=None, skipped=None) -> tuple[Path, str]:
    md = save_tw_equity_report(
        inputs=_inputs(), bundle=bundle,
        anchors_summary=anchors if anchors is not None else {},
        skill_results=skill_results, eval_results={"tw_cost_structure": {"passed": True}},
        skipped_tasks=skipped or [], out_dir=tmp_path,
    )
    return md, md.read_text(encoding="utf-8")


def test_full_values_render_sections_appendix_and_files(tmp_path):
    anchors = {"ar_mdna": PageRange(65, 67), "ar_risk": None}
    md, text = _run(tmp_path, _full_bundle(), FULL, anchors)

    for h in ("## 1. 成本結構", "## 2. 財務分析", "## 3. 附註品質",
              "## 附錄 A：解析表原始數字", "## 附錄 B：錨定與缺表"):
        assert h in text
    assert "健策" in text and "2025" in text
    # 三 skill 各節有值
    for marker in ("COVNOTE", "INVSTRUCT", "OPLEV", "COSTOBS", "BSSUM", "ISSUM",
                   "MGMTSUM", "HEALTHWHY", "GLSUM", "FNOBS"):
        assert marker in text
    assert NO_RETURN not in text
    # 附錄 A 各表為 Markdown 表且帶資料
    for marker in ("T7A列", "T7B列", "客戶甲", "T4列", "T5列", "T1列", "T2列", "T3列"):
        assert marker in text
    assert "| 項目 |" in text
    assert "未取得" not in text
    # 附錄 B
    assert "p65–67" in text and "未錨定" in text
    assert "0.85" in text
    # 檔案
    assert md.parent == tmp_path and md.name.startswith("3653_") and md.name.endswith("_tw_report.md")
    pdf = md.with_name(md.name.replace(".md", ".pdf"))
    assert pdf.exists() and pdf.stat().st_size > 0
    raws = list(tmp_path.glob("3653_*_raw.json"))
    assert len(raws) == 1
    raw = json.loads(raws[0].read_text(encoding="utf-8"))
    assert {"bundle", "skill_results", "eval_results", "anchors_summary"} <= set(raw)


def test_tone_filter_and_cell_escape(tmp_path):
    _, text = _run(tmp_path, _full_bundle(), FULL)
    assert "惡化" not in text  # 過 tone_filter（惡化→下降）
    bundle = _full_bundle()
    bundle.fin_position.rows[0].label = "含|管線"
    _, text2 = _run(tmp_path, bundle, FULL)
    assert "含\\|管線" in text2


def test_missing_skill_keys_print_marker_without_error(tmp_path):
    _, text = _run(tmp_path, _full_bundle(), PARTIAL)
    for h in ("## 1. 成本結構", "## 2. 財務分析", "## 3. 附註品質"):
        assert h in text
    assert NO_RETURN in text
    # 有的欄位仍照常印
    assert "PARTCOV" in text and "PARTCONT" in text
    # 缺的欄位（整個 skill 缺、單欄缺）都有標記
    fin = text.split("## 2. 財務分析")[1].split("## 3. 附註品質")[0]
    assert NO_RETURN in fin
    cost = text.split("## 1. 成本結構")[1].split("## 2. 財務分析")[0]
    assert cost.count(NO_RETURN) >= 3  # inventory／operating_leverage／key_observations 之外含 note 缺
    foot = text.split("## 3. 附註品質")[1].split("## 附錄 A")[0]
    assert foot.count(NO_RETURN) >= 2  # guarantees_and_loans／kam


def test_missing_tables_print_not_obtained_and_list_names_1b1(tmp_path):
    _, text = _run(tmp_path, _missing_bundle(coverage=0.5), FULL)
    appx_a = text.split("## 附錄 A")[1].split("## 附錄 B")[0]
    assert appx_a.count("未取得") == 12
    appx_b = text.split("## 附錄 B")[1]
    for name in ("T1", "T4", "T8_sales"):
        assert name in appx_b


def test_coverage_none_prints_cannot_compute(tmp_path):
    _, text = _run(tmp_path, _full_bundle_with(coverage=None), FULL)
    assert NO_COVERAGE in text.split("## 附錄 B")[1]


def _full_bundle_with(coverage):
    b = _full_bundle()
    b.parent_cost_coverage = coverage
    return b


def test_missing_tables_and_missing_skill_keys_degrade_independently(tmp_path):
    _, text = _run(tmp_path, _missing_bundle(coverage=None), PARTIAL, anchors={"ar_mdna": None})
    appx_a = text.split("## 附錄 A")[1].split("## 附錄 B")[0]
    assert "未取得" in appx_a
    assert NO_COVERAGE in text and "T8_sales" in text
    assert NO_RETURN in text.split("## 附錄 A")[0]
    assert "未錨定" in text


def test_skill_error_prints_failure_line(tmp_path):
    sr = {"tw_cost_structure": {"error": "boom", "insufficient_data": True}}
    _, text = _run(tmp_path, _full_bundle(), sr)
    assert "本節 skill 失敗：boom" in text
