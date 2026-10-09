"""金控 FY 損益：列對照、scope／schema、usable、FY 勾稽（Spec fh-schema §6.3／§6.4；task 4.3）。

fixture（唯一副本）：tests/fixtures/tw_equity/fh_fy_income_pages.json（依據 make_fh_fy_fixture.py；
tw_report/<t>_2025年報.pdf p243／p266／p120／p231／p242／p160，Spec §0.4 F9）。

契約 row：
  - 2881 p243 → scope consolidated、net_revenue 381306135、pretax_income 137062651、net_income 120981786、usable、is_pretax passed
  - 2882 p231 四列 → parent_only、net_income_parent 有值、usable；個體表「稅後純益」→ net_income_parent，其餘列不產生 canonical key
  - [邊界] 合併表缺 pretax_income → usable False 且 checks 對應項 passed=None
  - [組合] 2885 同頁合併＋個體 × 費用括號 → 取合併表值且費用絕對值勾稽 passed
  - group=None → to_dict() 無 scope／schema 鍵、與快照相同（快照比對住 test_fh_fy_candidates.py）
  - 6 家期望：2881、2885、2886 consolidated、usable；2882、2887、2891 parent_only、usable（§6.4）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.tw_equity.doc_anchor import PageRange
from runtime.tw_equity.fy_income import FyIncome, extract_fy_income
from runtime.tw_equity.pdf_doc import from_json
from runtime.tw_equity.tables import extract_tables

_FIX = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "tw_equity" / "fh_fy_income_pages.json").read_text(encoding="utf-8")
)


def _fy(t: str) -> FyIncome:
    doc = from_json(_FIX[t]["doc"])
    anchors = {k: PageRange(start=v[0], end=v[1]) for k, v in _FIX[t]["anchors"].items()}
    return extract_fy_income(doc, anchors, roc_year=114, group="fh")


def _passed(fy: FyIncome) -> dict[str, bool | None]:
    return {c["name"]: c["passed"] for c in fy.checks}


def test_2881_consolidated_values_usable_and_pretax_check_with_reserve_change():
    fy = _fy("2881")
    assert fy.scope == "consolidated" and fy.schema == "fh" and fy.usable is True
    assert fy.get("net_revenue")[0] == 381306135
    assert fy.get("pretax_income")[0] == 137062651
    assert fy.get("net_income")[0] == 120981786
    assert fy.get("insurance_reserve_change")[0] == 135253603  # 費用印正數；入式取絕對值
    assert _passed(fy)["is_pretax_current"] is True
    assert _passed(fy)["is_net_income_current"] is True


def test_2885_same_page_picks_consolidated_values_and_parenthesized_expenses_check_passes():
    fy = _fy("2885")
    assert fy.scope == "consolidated"
    assert fy.get("net_revenue") == (128424156, 120699682)
    assert fy.get("pretax_income")[0] == 47119267  # 個體表為 36,777,879，不可取到
    assert fy.get("provision")[0] == -2055024  # 括號＝負號
    assert set(_passed(fy).values()) == {True}  # 本期＋上期共 4 項全 passed


def test_2882_parent_only_four_rows_only_net_income_row_maps_to_canonical_key():
    fy = _fy("2882")
    assert fy.scope == "parent_only" and fy.usable is True
    assert fy.get("net_income_parent")[0] == 107141920
    keyed = [r for r in fy.rows if r["key"] is not None]
    assert [(r["label"], r["key"]) for r in keyed] == [("稅後純益", "net_income_parent")]
    assert {r["label"] for r in fy.rows} >= {"淨收益", "費用及損失", "稅前損益"}  # 其餘列保留原文


@pytest.mark.parametrize(
    "t,scope",
    [("2881", "consolidated"), ("2885", "consolidated"), ("2886", "consolidated"),
     ("2882", "parent_only"), ("2887", "parent_only"), ("2891", "parent_only")],
)
def test_six_companies_scope_and_usable(t, scope):
    fy = _fy(t)
    assert (fy.scope, fy.usable) == (scope, True)
    # 合併表：FY 勾稽全過；個體表：只對照淨利列，不跑勾稽
    assert set(_passed(fy).values()) == ({True} if scope == "consolidated" else set())


def test_2886_consolidated_also_maps_net_income_attributable_to_parent():
    fy = _fy("2886")
    assert fy.get("net_income_parent")[0] == 35038130


def test_consolidated_missing_pretax_is_unusable_and_checks_are_none():
    rows = [
        {"label": "淨收益", "key": "net_revenue", "current": 100.0, "prior": 90.0},
        {"label": "本期淨利", "key": "net_income", "current": 40.0, "prior": 30.0},
    ]
    fy = FyIncome(roc_year=114, page=1, unit="仟元", scale=1.0, rows=rows, scope="consolidated", schema="fh").finalize()
    assert fy.usable is False
    assert _passed(fy)["is_pretax_current"] is None and _passed(fy)["is_net_income_current"] is None


def test_to_dict_has_scope_and_schema_only_for_fh():
    d = _fy("2881").to_dict()
    assert (d["scope"], d["schema"]) == ("consolidated", "fh")
    ind = FyIncome(roc_year=114, page=1, unit="仟元", scale=1.0).to_dict()
    assert "scope" not in ind and "schema" not in ind


def test_extract_tables_passes_group_to_fy_income():
    ar = from_json(_FIX["2881"]["doc"])
    fh = extract_tables(ar, {}, None, None, None, None, roc_year=114, group="fh")
    assert fh.fy_income is not None and fh.fy_income.schema == "fh"
    assert fh.to_dict()["fy_income"]["scope"] == "consolidated"
    assert extract_tables(ar, {}, None, None, None, None, roc_year=114).fy_income is None  # 工業路徑對金控頁無候選
