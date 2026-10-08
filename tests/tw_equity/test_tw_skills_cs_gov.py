"""tests/tw_equity/test_tw_skills_cs_gov.py

tw_customer_supplier／tw_governance_flags 的結構契約（Spec §3.3、§3.4）：
frontmatter、Input 含 retry_hint、Output 骨架為合法 JSON 且 key 集合正確。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2] / "skills" / "tw"

EXPECTED_KEYS = {
    "tw_customer_supplier": {"customer_concentration", "supplier_concentration", "related_counterparties",
                             "bargaining_power", "key_observations", "insufficient_data"},
    "tw_governance_flags": {"pledge", "ownership", "board", "guarantees", "capital_actions",
                            "key_observations", "insufficient_data"},
}


def _read(name):
    return (SKILLS / f"{name}.md").read_text(encoding="utf-8")


def _skeleton(name):
    m = re.search(r"## Output Format\s*```json\n(.*?)```", _read(name), re.S)
    assert m, "missing Output JSON block"
    return json.loads(m.group(1))


@pytest.mark.parametrize("name", list(EXPECTED_KEYS))
def test_frontmatter_and_retry_hint(name):
    text = _read(name)
    fm = re.match(r"---\n(.*?)\n---", text, re.S)
    assert fm, "missing frontmatter"
    assert "skill_version:" in fm.group(1)
    assert "last_modified:" in fm.group(1)
    assert "retry_hint" in text


@pytest.mark.parametrize("name", list(EXPECTED_KEYS))
def test_output_skeleton_keys(name):
    assert set(_skeleton(name)) == EXPECTED_KEYS[name]


def test_pledge_status_enum():
    status = _skeleton("tw_governance_flags")["pledge"]["status"]
    assert status.split("|") == ["rows", "none", "external_reference", "unknown"]
