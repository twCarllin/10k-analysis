"""1B-2 端到端整合測試（task item 7.1，Spec §4／§5 DoD-2）。

邊界 mock：pdf_doc.load_pdf 依路徑回真實 fixture（2024 年報一律經 apply_ocr_policy，
OCR 變體以假 ocr 回 Mistral fixture 轉換後的頁）；run_agent（LLM 邊界）走 dry-run。
sabotage 自檢目標（各一處，見 item 7.1 DoD 3）由下列測試守住：
- pdf_doc.apply_ocr_policy 未取代亂碼頁清空 → test_no_ocr_cross_year_and_report
- doc_anchor.find_annual_report_sections 標題備援步驟② → test_ocr_variant_with_prior
- cross_year.build_cross_year 的 match 判斷 → test_no_ocr_cross_year_and_report
- tw_pipeline cross_year_compare 例外降級 → test_cross_year_compare_exception_degrades
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

from runtime.tw_equity import ocr as ocr_mod  # noqa: E402
from runtime.tw_equity import pdf_doc, tw_pipeline  # noqa: E402
from runtime.tw_equity.tw_pipeline import run_tw_equity_pipeline  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_HEADINGS = ("## 1. ", "## 2. ", "## 3. ", "## 4. ", "## 5. ", "## 6. ", "## 7. ",
             "## 8. ", "## 附錄 A", "## 附錄 B", "## 附錄 C")


def _load(name: str):
    doc = pdf_doc.from_json(json.loads((_FIX / name).read_text(encoding="utf-8")))
    assert doc is not None
    return doc


class _FixtureOcr:
    """假 OCR：回 Mistral 真實回應 fixture 轉換後的 Page（只回請求的頁）。"""

    def __init__(self) -> None:
        d = json.loads((_FIX / "mistral_3653_2024_p51_p79.json").read_text(encoding="utf-8"))
        self._pages = {int(k): ocr_mod.markdown_to_page(int(k), v) for k, v in d["pages"].items()}
        self.calls: list[list[int]] = []

    def __call__(self, path, pages):
        self.calls.append(list(pages))
        return {n: self._pages[n] for n in pages if n in self._pages}


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agent_runner
    import eval_runner

    (tmp_path / "tw_equity_inputs").mkdir()
    for n in ("ar.pdf", "fs.pdf", "ar_prior.pdf"):
        (tmp_path / n).write_bytes(b"%PDF-dummy")
    cur = {"ar.pdf": _load("ar_3653_pages.json"), "fs.pdf": _load("fs_3653_pages.json")}
    prior_raw = _load("ar2024_3653_pages.json")
    loaded: dict[str, pdf_doc.PdfDoc] = {}

    def fake_load(path, **kw):
        name = Path(path).name
        if name == "ar_prior.pdf":
            loaded[name] = pdf_doc.apply_ocr_policy(prior_raw, kw.get("ocr"))
            return loaded[name]
        return cur[name]

    monkeypatch.setattr(pdf_doc, "load_pdf", fake_load)

    state = {"raise": False}
    orig = agent_runner.run_agent

    def fake(agent_name, skill_name, inputs, **kw):
        if skill_name == "cross_year_compare" and state["raise"]:
            raise RuntimeError("boom-cross")
        return orig(agent_name, skill_name, inputs, **kw)

    agent_runner.set_dry_run(True)
    monkeypatch.setattr(agent_runner, "run_agent", fake)
    monkeypatch.setattr(eval_runner, "run_agent", fake)

    def run(with_prior: bool = True, ocr: bool = False, cross_raises: bool = False):
        state["raise"] = cross_raises
        d = {"ticker": "3653", "company_name": "健策精密工業股份有限公司",
             "fiscal_year": 2025, "annual_report_path": "ar.pdf",
             "consolidated_fs_path": "fs.pdf"}
        if with_prior:
            d["prior"] = {"fiscal_year": 2024, "annual_report_path": "ar_prior.pdf",
                          "consolidated_fs_path": None}
        (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps(d), encoding="utf-8")
        md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=tmp_path, ocr=ocr)
        (raw_path,) = md.parent.glob("*_raw.json")
        return md.read_text(encoding="utf-8"), json.loads(raw_path.read_text(encoding="utf-8"))

    yield run, loaded, monkeypatch
    agent_runner.set_dry_run(False)


def _start(v) -> int:
    return int(re.search(r"start=(\d+)", str(v)).group(1))


def _section(text: str, head: str) -> str:
    return re.split(rf"^## {head}", text, flags=re.M)[1].split("\n## ")[0]


def test_no_ocr_cross_year_and_report(env) -> None:
    run, loaded, _ = env
    text, raw = run()
    prior = raw["prior"]
    assert {51, 79} <= set(prior["garbled_pages"])
    assert prior["ocr_pages"] == []
    for n in (51, 79):  # 未取代的亂碼頁被清空
        page = next(p for p in loaded["ar_prior.pdf"].pages if p.number == n)
        assert page.text == "" and page.lines == [] and page.tables == []
    rev = next(s for s in raw["cross_year"]["fin_performance_series"] if s["label"] == "營業收入")
    assert set(rev["values"]) == {"112年度", "113年度", "114年度"}
    checks = [c for c in raw["cross_year"]["overlap_checks"]
              if c["table"] == "T7b" and c["label"] == "營業收入" and c["year"] == "113年度"]
    assert len(checks) == 1 and checks[0]["match"] is True
    assert len(re.findall(r"^## ", text, flags=re.M)) == 11
    for h in _HEADINGS:
        assert h in text


def test_ocr_variant_with_prior(env) -> None:
    run, _, mp = env
    fake = _FixtureOcr()
    mp.setattr(tw_pipeline, "_build_ocr", lambda: fake)
    text, raw = run(ocr=True)
    prior = raw["prior"]
    assert {51, 79} <= set(prior["ocr_pages"])
    assert "T10_top10" not in prior["bundle"]["missing_tables"]
    assert _start(prior["anchors_summary"]["ar_mdna"]) == 79
    assert prior["anchors_summary"]["ar_market"] is not None  # 2024 年報靠標題備援才找得到
    assert _start(prior["anchors_summary"]["ar_market"]) == 68
    for h in _HEADINGS:
        assert h in text


def test_no_prior_degrades_without_raising(env) -> None:
    run, _, _ = env
    text, raw = run(with_prior=False)
    assert raw["prior"] is None
    assert raw["cross_year"] is None
    assert raw["cross_year_compare"] is None
    assert len(re.findall(r"^## ", text, flags=re.M)) == 11
    for h in _HEADINGS:
        assert h in text
    assert "本節未執行" in _section(text, "8.")
    assert "未執行" in _section(text, "附錄 C")


def test_cross_year_compare_exception_degrades(env) -> None:
    run, _, _ = env
    text, raw = run(cross_raises=True)
    assert "boom-cross" in raw["cross_year_compare"]["error"]
    assert "失敗" in _section(text, "8.")
    for h in _HEADINGS:
        assert h in text
