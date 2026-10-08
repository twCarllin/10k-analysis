"""tests/tw_equity/test_tw_skills_kam_business.py

tw_kam_analysis／tw_business_analysis 的結構契約（Spec §3.1、§3.2）：
frontmatter、Input 含 retry_hint、Output 骨架為合法 JSON 且 key 集合正確。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2] / "skills" / "tw"

EXPECTED_KEYS = {
    "tw_kam_analysis": {"matters", "linkage_to_numbers", "key_observations", "insufficient_data"},
    "tw_business_analysis": {"business_summary", "products", "management_plans",
                             "narrative_vs_numbers", "key_observations", "insufficient_data"},
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


def test_kam_risk_area_enum():
    risk = _skeleton("tw_kam_analysis")["matters"][0]["risk_area"]
    assert risk.split("|") == ["revenue", "inventory", "valuation", "related_party", "other"]
