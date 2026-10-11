"""答案呈現與驗收輸出：bridge 合成項、停業單位、殘差統計（Spec 2026-10-11-tw-equity-bridge-residual §2.3、§2.4）。

契約 row：
  R1: 合成項「其他營業費用」→ 費用句型「費用增加（減少）Z 億，使淨利減少（增加）Z 億」；數字核對通過
  R2: 合成項「其他營業外收支」與停業單位 → 「變動 Z 億元」句型；數字核對通過
  R3: SUMMARY 行加 `bridge_residual_gt5pct=<淨利家數>/<營業利益家數>`（gt5pct：|殘差|>5%|變動| 且 >1000 仟元；金控 None 不計）
  R4: 每家記錄 `bridge_residual`（工業）＝{net_income, operating_income}各 {delta, residual, gt5pct}；殘差統計不影響 conform
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.tw_equity import fs_acceptance, qa  # noqa: E402
from runtime.tw_equity.metrics import BridgeComponent, BridgeResult  # noqa: E402
from test_qa_fcf import _ledger, _rows  # noqa: E402
from test_qa_llm import _is  # noqa: E402

M = 100_000  # 1 億（仟元）
BR = "bridge:net_income"


def _pack(comps: list[BridgeComponent]) -> dict:
    b = BridgeResult("net_income", "淨利變動", 10 * M, 20 * M, -10 * M, comps, 0.0, [])
    return {"answerable": True, "basis": "H1", "assurance": "reviewed",
            "periods": {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                        "bs_current": "115-06-30"},
            "topics": {BR: qa._bridge_topic(_ledger(_rows()), b)}}


def test_r1_synthetic_other_opex_uses_cost_wording() -> None:
    text = qa.render_topics_answer(_pack([BridgeComponent("other_opex_residual", "其他營業費用", -5 * M, -3 * M, -2 * M, 0.2, True)]),
                                   [BR], company="X")
    assert "其他營業費用：費用增加 2.00 億，使淨利減少 2.00 億" in text
    assert qa.verify_topics(text, _pack([BridgeComponent("other_opex_residual", "其他營業費用", -5 * M, -3 * M, -2 * M, 0.2, True)]), [BR]) == []
    assert qa.verify_topics(text.replace("費用增加 2.00 億", "費用增加 2.50 億"), _pack([BridgeComponent("other_opex_residual", "其他營業費用", -5 * M, -3 * M, -2 * M, 0.2, True)]), [BR]) == ["2.50 億"]


def test_r1_synthetic_flag_carried_into_topic() -> None:
    pack = _pack([BridgeComponent("other_opex_residual", "其他營業費用", -5 * M, -3 * M, -2 * M, 0.2, True),
                  BridgeComponent("gross_profit", "營業毛利", 1, 1, 0, 0.0)])
    comps = pack["topics"][BR]["components"]
    assert comps[0]["synthetic"] is True and "synthetic" not in comps[1]


def test_r2_nonop_residual_and_discontinued_use_change_wording() -> None:
    pack = _pack([BridgeComponent("other_nonoperating_residual", "其他營業外收支", 1 * M, 3 * M, -2 * M, 0.2, True),
                  BridgeComponent("discontinued_ops", "停業單位利益", -30 * M, 0, -30 * M, 3.0)])
    text = qa.render_topics_answer(pack, [BR], company="X")
    assert "其他營業外收支：變動 -2.00 億元" in text
    assert "停業單位利益：變動 -30.00 億元" in text
    assert "費用" not in text
    assert qa.verify_topics(text, pack, [BR]) == []
    assert qa.verify_topics(text.replace("-30.00 億元", "-31.00 億元"), pack, [BR]) != []


def _rec(t: str, group, br) -> dict:
    return {"ticker": t, "group": group, "expected": 22, "total": 22, "passed": 22, "excepted": [], "not_passed": [],
            "conform": True, "bridge_residual": br}


def _st(gt_ni: bool, gt_oi: bool) -> dict:
    return {"net_income": {"delta": 100.0, "residual": 9.0, "gt5pct": gt_ni},
            "operating_income": {"delta": 100.0, "residual": 9.0, "gt5pct": gt_oi}}


def test_r3_summary_counts_gt5pct_and_skips_fh(tmp_path, monkeypatch, capsys) -> None:
    recs = {"1": _rec("1", None, _st(True, True)), "2": _rec("2", None, _st(True, False)),
            "3": _rec("3", None, _st(False, False)), "4": _rec("4", "bank", None)}
    monkeypatch.setattr(fs_acceptance, "acceptance_tickers", lambda base: [(t, r["group"]) for t, r in recs.items()])
    monkeypatch.setattr(fs_acceptance, "check_company", lambda t, g, base: recs[t])
    out = tmp_path / "r.json"
    assert fs_acceptance.main(["--all70", "--out", str(out)]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last == "SUMMARY conform=4/4 known_limitations=0 exceptions=0 bridge_residual_gt5pct=2/1"
    assert json.loads(out.read_text(encoding="utf-8"))[3]["bridge_residual"] is None


def _stats_ledger(ni: tuple):
    """營業收入 ＋ 營業成本 ＋ 本期淨利：淨利變動 ni[0]−ni[1]，組成項只有收入、成本（合計 0）→ 殘差＝淨利變動。"""
    led = _ledger(_rows() + [_is(0, "營業收入合計", 120 * M, 100 * M, "revenue"), _is(1, "營業成本合計", 120 * M, 100 * M, "cogs"),
                             _is(2, "本期淨利（淨損）", *ni, "net_income")])
    led.periods = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                   "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": None}
    return led


def test_r4_stats_from_real_bridge_and_threshold() -> None:
    st = fs_acceptance.bridge_residual_stats(_stats_ledger((10 * M, 5 * M)))
    ni = st["net_income"]
    assert ni["delta"] == 5 * M and ni["residual"] is not None and abs(ni["residual"]) > 0.05 * 5 * M
    assert ni["gt5pct"] is True                       # 殘差遠大於 5% 且 > 1000 仟元
    assert set(st) == {"net_income", "operating_income"}
    assert set(st["operating_income"]) == {"delta", "residual", "gt5pct"}
    small = fs_acceptance.bridge_residual_stats(_stats_ledger((10 * M, 10 * M)))
    assert small["net_income"]["delta"] == 0 and small["net_income"]["gt5pct"] is False   # 變動 0 → 不計


# ── 審查 🟡：1000 仟元絕對門檻的反例；統計失敗不中斷、不影響 conform ──────────────


def test_r4_threshold_small_absolute_residual_not_flagged() -> None:
    # 淨利變動 800 仟元、無組成項 → 殘差 800（>5%，但 ≤ 1000 仟元）→ 不計
    st = fs_acceptance.bridge_residual_stats(_stats_ledger((10_800, 10_000)))
    ni = st["net_income"]
    assert ni["delta"] == 800 and abs(ni["residual"]) > 0.05 * 800 and abs(ni["residual"]) <= 1000
    assert ni["gt5pct"] is False


def test_safe_bridge_stats_none_on_failure_and_for_fh(monkeypatch) -> None:
    led = _stats_ledger((10 * M, 5 * M))
    assert fs_acceptance._safe_bridge_stats(led, "industrial")["net_income"]["gt5pct"] is True   # 正常：有統計
    assert fs_acceptance._safe_bridge_stats(led, "fh") is None                                   # 金控：None
    def boom(*a, **k):
        raise RuntimeError("bridge failed")
    monkeypatch.setattr(fs_acceptance, "compute_bridges", boom)                                  # patch：統計層例外
    assert fs_acceptance._safe_bridge_stats(led, "industrial") is None                           # 不丟出、為 None
