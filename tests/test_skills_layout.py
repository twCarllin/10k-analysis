"""tests/test_skills_layout.py

skills/ 分子目錄後的版面與 loader 契約（run 2026-10-08-skills-reorg）：
- skills/ 根目錄不再有 .md；四個子目錄內 basename 全域唯一
- runtime/agent_runner.skill_path 與 runtime/tw_credit/prompts._load_skill 都能解析既有 skill 名稱
- 找不到的名稱 raise FileNotFoundError 並列出搜尋目錄
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
SUBDIRS = ("common", "us", "jp", "tw")

# mock_outputs.json 的 key 是 orchestrator／jp_pipeline／eval_runner 引用的 skill 名稱集合；
# 下列四個未在 mock 內但被 orchestrator／section_splitter 直接引用
_EXTRA_REFERENCED = {"rerate_narrative", "rerate_quality", "rerate_structure",
                     "footnotes_combined", "transcript_analysis", "section_splitter"}


def _referenced_skill_names() -> set[str]:
    keys = set(json.loads((REPO / "runtime" / "mock_outputs.json").read_text()).keys())
    return keys | _EXTRA_REFERENCED


def _import_agent_runner():
    """匯入 agent_runner，把 SDK client 建立 mock 掉（測試不打 API、不依賴 provider 設定）。"""
    runtime_path = str(REPO / "runtime")
    if runtime_path not in sys.path:
        sys.path.insert(0, runtime_path)
    sys.modules.pop("agent_runner", None)
    with mock.patch.dict("sys.modules", {"anthropic": mock.MagicMock(), "openai": mock.MagicMock()}):
        return importlib.import_module("agent_runner")


def test_root_has_no_md():
    assert list(SKILLS.glob("*.md")) == []


def test_four_subdirs_exist_and_basenames_unique():
    names: dict[str, str] = {}
    for d in SUBDIRS:
        assert (SKILLS / d).is_dir(), f"missing skills/{d}/"
        for f in (SKILLS / d).glob("*.md"):
            assert f.stem not in names, f"duplicate skill name {f.stem} in {d} and {names[f.stem]}"
            names[f.stem] = d
    assert len(names) == 51  # 48（skills-reorg）＋3 個 tw_equity skill（run 2026-10-08-tw-equity-phase-1a，Spec §3）


def test_skill_path_resolves_every_referenced_skill():
    ar = _import_agent_runner()
    for name in sorted(_referenced_skill_names()):
        p = ar.skill_path(name)
        assert p.exists() and p.parent.parent == SKILLS, name
    assert ar.skill_path("jp_strategy") == SKILLS / "jp" / "jp_strategy.md"


def test_skill_path_missing_raises_listing_dirs():
    ar = _import_agent_runner()
    with pytest.raises(FileNotFoundError) as ei:
        ar.skill_path("not_exist")
    msg = str(ei.value)
    for d in SUBDIRS:
        assert f"skills/{d}/" in msg


def test_get_skill_version_still_reads_header():
    ar = _import_agent_runner()
    assert ar._get_skill_version("business_analysis") == "1.0"
    assert ar._get_skill_version("not_exist") == "unknown"


def test_tw_credit_prompts_load_from_subdir():
    from runtime.tw_credit import prompts
    body = prompts._load_skill("tw_credit_market")
    assert body.strip() and not body.startswith("---") and not body.startswith("#")
    consts = [v for k, v in vars(prompts).items() if k.startswith("PROMPT_") and k.endswith("_SYSTEM")]
    assert len(consts) == 8 and all(isinstance(c, str) and c.strip() for c in consts)
    with pytest.raises(FileNotFoundError):
        prompts._load_skill("not_exist")
