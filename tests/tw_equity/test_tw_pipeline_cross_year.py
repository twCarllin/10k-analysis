"""run_tw_equity_pipeline 跨年比較（1B-2 item 6.3，Spec §2.6／§3）。

邊界 mock：pdf_doc.load_pdf 回真實 fixture；run_agent（LLM 邊界）以 dry-run 為底並攔截
cross_year_compare 呼叫。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

import pytest  # noqa: E402

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.pdf_doc import PdfDoc  # noqa: E402
from runtime.tw_equity.tw_pipeline import run_tw_equity_pipeline  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_MARK = "QTREND-MARK-7"


def _load(name: str, policy: bool = False) -> PdfDoc:
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return pdf_doc.apply_ocr_policy(doc, None) if policy else doc


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agent_runner
    import eval_runner

    (tmp_path / "tw_equity_inputs").mkdir()
    for n in ("ar.pdf", "fs.pdf", "ar_prior.pdf"):
        (tmp_path / n).write_bytes(b"%PDF-dummy")

    def write_inputs(with_prior: bool) -> None:
        d = {"ticker": "3653", "company_name": "健策精密工業股份有限公司",
             "fiscal_year": 2025, "annual_report_path": "ar.pdf",
             "consolidated_fs_path": "fs.pdf"}
        if with_prior:
            d["prior"] = {"fiscal_year": 2024, "annual_report_path": "ar_prior.pdf",
                          "consolidated_fs_path": None}
        (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps(d), encoding="utf-8")

    docs = {"ar.pdf": _load("ar_3653_pages.json"), "fs.pdf": _load("fs_3653_pages.json"),
            "ar_prior.pdf": _load("ar2024_3653_pages.json", policy=True)}
    monkeypatch.setattr(pdf_doc, "load_pdf", lambda path, **kw: docs[Path(path).name])

    cross_calls: list[tuple[dict, dict]] = []
    eval_keys: list[set] = []
    orig_eval_all = eval_runner.eval_all

    def spy_eval_all(skill_results, *a, **kw):
        eval_keys.append(set(skill_results))
        return orig_eval_all(skill_results, *a, **kw)

    monkeypatch.setattr(eval_runner, "eval_all", spy_eval_all)
    state = {"raise": False}
    orig = agent_runner.run_agent

    def fake(agent_name, skill_name, inputs, **kw):
        if skill_name == "cross_year_compare":
            cross_calls.append((dict(inputs), dict(kw)))
            if state["raise"]:
                raise RuntimeError("boom-cross")
            return {"cross_checks": [], "mgmt_credibility": "high",
                    "mgmt_credibility_reason": "r", "quality_trend": _MARK,
                    "overall_direction": "positive"}
        return orig(agent_name, skill_name, inputs, **kw)

    agent_runner.set_dry_run(True)
    monkeypatch.setattr(agent_runner, "run_agent", fake)
    monkeypatch.setattr(eval_runner, "run_agent", fake)
    yield tmp_path, cross_calls, state, write_inputs, eval_keys
    agent_runner.set_dry_run(False)


def _raw(md: Path) -> dict:
    (raw_path,) = md.parent.glob("*_raw.json")
    return json.loads(raw_path.read_text(encoding="utf-8"))


def _section8(md: Path) -> str:
    text = md.read_text(encoding="utf-8")
    return re.split(r"^## 8\.", text, flags=re.M)[1].split("\n## ")[0]


def test_prior_calls_cross_year_compare_and_saves_result(env) -> None:
    base, cross_calls, _, write_inputs, eval_keys = env
    write_inputs(True)
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    (inputs, kw), = cross_calls
    assert kw.get("task_label") == "cross_year_compare"
    assert "_cross_year_tables" in json.loads(inputs["current_analysis"])
    assert "_cross_year_tables" not in json.loads(inputs["prior_analysis"])
    raw = _raw(md)
    assert "fin_performance_series" in raw["cross_year"]
    assert raw["cross_year_compare"]["quality_trend"] == _MARK
    assert _MARK in _section8(md)
    assert eval_keys and all("cross_year_compare" not in k for k in eval_keys)
    assert "cross_year_compare" not in raw["eval_results"]


def test_cross_year_compare_exception_degrades_without_abort(env) -> None:
    base, cross_calls, state, write_inputs, _ = env
    write_inputs(True)
    state["raise"] = True
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    raw = _raw(md)
    assert "boom-cross" in raw["cross_year_compare"]["error"]
    assert "失敗" in _section8(md)
    text = md.read_text(encoding="utf-8")
    for n in range(1, 8):
        assert re.search(rf"^## {n}\.", text, flags=re.M)


def test_no_prior_skips_cross_year_entirely(env) -> None:
    base, cross_calls, _, write_inputs, _ = env
    write_inputs(False)
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    raw = _raw(md)
    assert cross_calls == []
    assert raw["prior"] is None and raw["cross_year"] is None
    assert raw["cross_year_compare"] is None
    assert "本節未執行：未提供前一年度" in _section8(md)
