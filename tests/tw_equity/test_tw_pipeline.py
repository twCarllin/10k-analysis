"""run_tw_equity_pipeline 單元測試（契約：Spec §2.7、task item 4.4）。

邊界 mock：pdf_doc.load_pdf 回真實 3653 年報 fixture（不讀真 PDF）；
agent_runner／eval_runner 的 run_agent（LLM 邊界）用 dry-run mock 為底、可依 skill 覆寫。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

import pytest  # noqa: E402

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.pdf_doc import Page, PdfDoc  # noqa: E402
from runtime.tw_equity.tasks import TW_PHASE1_TASKS  # noqa: E402
from runtime.tw_equity.tw_pipeline import run_tw_equity_pipeline  # noqa: E402

_AR_FIXTURE = ROOT / "tests/fixtures/tw_equity/ar_3653_pages.json"


def _load_ar() -> PdfDoc:
    doc = pdf_doc.from_json(json.loads(_AR_FIXTURE.read_text(encoding="utf-8")))
    assert doc is not None
    return doc


@pytest.fixture
def env(tmp_path, monkeypatch):
    """輸入檔＋fixture 載入＋dry-run LLM；回傳 (base_dir, calls, overrides, state)。"""
    # fixture 內才 import：其他測試可能換掉 sys.modules 的 agent_runner，須與 pipeline 延遲 import 取同一份
    # （會 pop agent_runner 的測試檔：tests/test_skills_layout.py、tests/tw_equity/test_tw_skills_wiring.py）
    import agent_runner
    import eval_runner
    (tmp_path / "tw_equity_inputs").mkdir()
    (tmp_path / "ar.pdf").write_bytes(b"%PDF-dummy")
    (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps({
        "ticker": "3653", "company_name": "健策精密工業股份有限公司",
        "fiscal_year": 2025, "annual_report_path": "ar.pdf",
    }), encoding="utf-8")

    state = {"doc": _load_ar()}
    monkeypatch.setattr(pdf_doc, "load_pdf", lambda path, **kw: state["doc"])

    calls: list[tuple[str, dict]] = []
    overrides: dict = {}
    orig = agent_runner.run_agent

    def fake(agent_name, skill_name, inputs, **kw):
        if skill_name.startswith("tw_"):
            calls.append((skill_name, dict(inputs)))
            if skill_name in overrides:
                return overrides[skill_name]
        return orig(agent_name, skill_name, inputs, **kw)

    agent_runner.set_dry_run(True)
    monkeypatch.setattr(agent_runner, "run_agent", fake)
    monkeypatch.setattr(eval_runner, "run_agent", fake)
    yield tmp_path, calls, overrides, state
    agent_runner.set_dry_run(False)


def _raw(md: Path) -> dict:
    (raw_path,) = md.parent.glob("*_raw.json")
    return json.loads(raw_path.read_text(encoding="utf-8"))


def test_tasks_table_matches_spec_1b1():
    assert [t["task_id"] for t in TW_PHASE1_TASKS] == [
        "tw_cost_structure", "tw_financial_analysis", "tw_footnotes_quality",
        "tw_kam_analysis", "tw_business_analysis", "tw_customer_supplier",
        "tw_governance_flags"]
    assert all(t["skill"] == t["task_id"] for t in TW_PHASE1_TASKS)
    assert TW_PHASE1_TASKS[0]["input_keys"] == ["tables_json", "ar_market"]
    assert TW_PHASE1_TASKS[1]["input_keys"] == ["tables_json", "ar_mdna", "ar_letter"]
    assert TW_PHASE1_TASKS[2]["input_keys"] == [
        "fs_note_related", "fs_note_contingent", "fs_note_disclosure", "fs_audit_kam", "ar_risk"]


def test_dry_run_returns_md_and_writes_raw_json(env):
    base, calls, _, _ = env
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    assert md.exists() and md.suffix == ".md"
    raw = _raw(md)
    assert {"tw_cost_structure", "tw_financial_analysis"} <= set(raw["skill_results"])
    assert "ar_mdna" in raw["anchors_summary"]


def test_footnotes_all_empty_inputs_skipped_not_sent_to_llm(env):
    base, calls, _, state = env
    # 抹掉章名關鍵字 → ar_risk 錨定不到 → footnotes 五輸入全空
    state["doc"] = PdfDoc(path=state["doc"].path, pages=[
        Page(number=p.number, text=p.text.replace("風險事項", "風險"), tables=p.tables)
        for p in state["doc"].pages])
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    assert "tw_footnotes_quality" not in {s for s, _ in calls}
    assert "tw_footnotes_quality" in md.read_text(encoding="utf-8").split("### 跳過的任務")[1]


def test_skill_error_does_not_abort_and_report_prints_failure(env):
    base, _, overrides, _ = env
    overrides["tw_cost_structure"] = {"error": "boom", "insufficient_data": True}
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    assert "本節 skill 失敗：boom" in md.read_text(encoding="utf-8")
    assert "tw_financial_analysis" in _raw(md)["skill_results"]


def test_missing_annual_report_raises_file_not_found(env):
    base, _, _, _ = env
    (base / "ar.pdf").unlink()
    with pytest.raises(FileNotFoundError):
        run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)


def test_dry_run_with_footnote_inputs_runs_1a_tasks_plus_unskipped_new(env):
    base, calls, _, state = env
    run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    sent = {s for s, _ in calls}
    # 本 fixture 無合併財報 → fs_audit_kam 為空 → tw_kam_analysis 依 skip_if_empty 跳過；其餘新 task 輸入非空
    assert sent == {
        "tw_cost_structure", "tw_financial_analysis", "tw_footnotes_quality",
        "tw_business_analysis", "tw_customer_supplier", "tw_governance_flags",
    }
    foot = dict(calls)["tw_footnotes_quality"]
    assert foot["ar_risk"]


def test_dry_run_flag_alone_prevents_real_llm_call(env, monkeypatch):
    """不預先 set_dry_run，只傳 dry_run=True：真實 provider client 不得被碰。"""
    import agent_runner
    base, _, _, _ = env
    touched: list[str] = []

    class _BoomClient:
        def __getattr__(self, name):
            touched.append(name)
            raise AssertionError("real LLM client touched")

    agent_runner.set_dry_run(False)
    monkeypatch.setattr(agent_runner, "client", _BoomClient())
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    assert touched == []
    assert not any("error" in r for r in _raw(md)["skill_results"].values())


def _fail_eval_for(monkeypatch, task_id, hint, raise_on_retry=False):
    """系統邊界（LLM）：eval_analysis 對 task_id 回失敗＋retry_hint；可選重試時 skill 拋例外。"""
    import eval_runner
    prev = eval_runner.run_agent

    def fake(agent_name, skill_name, inputs, **kw):
        if skill_name == "eval_analysis" and inputs["skill_name"] == task_id:
            return {"pass": False, "total": 0, "retry_hint": hint}
        return prev(agent_name, skill_name, inputs, **kw)

    import agent_runner
    base_run = agent_runner.run_agent

    def skill_fake(agent_name, skill_name, inputs, **kw):
        if raise_on_retry and skill_name == task_id and "retry_hint" in inputs:
            raise RuntimeError("retry-boom")
        return base_run(agent_name, skill_name, inputs, **kw)

    monkeypatch.setattr(eval_runner, "run_agent", fake)
    monkeypatch.setattr(agent_runner, "run_agent", skill_fake)


def test_eval_loop_retries_exactly_twice_with_retry_hint(env, monkeypatch):
    base, calls, _, _ = env
    _fail_eval_for(monkeypatch, "tw_cost_structure", "HINT-X")
    run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    cost = [i for s, i in calls if s == "tw_cost_structure"]
    assert len(cost) == 3
    assert "retry_hint" not in cost[0]
    assert cost[1]["retry_hint"] == "HINT-X" and cost[2]["retry_hint"] == "HINT-X"


def test_retry_exception_degrades_to_error_and_does_not_abort(env, monkeypatch):
    base, _, _, _ = env
    _fail_eval_for(monkeypatch, "tw_cost_structure", "HINT-X", raise_on_retry=True)
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    assert "本節 skill 失敗：retry-boom" in md.read_text(encoding="utf-8")
    assert "tw_financial_analysis" in _raw(md)["skill_results"]
