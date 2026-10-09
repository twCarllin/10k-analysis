"""金控 FY 損益候選頁與欄序（Spec fh-schema §6.2；task 4.2）。

fixture（唯一副本）：tests/fixtures/tw_equity/fh_fy_income_pages.json
  依據 make_fh_fy_fixture.py，來源 tw_report/<t>_2025年報.pdf p243／p231／p266／p120／p242／p160（Spec §0.4 F9）；
  anchors 起頁依據 item 4.1 實測。`industrial_fy_3653` 為本 item 前 HEAD 的工業 FY 快照（共通條款 R②）。

契約 row：
  - 2881 p243 `2024年度 2025年度`（roc_year=114）→ 欄序舊年在前、current 取第二欄
  - 2885 p266 同頁合併＋個體 → 選合併表
  - 2882 p231 只有個體 → 選個體、scope 判定交 4.3
  - 表題含「合併」優先於「個體」
  - [邊界] 表頭只出現一個年度標記 → 回 None
  - [組合] 西元表頭 × 費用為正數／括號（2881 vs 2885）→ 兩種格式都能定位候選頁
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import PageRange
from runtime.tw_equity.fy_income import extract_fy_income, fh_candidate_tables, fh_select_table
from runtime.tw_equity.pdf_doc import Page, PdfDoc, from_json

_FIX = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "tw_equity" / "fh_fy_income_pages.json").read_text(encoding="utf-8")
)


def _doc(t: str) -> PdfDoc:
    return from_json(_FIX[t]["doc"])


def _anchors(t: str) -> dict:
    return {k: PageRange(start=v[0], end=v[1]) for k, v in _FIX[t]["anchors"].items()}


def _synth(number: int, lines: list[str]) -> Page:
    return Page(number=number, text="\n".join(lines), tables=[], lines=lines)


def _region(doc: PdfDoc, t) -> list[str]:
    pg = next(p for p in doc.pages if p.number == t.page)
    return pg.lines[t.start : t.end]


# t, 頁, scope_hint, family, current_col, prior_col
_SIX = [
    ("2881", 243, "consolidated", "west", 1, 0),   # 西元表頭、舊年在前、費用為正數
    ("2885", 266, "consolidated", "roc", 0, 1),    # 民國、114 在前、費用括號
    ("2886", 120, "consolidated", "roc", 0, 1),
    ("2882", 231, "parent_only", "roc", 1, 0),
    ("2887", 242, "parent_only", "roc", 1, 0),
    ("2891", 160, "parent_only", "roc", 1, 0),
]


@pytest.mark.parametrize("t,page,scope,family,cur,prior", _SIX)
def test_six_companies_page_scope_and_column_order(t, page, scope, family, cur, prior):
    tbl = fh_select_table(_doc(t), _anchors(t), 114)
    assert tbl is not None
    assert (tbl.page, tbl.scope_hint, tbl.family, tbl.current_col, tbl.prior_col) == (page, scope, family, cur, prior)


def test_2881_west_header_older_year_first_current_is_second_column():
    tbl = fh_select_table(_doc("2881"), _anchors("2881"), 114)
    assert tbl.family == "west" and tbl.current_col == 1 and tbl.prior_col == 0
    region = _region(_doc("2881"), tbl)
    assert any(ln.startswith("淨收益 347,463,495 381,306,135") for ln in region)  # 區段含表內列


def test_2885_same_page_consolidated_and_parent_picks_consolidated_region():
    doc = _doc("2885")
    tbl = fh_select_table(doc, _anchors("2885"), 114)
    region = "\n".join(_region(doc, tbl))
    assert tbl.scope_hint == "consolidated"
    assert "保險負債準備淨變動" in region
    assert "採權益法" not in region and "小計" not in region  # 個體表列不在取用區段
    assert {c.scope_hint for c in fh_candidate_tables(doc, _anchors("2885"), 114)} >= {"consolidated", "parent_only"}


def test_2882_parent_only_page_selected_and_region_is_income_table():
    doc = _doc("2882")
    tbl = fh_select_table(doc, _anchors("2882"), 114)
    assert tbl.page == 231 and tbl.scope_hint == "parent_only"
    region = _region(doc, tbl)
    assert any(ln.startswith("稅後純益") for ln in region)
    assert not any(ln.startswith("股東權益總計") for ln in region)  # 同頁前一張非損益表不入區段


_CONSOL_TABLE = [
    "(一) 合併綜合損益表",
    "單位：新臺幣仟元",
    "項目 114 年度 113 年度",
    "淨收益 100 90",
    "稅前淨利 50 40",
    "本期淨利 40 30",
]
_PARENT_TABLE = [
    "(二) 個體綜合損益表",
    "單位：新臺幣仟元",
    "項目 114 年度 113 年度",
    "採權益法認列之投資損益 100 90",
    "稅前淨利 50 40",
    "本期淨利 40 30",
]


def test_title_consolidated_preferred_over_parent_even_when_parent_listed_first():
    doc = PdfDoc(path=Path("x.pdf"), pages=[_synth(10, _PARENT_TABLE + _CONSOL_TABLE)])
    tbl = fh_select_table(doc, None, 114)
    assert tbl.scope_hint == "consolidated"
    assert "(一) 合併綜合損益表" in doc.pages[0].lines[tbl.start - 3 : tbl.start]


def test_header_with_single_year_marker_returns_none():
    lines = ["合併綜合損益表", "項目 114 年度 增減", "淨收益 100 90", "稅前淨利 50 40", "本期淨利 40 30"]
    doc = PdfDoc(path=Path("x.pdf"), pages=[_synth(10, lines)])
    assert fh_select_table(doc, None, 114) is None
    assert fh_candidate_tables(doc, None, 114) == []


def test_anchor_range_preferred_over_lower_numbered_page_outside_range():
    doc = PdfDoc(path=Path("x.pdf"), pages=[_synth(5, _CONSOL_TABLE), _synth(50, _PARENT_TABLE)])
    anchors = {"ar_fin_performance": PageRange(start=50, end=50)}
    assert fh_select_table(doc, anchors, 114).page == 50
    assert fh_select_table(doc, None, 114).page == 5  # 無錨點 → 全頁，合併優先


def test_extract_fy_income_fh_returns_selected_page_unit_and_basis():
    r = extract_fy_income(_doc("2885"), _anchors("2885"), roc_year=114, group="fh")
    assert (r.page, r.unit, r.scale, r.basis) == (266, "新臺幣仟元", 1.0, "consolidated")
    r2 = extract_fy_income(_doc("2882"), _anchors("2882"), roc_year=114, group="fh")
    assert (r2.page, r2.basis) == (231, "parent")


@pytest.mark.parametrize("group", [None, "industrial"])
def test_industrial_path_unchanged_for_non_fh_group(group):
    snap = _FIX["industrial_fy_3653"]
    ar = from_json(
        json.loads((Path(__file__).parent.parent / "fixtures" / "tw_equity" / "ar_3653_pages.json").read_text(encoding="utf-8"))
    )
    anchors = {k: (None if v is None else PageRange(start=v[0], end=v[1])) for k, v in snap["anchors"].items()}
    kw = {} if group is None else {"group": group}
    assert extract_fy_income(ar, anchors, roc_year=114, **kw).to_dict() == snap["to_dict"]
