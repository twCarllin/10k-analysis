"""extract_fy_income：候選頁選擇與入口（Spec 2026-10-09-tw-equity-period-model §2.1／§2.2／§2.4）。

頁文字列為合成（建構慣例同 test_doc_anchor_heading.py `_doc`）；真實頁用 fy_income_lines.json
（依據 pdf_doc.py:26 Page.lines，來源與頁碼見 JSON 內 source 欄）。
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.tw_equity.doc_anchor import PageRange
from runtime.tw_equity.fy_income import extract_fy_income
from runtime.tw_equity.pdf_doc import Page, PdfDoc

_FIX = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "tw_equity" / "fy_income_lines.json")
    .read_text(encoding="utf-8")
)


def _doc(pages: dict[int, list[str]]) -> PdfDoc:
    return PdfDoc(
        path="x.pdf",  # type: ignore[arg-type]
        pages=[Page(number=n, text="", tables=[], lines=ls) for n, ls in pages.items()],
    )


def _table(year_hdr="114 年度 113 年度", unit="單位：新台幣仟元", title="合併財務績效", extra=()):
    return [
        title,
        unit,
        f"項目 {year_hdr}",
        "營業收入 1,000 900",
        "營業成本 600 500",
        "營業毛利 400 400",
        "營業費用 100 100",
        "營業利益 300 300",
        "稅前淨利 320 310",
        "所得稅費用 20 10",
        "本期淨利 300 300",
        *extra,
    ]


def test_basic_extract_fields():
    fy = extract_fy_income(_doc({7: _table()}), None, roc_year=114)
    assert fy is not None
    assert fy.page == 7 and fy.roc_year == 114
    assert fy.scale == 1 and fy.basis == "consolidated"
    assert fy.get("revenue") == (1000, 900)
    assert fy.usable is True


def test_prefers_page_with_more_keys():
    short = [
        "致股東報告書",
        "項目 114 年度 113 年度",
        "營業收入 1,000 900",
        "營業毛利 400 400",
        "本期淨利 300 300",
    ]
    fy = extract_fy_income(_doc({3: short, 9: _table()}), None, roc_year=114)
    assert fy.page == 9


def test_same_key_count_takes_larger_page():
    fy = extract_fy_income(_doc({3: _table(), 9: _table()}), None, roc_year=114)
    assert fy.page == 9


def test_anchor_page_beats_outside_page():
    doc = _doc({3: _table(), 9: _table(extra=["本期綜合損益總額 300 300"])})
    fy = extract_fy_income(doc, {"ar_fin_performance": PageRange(3, 4)}, roc_year=114)
    assert fy.page == 3  # 錨點內優先，即使錨點外頁 key 數更多


def test_year_header_variants():
    for hdr in ("民國114年 民國113年", "114年度 113年度", "114年 113年"):
        fy = extract_fy_income(_doc({1: _table(year_hdr=hdr)}), None, roc_year=114)
        assert fy is not None, hdr
        assert fy.get("revenue") == (1000, 900)


def test_revenue_total_dropped_when_net_present():
    lines = [
        "單位：新台幣仟元 合併",
        "項目 114 年度 113 年度",
        "營業收入總額 1,100 1,000",
        "減:銷貨退回及折讓 100 100",
        "營業收入淨額 1,000 900",
        "營業毛利 400 400",
        "營業利益 300 300",
        "稅前淨利 320 310",
        "本期淨利 300 300",
    ]
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert fy.get("revenue") == (1000, 900)
    assert sum(1 for r in fy.rows if r["key"] == "revenue") == 1


def test_scale_units():
    fy = extract_fy_income(_doc({1: _table(unit="單位：新台幣千元")}), None, roc_year=114)
    assert fy.scale == 1 and fy.get("revenue") == (1000, 900)
    fy = extract_fy_income(_doc({1: _table(unit="單位：百萬新台幣")}), None, roc_year=114)
    assert fy.scale == 1000 and fy.get("revenue") == (1_000_000, 900_000)


def test_unknown_unit_not_usable():
    fy = extract_fy_income(_doc({1: _table(unit="單位：億元")}), None, roc_year=114)
    assert fy is not None and fy.scale is None and fy.usable is False


def test_basis_variants():
    parent = _table(title="個體財務績效", unit="單位：新台幣仟元")
    assert extract_fy_income(_doc({1: parent}), None, roc_year=114).basis == "parent"
    unk = _table(title="財務績效")
    assert extract_fy_income(_doc({1: unk}), None, roc_year=114).basis == "unknown"
    sub = _table(title="本公司及子公司")
    assert extract_fy_income(_doc({1: sub}), None, roc_year=114).basis == "consolidated"


def test_no_candidate_returns_none():
    no_year = ["營業收入 1,000 900", "營業毛利 400 400", "本期淨利 300 300"]
    prose = ["項目 114 年度 113 年度", "本公司營運穩定，無損益表格。"]
    assert extract_fy_income(_doc({1: no_year, 2: prose}), None, roc_year=114) is None


def test_real_pages_extract():
    for ticker, rev in (("3653", 20275577), ("2308", 554885168)):
        doc = _doc({_FIX[ticker]["page"]: _FIX[ticker]["lines"]})
        fy = extract_fy_income(doc, None, roc_year=114)
        assert fy is not None and fy.get("revenue")[0] == rev


def test_unit_whitespace_normalized():
    # 單位文字內含空白：NFKC＋去空白後仍得 scale 1（Spec §2.2 比對規則）
    fy = extract_fy_income(_doc({1: _table(unit="單位：新台幣 千元")}), None, roc_year=114)
    assert fy is not None and fy.scale == 1
    assert fy.get("revenue") == (1000, 900)


# ── Spec §2.7 第二輪修正 ─────────────────────────────────────────────────────


def _lines(rev=("營業收入 1,000 900",), cogs="營業成本 600 500", mid=(), gp="營業毛利 400 400",
           opex="營業費用 100 100", op="營業利益 300 300", tail=None, unit="單位：新台幣仟元", title="合併財務績效"):
    tail = tail or ["稅前淨利 320 310", "所得稅費用 20 10", "本期淨利 300 300"]
    return [title, unit, "項目 114 年度 113 年度", *rev, cogs, *mid, gp, opex, op, *tail]


def _check(fy, name):
    return next(c for c in fy.checks if c["name"] == name)


def test_unrealized_sales_profit_gross_check_passes():  # §2.7.1（1303 型）
    lines = _lines(mid=["減：未(已)實現銷貨損益 -10 5"], gp="營業毛利 410 395",
                   opex="營業費用 100 100", op="營業利益 310 295", tail=["稅前淨利 330 300", "所得稅費用 20 5", "本期淨利 310 295"])
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert _check(fy, "gross_current")["passed"] is True
    assert _check(fy, "gross_prior")["passed"] is True
    assert fy.usable is True


def test_gross_check_still_fails_without_unrealized_row():  # §2.7.1 邊界：缺列視為 0，差額仍 False
    lines = _lines(gp="營業毛利 410 400", op="營業利益 310 300")
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert _check(fy, "gross_current")["passed"] is False
    assert fy.usable is False


def test_other_operating_net_in_operating_check():  # §2.7.2（2303 型）
    lines = _lines(op="營業利益 320 310", tail=["稅前淨利 340 320", "所得稅費用 20 10", "本期淨利 320 310"])
    lines.insert(lines.index("營業費用 100 100") + 1, "其他收益及費損 20 10")
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert fy.get("other_operating_net") == (20, 10)
    assert _check(fy, "operating_current")["passed"] is True
    assert _check(fy, "operating_prior")["passed"] is True


def test_parent_page_excluded_even_if_richer():  # §2.7.3（2357 型）
    parent = _lines(title="個體財務績效") + ["本期綜合損益總額 300 300"]
    consol = _lines(title="合併財務績效")
    fy = extract_fy_income(_doc({3: consol, 9: parent}), None, roc_year=114)
    assert fy.page == 3 and fy.basis == "consolidated"


def test_only_parent_pages_kept_but_unusable():  # §2.7.3：全被剔除時保留原候選
    fy = extract_fy_income(_doc({3: _lines(title="個體財務績效")}), None, roc_year=114)
    assert fy.page == 3 and fy.basis == "parent" and fy.usable is False


def test_income_tax_negative_with_positive_cogs_is_benefit():  # §2.7.4（8046 型）
    lines = _lines(tail=["稅前淨利 100 100", "所得稅費用 40 -40", "本期淨利 60 140"],
                   op="營業利益 300 300", gp="營業毛利 400 400")
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert _check(fy, "net_current")["passed"] is True   # 100 - 40
    assert _check(fy, "net_prior")["passed"] is True     # 100 + 40（稅利益）


def test_income_tax_negative_cogs_keeps_minus_abs():  # §2.7.4 邊界；2026-10-11 改依帳上「淨利−稅前」定號（spec 2026-10-11-tw-equity-sign-fix §6 A2）
    from runtime.tw_equity.fy_income import normalize_sign

    assert normalize_sign("income_tax", "所得稅費用", 50, cogs_raw=-600) == -50
    assert normalize_sign("income_tax", "所得稅費用", 50) == -50
    # 稅利益：淨利 > 稅前 → 正值（舊規則靠 cogs 原值為正推斷，已改為帳上關係）
    assert normalize_sign("income_tax", "所得稅費用", -40661, pretax_raw=100000, net_income_raw=140661) == 40661
    # 無淨利／稅前可對照 → 退回 −|v|（不再以 cogs 原值為正推斷稅利益）
    assert normalize_sign("income_tax", "所得稅費用", -40661, cogs_raw=31925633) == -40661


def test_unit_from_previous_page():  # §2.7.5（2368 型）
    prev = ["財務績效", "單位:新台幣千元"]
    page = _lines(unit="（本頁無單位列）")
    fy = extract_fy_income(_doc({4: prev, 5: page}), None, roc_year=114)
    assert fy.scale == 1 and fy.get("revenue") == (1000, 900)


def test_no_unit_anywhere_gives_none_scale():
    fy = extract_fy_income(_doc({5: _lines(unit="（無）")}), None, roc_year=114)
    assert fy.scale is None and fy.usable is False


def test_rows_before_revenue_row_with_same_key_ignored():  # §2.7.5 同 key 多列
    head_table = ["項目 113 年度 114 年度", "營業毛利 11 22", "營業淨利 33 44"]
    lines = head_table + _lines()
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert fy.get("gross_profit") == (400, 400)
    assert fy.get("operating_income") == (300, 300)


def test_net_income_proxy_from_parent_net_income():  # §2.7.6（3017 型）
    lines = _lines(tail=["稅前淨利 320 310", "淨利歸屬於母公司業主 290 280"])
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert fy.get("net_income") == (290, 280)
    assert fy.net_income_basis == "parent"
    assert any("歸屬母公司淨利代用" in w for w in fy.warnings)
    assert fy.to_dict()["net_income_basis"] == "parent"
    assert fy.usable is True


def test_net_income_not_proxied_when_total_present():
    lines = _lines(tail=["稅前淨利 320 310", "所得稅費用 20 10", "本期淨利 300 300", "淨利歸屬於母公司業主 290 280"])
    fy = extract_fy_income(_doc({1: lines}), None, roc_year=114)
    assert fy.get("net_income") == (300, 300)
    assert fy.net_income_basis == "total"


def test_unit_from_narrative_after_amount():  # §2.7.5 第三輪（2368 型）：單位列缺，敘述「金額 仟元」
    prev = ["致股東報告書", "114 年度台灣營收總銷售值為59,144,461", "仟元，成長54.18%。"]
    fy = extract_fy_income(_doc({4: prev, 5: _lines(unit="（無）")}), None, roc_year=114)
    assert fy.scale == 1 and fy.get("revenue") == (1000, 900)


def test_conflicting_narrative_units_give_none():  # 第三輪：敘述同時有 仟元 與 百萬元 → scale None
    prev = ["營收為59,144,461 仟元", "資本額為1,200 百萬元"]
    fy = extract_fy_income(_doc({4: prev, 5: _lines(unit="（無）")}), None, roc_year=114)
    assert fy.scale is None and fy.usable is False
    assert fy.warnings


def test_unit_row_beats_narrative():
    fy = extract_fy_income(
        _doc({4: ["營收1,200 百萬元"], 5: _lines(unit="單位：新台幣仟元")}), None, roc_year=114
    )
    assert fy.scale == 1
