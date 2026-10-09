"""StatementLedger.value_at（period-model item 1.2，Spec §1.2；合成帳本，不依賴 PDF）。

契約 row：
  V1: H1 帳本 bs 列 columns=[300,200,250] → bs_current/bs_prior_same/bs_prior_fy_end = 300/200/250
  V2: is 列 value_at("revenue","flow_prior") → IS prior 欄值
  V3: columns 空 → flow_current／bs_current→row.current；其餘三 tag→row.prior（不論 basis）
  V4: 新欄位預設值
  V5: 列欄值 None → 0.0；key 無列 → None
  V6: [邊界] bs 列配 flow_current、tag 標籤為 None、欄索引越界 → None
"""
from __future__ import annotations

from runtime.tw_equity.statements import StatementLedger, StatementRow

_TAGS = ("flow_current", "flow_prior", "bs_current", "bs_prior_same", "bs_prior_fy_end")


def _row(st, key, cur, pri, columns):
    return StatementRow(st, None, key, key, None, cur, pri, None, None, 1, 0, columns=columns)


def _h1(rows, **kw) -> StatementLedger:
    base = dict(
        unit="仟元", period_current="115", period_prior="114", rows=rows, checks=[], unmapped_labels=[],
        column_periods={"bs": ["115-06-30", "114-12-31", "114-06-30"],
                        "is": ["115-01-01~115-06-30", "114-01-01~114-06-30"], "cf": []},
        basis="H1",
        periods={"flow_current": "115-01-01~115-06-30", "flow_prior": "114-01-01~114-06-30",
                 "bs_current": "115-06-30", "bs_prior_same": "114-06-30", "bs_prior_fy_end": "114-12-31"},
    )
    base.update(kw)
    return StatementLedger(**base)


def _bs_columns_ledger() -> StatementLedger:
    # 欄序依 column_periods["bs"]：115-06-30、114-12-31、114-06-30
    return _h1([_row("bs", "cash", 300, 200, [300, 200, 250]), _row("is", "revenue", 600, 500, [600, 500])])


def test_bs_tags_pick_columns() -> None:
    led = _bs_columns_ledger()
    assert led.value_at("cash", "bs_current") == 300
    assert led.value_at("cash", "bs_prior_same") == 250  # 114-06-30 在欄 2
    assert led.value_at("cash", "bs_prior_fy_end") == 200  # 114-12-31 在欄 1


def test_bs_columns_map_by_label_order_per_contract() -> None:
    # 契約：bs_prior_same 對欄 1、bs_prior_fy_end 對欄 2 → 以 column_periods 順序決定
    led = _h1([_row("bs", "cash", 300, 200, [300, 200, 250])],
              column_periods={"bs": ["115-06-30", "114-06-30", "114-12-31"], "is": [], "cf": []})
    assert [led.value_at("cash", t) for t in ("bs_current", "bs_prior_same", "bs_prior_fy_end")] == [300, 200, 250]


def test_is_flow_prior() -> None:
    assert _bs_columns_ledger().value_at("revenue", "flow_prior") == 500
    assert _bs_columns_ledger().value_at("revenue", "flow_current") == 600


def test_empty_columns_fall_back_to_current_prior() -> None:
    for basis in ("H1", "other"):
        led = _h1([_row("bs", "cash", 10, 20, []), _row("is", "revenue", 30, 40, [])], basis=basis)
        assert led.value_at("cash", "bs_current") == 10
        assert led.value_at("revenue", "flow_current") == 30
        assert led.value_at("cash", "bs_prior_same") == 20
        assert led.value_at("cash", "bs_prior_fy_end") == 20
        assert led.value_at("revenue", "flow_prior") == 40


def test_new_field_defaults() -> None:
    led = StatementLedger(unit="", period_current="", period_prior="", rows=[], checks=[], unmapped_labels=[])
    assert led.basis == "other"
    assert led.periods == dict.fromkeys(_TAGS)
    assert led.days == {"current": None, "prior": None}
    assert led.assurance is None


def test_none_cell_is_zero_and_missing_key_is_none() -> None:
    led = _h1([_row("bs", "cash", 1, None, [1, None, None])])
    assert led.value_at("cash", "bs_prior_same") == 0.0
    assert led.value_at("nope", "bs_current") is None


def test_boundaries_return_none() -> None:
    led = _bs_columns_ledger()
    assert led.value_at("cash", "flow_current") is None  # bs 列配 flow tag
    assert led.value_at("revenue", "bs_current") is None
    no_label = _h1([_row("bs", "cash", 1, 2, [1, 2, 3])],
                   periods={**_bs_columns_ledger().periods, "bs_prior_fy_end": None})
    assert no_label.value_at("cash", "bs_prior_fy_end") is None
    short = _h1([_row("bs", "cash", 1, 2, [1])])  # 欄索引 2 越界
    assert short.value_at("cash", "bs_prior_same") is None
