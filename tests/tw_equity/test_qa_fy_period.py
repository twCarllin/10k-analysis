"""問答選期間：全年財報 vs 半年報（task/2026-10-11-tw-equity-cf-bridge-fy.md Task 2；Spec §2.3）。

契約 row：
  P1: 問題含年度用詞（完整年份、民國年＋年、全年、整年、年度）且有全年財報 → fy；不含 → h1
  P2: 反例不觸發：20250、半年度、上半年度、去年、今年 → h1；問題另含半年用詞 → h1
  P3: 問題指定全年（用詞或 --period fy）但沒有全年財報 → h1 並要求加說明；--period h1 → h1 無說明
  P4: 輸入檔 fy_consolidated_fs_path／fy_fs_period 選填；沒有 → 欄位為 None
  P5: 沒有全年財報欄位、問題不含年度用詞 → 答案與 render_fcf_answer 直出完全相同
  P6: 選 fy → 用全年財報建帳本、出處寫全年財報檔名、期間說明寫全年期間；--llm 路徑同規則且不讀年報做 TTM
  P7: 指定全年但沒有全年財報 → 答案期間說明含「沒有 2025 全年財報，以下為 2026 上半年」
  P8: CLI --period {auto,h1,fy}，預設 auto
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import qa  # noqa: E402
from runtime.tw_equity.inputs import load_inputs  # noqa: E402
from tests.tw_equity.test_qa_fcf import _ledger, _rows  # noqa: E402

NOTE_2330 = "沒有 2025 全年財報，以下為 2026 上半年"


@pytest.mark.parametrize("q", [
    "2025 年聯發科的 FCF 是多少？", "2025年FCF", "114 年的 FCF", "114年 FCF", "全年 FCF", "整年的自由現金流",
    "年度 FCF 變化", "會計年度 FCF",
])
def test_p1_year_terms_select_fy(q) -> None:
    assert qa.select_period(q, True) == ("fy", False)


@pytest.mark.parametrize("q", ["本期影響 FCF 最多的是什麼？", "FCF 多少", "本季 FCF"])
def test_p1_no_year_term_selects_h1(q) -> None:
    assert qa.select_period(q, True) == ("h1", False)


@pytest.mark.parametrize("q", [
    "20250 的 FCF", "12025 FCF", "1140 年 FCF", "上半年度 FCF", "半年度 FCF", "下半年度的 FCF", "去年 FCF 多少",
    "今年 FCF 多少", "2025 上半年 FCF",
])
def test_p2_near_miss_does_not_select_fy(q) -> None:
    assert qa.select_period(q, True) == ("h1", False)


def test_p2_year_comes_from_input_not_hardcoded() -> None:
    assert qa.select_period("2026 全年 FCF", True, "auto", 2026) == ("fy", False)
    assert qa.select_period("2026 FCF", True, "auto", 2025) == ("h1", False)


def test_p3_fy_requested_without_fy_report_falls_back_with_note() -> None:
    assert qa.select_period("2025 年 FCF", False) == ("h1", True)
    assert qa.select_period("FCF 多少", False, "fy") == ("h1", True)
    assert qa.select_period("本期 FCF", False) == ("h1", False)  # 沒有指定全年 → 不加說明
    assert qa.select_period("2025 年 FCF", True, "h1") == ("h1", False)
    assert qa.select_period("本期 FCF", True, "fy") == ("fy", False)


def _write_inputs(base: Path, ticker: str, **extra) -> None:
    d = base / "tw_equity_inputs"
    d.mkdir(exist_ok=True)
    (d / f"{ticker}.json").write_text(json.dumps(
        {"ticker": ticker, "company_name": "測試", "group": "industrial", "fiscal_year": 2025,
         "annual_report_path": "ar.pdf", "consolidated_fs_path": "h1.pdf", "fs_period": "2026H1", **extra},
        ensure_ascii=False), encoding="utf-8")
    if extra.get("fy_consolidated_fs_path"):  # 全年財報檔要存在才算有（審查 🟡-3 後的規則）
        (base / extra["fy_consolidated_fs_path"]).write_bytes(b"x")


def test_p4_load_inputs_optional_fy_fields(tmp_path) -> None:
    for n in ("ar.pdf", "h1.pdf", "fy.pdf"):
        (tmp_path / n).write_bytes(b"x")
    _write_inputs(tmp_path, "1111")
    _write_inputs(tmp_path, "2222", fy_consolidated_fs_path="fy.pdf", fy_fs_period="FY2025")
    a, b = load_inputs("1111", base_dir=tmp_path), load_inputs("2222", base_dir=tmp_path)
    assert a.fy_consolidated_fs_path is None and a.fy_fs_period is None
    assert b.fy_consolidated_fs_path == tmp_path / "fy.pdf" and b.fy_fs_period == "FY2025"


def _fy_ledger():
    led = _ledger(_rows())
    led.basis = "FY"
    led.column_periods["cf"] = ["114-01-01~114-12-31", "113-01-01~113-12-31"]
    return led


def _spy_loader(monkeypatch, loaded: list):
    def load(path, group=None):
        loaded.append(Path(path).name)
        return _fy_ledger() if Path(path).name == "fy.pdf" else _ledger(_rows())
    monkeypatch.setattr(qa, "load_ledger", load)


def test_p5_company_without_fy_fields_unchanged(monkeypatch, tmp_path) -> None:
    _write_inputs(tmp_path, "9999")
    loaded: list = []
    _spy_loader(monkeypatch, loaded)
    text, facts = qa.answer("9999", "本期影響 FCF 最多的是什麼？", base_dir=tmp_path)
    assert text == qa.render_fcf_answer(qa.fcf_facts(_ledger(_rows())), company="9999 測試", source="h1.pdf")
    assert loaded == ["h1.pdf"]


def test_p6_fy_company_year_question_uses_fy_ledger(monkeypatch, tmp_path) -> None:
    _write_inputs(tmp_path, "2454", fy_consolidated_fs_path="fy.pdf", fy_fs_period="FY2025")
    loaded: list = []
    _spy_loader(monkeypatch, loaded)
    text, facts = qa.answer("2454", "2025 年的 FCF 是多少？", base_dir=tmp_path)
    assert loaded == ["fy.pdf"] and facts["basis"] == "FY"
    assert "民國 114/1/1–114/12/31" in text.split("三、期間與限制")[1]
    assert "四、出處：fy.pdf" in text and "2025 全年財報" in text
    assert qa.verify_numbers(text, facts) == []


def test_p6_fy_company_plain_question_uses_h1(monkeypatch, tmp_path) -> None:
    _write_inputs(tmp_path, "2454", fy_consolidated_fs_path="fy.pdf", fy_fs_period="FY2025")
    loaded: list = []
    _spy_loader(monkeypatch, loaded)
    text, facts = qa.answer("2454", "本期 FCF 是多少？", base_dir=tmp_path)
    assert loaded == ["h1.pdf"] and facts["basis"] == "H1" and "四、出處：h1.pdf" in text


def test_p6_llm_path_same_rule_and_no_ttm(monkeypatch, tmp_path) -> None:
    _write_inputs(tmp_path, "2454", fy_consolidated_fs_path="fy.pdf", fy_fs_period="FY2025")
    loaded: list = []
    _spy_loader(monkeypatch, loaded)

    def boom(*a, **k):
        raise AssertionError("全年帳本不做 TTM，不可讀年報")

    monkeypatch.setattr(qa, "load_fy_income", boom)
    pack, source = qa.build_pack(tmp_path, json.loads((tmp_path / "tw_equity_inputs/2454.json").read_text("utf-8")),
                                 "2025 年 FCF", "auto")
    assert loaded == ["fy.pdf"] and source == "fy.pdf" and pack["basis"] == "FY"
    assert not any(k.startswith("ttm:") for k in pack["topics"])
    assert any("2025 全年財報" in n for n in pack["period_notes"])
    # 同公司、不含年度用詞 → 半年報（讀年報做 TTM；此處以回傳「讀不到」取代真實年報）
    monkeypatch.setattr(qa, "load_fy_income", lambda *a, **k: (None, "x"))
    loaded.clear()
    pack, _ = qa.build_pack(tmp_path, json.loads((tmp_path / "tw_equity_inputs/2454.json").read_text("utf-8")),
                            "毛利率多少", "auto")
    assert loaded == ["h1.pdf"] and pack["basis"] == "H1" and "period_notes" not in pack


def test_p7_fy_requested_without_fy_report_notes_in_answer(monkeypatch, tmp_path) -> None:
    _write_inputs(tmp_path, "2330")
    loaded: list = []
    _spy_loader(monkeypatch, loaded)
    text, facts = qa.answer("2330", "2025 年的 FCF 是多少？", base_dir=tmp_path)
    assert loaded == ["h1.pdf"] and NOTE_2330 in text.split("三、期間與限制")[1]
    text, _ = qa.answer("2330", "FCF 多少", base_dir=tmp_path, period="fy")
    assert NOTE_2330 in text


def test_p8_cli_period_option(monkeypatch, tmp_path, capsys) -> None:
    _write_inputs(tmp_path, "2330")
    _spy_loader(monkeypatch, [])
    monkeypatch.chdir(tmp_path)
    assert qa.main(["--ticker", "2330", "--ask", "FCF 多少", "--period", "fy"]) == 0
    assert NOTE_2330 in capsys.readouterr().out
    assert qa.main(["--ticker", "2330", "--ask", "FCF 多少"]) == 0  # 預設 auto
    assert NOTE_2330 not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        qa.main(["--ticker", "2330", "--ask", "FCF 多少", "--period", "q3"])


# ── 審查 🟡：單季／今年度反例；全年檔案不在；period_notes 進 --llm 事實包 ─────────────


@pytest.mark.parametrize("q", ["2025年Q3 FCF", "2025 年第三季 FCF", "114年第一季 FCF", "2025Q2 FCF",
                               "2025年第二季 FCF", "114年上半年 FCF", "2025 H2 FCF", "2025 年單季 FCF",
                               "今年度 FCF", "本年度 FCF"])
def test_p2_subyear_and_this_year_terms_do_not_select_fy(q) -> None:
    assert qa.select_period(q, True) == ("h1", False)


def test_p2_contrast_plain_year_still_selects_fy() -> None:
    assert qa.select_period("2025 年度 FCF", True) == ("fy", False)   # 對照：只有年度用詞 → 全年
    assert qa.select_period("2025 FCF", True) == ("fy", False)


def test_p4_fy_file_missing_treated_as_absent(tmp_path) -> None:
    for n in ("ar.pdf", "h1.pdf"):
        (tmp_path / n).write_bytes(b"x")
    _write_inputs(tmp_path, "3333", fy_consolidated_fs_path="missing.pdf", fy_fs_period="FY2025")
    (tmp_path / "missing.pdf").unlink()                                                  # 欄位有值、檔案不在
    assert load_inputs("3333", base_dir=tmp_path).fy_consolidated_fs_path is None     # 不丟 FileNotFoundError
    raw = {"fy_consolidated_fs_path": "missing.pdf", "fy_fs_period": "FY2025", "fs_period": "2026H1"}
    period, notes = qa._period_choice(raw, "2025 年 FCF", "auto", tmp_path)
    assert period == "h1" and notes == ["沒有 2025 全年財報，以下為 2026 上半年"]


def test_p6_period_notes_reach_llm_facts() -> None:
    from runtime.tw_equity import qa_llm
    pack = {"topics": {}, "periods": {}, "basis": "FY", "assurance": "audited", "period_notes": ["本答案使用 2025 全年財報"]}
    ctx = json.loads(qa_llm.llm_inputs(pack, "q", "X")["facts_json"])["context"]
    assert ctx["period_notes"] == ["本答案使用 2025 全年財報"]
    pack.pop("period_notes")
    assert "period_notes" not in json.loads(qa_llm.llm_inputs(pack, "q", "X")["facts_json"])["context"]   # 對照：沒有說明 → 不帶


def test_p3_quarter_question_gets_no_quarterly_report_note() -> None:
    raw = {"fs_period": "2026H1"}
    assert qa._period_choice(raw, "2025 年第三季 FCF", "auto") == ("h1", ["沒有單季財報，以下為 2026 上半年累計數"])
    assert qa._period_choice(raw, "本期 FCF", "auto") == ("h1", [])        # 對照：沒有單季用詞 → 不加說明


def test_p3_quarter_note_without_fs_period_and_season_word() -> None:
    assert qa._period_choice({}, "季度 FCF", "auto") == ("h1", ["沒有單季財報，以下為上半年累計數"])


def test_p4_fy_path_wrong_type_raises(tmp_path) -> None:
    for n in ("ar.pdf", "h1.pdf"):
        (tmp_path / n).write_bytes(b"x")
    d = tmp_path / "tw_equity_inputs"; d.mkdir()
    (d / "4444.json").write_text(json.dumps({"ticker": "4444", "company_name": "測試", "group": "industrial",
        "fiscal_year": 2025, "annual_report_path": "ar.pdf", "consolidated_fs_path": "h1.pdf",
        "fy_consolidated_fs_path": 123}), encoding="utf-8")
    with pytest.raises(ValueError, match="fy_consolidated_fs_path 型別錯誤"):
        load_inputs("4444", base_dir=tmp_path)
