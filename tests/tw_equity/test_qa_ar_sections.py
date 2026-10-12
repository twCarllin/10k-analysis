"""年報三章節接入問答（item 2.3；spec/2026-10-12-tw-equity-ar-sections.md §2.4）黑箱行為測試。

契約 row（DoD／契約）：
  D1: topic_pack 在有年報章節時加 ar:cashflow／ar:contracts／ar:special
  D2: verify_topics 接受 ar:cashflow 的金額；引用不存在的金額 → 失敗；缺值欄位不是 0
  D3: basis 非 consolidated 時答案含口徑提示；arith_ok 非 True 時含驗算提示；表 B 寫「預估」
  D4: 3 個 render 函式的答案附頁碼；「其他必要補充說明事項」只給前 800 字並標示截斷
  D5: 模板路徑依問題用詞分流（含反例）；章節不可答 → 「年報此節無法解析（原因）」
  契約: 沒有年報或章節 not_found／failed → 不加主題，其他主題不變

fixture 欄位名旁的 `# source:` 為 producer（runtime/tw_equity/ar_sections.py）宣告行號。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc, qa, qa_llm  # noqa: E402
from runtime.tw_equity.ar_sections import (  # noqa: E402
    CashflowSection, CashflowTable, ContractRow, ContractsSection, SpecialItem, SpecialSection)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_qa_llm import _FakeLlm, _full_ledger  # noqa: E402

_PAGES_JSON = ROOT / "tests" / "fixtures" / "tw_equity" / "ar_sections_pages.json"


def _table(**kw) -> CashflowTable:
    base = dict(page=94,  # source: ar_sections.py:62
                opening_cash=2_267_253,  # source: ar_sections.py:63
                cfo=4_773_519,  # source: ar_sections.py:64
                cfi=None,  # source: ar_sections.py:65
                cff=None,  # source: ar_sections.py:66
                cfi_cff=2_063_139,  # source: ar_sections.py:67
                outflow=None,  # source: ar_sections.py:68
                fx=30_156,  # source: ar_sections.py:69
                closing_cash=9_134_067)  # source: ar_sections.py:70
    return CashflowTable(**{**base, **kw})


def _cf(basis: str | None = "consolidated", arith_ok: bool | None = True, **kw) -> CashflowSection:
    fc = _table(opening_cash=9_134_067, cfo=7_160_278, cfi_cff=-4_687_141, fx=None, closing_cash=11_821_787,
                applicable=True)  # source: ar_sections.py:74
    base = dict(status="parsed",  # source: ar_sections.py:107
                pages=[94],  # source: ar_sections.py:108
                actual=_table(),  # source: ar_sections.py:112
                actual_explanations={"operating": "營業活動產生淨現金流入4,773,519 仟元，主係獲利增加。",
                                     "investing": "投資活動產生淨現金流出1,013,580 仟元。",
                                     "financing": None},  # source: ar_sections.py:113
                forecast=fc,  # source: ar_sections.py:114
                forecast_explanations={"operating": "營業活動：獲利穩定。", "investing": None,
                                       "financing": None},  # source: ar_sections.py:115
                arith_ok=arith_ok,  # source: ar_sections.py:116
                basis=basis,  # source: ar_sections.py:117
                basis_note="期初：年報(表A) 97,737／帳本 100,442,408" if basis == "non_consolidated" else None)
    return CashflowSection(**{**base, **kw})


def _ct(**kw) -> ContractsSection:
    row = ContractRow(page=91,  # source: ar_sections.py:1120
                      entity=None,  # source: ar_sections.py:1121
                      nature="工程採購契約",  # source: ar_sections.py:1122
                      parties=["甲公司", "乙營造公司"],  # source: ar_sections.py:1123
                      period="112.9.25",  # source: ar_sections.py:1124
                      content="廠房興建工程，契約金額新台幣 50 億元",  # source: ar_sections.py:1125
                      restrictions="無")  # source: ar_sections.py:1126
    base = dict(status="parsed", pages=[91], rows=[row], none_entities=[])  # source: ar_sections.py:1144-1147
    return ContractsSection(**{**base, **kw})


def _sp(other_text: str = "無。", **kw) -> SpecialSection:
    items = {  # source: ar_sections.py:1765；SpecialItem 欄位 1746-1748
        "affiliates": SpecialItem("see_mops", 99, "請參閱公開資訊觀測站。"),
        "private_placement": SpecialItem("none", 99, "無。"),
        "other_supplement": SpecialItem("disclosed", 100, other_text),
        "material_events_36": SpecialItem("not_found")}
    base = dict(status="parsed", pages=[99, 100], items=items)  # source: ar_sections.py:1762-1765
    return SpecialSection(**{**base, **kw})


def _secs(**over) -> dict:
    return {"cashflow": _cf(), "contracts": _ct(), "special": _sp(), **over}


def _pack(**over) -> dict:
    return qa.topic_pack(_full_ledger(), ar_sections=_secs(**over))


# ── D1 主題與契約 ───────────────────────────────────────────────────────────

def test_d1_three_topics_added() -> None:
    p = _pack()
    t = p["topics"]
    assert t["ar:cashflow"]["kind"] == "ar_cashflow" and t["ar:contracts"]["kind"] == "ar_contracts"
    assert t["ar:special"]["kind"] == "ar_special"
    cf = t["ar:cashflow"]
    assert cf["actual"]["opening_cash"] == 2_267_253 and cf["actual"]["yi"]["opening_cash"] == "22.67 億元"
    assert cf["forecast"]["applicable"] is True and cf["basis"] == "consolidated" and cf["arith_ok"] is True
    assert t["ar:contracts"]["rows"][0]["page"] == 91 and t["ar:contracts"]["rows"][0]["nature"] == "工程採購契約"
    assert set(p["ar_sections_status"]) == {"cashflow", "contracts", "special"}
    assert p["ar_sections_status"]["cashflow"]["status"] == "parsed"


def test_d1_none_status_still_adds_topic() -> None:
    p = _pack(contracts=_ct(status="none", rows=[]))
    assert p["topics"]["ar:contracts"]["rows"] == [] and p["ar_sections_status"]["contracts"]["status"] == "none"


@pytest.mark.parametrize("status", ["failed", "not_found"])
def test_contract_unparsable_section_not_added_others_unchanged(status) -> None:
    base = qa.topic_pack(_full_ledger())
    p = _pack(contracts=_ct(status=status, rows=[], reason="文字層缺字：第 114 頁"))
    assert "ar:contracts" not in p["topics"] and "ar:cashflow" in p["topics"]
    assert p["ar_sections_status"]["contracts"] == {"status": status, "reason": "文字層缺字：第 114 頁"}
    assert set(p["topics"]) - {k for k in p["topics"] if k.startswith("ar:")} == set(base["topics"])


def test_contract_no_annual_report_no_ar_topics() -> None:
    base = qa.topic_pack(_full_ledger())
    assert not any(k.startswith("ar:") for k in base["topics"])
    assert base["ar_sections_status"]["cashflow"]["status"] == "not_found"
    err = qa.topic_pack(_full_ledger(), ar_sections_error="ValueError: boom")
    assert err["ar_sections_status"]["special"]["status"] == "failed" and "ValueError: boom" in err["ar_sections_status"]["special"]["reason"]
    assert not any(k.startswith("ar:") for k in err["topics"])


# ── D2 數字核對 ─────────────────────────────────────────────────────────────

def test_d2_verify_accepts_table_amounts_rejects_unknown() -> None:
    p = _pack()
    ok = "表 A 營業活動淨現金流量 47.74 億元，表 B 預估期末 118.22 億元，營業活動說明 4,773,519 仟元。"
    assert qa.verify_topics(ok, p, ["ar:cashflow"]) == []
    bad = qa.verify_topics("表 A 營業活動淨現金流量 99.99 億元。", p, ["ar:cashflow"])
    assert bad and "99.99 億" in bad[0]


def test_d2_missing_field_is_not_zero_and_not_allowed() -> None:
    p = _pack()
    assert p["topics"]["ar:cashflow"]["actual"]["cfi"] is None and p["topics"]["ar:cashflow"]["actual"]["yi"]["cfi"] is None
    assert qa.verify_topics("投資活動淨現金流量 0.00 億元。", p, ["ar:cashflow"])
    text = qa.render_ar_answer(p, ["cashflow"], company="X")
    assert "年報未列：" in text and "投資活動淨現金流量 0.00" not in text


def test_d2_contracts_and_special_text_numbers_not_flagged() -> None:
    p = _pack()
    assert qa.verify_topics("契約金額新台幣 50 億元（p.91）。", p, ["ar:contracts"]) == []
    assert qa.verify_topics("契約金額 77 億元。", p, ["ar:contracts"])  # 原文沒有的金額仍不可引用


# ── D3 口徑、驗算、預估 ─────────────────────────────────────────────────────

def test_d3_basis_hints_in_template_answer() -> None:
    non = qa.render_ar_answer(_pack(cashflow=_cf("non_consolidated")), ["cashflow"], company="X")
    assert "年報此節的數字不是合併數字" in non and "不可與財報合併現金流量表的數字混在同一句比較" in non
    unk = qa.render_ar_answer(_pack(cashflow=_cf("unknown")), ["cashflow"], company="X")
    assert "年報此節的數字無法確認是否為合併數字" in unk
    none_basis = qa.render_ar_answer(_pack(cashflow=_cf(None)), ["cashflow"], company="X")
    assert "無法確認是否為合併數字" in none_basis
    con = qa.render_ar_answer(_pack(), ["cashflow"], company="X")
    assert "不是合併數字" not in con and "無法確認是否為合併數字" not in con


def test_d3_arith_hint_and_forecast_label() -> None:
    for v in (False, None):
        t = qa.render_ar_answer(_pack(cashflow=_cf(arith_ok=v)), ["cashflow"], company="X")
        assert "此表期初＋各項流量與期末不平（或無法驗算）" in t
    ok = qa.render_ar_answer(_pack(), ["cashflow"], company="X")
    assert "不平" not in ok and "預估" in ok and "p.94" in ok


def test_d3_forecast_not_applicable_and_none_status() -> None:
    fc = _table(applicable=False)
    t = qa.render_ar_answer(_pack(cashflow=_cf(forecast=fc)), ["cashflow"], company="X")
    assert "年報寫「不適用」" in t
    t2 = qa.render_ar_answer(_pack(cashflow=_cf(status="none", actual=None, forecast=None, arith_ok=None)),
                             ["cashflow"], company="X")
    assert "沒有現金流量分析表" in t2


# ── D4 頁碼與 800 字 ────────────────────────────────────────────────────────

def test_d4_contracts_and_special_answers_carry_pages() -> None:
    p = _pack()
    c = qa.render_ar_answer(p, ["contracts"], company="X", source="s.pdf")
    assert "p.91" in c and "工程採購契約" in c and "甲公司、乙營造公司" in c
    s = qa.render_ar_answer(p, ["special"], company="X")
    assert "p.99" in s and "p.100" in s and "找不到此項" in s


def test_d4_other_supplement_truncated_to_800() -> None:
    long = "甲" * 800 + "乙" * 50
    t = _pack(special=_sp(long))["topics"]["ar:special"]["items"]["other_supplement"]
    assert t["text"] == "甲" * 800 and t["truncated"] is True and t["full_length"] == 850
    text = qa.render_ar_answer(_pack(special=_sp(long)), ["special"], company="X")
    assert "甲" * 800 in text and "乙" not in text and "只列前 800 字" in text and "p.100" in text
    exact = _pack(special=_sp("甲" * 800))["topics"]["ar:special"]["items"]["other_supplement"]
    assert exact["truncated"] is False and len(exact["text"]) == 800


def test_d4_all_special_items_truncated_to_800() -> None:
    """主 flow 2026-10-12：800 字上限擴及全部子項（2412 關係企業原文 15,304 字）；反例：短原文不截斷。"""
    sp = _sp()
    sp.items["affiliates"] = SpecialItem("disclosed", 99, "丙" * 1000)  # source: ar_sections.py:1746-1748
    items = _pack(special=sp)["topics"]["ar:special"]["items"]
    assert items["affiliates"]["truncated"] is True and items["affiliates"]["text"] == "丙" * 800
    assert items["affiliates"]["full_length"] == 1000
    assert items["private_placement"]["truncated"] is False and items["private_placement"]["text"] == "無。"


def test_d4_llm_view_carries_hints_pages_and_missing_marker() -> None:
    p = _pack(cashflow=_cf("non_consolidated", arith_ok=False), special=_sp("甲" * 900))
    v = qa_llm._topic_view(p["topics"]["ar:cashflow"])
    assert "不是合併數字" in v["basis_notice"] and v["arith_notice"] and v["table_a_actual"]["cfi"] == "年報未列"
    assert v["table_b_forecast_is_estimate_not_actual"]["page"] == 94
    sp = qa_llm._topic_view(p["topics"]["ar:special"])["items"]["other_supplement"]
    assert sp["truncated"] is True and sp["page"] == 100 and len(sp["text"]) == 800
    inputs = qa_llm.llm_inputs(p, "q", "X")
    assert "ar:contracts" in inputs["topics_catalog"] and "ar_sections_status" in inputs["facts_json"]


def test_d4_llm_path_selects_ar_topic_and_falls_back_to_template() -> None:
    p = _pack()
    good = {"supported": True, "topics": ["ar:contracts"], "answer": "年報列有工程採購契約（p.91），金額新台幣 50 億元。"}
    text, meta = qa_llm.answer_llm(p, "重要契約有哪些", company="X", llm=_FakeLlm(good))
    assert meta["source"] == "llm" and meta["topics"] == ["ar:contracts"]
    bad = {"supported": True, "topics": ["ar:cashflow"], "answer": "表 A 營業活動淨現金流量 1.00 億元。"}
    text2, meta2 = qa_llm.answer_llm(p, "現金流量預估", company="X", llm=_FakeLlm(bad, bad))
    assert meta2["source"] == "template" and "p.94" in text2


# ── D5 分流 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,keys", [
    ("有哪些重要契約？", ["contracts"]), ("公司簽了什麼契約", ["contracts"]),
    ("特別記載事項有什麼", ["special"]), ("私募辦理情形", ["special"]), ("關係企業資料", ["special"]),
    ("證交法第三十六條事項", ["special"]), ("有無重大影響事項", ["special"]),
    ("未來一年現金流動性如何", ["cashflow"]), ("現金流量預估", ["cashflow"]), ("現金剩餘多少", ["cashflow"]),
    ("會有現金不足嗎", ["cashflow"]), ("重要契約與私募", ["contracts", "special"]),
    ("未來一年的現金狀況", ["cashflow"]), ("私募有價證券辦理情形", ["special"]),
    ("有無對股東權益或證券價格有重大影響之事項", ["special"]),
])
def test_d5_route_positive(q, keys) -> None:
    assert qa.route_ar_sections(q) == keys


@pytest.mark.parametrize("q", ["自由現金流多少", "FCF 為什麼下降", "毛利率多少", "契約負債多少", "對公司有重大影響力嗎", "現金流量為什麼變動",
                               # 審查 Task 2 🟡1：非年報章節的問題不可分流
                               "未來一年營收會成長嗎", "未來一年資本支出多少", "受到匯率重大影響嗎", "關係企業交易占營收比",
                               "私募基金持股", "客戶契約收入",
                               # 審查 Task 2 修正輪 🟡A
                               "未來一年現金股利多少", "未來一年會現金增資嗎", "公司現金剩餘多少股"])
def test_d5_route_counterexamples(q) -> None:
    assert qa.route_ar_sections(q) == []


def _write_inputs(base: Path) -> None:
    d = base / "tw_equity_inputs"
    d.mkdir()
    (d / "9999.json").write_text(json.dumps(
        {"ticker": "9999", "company_name": "測試", "group": "industrial", "fiscal_year": 2025,
         "annual_report_path": "ar.pdf", "consolidated_fs_path": "h1.pdf", "fs_period": "2026H1"},
        ensure_ascii=False), encoding="utf-8")


def test_d5_unrouted_question_message_and_fcf_path_unchanged(monkeypatch, tmp_path) -> None:
    _write_inputs(tmp_path)
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    text, facts = qa.answer("9999", "毛利率多少", base_dir=tmp_path)
    assert "G1 只支援 FCF 問題" in text and facts is None
    text, facts = qa.answer("9999", "自由現金流為什麼變動", base_dir=tmp_path)  # 不分到 ar:cashflow
    assert facts is not None and "■ 年報現金流量" not in text and qa.verify_numbers(text, facts) == []


def test_d5_template_unparsable_section_says_cannot_parse(monkeypatch, tmp_path) -> None:
    _write_inputs(tmp_path)
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    text, pack = qa.answer("9999", "重要契約有哪些", base_dir=tmp_path)  # ar.pdf 不存在 → 年報讀取失敗
    assert "年報此節無法解析（年報讀取或解析失敗：" in text and "ar:contracts" not in pack["topics"]
    assert any(k.startswith("gross") or k == qa.FCF_TOPIC for k in pack["topics"])  # 既有主題不受影響


@pytest.mark.skipif(not _PAGES_JSON.exists(), reason="金標 fixture 不存在")
def test_d5_template_end_to_end_reads_annual_report_once(monkeypatch, tmp_path) -> None:
    pages = json.loads(_PAGES_JSON.read_text(encoding="utf-8"))["3653"]
    _write_inputs(tmp_path)
    loads: list[str] = []

    def fake_load_pdf(path, *a, **k):  # 系統邊界：PDF 檔讀取
        if "ocr" not in k:  # 帶 ocr 的是 _load_doc 對圖片頁的同次重讀，不算另一次讀年報
            loads.append(Path(path).name)
        return pdf_doc.from_json(copy.deepcopy(pages))

    monkeypatch.setattr(pdf_doc, "load_pdf", fake_load_pdf)
    monkeypatch.setattr(qa, "load_ledger", lambda p, group=None: _full_ledger())
    for q, page in (("重要契約有哪些", "p.91"), ("特別記載事項", "p.99"), ("未來一年現金流動性預估", "p.94")):
        loads.clear()
        text, pack = qa.answer("9999", q, base_dir=tmp_path)
        assert page in text and loads.count("ar.pdf") == 1 and "模板答案只回答年報章節" in text  # 審查 Task 2 🟡1：複合問題提示
        ar_topics = [k for k in qa.AR_TOPICS if k in pack["topics"]]
        assert ar_topics and qa.verify_topics(text, pack, ar_topics) == []
    assert "不是合併數字" in text or "無法確認是否為合併數字" in text  # H1 假帳本無年底現金可比 → 非合併或未知
