"""附錄 A 的 T9／T10 表與附錄 B 新 key／新缺表名稱測試（契約：task item 5.3、Spec §2.7／§4）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.inputs import TwEquityInputs  # noqa: E402
from runtime.tw_equity.report import save_tw_equity_report  # noqa: E402
from runtime.tw_equity.tables import (  # noqa: E402
    GuaranteeRow, GuaranteesLoans, PledgeRow, PledgeTable, ShareholderRow, TablesBundle,
    TopShareholders,
)

FULL = json.loads(
    (ROOT / "tests/fixtures/tw_equity/report_skill_results.json").read_text(encoding="utf-8")
)["full"]
NOT_OBTAINED = "未取得"


def _g(no: int, name: str) -> GuaranteeRow:
    return GuaranteeRow(no, name, f"被保{no}", "(2)", 100.0, 90.0, 80.0, 70.0, None, 5.5, 200.0,
                        "Y", "N", "N")


def _bundle(**kw) -> TablesBundle:
    base = dict(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=[], unit_notes={},
    )
    base.update(kw)
    return TablesBundle(**base)


def _run(tmp_path, bundle, anchors=None) -> str:
    inputs = TwEquityInputs(
        ticker="3653", company_name="健策", fiscal_year=2025,
        annual_report_path=Path("x.pdf"), consolidated_fs_path=None, parent_fs_path=None,
    )
    md = save_tw_equity_report(
        inputs=inputs, bundle=bundle, anchors_summary=anchors or {}, skill_results=FULL,
        eval_results={}, skipped_tasks=[], out_dir=tmp_path,
    )
    return md.read_text(encoding="utf-8")


def _appx_a(text: str) -> str:
    return text.split("## 附錄 A")[1].split("## 附錄 B")[0]


def _sub(appx: str, title: str) -> str:
    return appx.split(f"### {title}")[1].split("### ")[0]


def test_values_render_three_new_tables(tmp_path):
    bundle = _bundle(
        guarantees_loans=GuaranteesLoans("none", "table", [_g(1, "GUARA甲"), _g(2, "GUARA乙"), _g(3, "GUARA丙")], [], 5.5),
        pledges=PledgeTable("rows", [PledgeRow("PLEDGER董事", "借款", "114.01.01", "銀行", "無", 1000.0, 10.0, 35.0, 5000.0)], 35.0),
        top_shareholders=TopShareholders([
            ShareholderRow("TOPHOLD法人", False, 9000.0, 20.0, None, None, None, None),
            ShareholderRow("REPNAME代表人", True, 100.0, 0.5, None, None, None, None)], ["1.NOTE二親等"]),
    )
    a = _appx_a(_run(tmp_path, bundle))
    t9 = _sub(a, "T9 背書保證／資金貸與")
    for m in ("GUARA甲", "GUARA乙", "GUARA丙", "none", "table"):
        assert m in t9
    t10p = _sub(a, "T10 股權質押")
    assert "rows" in t10p and "PLEDGER董事" in t10p
    t10t = _sub(a, "T10 前十大股東")
    for m in ("TOPHOLD法人", "REPNAME代表人", "NOTE二親等"):
        assert m in t10t
    assert NOT_OBTAINED not in t9 + t10p + t10t


def test_t9_status_none_prints_status_without_rows(tmp_path):
    bundle = _bundle(guarantees_loans=GuaranteesLoans("none", "none", [], [], None))
    t9 = _sub(_appx_a(_run(tmp_path, bundle)), "T9 背書保證／資金貸與")
    assert "none" in t9
    assert "| 編號 |" not in t9 and NOT_OBTAINED not in t9


def test_missing_three_tables_print_not_obtained_once_each(tmp_path):
    a = _appx_a(_run(tmp_path, _bundle()))
    for title in ("T9 背書保證／資金貸與", "T10 股權質押", "T10 前十大股東"):
        assert _sub(a, title).count(NOT_OBTAINED) == 1


def test_pledge_external_reference_prints_status_no_empty_table(tmp_path):
    bundle = _bundle(pledges=PledgeTable("external_reference", [], None))
    t = _sub(_appx_a(_run(tmp_path, bundle)), "T10 股權質押")
    assert "external_reference" in t
    assert "| 姓名 |" not in t and NOT_OBTAINED not in t


def test_appendix_b_new_anchor_keys_and_missing_names(tmp_path):
    anchors = {"ar_governance": PageRange(30, 32), "fs_note_disclosure": PageRange(80, 81),
               "ar_pledge": None}
    bundle = _bundle(missing_tables=["T9", "T10_pledge", "T10_top10"])
    b = _run(tmp_path, bundle, anchors).split("## 附錄 B")[1]
    for m in ("ar_governance", "p30–32", "fs_note_disclosure", "p80–81", "ar_pledge", "未錨定",
              "T9", "T10_pledge", "T10_top10"):
        assert m in b
