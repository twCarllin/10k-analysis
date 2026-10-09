"""主題事實包、核對泛化、主題模板、LLM 問答與 CLI --llm（G2；task/2026-10-09-tw-equity-qa-llm.md）。

契約 row：
  L1: LLM 答案數字都在所選主題內 → 輸出 LLM 答案，註明核對通過
  L2: 第一次有錯、重試後全對 → 輸出重試答案
  L3: 兩次都有錯 → 輸出所選主題的模板答案，註明 LLM 未通過核對
  L4: LLM 選了不存在的主題 → 視同失敗（重試／退回）
  L5: LLM 例外或 JSON 無法解析 → 視同失敗，不中斷 CLI
  L6: supported=false → 回無法回答說明，不含數字
  L7: 不加 --llm → 行為同 G1，不呼叫 LLM
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import qa, qa_llm  # noqa: E402
from runtime.tw_equity.statements import StatementRow  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_qa_fcf import _ledger, _rows  # noqa: E402


def _is(i: int, label: str, cur, pri, key) -> StatementRow:
    return StatementRow(statement="is", section="", label=label, key=key, note=None, current=cur, prior=pri,
                        current_pct=None, prior_pct=None, page=5, line_idx=i)


def _full_ledger():
    led = _ledger(_rows() + [_is(0, "營業收入合計", 10_000_000, 8_000_000, "revenue"),
                             _is(1, "營業毛利", 2_000_000, 2_000_000, "gross_profit")])
    led.periods = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                   "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": None}
    return led


def _pack():
    return qa.topic_pack(_full_ledger())


# ── 1.1 主題事實包 ─────────────────────────────────────────────────────────

def test_topic_pack_three_kinds_and_pages() -> None:
    p = _pack()
    assert p["answerable"] and p["basis"] == "H1"
    t = p["topics"]
    assert t[qa.FCF_TOPIC]["kind"] == "fcf"
    gm = t["gross_margin"]
    assert gm["kind"] == "metric" and gm["current"] == 20.0 and gm["prior"] == 25.0 and gm["delta"] == -5.0
    assert {i["key"]: i["page"] for i in gm["inputs"]} == {"gross_profit": 5, "revenue": 5}
    assert gm["inputs"][1]["label"] == "營業收入合計"
    fcf_b = t["bridge:fcf"]
    assert fcf_b["kind"] == "bridge" and fcf_b["delta"] == -250_000
    assert [c["page"] for c in fcf_b["components"]] == [9, 9]
    assert sum(1 for v in t.values() if v["kind"] == "metric") == 30
    assert sum(1 for v in t.values() if v["kind"] == "bridge") == 8


def test_topic_pack_fh_and_none() -> None:
    p = qa.topic_pack(_full_ledger(), "fh")
    assert qa.FCF_TOPIC not in p["topics"] and "gross_margin" not in p["topics"]
    assert "cost_income_ratio" in p["topics"] and list(k for k in p["topics"] if k.startswith("bridge:")) == [
        "bridge:net_income"]
    assert qa.topic_pack(None)["answerable"] is False


# ── 1.2 核對泛化 ───────────────────────────────────────────────────────────

def test_verify_topics_metric_units_and_tamper() -> None:
    p = _pack()
    ok = "毛利率由 25.00% 降為 20.00%，變動 -5.00 百分點；營業收入 100.00 億元（p.5）。"
    assert qa.verify_topics(ok, p, ["gross_margin"]) == []
    assert qa.verify_topics(ok.replace("20.00%", "21.00%"), p, ["gross_margin"]) == ["21.00%"]


def test_verify_topics_only_selected_topics() -> None:
    p = _pack()
    text = "FCF 為 -0.50 億元。"
    assert qa.verify_topics(text, p, [qa.FCF_TOPIC]) == []
    assert qa.verify_topics(text, p, ["gross_margin"]) == ["-0.50 億"]
    assert qa.verify_topics(text, p, ["no_such_topic"]) == ["-0.50 億"]


def test_verify_topics_days_and_times() -> None:
    p = _pack()
    p["topics"]["dso"].update(current=54.04, prior=49.5, delta=4.54)
    p["topics"]["cfo_to_net_income"].update(current=1.234, prior=None, delta=None)
    assert qa.verify_topics("應收帳款天數 54.0 天、增加 4.5 天", p, ["dso"]) == []
    assert qa.verify_topics("1.23 倍", p, ["cfo_to_net_income"]) == []
    assert qa.verify_topics("1.50 倍", p, ["cfo_to_net_income"]) == ["1.50 倍"]


def test_metric_inputs_carry_unit_ccc_days() -> None:
    p = _pack()
    ccc = p["topics"]["ccc"]
    assert {i["key"]: i["unit"] for i in ccc["inputs"]} == {"dso": "天", "dio": "天", "dpo": "天"}
    assert {i["key"]: i["unit"] for i in p["topics"]["fcf_margin"]["inputs"]} == {"fcf": "仟元", "revenue": "仟元"}
    ccc["inputs"][0].update(current=54.04, prior=49.5)
    assert "54.0 天" in qa.render_topics_answer(p, ["ccc"], company="X")
    assert qa.verify_topics("應收帳款天數 54.0 天", p, ["ccc"]) == []
    assert qa.verify_topics("毛利率 20.00％", p, ["gross_margin"]) == []
    assert qa.verify_topics("毛利率 21.00％", p, ["gross_margin"]) == ["21.00％"]


# ── 1.3 主題模板 ───────────────────────────────────────────────────────────

def test_render_topics_answer_verifies() -> None:
    p = _pack()
    keys = list(p["topics"])
    for k in keys:
        assert qa.verify_topics(qa.render_topics_answer(p, [k], company="X"), p, [k]) == [], k
    text = qa.render_topics_answer(p, ["gross_margin", "bridge:operating_income"], company="X", source="x.pdf")
    assert "毛利率：本期 20.00%，去年同期 25.00%，變動 -5.00 百分點" in text
    assert "1–6 月累計" in text and "未年化" in text and "x.pdf" in text
    combo = qa.render_topics_answer(p, [qa.FCF_TOPIC, "gross_margin"], company="X")
    assert combo.count("期間與限制") == 1 and "四、出處" not in combo and "一、變動歸因" in combo
    assert qa.render_topics_answer(p, [qa.FCF_TOPIC], company="X") == qa.render_fcf_answer(
        p["topics"][qa.FCF_TOPIC]["facts"], company="X")


# ── 2.1 LLM 流程 ───────────────────────────────────────────────────────────

class _FakeLlm:
    def __init__(self, *outs):
        self.outs = list(outs)
        self.calls: list[dict] = []

    def __call__(self, inputs):
        self.calls.append(dict(inputs))
        out = self.outs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


_GOOD = {"supported": True, "topics": ["gross_margin"], "answer": "毛利率由 25.00% 降為 20.00%（p.5）。"}
_BAD = {"supported": True, "topics": ["gross_margin"], "answer": "毛利率由 25.00% 降為 19.00%（p.5）。"}


def test_l1_llm_pass_and_inputs() -> None:
    llm = _FakeLlm(_GOOD)
    text, meta = qa_llm.answer_llm(_pack(), "毛利率多少", company="X", llm=llm)
    assert meta == {"source": "llm", "topics": ["gross_margin"], "attempts": 1, "problems": []}
    assert text.startswith("毛利率由 25.00%") and "數字核對通過" in text
    facts = json.loads(llm.calls[0]["facts_json"])
    assert facts["topics"]["gross_margin"]["current"] == "20.00%"
    assert facts["topics"][qa.FCF_TOPIC]["fcf"]["current"] == "-0.50 億元"
    assert "retry_hint" not in llm.calls[0]


def test_l2_retry_then_pass() -> None:
    llm = _FakeLlm(_BAD, _GOOD)
    text, meta = qa_llm.answer_llm(_pack(), "毛利率多少", company="X", llm=llm)
    assert meta["source"] == "llm" and meta["attempts"] == 2
    assert "19.00%" in llm.calls[1]["retry_hint"]


def test_l3_two_failures_fall_back_to_template() -> None:
    text, meta = qa_llm.answer_llm(_pack(), "毛利率多少", company="X", llm=_FakeLlm(_BAD, _BAD))
    assert meta["source"] == "template" and meta["topics"] == ["gross_margin"]
    assert "毛利率：本期 20.00%" in text and "LLM 答案 2 次未通過檢查" in text and "19.00%" in text


def test_l4_unknown_topic_is_failure() -> None:
    bad = {"supported": True, "topics": ["revenue_growth"], "answer": "營收成長。"}
    llm = _FakeLlm(bad, bad)
    text, meta = qa_llm.answer_llm(_pack(), "營收成長多少", company="X", llm=llm)
    assert meta["source"] == "none" and "revenue_growth" in llm.calls[1]["retry_hint"]
    assert "無法回答" in text


def test_l4_non_string_topics_is_failure() -> None:
    bad = {"supported": True, "topics": [["gross_margin"]], "answer": "毛利率 20.00%。"}
    text, meta = qa_llm.answer_llm(_pack(), "毛利率多少", company="X", llm=_FakeLlm(bad, bad))
    assert meta["source"] == "none" and "topics 元素必須是字串" in text


def test_l5_exception_and_parse_error() -> None:
    llm = _FakeLlm(TimeoutError("timeout"), {"error": "JSON parse failed", "raw": "x"})
    text, meta = qa_llm.answer_llm(_pack(), "本季影響 FCF 最多的是什麼？", company="X", llm=llm)
    assert meta["source"] == "template" and meta["topics"] == [qa.FCF_TOPIC]  # FCF 問題退回 G1 模板
    assert text.startswith("【X】自由現金流（FCF）")


def test_l6_unsupported() -> None:
    out = {"supported": False, "topics": [], "answer": "帳本沒有股價資料，無法回答。"}
    text, meta = qa_llm.answer_llm(_pack(), "股價多少", company="X", llm=_FakeLlm(out))
    assert meta["source"] == "llm" and meta["topics"] == [] and "超出可回答範圍" in text
    with_num = {"supported": False, "topics": [], "answer": "股價 100 億元。"}
    _, meta = qa_llm.answer_llm(_pack(), "股價多少", company="X", llm=_FakeLlm(with_num, with_num))
    assert meta["source"] == "none"


# ── 2.2 CLI ────────────────────────────────────────────────────────────────

def _inputs(tmp_path: Path, ticker: str, group: str) -> Path:
    d = tmp_path / "tw_equity_inputs"
    d.mkdir(exist_ok=True)
    (d / f"{ticker}.json").write_text(json.dumps({"company_name": "測試", "group": group,
                                                  "consolidated_fs_path": "x.pdf"}), encoding="utf-8")
    return tmp_path


def test_l7_cli_llm_path_and_default(monkeypatch, tmp_path) -> None:
    base = _inputs(tmp_path, "9999", "industrial")
    seen = {}

    def fake_load(p, group=None):
        seen["group"] = group
        return _full_ledger()

    monkeypatch.setattr(qa, "load_ledger", fake_load)
    llm = _FakeLlm(_GOOD)
    text, pack = qa.answer("9999", "毛利率多少", base_dir=base, use_llm=True, llm=llm)
    assert "數字核對通過" in text and pack["topics"]["gross_margin"]["current"] == 20.0
    assert seen["group"] == "industrial" and llm.calls[0]["company"] == "9999 測試"
    unused = _FakeLlm()
    text, facts = qa.answer("9999", "毛利率多少", base_dir=base, llm=unused)  # 不加 --llm：同 G1
    assert "G1 只支援 FCF 問題" in text and facts is None
    text, facts = qa.answer("9999", "本季影響 FCF 最多的是什麼？", base_dir=base, llm=unused)
    assert facts["answerable"] and unused.calls == []  # 不呼叫 LLM


def test_cli_llm_fh_gets_metrics(monkeypatch, tmp_path) -> None:
    base = _inputs(tmp_path, "2881", "fh")
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    out = {"supported": False, "topics": [], "answer": "金控不適用 FCF。"}
    text, pack = qa.answer("2881", "FCF 多少", base_dir=base, use_llm=True, llm=_FakeLlm(out))
    assert qa.FCF_TOPIC not in pack["topics"] and "cost_income_ratio" in pack["topics"]


def test_cli_main_llm_flag(monkeypatch, tmp_path, capsys) -> None:
    base = _inputs(tmp_path, "9999", "industrial")
    monkeypatch.chdir(base)
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    llm = _FakeLlm(_GOOD)
    monkeypatch.setattr(qa_llm, "_azure_llm", llm)
    assert qa.main(["--ticker", "9999", "--ask", "毛利率多少", "--llm"]) == 0
    assert "數字核對通過" in capsys.readouterr().out and len(llm.calls) == 1
    assert qa.main(["--ticker", "9999", "--ask", "本季 FCF 多少"]) == 0  # 無 --llm：不呼叫
    assert len(llm.calls) == 1
