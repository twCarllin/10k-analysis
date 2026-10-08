"""1B-1 端到端整合測試（task item 6.1，Spec §4／§5 DoD-2）。

邊界 mock：pdf_doc.load_pdf 依路徑回真實 fs／ar fixture；run_agent（LLM 邊界）走 dry-run mock。
sabotage 自檢目標（各一處，見 item 6.1 DoD 4）由下列測試守住：
- tables.parse_key_lines_from_lines 續行合併 → test_real_fixture_numbers_and_missing_tables
- doc_anchor.find_heading_sections 的 after → test_real_fixture_numbers_and_missing_tables
- tables.parse_guarantees_loans 名稱續行 → test_heading_anchors_and_guarantor_name
- tw_pipeline 讀 skip_if_empty → test_fs_null_skips_kam_and_marks_missing
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
from runtime.tw_equity.tw_pipeline import run_tw_equity_pipeline  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"


def _load(name: str):
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
    docs = {"ar.pdf": _load("ar_3653_pages.json"), "fs.pdf": _load("fs_3653_pages.json")}
    monkeypatch.setattr(pdf_doc, "load_pdf", lambda path, **kw: docs[Path(path).name])

    state = {"gov_error": False}
    orig = agent_runner.run_agent

    def fake(agent_name, skill_name, inputs, **kw):
        if state["gov_error"] and skill_name == "tw_governance_flags":
            return {"error": "mock governance failure", "insufficient_data": True}
        return orig(agent_name, skill_name, inputs, **kw)

    agent_runner.set_dry_run(True)
    monkeypatch.setattr(agent_runner, "run_agent", fake)
    monkeypatch.setattr(eval_runner, "run_agent", fake)

    def run(with_fs: bool = True, gov_error: bool = False):
        state["gov_error"] = gov_error
        (tmp_path / "tw_equity_inputs" / "3653.json").write_text(json.dumps({
            "ticker": "3653", "company_name": "健策精密工業股份有限公司",
            "fiscal_year": 2025, "annual_report_path": "ar.pdf",
            "consolidated_fs_path": "fs.pdf" if with_fs else None,
            "parent_fs_path": None,
        }), encoding="utf-8")
        md = run_tw_equity_pipeline("3653", dry_run=True, base_dir=tmp_path)
        (raw_path,) = md.parent.glob("*_raw.json")
        return md.read_text(encoding="utf-8"), json.loads(raw_path.read_text(encoding="utf-8"))

    yield run
    agent_runner.set_dry_run(False)


def _start(v) -> int:
    return int(re.search(r"start=(\d+)", str(v)).group(1))


def test_real_fixture_numbers_and_missing_tables(env) -> None:
    text, raw = env()
    bundle = raw["bundle"]
    assert sorted(bundle["missing_tables"]) == ["T1", "T2", "T3", "T6"]
    assert tuple(bundle["consolidated_key_lines"]["營業成本"]) == (11841587, 8912721)
    assert bundle["parent_cost_coverage"] is None
    assert len(re.findall(r"^## ", text, flags=re.M)) == 12  # 8 主節 + 附錄 A–D
    for heading in ("## 1. ", "## 2. ", "## 3. ", "## 4. ", "## 5. ", "## 6. ", "## 7. ",
                    "## 8. ", "## 附錄 A", "## 附錄 B", "## 附錄 C"):
        assert heading in text


def test_heading_anchors_and_guarantor_name(env) -> None:
    _, raw = env()
    assert _start(raw["anchors_summary"]["fs_bs"]) == 10
    assert _start(raw["anchors_summary"]["ar_governance"]) == 8
    guarantees = raw["bundle"]["guarantees_loans"]["guarantees"]
    assert guarantees[0]["guarantor"] == "健策精密工業股份有限公司"


def test_fs_null_skips_kam_and_marks_missing(env) -> None:
    text, raw = env(with_fs=False)
    assert {"T4", "T5", "T9"} <= set(raw["bundle"]["missing_tables"])
    skipped = text.split("### 跳過的任務")[1]
    assert "tw_kam_analysis" in skipped
    assert "tw_kam_analysis" not in raw["skill_results"]


def test_governance_error_does_not_abort_other_sections(env) -> None:
    text, raw = env(gov_error=True)
    assert "error" in raw["skill_results"]["tw_governance_flags"]
    section7 = text.split("## 7. ")[1].split("## 附錄 A")[0]
    assert "失敗" in section7
    for name in ("tw_cost_structure", "tw_financial_analysis", "tw_footnotes_quality",
                 "tw_kam_analysis", "tw_business_analysis", "tw_customer_supplier"):
        assert "error" not in raw["skill_results"][name]
    for heading in ("## 1. ", "## 2. ", "## 3. ", "## 4. ", "## 5. ", "## 6. "):
        assert heading in text
