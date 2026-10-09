"""真實 3653 fixture 指標值（run 2026-10-09-tw-equity-metrics-t1 item 1.3；Spec §2.3）。"""
import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections
from runtime.tw_equity.metrics import compute_metrics
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.statements import extract_statements

_FIX = Path(__file__).parent.parent / "fixtures" / "tw_equity" / "fs_3653_pages.json"


@pytest.fixture(scope="module")
def pack():
    doc = from_json(json.loads(_FIX.read_text(encoding="utf-8")))
    ledger = extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()))
    return compute_metrics(ledger)


def test_spec_2_3_metric_values(pack):
    assert pack.get("fcf") == pytest.approx(3943937, abs=1)
    assert pack.get("fcf", "prior") == pytest.approx(2673476, abs=1)
    assert pack.get("gross_margin") == pytest.approx(41.60, abs=0.01)
    assert pack.get("net_margin") == pytest.approx(26.19, abs=0.01)
    assert pack.get("cfo_to_net_income") == pytest.approx(0.90, abs=0.01)
    assert pack.get("dso") == pytest.approx(97.45, abs=0.01)
    assert pack.get("current_ratio") == pytest.approx(416.91, abs=0.01)  # 與年報財務分析表一致
    assert pack.get("interest_bearing_debt") == pytest.approx(86967, abs=1)


def test_spec_2_3_bridges(pack):
    fcf = next(b for b in pack.bridges if b.target == "fcf")
    assert fcf.target_delta == pytest.approx(1270461, abs=1)
    assert {c.key: c.delta for c in fcf.components} == pytest.approx({"cfo": 1882843, "capex": -612382}, abs=1)
    assert fcf.residual == pytest.approx(0, abs=1) and fcf.top_drivers == ["cfo", "capex"]
    cash = next(b for b in pack.bridges if b.target == "net_change_in_cash")
    assert cash.target_delta == pytest.approx(8755184, abs=1)
    assert cash.top_drivers == ["cff", "cfo", "cfi"] and cash.residual == pytest.approx(0, abs=1)


def test_all_bridges_residual_small_except_cfo(pack):
    for b in pack.bridges:
        if b.residual is None or b.target == "cfo":
            continue
        assert abs(b.residual) <= 1, (b.target, b.residual)
    cfo = next(b for b in pack.bridges if b.target == "cfo")
    assert cfo.residual is not None and abs(cfo.residual) < 1000  # 間接法未列項吸收
