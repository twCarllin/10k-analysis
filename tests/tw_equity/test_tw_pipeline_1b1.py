"""run_tw_equity_pipeline 1B-1 接線測試（item 4.4，Spec §2.5／§2.6）。

邊界 mock：pdf_doc.load_pdf 依路徑回真實 fs／ar fixture；run_agent（LLM 邊界）以 dry-run mock 為底。
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
_NEW_TASKS = ["tw_kam_analysis", "tw_business_analysis", "tw_customer_supplier", "tw_governance_flags"]


def _load(name: str) -> PdfDoc:
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agent_runner
    import eval_runner

    (tmp_path / "tw_equity_inputs").mkdir()
    (tmp_path / "ar.pdf").write_bytes(b"%PDF-dummy")
    (tmp_path / "fs.pdf").write_bytes(b"%PDF-dummy")

    def write_inputs(with_fs: bool) -> None:
        d = {"ticker": "3653", "company_name": "健策精密工業股份有限公司",
             "fiscal_year": 2025, "annual_report_path": "ar.pdf"}
        if with_fs:
            d["consolidated_fs_path"] = "fs.pdf"
        else:
            d["consolidated_fs_path"] = None
        (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps(d), encoding="utf-8")

    docs = {"ar.pdf": _load("ar_3653_pages.json"), "fs.pdf": _load("fs_3653_pages.json")}
    monkeypatch.setattr(pdf_doc, "load_pdf", lambda path, **kw: docs[Path(path).name])

    calls: list[tuple[str, dict]] = []
    orig = agent_runner.run_agent

    def fake(agent_name, skill_name, inputs, **kw):
        if skill_name.startswith("tw_"):
            calls.append((skill_name, dict(inputs)))
        return orig(agent_name, skill_name, inputs, **kw)

    agent_runner.set_dry_run(True)
    monkeypatch.setattr(agent_runner, "run_agent", fake)
    monkeypatch.setattr(eval_runner, "run_agent", fake)
    yield tmp_path, calls, docs, write_inputs
    agent_runner.set_dry_run(False)


def _raw(md: Path) -> dict:
    (raw_path,) = md.parent.glob("*_raw.json")
    return json.loads(raw_path.read_text(encoding="utf-8"))


def _anchor_start(v) -> int:
    """raw.json 以 default=str 序列化 PageRange → 'PageRange(start=10, end=11)'。"""
    return int(re.search(r"start=(\d+)", str(v)).group(1))


def _skipped_section(md: Path) -> str:
    parts = md.read_text(encoding="utf-8").split("### 跳過的任務")
    return parts[1] if len(parts) > 1 else ""


def test_anchors_summary_has_heading_anchored_fs_and_gov(env) -> None:
    base, _, _, write_inputs = env
    write_inputs(True)
    raw = _raw(run_tw_equity_pipeline("3653", dry_run=True, base_dir=base))
    assert _anchor_start(raw["anchors_summary"]["fs_bs"]) == 10
    assert _anchor_start(raw["anchors_summary"]["ar_governance"]) == 8
    for t in _NEW_TASKS:
        assert t in raw["skill_results"]


def test_new_tasks_receive_tables_json(env) -> None:
    base, calls, _, write_inputs = env
    write_inputs(True)
    run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    by = dict(calls)
    for t in _NEW_TASKS:
        assert by[t]["tables_json"]


def test_empty_kam_skips_kam_task_without_calling_it(env) -> None:
    base, calls, docs, write_inputs = env
    write_inputs(True)
    docs["fs.pdf"] = _drop_kam(docs["fs.pdf"])
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    assert "tw_kam_analysis" in _skipped_section(md)
    assert "tw_kam_analysis" not in {s for s, _ in calls}
    assert "tw_business_analysis" in {s for s, _ in calls}


def _drop_kam(doc: PdfDoc) -> PdfDoc:
    from runtime.tw_equity.pdf_doc import Page
    pages = []
    for p in doc.pages:
        pages.append(Page(
            number=p.number, text=p.text.replace("關鍵查核事項", "查核事項"),
            tables=p.tables, lines=[ln.replace("關鍵查核事項", "查核事項") for ln in p.lines],
        ))
    return PdfDoc(path=doc.path, pages=pages)


def test_footnotes_all_empty_still_skipped(env) -> None:
    base, calls, docs, write_inputs = env
    write_inputs(False)
    ar = docs["ar.pdf"]
    from runtime.tw_equity.pdf_doc import Page
    docs["ar.pdf"] = PdfDoc(path=ar.path, pages=[
        Page(number=p.number, text=p.text.replace("風險事項", "風險"), tables=p.tables, lines=p.lines)
        for p in ar.pages])
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)
    assert "tw_footnotes_quality" in _skipped_section(md)
    assert "tw_footnotes_quality" not in {s for s, _ in calls}


def test_fs_path_null_all_fs_tables_missing_no_fs_anchors(env) -> None:
    base, _, _, write_inputs = env
    write_inputs(False)
    raw = _raw(run_tw_equity_pipeline("3653", dry_run=True, base_dir=base))
    assert {"T4", "T5", "T9"} <= set(raw["bundle"]["missing_tables"])
    assert not [k for k in raw["anchors_summary"] if k.startswith("fs_")]
