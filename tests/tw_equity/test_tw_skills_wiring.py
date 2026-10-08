"""tests/tw_equity/test_tw_skills_wiring.py

tw_equity 三個 skill 的接線契約（Spec §3.1–3.5）：REQUIRED_KEYS、mock_outputs、
skill .md frontmatter／Output 骨架、dry-run 載入、eval_single 組合。
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[2]
TW_SKILLS = ("tw_cost_structure", "tw_financial_analysis", "tw_footnotes_quality")

EXPECTED_REQUIRED = {
    "tw_cost_structure": ["coverage_basis", "cost_composition", "key_observations", "insufficient_data"],
    "tw_financial_analysis": ["balance_sheet", "income_statement", "overall_health", "insufficient_data"],
    "tw_footnotes_quality": ["related_party", "guarantees_and_loans", "insufficient_data"],
}

# §3.1–3.3 Output 骨架的頂層欄位
OUTPUT_FIELDS = {
    "tw_cost_structure": ["coverage_basis", "coverage_note", "cost_composition", "expense_nature",
                          "inventory", "unit_economics", "operating_leverage",
                          "key_observations", "insufficient_data"],
    "tw_financial_analysis": ["balance_sheet", "income_statement", "management_explanation",
                              "overall_health", "overall_health_rationale", "insufficient_data"],
    "tw_footnotes_quality": ["related_party", "contingencies", "guarantees_and_loans", "kam",
                             "key_observations", "insufficient_data"],
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


@pytest.mark.parametrize("name", TW_SKILLS)
def test_required_keys_match_spec(mods, name):
    assert mods[1].REQUIRED_KEYS[name] == EXPECTED_REQUIRED[name]


@pytest.mark.parametrize("name", TW_SKILLS)
def test_mock_has_required_and_output_fields_nonempty(mods, mock_outputs, name):
    out = mock_outputs[name]
    for k in EXPECTED_REQUIRED[name]:
        assert k in out and out[k] not in ("", None, [], {}), k
    for k in OUTPUT_FIELDS[name]:
        assert k in out, k


@pytest.mark.parametrize("name", TW_SKILLS)
def test_skill_md_frontmatter_and_output_skeleton(name):
    text = (REPO / "skills" / "tw" / f"{name}.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert re.search(r"skill_version:\s*[\d.]+", head)
    assert re.search(r"last_modified:\s*\d{4}-\d{2}-\d{2}", head)
    m = re.search(r"## Output Format\s*```json\n(.*?)```", text, re.S)
    assert m, "missing Output JSON block"
    skeleton = m.group(1)
    for k in OUTPUT_FIELDS[name]:
        assert f'"{k}"' in skeleton, k


@pytest.mark.parametrize("name", TW_SKILLS)
def test_dry_run_returns_nonempty_dict_with_insufficient_data(mods, name):
    ar = mods[0]
    ar.set_dry_run(True)
    try:
        out = ar.run_agent("analyst_agent", name, {"tables_json": "{}"})
    finally:
        ar.set_dry_run(False)
    assert isinstance(out, dict) and out
    assert "insufficient_data" in out


@pytest.mark.parametrize("name", TW_SKILLS)
def test_eval_single_passes_with_mock_output(mods, mock_outputs, name):
    ar, er = mods
    ar.set_dry_run(True)
    try:
        res = er.eval_single(name, mock_outputs[name], "source")
    finally:
        ar.set_dry_run(False)
    assert res["pass"] is True
