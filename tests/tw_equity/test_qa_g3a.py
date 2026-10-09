"""問答核對擴充：萬元／兆／pp 單位、方向詞核對、毛利 bridge 與毛利率拆解（G3a；task/2026-10-10-tw-equity-qa-g3a.md）。

契約 row：
  V1: 數字＋萬元／兆／pp，值正確 → 通過
  V2: 方向詞＋緊接數字，數字對到 delta 且同號 → 通過
  V3: 方向詞＋緊接數字，對到的 delta 全部反號、且不等於任何非 delta 值 → 回傳該片段（方向與帳本不符）
  V4: 方向詞後接至／到／為 → 不檢查方向
  V5: 方向詞無緊接數字 → 不檢查
  V6: 組成項／輸入兩期皆負（成本、流出） → delta 或絕對值變化任一方向一致即通過
  V7: G1／G2 既有答案與測試 → 結果不變（test_qa_fcf.py、test_qa_llm.py 不改且通過）
  V8: 金控 pack → 無 gross_profit／gross_margin 主題
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import qa, qa_llm  # noqa: E402
from runtime.tw_equity.metrics import BRIDGE_SPECS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_qa_fcf import _ledger, _rows  # noqa: E402
from test_qa_llm import _is  # noqa: E402

M = 1_000_000  # 帳本仟元；100*M 仟元＝1,000 億元


def _pack(topics: dict) -> dict:
    return {"answerable": True, "topics": topics}


def _metric(unit: str, cur: float, pri: float) -> dict:
    return {"kind": "metric", "unit": unit, "current": cur, "prior": pri, "delta": cur - pri, "inputs": []}


def _bridge(cur: float, pri: float, components: list[dict] | None = None) -> dict:
    return {"kind": "bridge", "current": cur, "prior": pri, "delta": cur - pri, "residual": 0.0,
            "components": components or []}


def _comp(cur: float, pri: float) -> dict:
    return {"current": cur, "prior": pri, "delta": cur - pri, "share": None}


def _gross_ledger(rev: tuple, cogs: tuple, gp: tuple):
    led = _ledger(_rows() + [_is(0, "營業收入合計", *rev, "revenue"), _is(1, "營業成本合計", *cogs, "cogs"),
                             _is(2, "營業毛利（毛損）", *gp, "gross_profit")])
    led.periods = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                   "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": None}
    return led


# ── 1.1 單位擴充 ───────────────────────────────────────────────────────────

def test_v1_wan_and_zhao_units() -> None:
    p = _pack({"m": _metric("仟元", 1_234_560, 1_000_000)})
    assert qa.verify_topics("本期 123,456 萬元，亦即 0.00123456 兆元", p, ["m"]) == []
    assert qa.verify_topics("本期 123,457 萬元", p, ["m"]) == ["123,457 萬元"]


def test_v1_pp_unit() -> None:
    p = _pack({"gm": _metric("%", 6.15, 6.23)})
    assert qa.verify_topics("毛利率變動 -0.08 pp", p, ["gm"]) == []
    assert qa.verify_topics("毛利率變動 -0.09 pp", p, ["gm"]) == ["-0.09 pp"]


def test_v1_million_not_parsed_as_wan() -> None:
    p = _pack({"m": _metric("仟元", 12_000, 1)})
    assert qa.verify_topics("本期 12 百萬元", p, ["m"]) == []
    assert qa.verify_topics("本期 12 萬元", p, ["m"]) == ["12 萬元"]


# ── 1.2 方向詞核對 ─────────────────────────────────────────────────────────

def test_v2_v3_direction_against_delta() -> None:
    p = _pack({"b": _bridge(10 * M, 15 * M)})  # delta -50 億
    assert qa.verify_topics("營業利益減少 50 億元", p, ["b"]) == []
    assert qa.verify_topics("營業利益增加 50 億元", p, ["b"]) == ["增加 50 億（方向與帳本不符）"]
    assert qa.verify_topics("營業利益下降了約 50.00 億元", p, ["b"]) == []


def test_v4_v5_level_and_no_number_not_checked() -> None:
    p = _pack({"b": _bridge(10 * M, 15 * M)})
    assert qa.verify_topics("營業利益上升至 100 億元", p, ["b"]) == []
    assert qa.verify_topics("營業利益增加，本期 100 億元", p, ["b"]) == []


def test_v3_number_equal_to_level_not_flagged() -> None:
    p = _pack({"b": _bridge(5 * M, 10 * M)})  # delta -50 億＝本期水準 50 億
    assert qa.verify_topics("增加 50 億元", p, ["b"]) == []


def test_v6_cost_component_either_direction() -> None:
    p = _pack({"b": _bridge(20 * M, 18 * M, [_comp(-15 * M, -10 * M)])})  # 成本 -100→-150 億
    assert qa.verify_topics("營業成本增加 50 億元", p, ["b"]) == []
    assert qa.verify_topics("使營業利益減少 50 億元", p, ["b"]) == []


def test_v3_negative_target_still_strict() -> None:
    p = _pack({"b": _bridge(-15 * M, -10 * M)})  # 合計（非組成項）兩期皆負，delta -50 億
    assert qa.verify_topics("增加 50 億元", p, ["b"]) == ["增加 50 億（方向與帳本不符）"]


def test_v3_metric_input_direction() -> None:
    m = _metric("%", 20.0, 25.0)
    m["inputs"] = [{"unit": "仟元", "current": 12 * M, "prior": 10 * M}]  # 營收輸入 100→120 億，delta +20 億
    p = _pack({"gm": m})
    assert qa.verify_topics("營收增加 20 億元", p, ["gm"]) == []
    assert qa.verify_topics("營收減少 20 億元", p, ["gm"]) == ["減少 20 億（方向與帳本不符）"]


def test_v3_margin_direction() -> None:
    p = _pack({"gm": _metric("%", 6.15, 6.23)})
    assert qa.verify_topics("毛利率下降 0.08 百分點", p, ["gm"]) == []
    assert qa.verify_topics("毛利率上升 0.08 百分點", p, ["gm"]) == ["上升 0.08 百分點（方向與帳本不符）"]


def test_v3_g1_fcf_direction() -> None:
    facts = qa.fcf_facts(_ledger(_rows()))  # FCF 2.00 → -0.50 億，delta -2.50 億
    assert qa.verify_numbers("FCF 較去年同期減少 2.50 億元", facts) == []
    assert qa.verify_numbers("FCF 較去年同期增加 2.50 億元", facts) == ["增加 2.50 億（方向與帳本不符）"]
    assert qa.verify_numbers(qa.render_fcf_answer(facts, company="X"), facts) == []


# ── 1.3 毛利金額 bridge ─────────────────────────────────────────────────────

def test_gross_profit_bridge() -> None:
    led = _gross_ledger((120 * M, 100 * M), (-80 * M, -60 * M), (40 * M, 40 * M))
    b = qa.topic_pack(led)["topics"]["bridge:gross_profit"]
    assert b["kind"] == "bridge" and b["delta"] == 0 and b["residual"] == 0
    assert {c["key"]: c["delta"] for c in b["components"]} == {"revenue": 20 * M, "cogs": -20 * M}
    assert all(c["page"] == 5 for c in b["components"])


def test_v8_fh_and_bridge_specs_unchanged() -> None:
    led = _gross_ledger((120 * M, 100 * M), (-80 * M, -60 * M), (40 * M, 40 * M))
    t = qa.topic_pack(led, "fh")["topics"]
    assert "bridge:gross_profit" not in t and "bridge:gross_margin" not in t
    assert "gross_profit" not in [s.target for s in BRIDGE_SPECS]


# ── 1.4 毛利率拆解 ─────────────────────────────────────────────────────────

def _margin_pack():
    return qa.topic_pack(_gross_ledger((125 * M, 100 * M), (-80 * M, -60 * M), (45 * M, 40 * M)))


def test_gross_margin_decomposition() -> None:
    t = _margin_pack()["topics"]["bridge:gross_margin"]
    assert t["kind"] == "margin_bridge"
    assert abs(t["current"] - 36) < 1e-9 and abs(t["prior"] - 40) < 1e-9 and abs(t["delta"] + 4) < 1e-9
    eff = {c["key"]: c["value"] for c in t["components"]}
    assert abs(eff["revenue_effect"] - 12) < 1e-9 and abs(eff["cost_effect"] + 16) < 1e-9
    assert abs(sum(eff.values()) - t["delta"]) < 1e-9
    assert [i["key"] for i in t["inputs"]] == ["revenue", "cogs"]


def test_margin_template_verifies_and_llm_view() -> None:
    p = _margin_pack()
    keys = ["gross_margin", "bridge:gross_margin", "bridge:gross_profit"]
    text = qa.render_topics_answer(p, keys, company="X")
    assert "營收變動效果：12.00 百分點" in text and "成本變動效果：-16.00 百分點" in text
    assert qa.verify_topics(text, p, keys) == []
    view = qa_llm._topic_view(p["topics"]["bridge:gross_margin"])
    assert [c["delta"] for c in view["components"]] == ["12.00 百分點", "-16.00 百分點"]


def test_margin_requires_cogs() -> None:
    led = _ledger(_rows() + [_is(0, "營業收入合計", 120 * M, 100 * M, "revenue"),
                             _is(2, "營業毛利", 40 * M, 40 * M, "gross_profit")])
    t = qa.topic_pack(led)["topics"]
    assert "bridge:gross_profit" not in t and "bridge:gross_margin" not in t
