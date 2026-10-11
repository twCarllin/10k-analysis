"""run 2026-10-11-tw-equity-cf-bridge-fy Task 1：現金流量表 bridge 區段限定組成項＋合成項（1.1）、呈現（1.2）。

契約 row（Task 1 DoD／契約）：
  1.1-③ 利息收取列在營業區段時不進投資 bridge
  1.1-④ 合成項＝區段合計 − Σ區段內已對到 key 的列（＝區段內未對到 key 列的合計）；合計缺值為 None
  1.1-契約 fcf、net_change_in_cash 與損益表 bridge 不變
  1.2-① 資本支出（兩期皆負）寫成「支出增加 Z 億，使投資現金流減少 Z 億」；數字核對通過
  1.2-② 其他現金流量項目寫「對現金的影響」；損益表 bridge 寫法不變
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.tw_equity import metrics, qa  # noqa: E402
from runtime.tw_equity.metrics import BRIDGE_SPECS, BridgeComponent, BridgeResult, compute_bridges, compute_metrics  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402
from test_qa_fcf import _ledger as _qa_ledger, _rows as _qa_rows  # noqa: E402

M = 100_000  # 1 億（仟元）
_PERIODS = {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
            "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": "114-12-31"}


def _cf_ledger(rows: list[tuple], one_column: frozenset[str] = frozenset()) -> StatementLedger:
    """rows：(key|None, label, cur, pri, section)，依序成列（帳本列序）；one_column 內的 key 只有 1 個期間欄（模擬缺欄）。"""
    srows = [StatementRow("cf", sec, lab, k, None, c, p, None, None, 1, i,
                          columns=[c] if k in one_column else [c, p])
             for i, (k, lab, c, p, sec) in enumerate(rows)]
    flow = [_PERIODS["flow_current"], _PERIODS["flow_prior"]]
    return StatementLedger(
        unit="仟元", period_current="115", period_prior="114", rows=srows, checks=[], unmapped_labels=[],
        column_periods={"bs": [], "is": [], "cf": flow}, basis="H1", periods=dict(_PERIODS),
        days={"current": 181, "prior": 181})


OP, INV, FIN = "營業活動之現金流量", "投資活動之現金流量", "籌資活動之現金流量"


def _rows_standard() -> list[tuple]:
    """營業：稅前 100/80、收取利息 5/6（列在營業區段）、cfo 105/86；投資：capex −30/−20、未對到 key 的「取得 FVOCI」−40/−10、
    cfi −70/−30；籌資：發放股利 −50/−40、未對到 key 的「其他籌資」3/1、cff −47/−39。"""
    return [
        ("pretax_income_cf", "稅前淨利", 100.0, 80.0, OP),
        ("interest_received", "收取之利息", 5.0, 6.0, OP),
        ("cfo", "營業活動之淨現金流入", 105.0, 86.0, OP),
        ("capex", "取得不動產、廠房及設備", -30.0, -20.0, INV),
        (None, "取得透過其他綜合損益按公允價值衡量之金融資產", -40.0, -10.0, INV),
        ("cfi", "投資活動之淨現金流出", -70.0, -30.0, INV),
        ("dividends_paid", "發放現金股利", -50.0, -40.0, FIN),
        (None, "其他籌資活動", 3.0, 1.0, FIN),
        ("cff", "籌資活動之淨現金流出", -47.0, -39.0, FIN),
        ("fx_effect", "匯率變動之影響", 1.0, 2.0, FIN),
        ("net_change_in_cash", "本期現金增加數", -11.0, 9.0, FIN),
    ]


def _bridges(led: StatementLedger) -> dict:
    return {b.target: b for b in compute_bridges(led, compute_metrics(led))}


def _comps(b) -> dict:
    return {c.key: c for c in b.components}


# ── 1.1 區段限定組成項 ───────────────────────────────────────────────────────

def test_interest_received_in_operating_section_not_in_cfi_bridge() -> None:
    br = _bridges(_cf_ledger(_rows_standard()))
    assert "interest_received" in _comps(br["cfo"])
    assert "interest_received" not in _comps(br["cfi"])
    assert set(_comps(br["cfi"])) == {"capex", "other_investing_cf"}  # 區段明細＋合成項
    assert set(_comps(br["cff"])) == {"dividends_paid", "other_financing_cf"}
    assert set(_comps(br["cfo"])) == {"pretax_income_cf", "interest_received", "other_operating_cf"}


def test_mutation_self_check_section_rule_vs_fixed_list(monkeypatch) -> None:
    """對照：(1) 正常 → 投資 bridge 不含 interest_received；(2) 把區段規則換回固定清單（cf_section_rows → None）→ 含。"""
    rows = _rows_standard()
    assert "interest_received" not in _comps(_bridges(_cf_ledger(rows))["cfi"])
    monkeypatch.setattr(metrics, "_cf_section_rows", lambda led, target: None)
    assert "interest_received" in _comps(_bridges(_cf_ledger(rows))["cfi"])


def test_synthetic_equals_unkeyed_rows_in_section() -> None:
    br = _bridges(_cf_ledger(_rows_standard()))
    s = _comps(br["cfi"])["other_investing_cf"]
    assert s.synthetic is True and s.name == "其他投資活動項目"
    assert (s.current, s.prior, s.delta) == (-40.0, -10.0, -30.0)  # ＝未對到 key 的 FVOCI 取得列
    assert br["cfi"].residual == pytest.approx(0.0)
    f = _comps(br["cff"])["other_financing_cf"]
    assert (f.current, f.prior) == (3.0, 1.0) and f.name == "其他籌資活動項目"
    o = _comps(br["cfo"])["other_operating_cf"]
    assert (o.current, o.prior) == (0.0, 0.0) and o.name == "其他營業活動項目"  # 營業區段每列都有 key → 合成項 0
    assert [c.synthetic for c in br["cfi"].components if c.key == "capex"] == [False]
    assert _comps(br["cfi"])["other_investing_cf"].to_dict()["synthetic"] is True


def test_synthetic_none_when_section_total_missing_value() -> None:
    """合計列缺本期以外的欄（只有 1 個期間欄）→ 去年同期合成項為 None、delta 為 None；本期仍有值。"""
    led = _cf_ledger(_rows_standard(), one_column=frozenset({"cfi"}))
    s = _comps(_bridges(led)["cfi"])["other_investing_cf"]
    assert s.current == -40.0
    assert s.prior is None and s.delta is None


def test_duplicate_key_across_sections_takes_row_in_own_section() -> None:
    """同 key 在營業與投資區段各有一列（如 3045 的 interest_received）→ 投資 bridge 用投資區段那一列的值。"""
    rows = _rows_standard()
    rows.insert(5, ("interest_received", "收取之利息", 9.0, 4.0, INV))
    br = _bridges(_cf_ledger(rows))
    inv = _comps(br["cfi"])["interest_received"]
    assert (inv.current, inv.prior) == (9.0, 4.0)
    assert (_comps(br["cfo"])["interest_received"].current) == 5.0
    assert br["cfi"].residual == pytest.approx(0.0) and br["cfo"].residual == pytest.approx(0.0)


def test_section_without_any_keyed_row_keeps_only_synthetic() -> None:
    """區段有合計列但沒有任何對到 key 的列（如 1216 投資區段）→ 組成項只剩合成項，不從別區段借固定清單的列。"""
    rows = [r for r in _rows_standard() if r[0] != "capex"]
    br = _bridges(_cf_ledger(rows))
    assert list(_comps(br["cfi"])) == ["other_investing_cf"]
    assert "interest_received" not in _comps(br["cfi"])
    assert br["cfi"].residual == pytest.approx(0.0)


def test_no_total_row_falls_back_to_fixed_list_without_synthetic() -> None:
    rows = [r for r in _rows_standard() if r[0] != "cfi"]
    cfi = _bridges(_cf_ledger(rows))["cfi"]
    assert "other_investing_cf" not in _comps(cfi)
    assert set(_comps(cfi)) == set(next(s.components for s in BRIDGE_SPECS if s.target == "cfi"))


def test_fcf_and_net_change_bridges_unchanged() -> None:
    br = _bridges(_cf_ledger(_rows_standard()))
    assert set(_comps(br["net_change_in_cash"])) == {"cfo", "cfi", "cff", "fx_effect"}
    assert set(_comps(br["fcf"])) == {"cfo", "capex"}
    assert not any(c.synthetic for k in ("fcf", "net_change_in_cash") for c in br[k].components)


# ── 1.2 呈現 ─────────────────────────────────────────────────────────────────

def _pack(name: str, target_key: str, comps: list[BridgeComponent], topic: str) -> dict:
    b = BridgeResult(target_key, name, -10 * M, -8 * M, -2 * M, comps, 0.0, [])
    return {"answerable": True, "basis": "H1", "assurance": "reviewed",
            "periods": {"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                        "bs_current": "115-06-30"},
            "topics": {topic: qa._bridge_topic(_qa_ledger(_qa_rows()), b)}}


def _render(comps: list[BridgeComponent], name: str = "投資現金流變動", key: str = "cfi") -> tuple[str, dict, str]:
    topic = f"bridge:{key}"
    pack = _pack(name, key, comps, topic)
    return qa.render_topics_answer(pack, [topic], company="X"), pack, topic


def test_capex_expense_increase_sentence_and_verified() -> None:
    text, pack, topic = _render([BridgeComponent("capex", "取得不動產、廠房及設備", -10 * M, -8 * M, -2 * M, 1.0)])
    assert "本期支出 10.00、去年同期支出 8.00，支出增加 2.00 億，使投資現金流減少 2.00 億" in text
    assert qa.verify_topics(text, pack, [topic]) == []


def test_intangible_purchase_decrease_sentence() -> None:
    text, _, _ = _render([BridgeComponent("intangible_purchase", "取得無形資產", -6 * M, -9 * M, 3 * M, 1.0)])
    assert "支出減少 3.00 億，使投資現金流增加 3.00 億" in text


def test_capex_with_positive_period_falls_back_to_cash_effect() -> None:
    """反例：資本支出任一期為正（非支出）→ 不用支出句型，退回「對現金的影響」。"""
    text, _, _ = _render([BridgeComponent("capex", "取得不動產、廠房及設備", 1 * M, -8 * M, 9 * M, 1.0)])
    assert "支出增加" not in text and "支出減少" not in text
    assert "取得不動產、廠房及設備：對現金的影響 9.00 億元" in text


def test_other_cash_flow_items_say_effect_on_cash() -> None:
    comps = [BridgeComponent("other_investing_cf", "其他投資活動項目", -4 * M, -1 * M, -3 * M, 1.5, True),
             BridgeComponent("ppe_disposal_proceeds", "處分不動產、廠房及設備價款", -1 * M, -2 * M, 1 * M, 0.5)]
    text, pack, topic = _render(comps)
    assert "其他投資活動項目：對現金的影響 -3.00 億元" in text
    assert "處分不動產、廠房及設備價款：對現金的影響 1.00 億元" in text
    assert qa.verify_topics(text, pack, [topic]) == []
    for name, key in (("營業現金流變動（間接法）", "cfo"), ("籌資現金流變動", "cff"), ("自由現金流變動", "fcf"),
                      ("現金變動", "net_change_in_cash")):
        t, _, _ = _render(comps[:1], name=name, key=key)
        assert "對現金的影響" in t


def test_income_statement_bridge_wording_unchanged() -> None:
    """損益表 bridge 的其他項目仍寫「變動 Z 億元」，不寫「對現金的影響」。"""
    text, _, _ = _render([BridgeComponent("revenue", "營業收入", 5 * M, 3 * M, 2 * M, 1.0)],
                         name="淨利變動", key="net_income")
    assert "營業收入：變動 2.00 億元" in text
    assert "對現金的影響" not in text


# ── 審查 🟡：跨區段同 key 的頁碼；上一合計列缺且區段標題為 None ─────────────────


def test_duplicate_key_page_points_to_own_section_row() -> None:
    rows = _rows_standard()
    rows.insert(5, ("interest_received", "收取之利息", 9.0, 4.0, INV))
    led = _cf_ledger(rows)
    led.rows[5].page = 9                                                   # 投資區段那一列在 p.9；營業區段那一列在 p.1
    b = _bridges(led)["cfi"]
    assert _comps(b)["interest_received"].page == 9
    topic = qa._bridge_topic(led, b)
    page = next(c["page"] for c in topic["components"] if c["key"] == "interest_received")
    assert page == 9                                                       # 對照：舊寫法以 key 查第一列 → p.1
    assert qa._row_page(led, "interest_received") == 1


def test_missing_previous_total_and_none_section_collects_nothing() -> None:
    rows = [(k, lab, c, p, None) for k, lab, c, p, _ in _rows_standard() if k != "cfo"]   # 沒有 cfo 合計列、標題全為 None
    b = _bridges(_cf_ledger(rows))["cfi"]
    keys = {c.key for c in b.components}
    assert keys == {"other_investing_cf"}                                  # 不誤收營業區段的 pretax_income_cf／interest_received
    assert _comps(b)["other_investing_cf"].delta == pytest.approx(-40.0)   # 合成項＝cfi 合計變動（−70 − −30）
