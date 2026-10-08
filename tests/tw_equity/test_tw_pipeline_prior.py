"""run_tw_equity_pipeline 前一年度分析（1B-2 item 6.2，Spec §2.6／§6 Q2）。

邊界 mock：pdf_doc.load_pdf 依檔名回真實 fixture（記錄 kwargs）；run_agent 走 dry-run。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

import pytest  # noqa: E402

from runtime.tw_equity import pdf_doc, tw_pipeline  # noqa: E402
from runtime.tw_equity.pdf_doc import PdfDoc  # noqa: E402
from runtime.tw_equity.tw_pipeline import run_tw_equity_pipeline  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"


def _load(name: str, policy: bool = False) -> PdfDoc:
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return pdf_doc.apply_ocr_policy(doc, None) if policy else doc


class _FakeOcr:
    def __call__(self, path, pages):
        return {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agent_runner

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
    load_calls: list[tuple[str, dict]] = []

    def fake_load(path, **kw):
        load_calls.append((Path(path).name, dict(kw)))
        return docs[Path(path).name]

    monkeypatch.setattr(pdf_doc, "load_pdf", fake_load)
    agent_runner.set_dry_run(True)
    yield tmp_path, load_calls, write_inputs, monkeypatch
    agent_runner.set_dry_run(False)


def _raw(md: Path) -> dict:
    (raw_path,) = md.parent.glob("*_raw.json")
    return json.loads(raw_path.read_text(encoding="utf-8"))


def test_prior_present_raw_has_six_fields_and_skips_kam(env, capsys) -> None:
    base, _, write_inputs, _ = env
    write_inputs(True)
    raw = _raw(run_tw_equity_pipeline("3653", dry_run=True, base_dir=base))
    prior = raw["prior"]
    for k in ("bundle", "anchors_summary", "skill_results", "skipped_tasks",
              "garbled_pages", "ocr_pages"):
        assert k in prior
    assert {51, 79} <= set(prior["garbled_pages"])
    assert prior["ocr_pages"] == []
    assert "tw_kam_analysis" in prior["skipped_tasks"]
    out = capsys.readouterr().out
    assert "[tw-equity prior Phase 2]" in out and "[tw-equity Phase 2]" in out


def test_prior_missing_required_anchor_does_not_abort(env) -> None:
    base, _, write_inputs, _ = env
    write_inputs(True)
    raw = _raw(run_tw_equity_pipeline("3653", dry_run=True, base_dir=base))
    assert "ar_mdna" in raw["prior"]["anchors_summary"]
    assert raw["prior"]["anchors_summary"]["ar_mdna"] is None


def test_no_prior_never_loads_prior_pdf(env) -> None:
    base, load_calls, write_inputs, _ = env
    write_inputs(False)
    raw = _raw(run_tw_equity_pipeline("3653", dry_run=True, base_dir=base))
    assert raw["prior"] is None
    assert "ar_prior.pdf" not in [n for n, _ in load_calls]


def test_ocr_true_with_prior_passes_ocr_to_both_years(env) -> None:
    base, load_calls, write_inputs, mp = env
    write_inputs(True)
    fake = _FakeOcr()
    mp.setattr(tw_pipeline, "_build_ocr", lambda: fake)
    run_tw_equity_pipeline("3653", dry_run=True, base_dir=base, ocr=True)
    by_name = {n: kw for n, kw in load_calls}
    assert set(by_name) == {"ar.pdf", "fs.pdf", "ar_prior.pdf"}
    assert all(kw.get("ocr") is fake for kw in by_name.values())
