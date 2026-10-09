"""金控 6 家 H1 三表勾稽整合（fh-schema Spec §0.3 第一條；task 1.5）。

契約 row：
  I1: 6 家各 len(checks)==18 且 passed 皆 True（9 項 × current／prior）；未過 → 失敗訊息含家別、項目、期間、lhs／rhs、缺 key（根因欄位）
  I2: 每家 n_unmapped ≤ 實測基線（_UNMAPPED_CEILING）
  I3: 2881 BS 並排頁 total_assets＝total_liabilities_and_equity（current／prior）
  I4: [邊界] 非保險金控（無 insurance_other_cost、無 insurance_service_result 列）→ is_pretax 仍 passed
  I5: 5 位數會計代碼剝除：6 家 IS `41000 利息收入` → code=="41000"、對到 interest_income
  I6: is_pretax 含 total_opex：2886 is_pretax 兩期 passed（mutation 對照：公式漏減 total_opex 必 FAIL）
fixture：fh_statements_pages.json（依據 make_fh_statements_fixture.py；各家 PDF 檔名與頁碼見其 `_source`）。
不走 extract_tables：它需年報 PdfDoc 等與三表勾稽無關的參數；本檔直接呼叫其內部所呼叫的
extract_statements(fs, anchors, group="fh")（extract_tables 的 group 傳遞已由 test_group_wiring 驗證）。
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import PageRange  # noqa: E402
from runtime.tw_equity.fh_schema import FH_CHECK_SPECS, FH_OPTIONAL_KEYS  # noqa: E402
from runtime.tw_equity.statements import extract_statements, run_cross_checks  # noqa: E402

_FH = json.loads((ROOT / "tests/fixtures/tw_equity/fh_statements_pages.json").read_text(encoding="utf-8"))
_TICKERS = ("2881", "2882", "2885", "2886", "2887", "2891")

# 1.6 修正後的實測 n_unmapped（OCI 區段、CF 明細等無對應 key 的列；只許不增）
_UNMAPPED_CEILING = {"2881": 69, "2882": 65, "2885": 57, "2886": 40, "2887": 50, "2891": 68}

_LEDGERS: dict[str, object] = {}


def _ledger(ticker: str):
    if ticker not in _LEDGERS:
        entry = _FH[ticker]
        anchors = {k: (PageRange(*r) if r else None) for k, r in entry["fs_anchors"].items()}
        _LEDGERS[ticker] = extract_statements(pdf_doc.from_json(entry["doc"]), anchors, group="fh")
    return _LEDGERS[ticker]


def _failure_report(ticker: str, led) -> str:
    present = {r.key for r in led.rows if r.key}
    specs = {n: (lhs, rhs) for n, lhs, rhs in FH_CHECK_SPECS}
    lines = []
    for c in led.checks:
        if c.passed is True:
            continue
        lhs, rhs = specs[c.name]
        missing = [k for k in (*lhs, *rhs) if k not in present and k not in FH_OPTIONAL_KEYS]
        lines.append(
            f"{ticker} {c.name}/{c.period}: passed={c.passed} lhs={c.lhs} rhs={c.rhs} 缺 key={missing}"
        )
    return "\n".join(lines)


@pytest.mark.parametrize("ticker", _TICKERS)
def test_h1_nine_checks_both_periods_all_passed(ticker) -> None:
    led = _ledger(ticker)
    assert led is not None and led.schema == "fh"
    assert len(led.checks) == 18
    bad = _failure_report(ticker, led)
    assert not bad, "勾稽未全過（家別／項目／期間／lhs／rhs／缺 key）：\n" + bad


@pytest.mark.parametrize("ticker", _TICKERS)
def test_n_unmapped_not_above_baseline(ticker) -> None:
    led = _ledger(ticker)
    assert len(led.unmapped_labels) <= _UNMAPPED_CEILING[ticker], led.unmapped_labels


def test_2881_side_by_side_bs_assets_equal_liabilities_and_equity() -> None:
    by_key = {r.key: r for r in _ledger("2881").rows if r.statement == "bs" and r.key}
    ta, tle = by_key["total_assets"], by_key["total_liabilities_and_equity"]
    assert ta.current is not None and ta.current == tle.current
    assert ta.prior is not None and ta.prior == tle.prior


@pytest.mark.parametrize("ticker", _TICKERS)
def test_five_digit_code_stripped_on_interest_income(ticker) -> None:
    rows = [r for r in _ledger(ticker).rows if r.statement == "is" and r.code == "41000"]
    assert rows and rows[0].key == "interest_income"
    assert rows[0].label == "利息收入"


def test_2886_is_pretax_passed_both_periods() -> None:
    got = [c for c in _ledger("2886").checks if c.name == "is_pretax"]
    assert [c.period for c in got] == ["current", "prior"]
    assert all(c.passed is True for c in got), got


def test_non_insurance_group_is_pretax_still_passed() -> None:
    """2886 的帳本拿掉保險列（insurance_other_cost、insurance_service_result），pretax 加回保險成本（等同無此列的公司）。"""
    led = _ledger("2886")
    by_key = {r.key: r for r in led.rows if r.key}
    ins = by_key["insurance_other_cost"]
    rows = []
    for r in led.rows:
        if r.key in ("insurance_other_cost", "insurance_service_result"):
            continue
        if r.key == "pretax_income":
            r = dataclasses.replace(
                r, current=r.current + abs(ins.current), prior=r.prior + abs(ins.prior)
            )
        rows.append(r)
    got = [c for c in run_cross_checks(rows, led.column_periods, schema="fh") if c.name == "is_pretax"]
    assert len(got) == 2 and all(c.passed is True for c in got), got


@pytest.mark.parametrize("ticker", _TICKERS)
def test_net_income_parent_current_present(ticker) -> None:
    row = next(r for r in _ledger(ticker).rows if r.statement == "is" and r.key == "net_income_parent")
    assert row.current is not None


@pytest.mark.parametrize("ticker", ["2882", "2887"])
def test_two_line_header_is_current_prior_columns(ticker) -> None:
    led = _ledger(ticker)
    cols = led.column_periods["is"]
    assert cols[led.current_col["is"]] == "115-01-01~115-06-30"
    assert cols[led.prior_col["is"]] == "114-01-01~114-06-30"


def test_2891_total_liabilities_both_periods_present() -> None:
    row = next(r for r in _ledger("2891").rows if r.statement == "bs" and r.key == "total_liabilities")
    assert row.current is not None and row.prior is not None
