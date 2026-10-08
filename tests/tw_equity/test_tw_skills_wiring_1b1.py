"""tests/tw_equity/test_tw_skills_wiring_1b1.py

Phase 1B-1 四個 skill 的接線契約（Spec §3.5、§3.6）：REQUIRED_KEYS、mock_outputs、
dry-run 載入、eval_single 組合。
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILLS_1B1 = ("tw_kam_analysis", "tw_business_analysis", "tw_customer_supplier", "tw_governance_flags")

EXPECTED_REQUIRED = {
    "tw_kam_analysis": ["matters", "key_observations", "insufficient_data"],
    "tw_business_analysis": ["business_summary", "narrative_vs_numbers", "insufficient_data"],
    "tw_customer_supplier": ["customer_concentration", "supplier_concentration", "insufficient_data"],
    "tw_governance_flags": ["pledge", "ownership", "insufficient_data"],
}


@pytest.fixture(scope="module")
def mods():
    runtime_path = str(REPO / "runtime")
    if runtime_path not in sys.path:
        sys.path.insert(0, runtime_path)
    sys.modules.pop("agent_runner", None)
    sys.modules.pop("eval_runner", None)
    with mock.patch.dict("sys.modules", {"anthropic": mock.MagicMock(), "openai": mock.MagicMock()}):
        ar = importlib.import_module("agent_runner")
        er = importlib.import_module("eval_runner")
    yield ar, er
    ar.set_dry_run(False)


@pytest.fixture(scope="module")
def mock_outputs():
    return json.loads((REPO / "runtime" / "mock_outputs.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", SKILLS_1B1)
def test_required_keys_match_spec(mods, name):
    assert mods[1].REQUIRED_KEYS[name] == EXPECTED_REQUIRED[name]


@pytest.mark.parametrize("name", SKILLS_1B1)
def test_mock_has_all_required_fields(mock_outputs, name):
    out = mock_outputs[name]
    for k in EXPECTED_REQUIRED[name]:
        assert k in out
    assert out["insufficient_data"] is False


@pytest.mark.parametrize("name", SKILLS_1B1)
def test_dry_run_returns_nonempty_dict(mods, name):
    ar = mods[0]
    ar.set_dry_run(True)
    try:
        out = ar.run_agent("analyst_agent", name, {"tables_json": "{}"})
    finally:
        ar.set_dry_run(False)
    assert isinstance(out, dict) and out


@pytest.mark.parametrize("name", SKILLS_1B1)
def test_eval_single_passes_with_mock_output(mods, mock_outputs, name):
    ar, er = mods
    ar.set_dry_run(True)
    try:
        res = er.eval_single(name, mock_outputs[name], "source")
    finally:
        ar.set_dry_run(False)
    assert res["pass"] is True


@pytest.mark.parametrize("name", SKILLS_1B1)
def test_schema_score_drops_when_required_key_missing(mods, mock_outputs, name):
    er = mods[1]
    full = er._schema_score(name, mock_outputs[name])
    broken = {k: v for k, v in mock_outputs[name].items() if k != EXPECTED_REQUIRED[name][0]}
    assert er._schema_score(name, broken) < full
