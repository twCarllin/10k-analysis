"""run_tw_equity_pipeline 的 ocr 旗標與 OCR 鏈（1B-2 item 6.1，Spec §2.6）。

邊界 mock：pdf_doc.load_pdf 依路徑回真實 fixture（記錄 kwargs）；OCR 鏈建構點與
run_agent（LLM 邊界）以假物件／dry-run 取代。不打任何真實 API。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runtime"))

import pytest  # noqa: E402

from runtime.tw_credit.adapters import AdapterError  # noqa: E402
from runtime.tw_equity import pdf_doc, tw_pipeline  # noqa: E402
from runtime.tw_equity.doc_anchor import AnchorError  # noqa: E402
from runtime.tw_equity.pdf_doc import PdfDoc  # noqa: E402
from runtime.tw_equity.tw_pipeline import run_tw_equity_pipeline  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"


def _load(name: str) -> PdfDoc:
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


class _FakeOcr:
    def __call__(self, path, pages):
        return {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agent_runner
    import eval_runner

    (tmp_path / "tw_equity_inputs").mkdir()
    (tmp_path / "ar.pdf").write_bytes(b"%PDF-dummy")
    (tmp_path / "fs.pdf").write_bytes(b"%PDF-dummy")

    def write_inputs(with_fs: bool) -> None:
        d = {"ticker": "3653", "company_name": "健策精密工業股份有限公司",
             "fiscal_year": 2025, "annual_report_path": "ar.pdf",
             "consolidated_fs_path": "fs.pdf" if with_fs else None}
        (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps(d), encoding="utf-8")

    docs = {"ar.pdf": _load("ar_3653_pages.json"), "fs.pdf": _load("fs_3653_pages.json")}
    load_calls: list[tuple[str, dict]] = []

    def fake_load(path, **kw):
        load_calls.append((Path(path).name, dict(kw)))
        return docs[Path(path).name]

    monkeypatch.setattr(pdf_doc, "load_pdf", fake_load)
    agent_runner.set_dry_run(True)
    yield tmp_path, load_calls, docs, write_inputs, monkeypatch
    agent_runner.set_dry_run(False)


def _raw(md: Path) -> dict:
    (raw_path,) = md.parent.glob("*_raw.json")
    return json.loads(raw_path.read_text(encoding="utf-8"))


def test_ocr_false_does_not_pass_ocr_kwarg(env) -> None:
    base, load_calls, _, write_inputs, _ = env
    write_inputs(True)
    run_tw_equity_pipeline("3653", dry_run=True, base_dir=base, ocr=False)
    assert [n for n, _ in load_calls] == ["ar.pdf", "fs.pdf"]
    assert all("ocr" not in kw for _, kw in load_calls)


def test_ocr_true_passes_chain_instance_to_every_load(env) -> None:
    import dataclasses
    base, load_calls, docs, write_inputs, mp = env
    write_inputs(True)
    docs["ar.pdf"] = dataclasses.replace(docs["ar.pdf"], garbled_pages=[7, 9], ocr_pages=[7])
    fake = _FakeOcr()
    mp.setattr(tw_pipeline, "_build_ocr", lambda: fake)
    md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=base, ocr=True)
    assert len(load_calls) == 2
    assert all(kw.get("ocr") is fake for _, kw in load_calls)
    raw = _raw(md)
    assert raw["garbled_pages"] == [7, 9]
    assert raw["ocr_pages"] == [7]


def test_ocr_true_without_fs_only_ar_gets_ocr(env) -> None:
    base, load_calls, _, write_inputs, mp = env
    write_inputs(False)
    fake = _FakeOcr()
    mp.setattr(tw_pipeline, "_build_ocr", lambda: fake)
    run_tw_equity_pipeline("3653", dry_run=True, base_dir=base, ocr=True)
    assert [(n, kw.get("ocr") is fake) for n, kw in load_calls] == [("ar.pdf", True)]


def test_no_prior_leaves_cross_year_fields_none(env) -> None:
    base, _, _, write_inputs, _ = env
    write_inputs(True)
    raw = _raw(run_tw_equity_pipeline("3653", dry_run=True, base_dir=base))
    assert raw["prior"] is None
    assert raw["cross_year"] is None
    assert raw["cross_year_compare"] is None
    assert raw["ocr_pages"] == []
    assert "tw_cost_structure" in raw["skill_results"]


def test_current_year_missing_required_anchor_raises(env) -> None:
    base, _, docs, write_inputs, _ = env
    write_inputs(True)
    docs["ar.pdf"] = PdfDoc(path=Path("x"), pages=docs["ar.pdf"].pages[:1])
    with pytest.raises(AnchorError):
        run_tw_equity_pipeline("3653", dry_run=True, base_dir=base)


class _Boom:
    def __init__(self, msg):
        self._msg = msg

    def __call__(self, path, pages):
        raise AdapterError(self._msg)


def test_ocr_chain_falls_back_to_di_when_mistral_fails(monkeypatch) -> None:
    ok = {51: "page"}
    monkeypatch.setattr(tw_pipeline.ocr_mod, "MistralPageOcr", lambda: _Boom("mistral-down"))
    monkeypatch.setattr(tw_pipeline.ocr_mod, "DiPageOcr", lambda: (lambda p, pg: ok))
    assert tw_pipeline._build_ocr()(Path("a.pdf"), [51]) is ok


def test_ocr_chain_both_fail_raises_with_both_reasons(monkeypatch) -> None:
    monkeypatch.setattr(tw_pipeline.ocr_mod, "MistralPageOcr", lambda: _Boom("mistral-down"))
    monkeypatch.setattr(tw_pipeline.ocr_mod, "DiPageOcr", lambda: _Boom("di-down"))
    with pytest.raises(AdapterError) as ei:
        tw_pipeline._build_ocr()(Path("a.pdf"), [51])
    assert "mistral-down" in str(ei.value) and "di-down" in str(ei.value)
