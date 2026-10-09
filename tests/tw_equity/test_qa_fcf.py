"""FCF 事實包、模板答案、數字核對、CLI 路由（G1；task/2026-10-09-tw-equity-qa-fcf.md）。

契約 row：
  Q1: cfo、capex 皆有值 → 第一層兩項變動和＝FCF 變動
  Q2: 營業活動列含未對照科目 → 以原 label 列入第二層
  Q3: 並排頁投資／籌資區段列夾在營業活動列之間 → 不計入第二層
  Q4: cfo 或 capex 缺 → 不可答，附原因，不輸出數字
  Q5: 答案任一金額被竄改 → verify_numbers 回傳該數字
  Q6: 問題不含 FCF／自由現金流 → 回「G1 只支援 FCF 問題」
  Q7: group=fh → 回不適用說明
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import qa  # noqa: E402
from runtime.tw_equity.statements import StatementLedger, StatementRow  # noqa: E402


def _r(i: int, label: str, cur, pri, key=None, section="營業活動之現金流量") -> StatementRow:
    return StatementRow(statement="cf", section=section, label=label, key=key, note=None,
                        current=cur, prior=pri, current_pct=None, prior_pct=None, page=9, line_idx=i)


def _ledger(rows: list[StatementRow]) -> StatementLedger:
    return StatementLedger(unit="新台幣仟元", period_current="115", period_prior="114", rows=rows, checks=[],
                           unmapped_labels=[],
                           column_periods={"bs": [], "is": [], "cf": ["115-01-01~115-06-30", "114-01-01~114-06-30"]},
                           current_col={"bs": None, "is": None, "cf": 0}, prior_col={"bs": None, "is": None, "cf": 1},
                           basis="H1", assurance="reviewed")


def _rows() -> list[StatementRow]:
    # CFO＝1000+200-600+(-150)+(-100)+? ；本期 cfo=350、上期 cfo=500
    return [
        _r(0, "本期稅前淨利", 1_000_000, 800_000, key="pretax_income_cf"),
        _r(0, "取得透過損益按公允價值衡量之金融資產", -5_000, -1_000, section="投資活動之現金流量"),  # Q3 並排右半
        _r(1, "折舊費用", 200_000, 180_000, key="depreciation", section="收益費損項目"),
        _r(2, "應收帳款淨額增加", -600_000, -300_000, section="與營業活動相關之資產/負債變動數"),  # Q2 未對照
        _r(3, "應付帳款增加", -150_000, 20_000, section="與營業活動相關之資產/負債變動數"),
        _r(3, "短期借款增加", 9_000, 9_000, section="籌資活動之現金流量"),  # Q3 並排右半
        _r(4, "營運產生之現金流入", 450_000, 700_000, section="與營業活動相關之資產/負債變動數"),
        _r(5, "支付之所得稅", -100_000, -200_000, section="與營業活動相關之資產/負債變動數"),
        _r(6, "營業活動之淨現金流入", 350_000, 500_000, key="cfo"),
        _r(7, "取得不動產、廠房及設備", -400_000, -300_000, key="capex", section="投資活動之現金流量"),
    ]


def test_q1_level1_sums_to_fcf_delta() -> None:
    f = qa.fcf_facts(_ledger(_rows()))
    assert f["fcf"] == {"current": -50_000, "prior": 200_000, "delta": -250_000}
    assert sum(x["delta"] for x in f["level1"]) == f["fcf"]["delta"]
    assert [x["key"] for x in f["level1"]] == ["cfo", "capex"]  # |−150,000| ≥ |−100,000|


def test_q2_q3_level2_rows_groups_and_residual() -> None:
    f = qa.fcf_facts(_ledger(_rows()))
    labels = [x["label"] for x in f["level2"]]
    assert labels == ["應收帳款淨額增加", "本期稅前淨利", "應付帳款增加", "支付之所得稅", "折舊費用"]  # |Δ| 降序
    assert "短期借款增加" not in labels and "取得透過損益按公允價值衡量之金融資產" not in labels
    assert f["residual"] == 0
    assert f["group_deltas"] == {"稅前淨利": 200_000, "非現金調整": 20_000,
                                 "營運資金變動": -470_000, "利息股利與所得稅": 100_000}
    assert all(x["page"] == 9 for x in f["level2"])


def test_composition_top3() -> None:
    f = qa.fcf_facts(_ledger(_rows()))
    assert [x["label"] for x in f["inflows"]] == ["本期稅前淨利", "折舊費用"]
    assert [x["label"] for x in f["outflows"]] == ["應收帳款淨額增加", "資本支出（取得不動產、廠房及設備）", "應付帳款增加"]


def test_one_side_dash_counts_as_zero() -> None:
    rows = _rows()
    rows.insert(2, _r(1, "處分子公司損失", None, 50_000, section="收益費損項目"))
    rows[-2] = _r(6, "營業活動之淨現金流入", 350_000, 550_000, key="cfo")
    f = qa.fcf_facts(_ledger(rows))
    assert f["residual"] == 0


def test_q4_missing_capex_unanswerable() -> None:
    f = qa.fcf_facts(_ledger([r for r in _rows() if r.key != "capex"]))
    assert f["answerable"] is False and "取得不動產、廠房及設備" in f["reason"]
    text = qa.render_fcf_answer(f, company="X")
    assert "無法回答" in text and "億" not in text
    assert qa.fcf_facts(None)["answerable"] is False


def test_answer_numbers_verify_and_q5_tamper() -> None:
    f = qa.fcf_facts(_ledger(_rows()))
    text = qa.render_fcf_answer(f, company="X", source="x.pdf")
    assert "上半年累計" in text and "核閱" in text and "p.9" in text
    assert qa.verify_numbers(text, f) == []
    assert "FCF 為 -0.50 億元" in text
    tampered = text.replace("FCF 為 -0.50 億元", "FCF 為 -0.70 億元", 1)
    assert qa.verify_numbers(tampered, f) == ["-0.70 億"]


def test_verify_rounding_tolerance() -> None:
    f = qa.fcf_facts(_ledger(_rows()))
    assert qa.verify_numbers("FCF 減少 2.5 億元，CFO 占 60%", f) == []  # 250,000 仟元＝2.5 億；150/250＝60%
    assert qa.verify_numbers("減少 3.3 億元", f) == ["3.3 億"]


def _inputs(tmp_path: Path, ticker: str, group: str) -> Path:
    d = tmp_path / "tw_equity_inputs"
    d.mkdir(exist_ok=True)
    (d / f"{ticker}.json").write_text(json.dumps({"company_name": "測試", "group": group,
                                                  "consolidated_fs_path": "x.pdf"}), encoding="utf-8")
    return tmp_path


def test_q6_q7_cli_routing(monkeypatch, tmp_path) -> None:
    base = _inputs(tmp_path, "9999", "industrial")
    _inputs(tmp_path, "2881", "fh")
    monkeypatch.setattr(qa, "load_ledger", lambda p: _ledger(_rows()))
    text, facts = qa.answer("9999", "毛利率多少", base_dir=base)
    assert "G1 只支援 FCF 問題" in text and facts is None
    text, facts = qa.answer("2881", "FCF 多少", base_dir=base)
    assert "不適用" in text and facts is None
    text, facts = qa.answer("9999", "本季影響 FCF 最多的是什麼？", base_dir=base)
    assert facts["answerable"] and text.startswith("【9999 測試】")


def test_capex_aliases() -> None:
    from runtime.tw_equity.statements import map_key
    for label in ("取得不動產、廠房及設備", "購置不動產、廠房及設備", "取得不動產、廠房及設備：支付之成本"):
        assert map_key("cf", label, "投資活動之現金流量") == "capex"
