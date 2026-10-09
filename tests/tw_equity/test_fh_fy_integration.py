"""test_fh_fy_integration.py — run 2026-10-09-tw-equity-fh-schema item 4.5：6 家年報錨點＋FY 損益＋TTM 整合（Spec §0.3）。

契約表：
  A1: 6 家 ar_business／ar_mdna／ar_fin_performance 非 None；2886 ar_mdna 起頁 ≥118 且 <151
  A2: FY：2881／2885／2886 scope consolidated、2882／2887／2891 parent_only，6 家 usable
  A3: TTM status 全 ok（scope 同 A2；consolidated 取 net_income、parent_only 取 net_income_parent）
  A4: [邊界] 某家 FY 頁缺失 → extract_fy_income 回 None、該家 TTM unavailable，其餘 5 家不受影響
入口：TTM 需 H1 帳本——以 fh_statements_pages.json 建帳本，配 fh_fy_income_pages.json 的 FY，直接組函式（比照 1.5／3.5）。
錨點頁細節（F10 章範圍）由 test_fh_anchors.py 擁有；本檔只做非 None 與 2886 範圍檢查。
sabotage 對照：西元表頭只認民國 → A2／A3 FAIL；合併優先改個體優先 → A2 FAIL。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import PageRange, find_annual_report_sections  # noqa: E402
from runtime.tw_equity.fy_income import extract_fy_income  # noqa: E402
from runtime.tw_equity.metrics import compute_metrics  # noqa: E402
from runtime.tw_equity.statements import extract_statements  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_HEAD = json.loads((_FIX / "fh_ar_headings.json").read_text(encoding="utf-8"))
_FY = json.loads((_FIX / "fh_fy_income_pages.json").read_text(encoding="utf-8"))
_ST = json.loads((_FIX / "fh_statements_pages.json").read_text(encoding="utf-8"))
_TICKERS = ("2881", "2882", "2885", "2886", "2887", "2891")
_SCOPE = {"2881": "consolidated", "2885": "consolidated", "2886": "consolidated",
          "2882": "parent_only", "2887": "parent_only", "2891": "parent_only"}


def _ledger(t: str):
    e = _ST[t]
    anchors = {k: (PageRange(*r) if r else None) for k, r in e["fs_anchors"].items()}
    return extract_statements(pdf_doc.from_json(e["doc"]), anchors, group="fh")


def _fy(t: str, *, drop_pages: bool = False):
    doc = pdf_doc.from_json(_FY[t]["doc"])
    if drop_pages:
        doc = pdf_doc.PdfDoc(path=doc.path, pages=[])
    anchors = {k: PageRange(start=v[0], end=v[1]) for k, v in _FY[t]["anchors"].items()}
    return extract_fy_income(doc, anchors, roc_year=114, group="fh")


@pytest.mark.parametrize("t", _TICKERS)
def test_six_anchor_keys_found(t):  # A1
    got = find_annual_report_sections(pdf_doc.from_json(_HEAD[t]["doc"]), required=set(), group="fh")
    for k in ("ar_business", "ar_mdna", "ar_fin_performance"):
        assert got[k] is not None, k


def test_2886_mdna_start_in_chapter():  # A1（2886 章名無「事項」）
    got = find_annual_report_sections(pdf_doc.from_json(_HEAD["2886"]["doc"]), required=set(), group="fh")
    assert 118 <= got["ar_mdna"].start < 151


@pytest.mark.parametrize("t", _TICKERS)
def test_fy_scope_and_usable(t):  # A2
    fy = _fy(t)
    assert fy is not None and fy.scope == _SCOPE[t] and fy.usable is True


@pytest.mark.parametrize("t", _TICKERS)
def test_ttm_status_ok(t):  # A3
    pack = compute_metrics(_ledger(t), _fy(t), group="fh")
    ttm = pack.ttm
    assert ttm.status == "ok" and ttm.scope == _SCOPE[t]
    key = "net_income_parent" if _SCOPE[t] == "parent_only" else "net_income"
    assert ttm.values[key]["ttm"] is not None
    assert ttm.comparability == ("ifrs17_break" if pack.ifrs17_break else None)
    print(t, ttm.status, ttm.scope, ttm.comparability, key, ttm.values[key])


@pytest.mark.parametrize("missing", _TICKERS)
def test_missing_fy_page_isolated(missing):  # A4
    assert _fy(missing, drop_pages=True) is None
    ttm = compute_metrics(_ledger(missing), None, group="fh").ttm
    assert ttm.status == "unavailable"
    for t in [x for x in _TICKERS if x != missing]:
        assert _fy(t) is not None
