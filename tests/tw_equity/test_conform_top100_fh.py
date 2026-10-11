"""銀行解析（2834、5876）與 101 家驗收的已知限制（run 2026-10-10-tw-equity-top100-conform，Task 2：items 2.1–2.2）。

契約 row（task/2026-10-10-tw-equity-top100-conform.md）：
  2.1: fh 損益表的併行，只在「單獨一行對不到 key、併入後對得到 key」時才併。
  2.1 DoD: 2834、5876 都是 18/0/0；2880、2882、2883、2884、5880 仍是 18/0/0。
  F-7（Spec §3.2）: 沒有 net_income 列時，才把第一個 net_income_continuing 改成 net_income；2890 結果不變。
  2.2: `KNOWN_LIMITATIONS` 寫死 6223、1101、3529，輸出標示為已知限制，SUMMARY 分開列出；已知限制不算進符合數。
fixture 行文字取自 2834／5876 2026Q2 財報 PDF 的原文列（tw_report/）。逐家 18/0/0 的測試讀本地 PDF，不在則 skip。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import fs_acceptance, pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, find_heading_sections  # noqa: E402
from runtime.tw_equity.fh_schema import FH_NON_INTEREST_COMPONENT_KEYS, FH_SECTION_HEADERS  # noqa: E402
from runtime.tw_equity.inputs import load_inputs  # noqa: E402
from runtime.tw_equity.statements import extract_statements, map_key, parse_statement_lines  # noqa: E402

_HDR = [
    "○○金融控股股份有限公司及子公司",
    "合併綜合損益表",
    "民國115年及114年4月1日至6月30日以及民國115年及114年1月1日至6月30日",
    "單位：新台幣仟元",
    "115年4月1日至6月30日 114年4月1日至6月30日 115年1月1日至6月30日 114年1月1日至6月30日",
    "代 碼 金 額 ％ 金 額 ％ 金 額 ％ 金 額 ％",
]
_FVOCI_WRAPPED = [
    "49310 　透過其他綜合損益按公允價值衡量之金融資產已實 478,574 5 696,526 8 681,735 4 843,771 5",
    "現損益(附註六(三十三))",
]


def _parse_is(texts: list[str]):
    lines = [(1, i, t) for i, t in enumerate(_HDR + texts)]
    rows, _, _ = parse_statement_lines(lines, "is", section_headers=FH_SECTION_HEADERS["is"], schema="fh")
    return rows


def _ledger(ticker: str):
    inp = load_inputs(ticker, base_dir=ROOT)
    doc = pdf_doc.load_pdf(inp.consolidated_fs_path)
    return extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()), group=inp.group)


def _need(ticker: str) -> None:
    if not (ROOT / "tw_report" / f"{ticker}_2026Q2財報.pdf").exists():
        pytest.skip(f"需本地 tw_report/{ticker}_2026Q2財報.pdf")


# ── 2.1 F-6 別名 ──────────────────────────────────────────────────────────

def test_f6_f7_aliases_map_to_fh_keys() -> None:
    assert map_key("is", "手續費淨收益", None, schema="fh") == "fee_income_net"
    assert map_key("is", "手續費及佣金淨收益", None, schema="fh") == "fee_income_net"  # 既有別名不變
    assert map_key("is", "證券經紀收入淨額", None, schema="fh") == "brokerage_income_net"
    assert map_key("is", "繼續營業單位本期淨利", None, schema="fh") == "net_income_continuing"
    assert map_key("bs", "負債權益總計", None, schema="fh") == "total_liabilities_and_equity"
    assert "brokerage_income_net" in FH_NON_INTEREST_COMPONENT_KEYS


# ── 2.1 F-6 併行規則 ──────────────────────────────────────────────────────

def test_f6_wrapped_label_merged_when_only_merged_label_maps() -> None:
    """2834：非並排頁，首行單獨對不到 key、併入續行後對得到 → 併為一列 fvoci_realized_gain。"""
    rows = _parse_is(_FVOCI_WRAPPED)
    hit = [r for r in rows if r.key == "fvoci_realized_gain"]
    assert len(hit) == 1
    assert (hit[0].current, hit[0].prior) == (681735.0, 843771.0)


def test_f6_fragment_not_merged_when_label_already_maps() -> None:
    """契約反例：首行本身已對到 key → 不併續行（2880、2882、2883、2884、5880 不退步的保護）。"""
    rows = _parse_is([
        "49100 　手續費淨收益 1,669,918 17 1,802,580 20 3,593,230 19 3,730,163 21",
        "現損益(附註六(三十三))",
    ])
    fee = [r for r in rows if r.key == "fee_income_net"]
    assert len(fee) == 1 and "現損益" not in fee[0].label
    assert fee[0].current == 3593230.0


def test_f6_fragment_not_merged_when_merged_label_still_unmapped() -> None:
    """契約反例：併入後仍對不到 key → 不併（首行 label 維持原樣）。"""
    rows = _parse_is([
        "49999 　某某未知科目 1,000 1 2,000 1 3,000 1 4,000 1",
        "甲乙丙丁(附註六(九))",
    ])
    assert not any("甲乙丙丁" in r.label for r in rows)
    assert any(r.label == "某某未知科目" and r.current == 3000.0 for r in rows)  # 首行列仍在、未被吞掉


# ── 2.1 F-7 繼續營業單位本期淨利 ──────────────────────────────────────────

_CONT = "64000 繼續營業單位本期淨利 $ 6,184,993 45 $ 3,162,167 22 $ 12,708,433 46 $ 9,052,862 32"


def test_f7_continuing_becomes_net_income_when_no_net_income_row() -> None:
    rows = _parse_is([_CONT])
    ni = [r for r in rows if r.key == "net_income"]
    assert len(ni) == 1 and (ni[0].current, ni[0].prior) == (12708433.0, 9052862.0)
    assert not [r for r in rows if r.key == "net_income_continuing"]


def test_f7_continuing_kept_when_net_income_row_exists() -> None:
    """2890 型：有本期淨利列 → 繼續營業單位本期淨利維持 net_income_continuing，net_income 只有本期淨利列。"""
    rows = _parse_is([_CONT, "69000 本期淨利 6,000,000 45 3,000,000 22 12,000,000 46 9,000,000 32"])
    assert [r.current for r in rows if r.key == "net_income"] == [12000000.0]
    assert [r.current for r in rows if r.key == "net_income_continuing"] == [12708433.0]


# ── 2.1 整份財報 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("ticker", ["2834", "5876", "2880", "2882", "2883", "2884", "5880"])
def test_bank_fh_real_reports_18_passed(ticker) -> None:
    _need(ticker)
    led = _ledger(ticker)
    assert (len(led.checks), sum(c.passed is True for c in led.checks)) == (18, 18), [
        (c.name, c.period, c.lhs, c.rhs) for c in led.checks if c.passed is not True]


def test_2890_only_is_net_income_current_not_passed() -> None:
    _need("2890")
    led = _ledger("2890")
    assert [f"{c.name}/{c.period}" for c in led.checks if c.passed is not True] == ["is_net_income/current"]


# ── 2.2 已知限制 ──────────────────────────────────────────────────────────

def test_known_limitations_fixed_set() -> None:
    assert fs_acceptance.KNOWN_LIMITATIONS == frozenset({"6223", "1101", "3529"})


def _rec(t, g, conform):
    return {"ticker": t, "group": g, "expected": 22, "total": 22, "passed": 22 if conform else 20,
            "excepted": [], "not_passed": [] if conform else ["is_pretax/current"], "conform": conform}


def test_main_all70_marks_known_limitations_and_summary_separates_counts(tmp_path, monkeypatch, capsys) -> None:
    ticks = [("1111", None), ("1101", None), ("6223", None), ("3529", None)]
    monkeypatch.setattr(fs_acceptance, "acceptance_tickers", lambda base: ticks)
    monkeypatch.setattr(fs_acceptance, "check_company",
                        lambda t, g, base: _rec(t, g, t == "1111") if t != "3529"
                        else {"ticker": t, "group": g, "expected": 22, "error": "no_statements"})
    out = tmp_path / "r.json"
    assert fs_acceptance.main(["--all70", "--out", str(out)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    by_t = {ln.split(" ")[0]: ln for ln in lines if ln.startswith(("1111", "1101", "6223", "3529"))}
    assert "known_limitation" not in by_t["1111"]
    assert all("known_limitation" in by_t[t] for t in ("1101", "6223", "3529"))
    assert lines[-1] == "SUMMARY conform=1/4 known_limitations=3 exceptions=0 bridge_residual_gt5pct=0/0"  # 2026-10-11 bridge-residual Spec §2.4
    recs = json.loads(out.read_text(encoding="utf-8"))
    assert len(recs) == 4
    assert {r["ticker"]: r["known_limitation"] for r in recs} == {"1111": False, "1101": True, "6223": True, "3529": True}


def test_known_limitation_never_counted_as_conform(tmp_path, monkeypatch, capsys) -> None:
    """已知限制公司即使 conform=True，也不算進符合數。"""
    monkeypatch.setattr(fs_acceptance, "acceptance_tickers", lambda base: [("1101", None), ("1111", None)])
    monkeypatch.setattr(fs_acceptance, "check_company", lambda t, g, base: _rec(t, g, True))
    fs_acceptance.main(["--all70", "--out", str(tmp_path / "r.json")])
    assert capsys.readouterr().out.strip().splitlines()[-1] == "SUMMARY conform=1/2 known_limitations=1 exceptions=0 bridge_residual_gt5pct=0/0"  # 2026-10-11 bridge-residual Spec §2.4
