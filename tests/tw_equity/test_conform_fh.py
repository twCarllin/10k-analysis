"""金控／銀行三表解析修正（run 2026-10-10-tw-equity-70-conform，Task 2：items 2.1、2.2）。

契約 row（task/2026-10-10-tw-equity-70-conform.md）：
  2.1 DoD ①: 2880、2883、2892 勾稽 18/0/0；2890 只剩例外 `is_net_income/current`
  2.1 DoD ③: 每個修法一個 fixture 測試（F-1、F-2、F-3、F-5；F-4 停業單位依 Spec §5 Q3 不做）
  2.1 契約: 6 家既有通過的金控，已對 key 列數值不變（fh_acceptance 6/6 為既有測試；快照比對見工作報告）
  2.2 DoD ①: 2801 勾稽 18/0/0、批次輸出 schema == "fh"、group == "bank"
  2.2 DoD ②: batch_summary 把 2801 列入金控排名表
  2.2 DoD ③: 分流單元測試
行文字取自 2026Q2 財報 PDF 的原文列（tw_report/，以 pdfplumber 列通道抽出）；整份 PDF 的測試在 PDF 不在時 skip。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import batch, pdf_doc, qa  # noqa: E402
from runtime.tw_equity.batch_summary import build_summary  # noqa: E402
from runtime.tw_equity.doc_anchor import (  # noqa: E402
    FS_HEADING_ANCHORS,
    find_annual_report_sections,
    find_heading_sections,
)
from runtime.tw_equity.fh_schema import FH_SECTION_HEADERS  # noqa: E402
from runtime.tw_equity.inputs import load_inputs, uses_fh_schema  # noqa: E402
from runtime.tw_equity.statements import (  # noqa: E402
    StatementRow,
    extract_statements,
    map_key,
    parse_statement_lines,
    run_cross_checks,
)


def _local(name: str):
    return pytest.mark.skipif(not (ROOT / "tw_report" / name).exists(), reason=f"需本地 tw_report/{name}")


def _ledger(ticker: str):
    inp = load_inputs(ticker, base_dir=ROOT)
    doc = pdf_doc.load_pdf(inp.consolidated_fs_path)
    return extract_statements(doc, find_heading_sections(doc, FS_HEADING_ANCHORS, required=set()), group=inp.group)


# ── 2.1 F-1：多行科目名（2880 合併綜合損益表原文列） ───────────────────────────────

_HDR_2880 = [
    "華南金融控股股份有限公司及子公司",
    "合併綜合損益表",
    "民國115 年及114 年4 月1 日至6 月30 日以及民國115 年及114 年1 月1 日至6 月30 日",
    "單位：新台幣仟元，惟",
    "每股盈餘為元",
    "114年4月1日至6月30日 114年1月1日至6月30日",
    "115年4月1日至6月30日 （重編後） 115年1月1日至6月30日 （重編後）",
    "代 碼 金 額 ％ 金 額 ％ 金 額 ％ 金 額 ％",
]
_PROVISION_4LINES = [
    "4xxxx 淨 收 益 22,002,481 100 14,546,055 100 40,731,082 100 29,901,124 100",
    "58100 呆帳費用、承諾及保證責任準",
    "備（提存）迴轉（附註六、",
    "七、十三、十四、十八及三",
    "一） ( 989,195 ) ( 4 ) 1,372,289 10 ( 1,521,964 ) ( 4 ) 548,494 2",
    "58200 保險其他營業成本 27,684 - 36,849 - 47,604 - ( 78,508 ) -",
]


def _parse_fh_is(texts: list[str]):
    lines = [(9, i, t) for i, t in enumerate(_HDR_2880 + texts)]
    rows, _, _ = parse_statement_lines(lines, "is", section_headers=FH_SECTION_HEADERS["is"], schema="fh")
    return rows


def test_f1_four_line_provision_label_is_merged_with_amounts() -> None:
    """F-1：帶代碼首行＋2 行名稱／附註＋1 行附註＋金額行 → 一列 provision，不丟失。"""
    rows = _parse_fh_is(_PROVISION_4LINES)
    prov = [r for r in rows if r.key == "provision"]
    assert len(prov) == 1
    assert prov[0].label == "呆帳費用、承諾及保證責任準備(提存)迴轉"
    assert (prov[0].current, prov[0].prior) == (-1521964.0, 548494.0)
    other = next(r for r in rows if r.key == "insurance_other_cost")  # 下一筆帶代碼列不被吞
    assert (other.current, other.prior) == (47604.0, -78508.0)


def test_f1_code_line_followed_by_coded_line_is_not_merged() -> None:
    """F-1 邊界：帶代碼首行之後緊接另一筆帶代碼列（無金額尾列）→ 不跨列合併，後一列照常解析。"""
    rows = _parse_fh_is([
        "4xxxx 淨 收 益 22,002,481 100 14,546,055 100 40,731,082 100 29,901,124 100",
        "58100 呆帳費用、承諾及保證責任準",
        "58200 保險其他營業成本 27,684 - 36,849 - 47,604 - ( 78,508 ) -",
    ])
    assert not [r for r in rows if r.key == "provision"]
    assert [r.current for r in rows if r.key == "insurance_other_cost"] == [47604.0]


# ── 2.1 F-2／F-3：別名與符號 ────────────────────────────────────────────────

def test_f2_f3_aliases_map_to_fh_keys() -> None:
    assert map_key("is", "呆帳費用、承諾及保證責任準備(提存)迴轉", None, schema="fh") == "provision"
    assert map_key("is", "呆帳費用、承諾及保證責任準備提存", None, schema="fh") == "provision"  # 既有別名不變
    assert map_key("is", "利息以外淨損益合計", None, schema="fh") == "non_interest_income"
    assert map_key("is", "利息以外淨收益合計", None, schema="fh") == "non_interest_income"  # 既有別名不變


def _row(label: str, key: str, cur: float | None, pri: float | None, i: int) -> StatementRow:
    return StatementRow("is", None, label, key, None, cur, pri, None, None, 1, i)


def _check(rows, name: str, period: str):
    return next(c for c in run_cross_checks(rows, schema="fh") if c.name == name and c.period == period)


def _pretax_rows(provision_label: str, provision: float):
    # 淨收益 1000；provision；營業費用合計 -100；稅前淨利 = 1000 + provision' - 100
    return [
        _row("淨收益", "net_revenue", 1000.0, 1000.0, 0),
        _row(provision_label, "provision", provision, provision, 1),
        _row("營業費用合計", "total_opex", -100.0, -100.0, 2),
    ]


def test_f2_provision_reversal_keeps_printed_sign() -> None:
    """F-2：「(提存)迴轉」印正數＝迴轉利益，依印出號相加；舊式「準備提存」印括號＝費用，取 −|v|。"""
    rev = _pretax_rows("呆帳費用、承諾及保證責任準備(提存)迴轉", 50.0) + [_row("稅前淨利", "pretax_income", 950.0, 950.0, 3)]
    c = _check(rev, "is_pretax", "prior")
    assert (c.lhs, c.rhs, c.passed) == (950.0, 950.0, True)
    exp = _pretax_rows("呆帳費用、承諾及保證責任準備提存", -50.0) + [_row("稅前淨利", "pretax_income", 850.0, 850.0, 3)]
    c = _check(exp, "is_pretax", "current")
    assert (c.lhs, c.rhs, c.passed) == (850.0, 850.0, True)
    neg = _pretax_rows("呆帳費用、承諾及保證責任準備(提存)迴轉", -50.0) + [_row("稅前淨利", "pretax_income", 850.0, 850.0, 3)]
    assert _check(neg, "is_pretax", "current").passed is True  # 迴轉列印負數（提存）同樣依印出號


def _tax_rows(label: str, tax: float, net: float):
    return [_row("稅前淨利", "pretax_income", 1000.0, 1000.0, 0), _row(label, "income_tax", tax, tax, 1),
            _row("本期稅後淨利", "net_income", net, net, 2)]


@pytest.mark.parametrize("label,tax,net", [
    ("所得稅費用(利益)", -300.0, 700.0),   # 2883 現期：費用印括號 → 淨利 = 稅前 + 印出值
    ("所得稅費用(利益)", 200.0, 1200.0),   # 2883 前期：利益印正數 → 同樣照印出值加
    ("所得稅(費用)利益", -300.0, 700.0),
    ("減:所得稅費用", 300.0, 700.0),       # 「減:」開頭 → −v
    ("所得稅費用", -300.0, 700.0),         # 純「所得稅費用」→ −|v|
    ("所得稅費用", 300.0, 700.0),
])
def test_f3_income_tax_sign_rule(label, tax, net) -> None:
    c = _check(_tax_rows(label, tax, net), "is_net_income", "current")
    assert (c.lhs, c.rhs, c.passed) == (net, net, True)


def test_f3_income_tax_sign_rule_contrast_wrong_sign_fails() -> None:
    """對照：同一組數字若按「純費用」規則（−|v|）會算出 700 ≠ 1200，確認符號規則有鑑別力。"""
    c = _check(_tax_rows("所得稅費用(利益)", 200.0, 1200.0), "is_net_income", "current")
    assert c.lhs == 1200.0
    c2 = _check(_tax_rows("所得稅費用", 200.0, 1200.0), "is_net_income", "current")
    assert c2.lhs == 800.0 and c2.passed is False


# ── 2.1 F-5：營業費用無合計列 ───────────────────────────────────────────────

def _opex_components(drop: str | None = None):
    comp = [("員工福利費用", "employee_benefits", -60.0), ("折舊及攤銷費用", "depreciation_amortization", -10.0),
            ("其他業務及管理費用", "other_ga", -30.0)]
    return [_row(lb, k, v, v, 10 + n) for n, (lb, k, v) in enumerate(comp) if k != drop]


def _pretax_no_total_opex(extra):
    return [_row("淨收益", "net_revenue", 1000.0, 1000.0, 0), _row("呆帳費用、承諾及保證責任準備提存", "provision", -50.0, -50.0, 1),
            _row("稅前淨利", "pretax_income", 850.0, 850.0, 2)] + extra


def test_f5_missing_total_opex_uses_sum_of_components() -> None:
    c = _check(_pretax_no_total_opex(_opex_components()), "is_pretax", "current")
    assert (c.lhs, c.rhs, c.passed) == (850.0, 850.0, True)


def test_f5_missing_total_opex_and_component_stays_none() -> None:
    c = _check(_pretax_no_total_opex(_opex_components(drop="other_ga")), "is_pretax", "current")
    assert c.passed is None and c.lhs is None


def test_f5_total_opex_row_present_takes_precedence() -> None:
    rows = _pretax_no_total_opex(_opex_components()) + [_row("營業費用合計", "total_opex", -100.0, -100.0, 20)]
    c = _check(rows, "is_pretax", "current")
    assert (c.lhs, c.passed) == (850.0, True)
    rows2 = _pretax_no_total_opex(_opex_components()) + [_row("營業費用合計", "total_opex", -80.0, -80.0, 20)]
    assert _check(rows2, "is_pretax", "current").lhs == 870.0  # 以合計列為準、不用組成項


# ── 2.1 DoD ①（整份財報） ─────────────────────────────────────────────────

@pytest.mark.parametrize("ticker", ["2880", "2883", "2892"])
def test_fh_real_reports_18_passed(ticker) -> None:
    if not (ROOT / "tw_report" / f"{ticker}_2026Q2財報.pdf").exists():
        pytest.skip("需本地 tw_report")
    led = _ledger(ticker)
    assert (len(led.checks), sum(c.passed is True for c in led.checks)) == (18, 18), [
        (c.name, c.period, c.lhs, c.rhs) for c in led.checks if c.passed is not True]


def test_2890_only_is_net_income_current_not_passed() -> None:
    if not (ROOT / "tw_report" / "2890_2026Q2財報.pdf").exists():
        pytest.skip("需本地 tw_report")
    led = _ledger("2890")
    bad = [f"{c.name}/{c.period}" for c in led.checks if c.passed is not True]
    assert bad == ["is_net_income/current"] and sum(c.passed is False for c in led.checks) == 1


# ── 2.2 銀行分流 ──────────────────────────────────────────────────────────

def test_uses_fh_schema_dispatch() -> None:
    assert uses_fh_schema("fh") and uses_fh_schema("bank")
    assert not any(uses_fh_schema(g) for g in (None, "industrial", "petrochemical", ""))


def test_bank_group_gets_fh_schema_in_extract_statements() -> None:
    """同一份 fh 版面文件，group="bank" 與 "fh" 解析結果相同（schema 為 fh）、"industrial" 則否。"""
    texts = _HDR_2880 + _PROVISION_4LINES
    doc = pdf_doc.PdfDoc(path=Path("x.pdf"), pages=[pdf_doc.Page(number=1, text="", tables=[], lines=texts)])
    anchors = find_heading_sections(
        pdf_doc.PdfDoc(path=Path("x.pdf"), pages=[pdf_doc.Page(number=1, text="合併綜合損益表\n", tables=[], lines=texts)]),
        FS_HEADING_ANCHORS, required=set())
    got = {g: extract_statements(doc, anchors, group=g) for g in ("fh", "bank")}
    if got["fh"] is None:
        pytest.skip("合成頁未被錨定為三表（此測試依賴錨點；整份 PDF 版本見 2801）")
    assert got["bank"].schema == got["fh"].schema == "fh"
    assert [(r.key, r.current) for r in got["bank"].rows] == [(r.key, r.current) for r in got["fh"].rows]


@_local("2801_2026Q2財報.pdf")
def test_2801_ledger_fh_schema_18_passed() -> None:
    led = _ledger("2801")
    assert led.schema == "fh"
    assert (len(led.checks), sum(c.passed is True for c in led.checks)) == (18, 18)


@_local("2801_2025年報.pdf")
def test_2801_annual_report_anchors_follow_fh_path() -> None:
    inp = load_inputs("2801", base_dir=ROOT)
    ar = pdf_doc.load_pdf(inp.annual_report_path)
    assert find_annual_report_sections(ar, required=set(), group="bank") == \
        find_annual_report_sections(ar, required=set(), group="fh")


@_local("2801_2026Q2財報.pdf")
def test_2801_qa_pack_has_no_fcf_topic() -> None:
    led = _ledger("2801")
    pack = qa.topic_pack(led, "bank")
    assert pack["answerable"] is True and qa.FCF_TOPIC not in pack["topics"]


@_local("2801_2026Q2財報.pdf")
@_local("2801_2025年報.pdf")
def test_2801_batch_record_is_fh_schema_with_bank_group() -> None:
    rec = batch.run_company("2801", base_dir=ROOT)
    assert rec["status"] == "ok", rec["error"]
    assert rec["schema"] == "fh" and rec["group"] == "bank"
    assert rec["checks"]["failed"] == 0 and rec["checks"]["none"] == 0 and rec["checks"]["passed"] == 18
    assert "fh_notes" in rec and rec["ifrs17_break"] in (True, False)


def _bank_rec(**over):
    rec = {"ticker": "2801", "company_name": "彰化銀行", "group": "bank", "schema": "fh", "status": "ok",
           "error": None, "fs_period": "2026H1", "basis": "H1", "ifrs17_break": False,
           "metrics": {"roe": {"current": 7.0}, "group_car": {"current": None}},
           "values": {"net_revenue": {"current": 10_000_000.0}, "net_income": {"current": 3_000_000.0},
                      "net_income_parent": {"current": 3_000_000.0}},
           "checks": {"passed": 18, "failed": 0, "none": 0, "not_passed": []}, "ttm": None}
    rec.update(over)
    return rec


@pytest.mark.parametrize("over", [{}, {"schema": None}])
def test_bank_record_is_in_fh_ranking_not_industrial(over) -> None:
    """2.2 DoD ②：group == "bank" 的記錄列入金控排名表（含 schema 缺漏、僅靠 group 判斷的情形），不進工業表、不產工業旗標。"""
    s = build_summary([_bank_rec(**over)])
    assert [r["ticker"] for r in s["fh_ranking"]] == ["2801"]
    assert s["fh_ranking"][0]["group"] == "bank"
    assert s["rows"] == [] and s["flags"] == [] and s["unsupported"] == [] and s["failed"] == []
