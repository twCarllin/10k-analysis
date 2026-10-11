"""答案呈現：支出與費用的方向（Spec 2026-10-11-tw-equity-sign-fix §2 D、§6 A3；Task 2.1）。

契約 row：
  R1: FCF 答案的資本支出（兩期皆負）→「本期支出 X、去年同期支出 Y，支出增加 Z 億，使 FCF 減少 Z 億」；支出減少 → 「支出減少 Z 億，使 FCF 增加 Z 億」；數字核對通過
  R2: bridge 費用類組成項 → 「費用增加（減少）Z 億，使〈目標〉減少（增加）Z 億」；數字核對通過
  R3: 所得稅為利益（正值）→ 「所得稅利益……」，不寫成費用
  R4: bridge 殘差不為 0 → 列「未歸類項目 X 億」；為 0 → 不列
  R5: 收入與損益類組成項維持「變動 Z 億元」寫法
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.tw_equity import qa  # noqa: E402
from test_qa_fcf import _ledger, _r, _rows  # noqa: E402
from test_qa_g3a import M, _gross_ledger  # noqa: E402

BR = "bridge:gross_profit"


def _bridge_text(cogs: tuple, gp: tuple, rev: tuple = (120 * M, 100 * M)) -> tuple[str, dict]:
    """cogs 以正數印（工業公司常見印法）→ 走生產路徑 topic_pack → render_topics_answer。"""
    pack = qa.topic_pack(_gross_ledger(rev, cogs, gp))
    return qa.render_topics_answer(pack, [BR], company="X"), pack


def test_r1_capex_increase_wording_and_verified() -> None:
    facts = qa.fcf_facts(_ledger(_rows()))  # capex 本期 −400,000、去年同期 −300,000 仟元＝4.00／3.00 億
    text = qa.render_fcf_answer(facts, company="X")
    assert "資本支出：本期支出 4.00、去年同期支出 3.00，支出增加 1.00 億，使 FCF 減少 1.00 億（p.9）" in text
    assert "支出減少" not in text
    assert qa.verify_numbers(text, facts) == []
    # mutation 對照：改壞金額 → 核對抓到
    assert qa.verify_numbers(text.replace("支出增加 1.00 億", "支出增加 9.99 億"), facts) == ["9.99 億"]


def test_r1_capex_decrease_wording() -> None:
    rows = [(_r(r.line_idx, r.label, -250_000, -300_000, key="capex", section=r.section) if r.key == "capex" else r)
            for r in _rows()]
    facts = qa.fcf_facts(_ledger(rows))
    text = qa.render_fcf_answer(facts, company="X")
    assert "本期支出 2.50、去年同期支出 3.00，支出減少 0.50 億，使 FCF 增加 0.50 億" in text
    assert "支出增加" not in text
    assert qa.verify_numbers(text, facts) == []


def test_r2_expense_increase_printed_positive() -> None:
    text, pack = _bridge_text(cogs=(80 * M, 60 * M), gp=(40 * M, 40 * M))  # 成本 800／600 億
    assert "費用增加 200.00 億，使毛利減少 200.00 億" in text
    assert "費用減少" not in text
    assert qa.verify_topics(text, pack, [BR]) == []
    assert qa.verify_topics(text.replace("費用增加 200.00 億", "費用增加 201.00 億"), pack, [BR]) == ["201.00 億"]


def test_r2_expense_decrease() -> None:
    text, pack = _bridge_text(cogs=(60 * M, 80 * M), gp=(60 * M, 20 * M), rev=(120 * M, 100 * M))
    assert "費用減少 200.00 億，使毛利增加 200.00 億" in text
    assert "費用增加" not in text
    assert qa.verify_topics(text, pack, [BR]) == []


def test_r5_revenue_component_and_r4_zero_residual() -> None:
    text, _ = _bridge_text(cogs=(80 * M, 60 * M), gp=(40 * M, 40 * M))
    rev_line = next(ln for ln in text.splitlines() if "營業收入" in ln)
    assert "變動 200.00 億元" in rev_line and "費用" not in rev_line
    assert "未歸類項目" not in text


def test_r4_nonzero_residual_listed() -> None:
    text, pack = _bridge_text(cogs=(80 * M, 60 * M), gp=(45 * M, 40 * M))  # 目標變動 50 億，組成項合計 0 → 殘差 50 億
    assert "未歸類項目 50.00 億" in text
    assert qa.verify_topics(text, pack, [BR]) == []


def test_r3_tax_benefit_not_written_as_expense() -> None:
    comp = {"key": "income_tax", "label": "所得稅", "current": 5 * M, "prior": -3 * M, "delta": 8 * M,
            "share": 1.0, "page": 5}
    topic = {"kind": "bridge", "name": "淨利變動", "current": 5 * M, "prior": -3 * M, "delta": 8 * M,
             "residual": 0.0, "page": 5, "components": [comp]}
    pack = {"answerable": True, "topics": {"bridge:net_income": topic}, "periods": {}, "basis": "H1",
            "assurance": "reviewed"}
    text = qa.render_topics_answer(pack, ["bridge:net_income"], company="X")
    line = next(ln for ln in text.splitlines() if ln.lstrip().startswith("- 所得稅"))
    assert "所得稅利益增加 80.00 億，使淨利增加 80.00 億" in line
    assert "費用" not in line
    assert qa.verify_topics(text, pack, ["bridge:net_income"]) == []


# ── 審查 🟡-2／🟡-3 邊界（spec 2026-10-11-tw-equity-sign-fix §2 D） ──────────────────


def _tax_line(cur: float, pri: float) -> str:
    comp = {"key": "income_tax", "label": "所得稅", "current": cur, "prior": pri, "delta": cur - pri,
            "share": 1.0, "page": 5}
    topic = {"kind": "bridge", "name": "淨利變動", "current": 0.0, "prior": 0.0, "delta": cur - pri,
             "residual": 0.0, "page": 5, "components": [comp]}
    pack = {"answerable": True, "topics": {"bridge:net_income": topic}, "periods": {}, "basis": "H1",
            "assurance": "reviewed"}
    text = qa.render_topics_answer(pack, ["bridge:net_income"], company="X")
    return next(ln for ln in text.splitlines() if ln.lstrip().startswith("- 所得稅"))


def test_r3_tax_expense_now_benefit_prior_1301_shape() -> None:
    # 1301 型：本期費用 30 億（正規化 −30）、去年同期利益 18.5 億（+18.5）→ 利益轉為費用，淨利減少 48.5 億（M＝10 億）
    line = _tax_line(-3 * M, 1.85 * M)
    assert "所得稅利益減少 48.50 億，使淨利減少 48.50 億" in line
    assert "費用增加" not in line


def test_cost_text_equal_amounts_falls_back_to_plain_change() -> None:
    c = {"key": "rd_expenses", "current": -5 * M, "prior": -5 * M, "delta": 0.0}
    assert qa._cost_text(c, "淨利") is None                                   # 兩期同額 → 退回「變動」寫法
    c2 = {"key": "rd_expenses", "current": -6 * M, "prior": -5 * M, "delta": -1 * M}
    assert qa._cost_text(c2, "淨利") == "費用增加 10.00 億，使淨利減少 10.00 億"  # 對照：不同額 → 費用句型


def test_capex_text_single_negative_or_zero() -> None:
    assert qa._capex_text({"key": "capex", "current": 1 * M, "prior": -3 * M}) is None     # 只有一期為負 → 退回
    assert qa._capex_text({"key": "capex", "current": 0.0, "prior": -3 * M}) == (
        "本期支出 0.00、去年同期支出 30.00，支出減少 30.00 億，使 FCF 增加 30.00 億")
    assert qa._capex_text({"key": "capex", "current": 0.0, "prior": 0.0}) == (
        "本期支出 0.00、去年同期支出 0.00，支出不變，對 FCF 無影響")
