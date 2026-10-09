"""FyIncome 資料結構、符號正規化、勾稽、可用判準（Spec 2026-10-09-tw-equity-period-model §2.1／§2.4–§2.6）。

純合成資料，無 fixture 檔；數值由各測試依契約表自行構造。
"""

from __future__ import annotations

from runtime.tw_equity.fy_income import FyIncome, normalize_sign, scale_for_unit


def _row(label, key, cur, pri=None):
    return {"label": label, "key": key, "current": cur, "prior": pri}


def _good_rows():
    return [
        _row("營業收入", "revenue", 1000, 900),
        _row("營業成本", "cogs", 600, 500),
        _row("營業毛利", "gross_profit", 400, 400),
        _row("營業費用", "total_opex", -100, -100),
        _row("營業利益", "operating_income", 300, 300),
        _row("稅前淨利", "pretax_income", 320, 310),
        _row("所得稅費用", "income_tax", 20, 10),
        _row("本期淨利", "net_income", 300, 300),
    ]


def _fy(rows, scale=1.0, basis="consolidated"):
    return FyIncome(114, 5, "仟元", scale, basis, rows).finalize()


def _check(fy, name):
    return next(c for c in fy.checks if c["name"] == name)


def test_normalize_sign_contract_rows():
    assert normalize_sign("cogs", "營業成本", 300) == -300
    assert normalize_sign("total_opex", "營業費用", -80) == -80
    assert normalize_sign("income_tax", "所得稅費用(利益)", -50) == 50
    assert normalize_sign("income_tax", "所得稅(費用)利益", 50) == 50
    assert normalize_sign("income_tax", "所得稅費用", 50) == -50
    assert normalize_sign("operating_income", "營業損失 (12,314)", -12314) == -12314


def test_scale_table():
    assert scale_for_unit("仟元") == 1
    assert scale_for_unit("千元") == 1
    assert scale_for_unit("百萬元") == 1000
    assert scale_for_unit("百萬新台幣") == 1000
    assert scale_for_unit("元") == 0.001
    assert scale_for_unit("億元") is None


def test_get_and_to_dict():
    fy = _fy(_good_rows())
    assert fy.get("revenue") == (1000, 900)
    assert fy.get("fx_effect") == (None, None)
    d = fy.to_dict()
    assert d["roc_year"] == 114 and d["page"] == 5 and d["scale"] == 1.0
    assert isinstance(d["rows"], list) and isinstance(d["checks"], list)
    assert d["usable"] is True and isinstance(d["warnings"], list)


def test_gross_check_pass_and_fail():
    fy = _fy(_good_rows())
    assert _check(fy, "gross_current")["passed"] is True
    rows = _good_rows()
    rows[2] = _row("營業毛利", "gross_profit", 402, 400)  # 差 2 仟元
    fy = _fy(rows)
    assert _check(fy, "gross_current")["passed"] is False
    assert fy.usable is False


def test_operating_uses_gross_profit_net_when_present():
    rows = _good_rows()
    rows[2] = _row("營業毛利", "gross_profit", 400, 400)
    rows.insert(3, _row("營業毛利淨額", "gross_profit_net", 390, 390))
    rows[5] = _row("營業利益", "operating_income", 290, 290)  # 390-100
    fy = _fy(rows)
    assert _check(fy, "operating_current")["passed"] is True


def test_none_input_gives_none_and_keeps_usable():
    rows = _good_rows()
    rows[1] = _row("營業成本", "cogs", 600, None)  # prior None
    fy = _fy(rows)
    c = _check(fy, "gross_prior")
    assert c["passed"] is None
    assert fy.usable is True


def test_usable_scale_and_basis():
    assert _fy(_good_rows(), scale=None).usable is False
    assert _fy(_good_rows(), basis="parent").usable is False
    assert _fy(_good_rows(), basis="unknown").usable is True


def test_usable_requires_current_core_rows():
    rows = [r for r in _good_rows() if r["key"] != "net_income"]
    assert _fy(rows).usable is False


def test_operating_none_when_gross_profit_net_row_has_none_value():
    # 主 flow 裁決：gross_profit_net 列存在但值為 None → operating 勾稽 None，不退回 gross_profit
    rows = _good_rows()
    rows.insert(3, _row("營業毛利淨額", "gross_profit_net", None, 390))
    fy = _fy(rows)
    assert _check(fy, "operating_current")["passed"] is None
