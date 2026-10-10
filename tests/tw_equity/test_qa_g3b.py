"""TTM 與金控附註指標接入問答（G3b；task/2026-10-10-tw-equity-qa-g3b.md）。

契約 row：
  V1: H1 帳本＋可用 FY 損益表 → 有 ttm:values、ttm:<指標>、ttm:bridge:*（工業）
  V2: 年報缺／解析失敗／年度不符 → 無 ttm:* 主題；ttm_status unavailable＋原因；其他主題照常
  V3: 金控 → ttm:values（含 scope、IFRS 17 說明）；附註三指標主題附出處
  V4: G1 路徑 → 不讀年報，輸出不變
  V5: TTM 主題數字 → 模板答案核對通過；方向詞以 TTM−FY 判定
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import qa, qa_llm  # noqa: E402
from runtime.tw_equity.fh_notes import CarResult, FhNotes  # noqa: E402
from runtime.tw_equity.fy_income import FyIncome  # noqa: E402
from runtime.tw_equity.metrics import TtmView  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_qa_g3a import _gross_ledger  # noqa: E402
from test_qa_llm import _FakeLlm, _full_ledger  # noqa: E402

M = 1_000_000  # 帳本仟元


def _ledger():
    return _gross_ledger((220 * M, 200 * M), (-130 * M, -120 * M), (90 * M, 80 * M))


def _fy() -> FyIncome:
    rows = [{"label": "營業收入合計", "key": "revenue", "current": 400 * M, "prior": 380 * M},
            {"label": "營業成本合計", "key": "cogs", "current": -240 * M, "prior": -230 * M},
            {"label": "營業毛利", "key": "gross_profit", "current": 160 * M, "prior": 150 * M}]
    return FyIncome(roc_year=114, page=77, unit="新台幣仟元", scale=1.0, rows=rows, usable=True)


def _pack():
    return qa.topic_pack(_ledger(), fy_income=_fy())


# ── 1.1 讀年報與附註 ───────────────────────────────────────────────────────

def test_v2_no_fy_income_same_topics_as_g3a() -> None:
    base = qa.topic_pack(_ledger())
    assert not any(k.startswith("ttm:") for k in base["topics"])
    assert base["ttm_status"] == "unavailable" and base["ttm_reason"] == "年報找不到 FY 損益比較表（fy_income_missing）"
    assert set(_pack()["topics"]) - set(base["topics"]) == {k for k in _pack()["topics"] if k.startswith("ttm:")}


def test_v2_annual_report_failure_still_answers(monkeypatch, tmp_path) -> None:
    d = tmp_path / "tw_equity_inputs"
    d.mkdir()
    (d / "9999.json").write_text(json.dumps({"company_name": "測試", "group": "industrial", "fiscal_year": 2025,
                                             "consolidated_fs_path": "x.pdf", "annual_report_path": "ar.pdf"}),
                                 encoding="utf-8")
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    good = {"supported": True, "topics": ["gross_margin"], "answer": "毛利率 20.00%。"}
    text, pack = qa.answer("9999", "毛利率多少", base_dir=tmp_path, use_llm=True, llm=_FakeLlm(good))
    assert "數字核對通過" in text
    assert pack["ttm_status"] == "unavailable" and "FileNotFoundError" in pack["ttm_reason"]
    assert not any(k.startswith("ttm:") for k in pack["topics"])


def test_v4_g1_path_does_not_read_annual_report(monkeypatch, tmp_path) -> None:
    d = tmp_path / "tw_equity_inputs"
    d.mkdir()
    (d / "9999.json").write_text(json.dumps({"company_name": "測試", "group": "industrial", "fiscal_year": 2025,
                                             "consolidated_fs_path": "x.pdf", "annual_report_path": "ar.pdf"}),
                                 encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("G1 不可讀年報")

    monkeypatch.setattr(qa, "load_fy_income", boom)
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    text, facts = qa.answer("9999", "FCF 多少", base_dir=tmp_path)
    assert facts is not None and qa.verify_numbers(text, facts) == []


def test_v2_fy_year_mismatch_no_ttm_topics() -> None:
    fy = _fy()
    fy.roc_year = 113
    p = qa.topic_pack(_ledger(), fy_income=fy)
    assert p["ttm_status"] == "unavailable" and "fy_year_mismatch" in p["ttm_reason"]
    assert not any(k.startswith("ttm:") for k in p["topics"]) and "gross_margin" in p["topics"]


def test_v2_missing_fiscal_year_still_answers(monkeypatch, tmp_path) -> None:
    d = tmp_path / "tw_equity_inputs"
    d.mkdir()
    (d / "9999.json").write_text(json.dumps({"company_name": "測試", "group": "industrial",
                                             "consolidated_fs_path": "x.pdf", "annual_report_path": "ar.pdf"}),
                                 encoding="utf-8")
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    good = {"supported": True, "topics": ["gross_margin"], "answer": "毛利率 20.00%。"}
    text, pack = qa.answer("9999", "毛利率多少", base_dir=tmp_path, use_llm=True, llm=_FakeLlm(good))
    assert "數字核對通過" in text and "fiscal_year" in pack["ttm_reason"]


# ── 1.2 一般公司 TTM 主題 ──────────────────────────────────────────────────

def test_v1_ttm_values_metrics_bridges() -> None:
    p = _pack()
    assert p["ttm_status"] == "ok" and p["ttm_period"] == "115-06-30" and p["fy_period"] == "114"
    rows = {r["key"]: r for r in p["topics"]["ttm:values"]["rows"]}
    assert rows["revenue"]["ttm"] == 420 * M and rows["revenue"]["fy"] == 400 * M
    assert p["topics"]["ttm:values"]["fy_page"] == 77
    assert "ttm:revenue" not in p["topics"]  # 非指標
    gm = p["topics"]["ttm:gross_margin"]
    assert gm["compare"] == "ttm_vs_fy" and abs(gm["current"] - 170 / 420 * 100) < 1e-9
    assert abs(gm["prior"] - 160 / 400 * 100) < 1e-9


def test_v1_ttm_bridge_residual_matches_view() -> None:
    from runtime.tw_equity.metrics import compute_metrics
    view = compute_metrics(_ledger(), _fy()).ttm
    b = next(x for x in view.bridges if x.target == "net_income")
    t = _pack()["topics"].get("ttm:bridge:net_income")
    assert t is not None and t["residual"] == b.residual and t["page"] is None


def test_v5_template_answers_verify_clean() -> None:
    p = _pack()
    keys = [k for k in p["topics"] if k.startswith("ttm:")]
    for k in keys:
        text = qa.render_topics_answer(p, [k], company="9999")
        assert qa.verify_topics(text, p, [k]) == [], (k, text)
    text = qa.render_topics_answer(p, keys, company="9999")
    assert "近四季" in text and "FY 114 年度" in text


def test_v5_direction_uses_ttm_minus_fy() -> None:
    p = _pack()  # 營收 TTM 4,200 億 vs FY 4,000 億 → TTM−FY ＝ +200 億
    d = (420 - 400) * M / 100_000  # 億
    assert qa.verify_topics(f"TTM 營收較 FY 增加 {d:,.2f} 億", p, ["ttm:values"]) == []
    assert qa.verify_topics(f"TTM 營收較 FY 減少 {d:,.2f} 億", p, ["ttm:values"]) != []


# ── 1.3 金控 TTM 與附註主題 ────────────────────────────────────────────────

def test_v3_fh_note_metrics_with_source() -> None:
    notes = FhNotes(group_car=CarResult(value=125.3, period="115-06-30", page=88))
    p = qa.topic_pack(_full_ledger(), "fh", notes=notes)
    car = p["topics"]["group_car"]
    assert car["current"] == 125.3 and car["prior"] is None
    assert car["source"]["current"]["page"] == 88
    assert p["topics"]["npl_ratio"]["source"]["current"]["reason"] == "無資產品質附註"
    for k in ("group_car", "npl_ratio", "coverage_ratio"):
        text = qa.render_topics_answer(p, [k], company="2881")
        assert qa.verify_topics(text, p, [k]) == [], text
    assert "財報附註 p.88" in qa.render_topics_answer(p, ["group_car"], company="2881")


def test_v3_fh_ttm_values_comparability_note() -> None:
    view = TtmView(status="ok", period_ttm="115-06-30", period_fy="114", source_page=9, scope="consolidated",
                   comparability="ifrs17_break", comparability_note="TTM 混用兩種準則",
                   values={"net_income": {"fy": 100 * M, "h1_current": 60 * M, "h1_prior": 50 * M, "ttm": 110 * M}})
    t = qa._ttm_topics(_full_ledger(), view)
    assert t["ttm:values"]["comparability_note"] == "TTM 混用兩種準則"
    p = {"answerable": True, "topics": t, "periods": {}, "basis": "H1", "assurance": "reviewed"}
    text = qa.render_topics_answer(p, ["ttm:values"], company="2881")
    assert "可比性" in text and qa.verify_topics(text, p, ["ttm:values"]) == []


def test_v3_fh_parent_only_scope_rendered() -> None:
    view = TtmView(status="ok", period_ttm="115-06-30", period_fy="114", source_page=9, scope="parent_only",
                   values={"net_income_parent": {"fy": 100 * M, "h1_current": 60 * M, "h1_prior": 50 * M,
                                                  "ttm": 110 * M}})
    t = qa._ttm_topics(_full_ledger(), view)
    assert t["ttm:values"]["scope"] == "parent_only"
    p = {"answerable": True, "topics": t, "periods": {}, "basis": "H1", "assurance": "reviewed"}
    text = qa.render_topics_answer(p, ["ttm:values"], company="2882")
    assert "只算歸屬母公司淨利" in text and qa.verify_topics(text, p, ["ttm:values"]) == []


# ── 1.4 LLM 事實包 ─────────────────────────────────────────────────────────

def test_llm_inputs_carry_ttm() -> None:
    facts = json.loads(qa_llm.llm_inputs(_pack(), "近四季毛利率", "9999")["facts_json"])
    assert facts["context"]["ttm_status"] == "ok" and "ttm:values" in facts["topics"]
    assert "近四季 TTM" in facts["topics"]["ttm:gross_margin"]["compare"]
