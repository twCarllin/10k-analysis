"""test_fh_batch_integration.py — run 2026-10-09-tw-equity-fh-schema item 5.5：6 家金控批次全流程（本地 fixture）。

契約表：
  B1: 6 家記錄 schema=="fh"、values 12 鍵（與本檔常數一致）、metrics 13 鍵
  B2: build_summary → fh_ranking 長度 6，且工業記錄只進 rows
  B3: 工業 3653 記錄對本 run 前快照（industrial_batch_record.json）既有鍵逐值相同（忽略 schema／ifrs17_break／schema_version）
  B4: [邊界] 6 家之一 status 非 ok → 其餘 5 家照常輸出、fh_ranking 5 列
  B5: 摘要 md／html 與 6 家附錄 E 可渲染（金控節／fh 附錄存在）
「run_company 等價流程」：extract_statements(group="fh")＋extract_fh_notes＋extract_fy_income＋compute_metrics 組 bundle，
再呼叫 batch._fill（run_company 內 extract_tables 需年報／PDF，故以等價組裝）。fixture 不讀 data/cache、不打 API。
B5 另渲染 6 家報告附錄 E（report._appendix_e）。
sabotage（任務驗收用，非常駐）：FH_VALUE_KEYS 漏一鍵 → B1 FAIL；build_summary 讓工業記錄也進 fh_ranking → B2／B4 FAIL。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import batch, pdf_doc  # noqa: E402
from runtime.tw_equity.batch_summary import build_summary, render_html, render_md  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, PageRange, find_heading_sections  # noqa: E402
from runtime.tw_equity.fh_notes import extract_fh_notes  # noqa: E402
from runtime.tw_equity.fy_income import extract_fy_income  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.report import _appendix_e  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402
from runtime.tw_equity.tables import TablesBundle  # noqa: E402
from tests.tw_equity.test_batch import TOP_KEYS  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_ST = json.loads((_FIX / "fh_statements_pages.json").read_text(encoding="utf-8"))
_NT = json.loads((_FIX / "fh_notes_pages.json").read_text(encoding="utf-8"))
_FY = json.loads((_FIX / "fh_fy_income_pages.json").read_text(encoding="utf-8"))
TICKERS = ("2881", "2882", "2885", "2886", "2887", "2891")

EXPECTED_VALUE_KEYS = {"net_interest_income", "non_interest_income", "net_revenue", "provision", "total_opex",
                       "pretax_income", "net_income", "net_income_parent", "total_assets", "total_equity",
                       "loans_net", "deposits"}
EXPECTED_METRIC_KEYS = {"equity_to_assets", "group_car", "npl_ratio", "coverage_ratio", "credit_cost",
                        "cost_income_ratio", "roa", "roe", "nii_share", "fee_share", "pretax_margin",
                        "loan_to_deposit", "liquid_to_assets"}
_SCHEMA_ADDED = {"schema", "ifrs17_break", "schema_version"}  # Spec §8.1 允許的與舊工業記錄差異

_CACHE: dict[str, SimpleNamespace] = {}


def build_fh_bundle(t: str) -> SimpleNamespace:
    """fh 一家的 bundle（statements／metrics／fy_income／fh_notes／fh_notes_error）；結果快取（唯讀使用）。"""
    if t not in _CACHE:
        e = _ST[t]
        anchors = {k: (PageRange(*r) if r else None) for k, r in e["fs_anchors"].items()}
        led = extract_statements(pdf_doc.from_json(e["doc"]), anchors, group="fh")
        notes = extract_fh_notes(pdf_doc.from_json(_NT[t]["doc"]),
                                 bs_current_period=led.column_periods["bs"][led.current_col["bs"]])
        fy = extract_fy_income(pdf_doc.from_json(_FY[t]["doc"]),
                               {k: PageRange(start=v[0], end=v[1]) for k, v in _FY[t]["anchors"].items()},
                               roc_year=114, group="fh")
        _CACHE[t] = SimpleNamespace(statements=led, fy_income=fy, fh_notes=notes, fh_notes_error=None,
                                    metrics=compute_metrics(led, fy, group="fh", notes=notes))
    return _CACHE[t]


def fh_record(t: str) -> dict:
    rec = batch._empty_record(t, "fh")
    rec["group"] = "fh"
    batch._fill(rec, build_fh_bundle(t))
    rec["status"] = "ok"
    rec["company_name"], rec["fs_period"] = f"金控{t}", "2026H1"
    return rec


def industrial_record() -> dict:
    doc = pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))
    led = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))
    rec = batch._empty_record("3653")
    batch._fill(rec, SimpleNamespace(statements=led, metrics=compute_metrics(led), fy_income=None))
    rec["status"] = "ok"
    return rec


@pytest.mark.parametrize("t", TICKERS)
def test_fh_record_fixed_schema(t):  # B1
    rec = fh_record(t)
    assert rec["schema_version"] == 2 and rec["schema"] == "fh" and isinstance(rec["ifrs17_break"], bool)
    assert set(rec["values"]) == EXPECTED_VALUE_KEYS
    assert set(rec["metrics"]) == EXPECTED_METRIC_KEYS
    assert rec["fh_notes"] is not None and rec["bridges"][0]["target"] == "net_income"
    assert set(rec) == TOP_KEYS | {"fh_notes", "fh_notes_error"}
    assert rec["fh_notes_error"] is None
    assert rec["ttm"]["scope"] in ("consolidated", "parent_only") and "comparability" in rec["ttm"]
    for k in ("group_car", "npl_ratio", "coverage_ratio"):
        assert "source" in rec["metrics"][k]


def test_fh_notes_error_key_only_in_fh_records():
    assert "fh_notes_error" not in industrial_record() and "fh_notes" not in industrial_record()


def test_fh_ranking_six_rows_and_industrial_excluded():  # B2
    s = build_summary([fh_record(t) for t in TICKERS] + [industrial_record()])
    assert [r["ticker"] for r in s["fh_ranking"]] == list(TICKERS)
    assert [r["ticker"] for r in s["rows"]] == ["3653"]
    assert s["unsupported"] == [] and s["failed"] == []


def test_industrial_record_matches_pre_run_snapshot():  # B3
    old = json.loads((_FIX / "industrial_batch_record.json").read_text(encoding="utf-8"))
    new = industrial_record()
    assert new["schema"] == "industrial" and new["ifrs17_break"] is None and new["schema_version"] == 2
    assert {k: v for k, v in new.items() if k not in _SCHEMA_ADDED} == {
        k: v for k, v in old.items() if k not in _SCHEMA_ADDED}
    assert set(new) - set(old) == {"schema", "ifrs17_break"}


def test_one_failed_company_leaves_five_rows():  # B4
    bad = batch._empty_record("2886", "fh")  # status "error"
    recs = [bad if t == "2886" else fh_record(t) for t in TICKERS]
    s = build_summary(recs)
    assert [r["ticker"] for r in s["fh_ranking"]] == [t for t in TICKERS if t != "2886"]
    assert [x["ticker"] for x in s["failed"]] == ["2886"]


def test_summary_renders_fh_section():  # B5
    s = build_summary([fh_record(t) for t in TICKERS])
    md, html = render_md(s), render_html(s)
    assert "## 金控" in md and all(f"| {t} " in md for t in TICKERS)
    assert 'id="fh-section"' in html


@pytest.mark.parametrize("t", TICKERS)
def test_report_appendix_e_renders(t):  # B5
    b = build_fh_bundle(t)
    kl = {k: (None, None) for k in ["營業收入", "營業成本", "營業毛利", "營業費用", "營業利益", "本期淨利"]}
    bundle = TablesBundle(None, None, None, None, None, None, None, None, None, None, dict(kl), dict(kl),
                          None, [], {}, statements=b.statements, metrics=b.metrics, fy_income=b.fy_income,
                          fh_notes=b.fh_notes)
    text = "\n".join(_appendix_e(bundle))
    assert "逾放比" in text and "IFRS 17" in text
