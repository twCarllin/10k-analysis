"""附錄 D 合併財報三表勾稽（Spec §4.2，task item 2.2）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

from runtime.tw_equity.inputs import TwEquityInputs  # noqa: E402
from runtime.tw_equity.report import save_tw_equity_report  # noqa: E402
from runtime.tw_equity.statements import CrossCheck, StatementLedger, StatementRow  # noqa: E402
from runtime.tw_equity.tables import TablesBundle  # noqa: E402


def _row(st, key, cur, prior=None):
    return StatementRow(statement=st, section=None, label=key, key=key, note=None,
                        current=cur, prior=prior, current_pct=None, prior_pct=None,
                        page=1, line_idx=0)


def _ledger(n_unmapped=35):
    checks = []
    for i in range(11):
        for period in ("current", "prior"):
            passed = True if i < 9 else (False if period == "current" else None)
            checks.append(CrossCheck(name=f"chk{i}", period=period, lhs=1.0,
                                     rhs=1.0 if passed is not False else 9.0,
                                     passed=passed))
    return StatementLedger(
        unit="新台幣仟元", period_current="114年度", period_prior="113年度",
        rows=[_row("bs", "total_assets", 1), _row("is", "net_income", 2),
              _row("cf", "cfo", 3), _row("cf", "capex", 4)],
        checks=checks, unmapped_labels=[f"科目{i}" for i in range(n_unmapped)])


def _bundle(statements):
    return TablesBundle(
        fin_position=None, fin_performance=None, customers_sales=None,
        customers_purchase=None, production_sales=None, expense_nature=None,
        inventory=None, cost_detail_cogs=None, cost_detail_mfg=None, cost_detail_opex=None,
        consolidated_key_lines={}, parent_key_lines={}, parent_cost_coverage=None,
        missing_tables=[], unit_notes={}, statements=statements)


def _run(tmp_path, bundle):
    md = save_tw_equity_report(
        inputs=TwEquityInputs(ticker="3653", company_name="測試", fiscal_year=2025,
                              annual_report_path=Path("ar.pdf"),
                              consolidated_fs_path=None, parent_fs_path=None),
        bundle=bundle, anchors_summary={}, skill_results={}, eval_results={},
        skipped_tasks=[], out_dir=tmp_path)
    (raw,) = tmp_path.glob("*_raw.json")
    return md.read_text(encoding="utf-8"), json.loads(raw.read_text(encoding="utf-8"))


def _section_d(text):
    return text.split("## 附錄 D")[1]


def test_ledger_renders_check_table_with_symbols(tmp_path):
    text, _ = _run(tmp_path, _bundle(_ledger()))
    d = _section_d(text)
    table = [ln for ln in d.splitlines() if ln.startswith("| chk")]
    assert len(table) == 22
    assert sum("✅" in ln for ln in table) == 18
    assert sum("❌" in ln for ln in table) == 2
    assert sum(ln.rstrip().endswith("| — |") for ln in table) == 2


def test_unmapped_capped_at_30_with_ellipsis(tmp_path):
    text, _ = _run(tmp_path, _bundle(_ledger(35)))
    d = _section_d(text)
    assert "科目29" in d and "科目30" not in d
    assert "…" in d


def test_no_ledger_prints_unparsed_sentence(tmp_path):
    text, raw = _run(tmp_path, _bundle(None))
    assert "三表未解析" in _section_d(text)
    assert raw["bundle"]["statements"] is None


def test_raw_json_rows_match_row_counts(tmp_path):
    _, raw = _run(tmp_path, _bundle(_ledger()))
    st = raw["bundle"]["statements"]
    assert len(st["rows"]) == sum(st["row_counts"].values()) == 4


def test_appendix_d_follows_c_without_changing_ab(tmp_path):
    text, _ = _run(tmp_path, _bundle(None))
    assert text.index("## 附錄 A") < text.index("## 附錄 B") < text.index("## 附錄 C") < text.index("## 附錄 D")
