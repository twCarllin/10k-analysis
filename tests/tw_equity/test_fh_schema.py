"""fh_schema 純資料表測試（Spec 2026-10-09-tw-equity-fh-schema §0.4 F3–F5、§2.2–§2.4）。"""

from __future__ import annotations

import pytest

from runtime.tw_equity import fh_schema as fh
from runtime.tw_equity.fh_schema import norm_label

_F3_BS = (
    "現金及約當現金－淨額 存放央行及拆借金融同業 透過損益按公允價值衡量之金融資產 "
    "透過其他綜合損益按公允價值衡量之金融資產 按攤銷後成本衡量之債務工具投資 附賣回票券及債券投資 "
    "應收款項－淨額 本期所得稅資產 貼現及放款－淨額 保險合約資產及再保險合約資產 採用權益法之投資 "
    "其他金融資產 投資性不動產 不動產及設備 使用權資產 無形資產 遞延所得稅資產 其他資產 資產總計 "
    "央行及金融同業存款 央行及同業融資 透過損益按公允價值衡量之金融負債 附買回票券及債券負債 "
    "應付商業本票 應付款項 本期所得稅負債 存款及匯款 應付債券 其他借款 負債準備 其他金融負債 "
    "保險合約負債及再保險合約負債 租賃負債 遞延所得稅負債 其他負債 負債總計 普通股股本 資本公積 "
    "法定盈餘公積 特別盈餘公積 未分配盈餘 其他權益 權益總計 負債及權益總計 "
    "特別股股本 待分配股票股利 股本合計 保留盈餘合計 歸屬於母公司業主之權益總計 非控制權益 "
    "待出售資產 與待出售資產直接相關之負債"
).split()


def _all_values() -> set[str]:
    vals: set[str] = set()
    for tbl in fh.FH_CANONICAL_KEYS.values():
        vals |= set(tbl.values())
    return vals | set(fh.FH_CF_INHERITED_KEYS)


def test_check_spec_names_in_order():
    assert [n for n, _, _ in fh.FH_CHECK_SPECS] == [
        "bs_assets_eq_liab_equity", "bs_liab_equity_sum", "is_net_interest", "is_net_revenue",
        "is_pretax", "is_net_income", "cf_net_change", "cf_ending", "cf_pretax_eq_is",
    ]


def test_every_check_key_exists_in_canonical_values():
    vals = _all_values()
    for name, lhs, rhs in fh.FH_CHECK_SPECS:
        for k in (*lhs, *rhs):
            assert k in vals, (name, k)


@pytest.mark.parametrize("label", _F3_BS)
def test_f3_bs_labels_all_mapped(label):
    assert norm_label(label) in fh.FH_CANONICAL_KEYS["bs"]


def test_f3_insurance_and_loans_labels_map_to_expected_keys():
    bs = fh.FH_CANONICAL_KEYS["bs"]
    assert bs[norm_label("貼現及放款－淨額")] == "loans_net"
    assert bs[norm_label("保險合約負債及再保險合約負債")] == "insurance_contract_liabilities"


@pytest.mark.parametrize("raw,key", [
    ("利息收入", "interest_income"),
    ("減：利息費用", "interest_expense"),
    ("手續費及佣金淨收益", "fee_income_net"),
    ("呆帳費用、承諾及保證責任準備提存", "provision"),
])
def test_f4_is_labels_mapped(raw, key):
    assert fh.FH_CANONICAL_KEYS["is"][norm_label(raw)] == key


def test_interest_expense_matches_after_stripping_jian_prefix():
    stripped = norm_label("減：利息費用").removeprefix(norm_label("減："))
    assert fh.FH_CANONICAL_KEYS["is"][stripped] == "interest_expense"


def test_optional_keys_only_insurance_other_cost():
    assert "insurance_other_cost" in fh.FH_OPTIONAL_KEYS
    others = {k for n, lhs, rhs in fh.FH_CHECK_SPECS if n != "is_pretax" for k in (*lhs, *rhs)}
    assert not (others & fh.FH_OPTIONAL_KEYS)


def test_expense_keys_are_known_and_cf_extras_listed_separately():
    assert fh.FH_EXPENSE_KEYS <= _all_values()
    assert set(fh.FH_CF_EXTRA_KEYS.values()) == {"provision_cf", "loans_change", "deposits_change"}
    assert set(fh.FH_CANONICAL_KEYS) == {"bs", "is", "cf"}


def test_section_headers_normalized():
    for tbl, hs in fh.FH_SECTION_HEADERS.items():
        assert hs and all(h == norm_label(h) for h in hs), tbl
    assert norm_label("淨利歸屬於：") in fh.FH_SECTION_HEADERS["is"]


def test_industrial_tables_untouched_by_import():
    from runtime.tw_equity import statements as st
    assert len(st._CHECK_SPECS) == 11
    assert [n for n, _, _ in st._CHECK_SPECS][:2] == ["bs_assets_eq_liab_equity", "bs_assets_sum"]
