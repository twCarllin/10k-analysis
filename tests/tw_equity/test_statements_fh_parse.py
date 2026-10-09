"""金控（group == "fh"）三表解析分流（fh-schema Spec §2.1／§2.5；task 1.2）。

契約 row：
  P1: 2881 BS p8 並排頁 fh → 左右兩半皆解析出列（≥25 列），total_assets／total_liabilities 皆有值
  P2: 2881 IS `41000 利息收入` fh → row.code=="41000"、金額欄不含 41000；`51000 減：利息費用` → interest_expense、label 保留原文
  P3: 2886 BS 4 欄含 `(重編後)` fh → column_periods["bs"] 4 欄、current 115-06-30、prior 114-12-31
  P4: ledger.schema：fh → "fh"、其餘 → "industrial"（進 to_dict）
  P5: [邊界] group 非 fh → 5 位數 41000 不剝除（無 code=="41000" 的列）
  P6: [組合] group=="fh" × 工業 fixture → 不報錯、schema=="fh"、4 位數代碼照舊剝除（3653 年度表無代碼欄，代碼部分改由有代碼的半年報 fixture 驗）
  P7: 工業回歸 → 3653 FY＋2059／2308 H1 的 rows／checks／unmapped_labels 與 industrial_snapshot.json 逐值相同
fixture：fh_statements_pages.json（依據 make_fh_statements_fixture.py；PDF 檔名與頁碼見各區塊 `_source`）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.tw_equity import pdf_doc  # noqa: E402
from runtime.tw_equity.doc_anchor import FS_HEADING_ANCHORS, PageRange, find_heading_sections  # noqa: E402
from runtime.tw_equity.statements import extract_statements, map_key  # noqa: E402

_FIX = ROOT / "tests/fixtures/tw_equity"
_FH = json.loads((_FIX / "fh_statements_pages.json").read_text(encoding="utf-8"))
_SNAP = json.loads((_FIX / "industrial_snapshot.json").read_text(encoding="utf-8"))
_H1 = json.loads((_FIX / "fs_h1_pages.json").read_text(encoding="utf-8"))


def _anchors(raw: dict) -> dict:
    return {k: (PageRange(*r) if r else None) for k, r in raw.items()}


def _ledger(ticker: str, group: str | None):
    entry = _FH[ticker]
    return extract_statements(pdf_doc.from_json(entry["doc"]), _anchors(entry["fs_anchors"]), group=group)


@pytest.fixture(scope="module")
def led_2881():
    return _ledger("2881", "fh")


@pytest.fixture(scope="module")
def led_2886():
    return _ledger("2886", "fh")


@pytest.fixture(scope="module")
def doc_3653():
    return pdf_doc.from_json(json.loads((_FIX / "fs_3653_pages.json").read_text(encoding="utf-8")))


def _bs(led):
    return [r for r in led.rows if r.statement == "bs"]


# P1
def test_2881_side_by_side_bs_both_halves_parsed(led_2881) -> None:
    bs = _bs(led_2881)
    assert len(bs) >= 25
    by_key = {r.key: r for r in bs if r.key}
    assert by_key["total_assets"].current is not None  # 左半
    assert by_key["total_liabilities"].current is not None  # 右半
    assert by_key["total_assets"].current == by_key["total_liabilities_and_equity"].current  # 左右兩半 4 欄金額對得上


# P2
def test_2881_is_five_digit_code_stripped_and_less_prefix_mapped(led_2881) -> None:
    is_rows = {r.code: r for r in led_2881.rows if r.statement == "is" and r.code}
    inc = is_rows["41000"]
    assert inc.label == "利息收入"
    assert inc.key == "interest_income"
    assert 41000 not in inc.columns
    assert inc.columns[2:] == [176312654.0, 148923921.0]  # IS 4 欄的後兩欄（115-01-01~06-30、114-01-01~06-30）
    exp = is_rows["51000"]
    assert exp.key == "interest_expense"
    assert exp.label.startswith("減")  # label 保留原文，只在對照前移除前綴
    assert map_key("is", "減：利息費用", None) is None  # 預設 schema（工業）不認得
    assert map_key("is", "減：利息費用", None, "fh") == "interest_expense"


# P3
def test_2886_bs_four_columns_with_restated_header(led_2886) -> None:
    cols = led_2886.column_periods["bs"]
    assert cols == ["115-06-30", "114-12-31", "114-06-30", "114-01-01"]
    assert cols[led_2886.current_col["bs"]] == "115-06-30"
    assert cols[led_2886.prior_col["bs"]] == "114-12-31"


# P4
def test_ledger_schema_value(led_2881) -> None:
    assert led_2881.schema == "fh"
    assert led_2881.to_dict()["schema"] == "fh"
    assert _ledger("2881", None).schema == "industrial"
    assert _ledger("2881", "industrial").to_dict()["schema"] == "industrial"


# P5
def test_non_fh_keeps_five_digit_code_as_before() -> None:
    for group in (None, "industrial"):
        led = _ledger("2881", group)
        assert not any(r.code == "41000" for r in led.rows)
        assert not any(r.statement == "is" and r.key == "interest_income" for r in led.rows)
        assert len(_bs(led)) < 25  # 並排頁 5 位數代碼不認得 → 保持舊行為（7 列）


# P6
def test_fh_on_industrial_fy_fixture_no_error(doc_3653) -> None:
    anchors = find_heading_sections(doc_3653, FS_HEADING_ANCHORS, required=set())
    fh = extract_statements(doc_3653, anchors, group="fh")
    assert fh is not None and fh.schema == "fh"
    assert {r.statement for r in fh.rows} == {"bs", "is", "cf"}


@pytest.mark.parametrize("ticker", ["2308", "1303"])  # 3653 年度表無代碼欄；以有 4 位數代碼的半年報（1303 為並排）驗證
def test_fh_on_industrial_h1_keeps_four_digit_codes(ticker: str) -> None:
    e = _H1[ticker]
    doc = pdf_doc.from_json(e["doc"])
    fh = extract_statements(doc, _anchors(e["fs_anchors"]), group="fh")
    ind = extract_statements(doc, _anchors(e["fs_anchors"]))
    assert fh.schema == "fh"
    codes = [(r.statement, r.code) for r in fh.rows if r.code]
    assert codes and all(len(c) == 4 for _, c in codes)
    assert codes == [(r.statement, r.code) for r in ind.rows if r.code]


# P7
def _snap_view(led) -> dict:
    d = led.to_dict()
    return json.loads(json.dumps({k: d[k] for k in ("rows", "checks", "unmapped_labels")}))


def _snap_ref(name: str) -> dict:
    return {k: _SNAP[name][k] for k in ("rows", "checks", "unmapped_labels")}


def test_industrial_snapshot_3653_fy(doc_3653) -> None:
    anchors = find_heading_sections(doc_3653, FS_HEADING_ANCHORS, required=set())
    assert _snap_view(extract_statements(doc_3653, anchors)) == _snap_ref("3653_FY")


@pytest.mark.parametrize("ticker", ["2059", "2308"])
def test_industrial_snapshot_h1(ticker: str) -> None:
    e = _H1[ticker]
    led = extract_statements(pdf_doc.from_json(e["doc"]), _anchors(e["fs_anchors"]))
    assert _snap_view(led) == _snap_ref(f"{ticker}_H1")


# ── item 1.6：金控解析修正（②–⑤ 只在 group=="fh" 啟用） ──────────────────────────
#   Q2: `4xxxx 淨收益` 的 4xxxx 是代碼 → 2882／2887 有 net_revenue 列；非 fh 不啟用
#   Q3: 雙行 IS／BS 表頭（第一行上年、第二行本年）→ column_periods 與資料欄序一致（2882、2887）
#   Q4: 附註殘片前綴 `(十四)及八)負債總計` 剝除 → 2891 total_liabilities 兩期有值
#   Q5: IS 歸屬區段變體與「本公司業主」對到 net_income_parent／nci；非 fh 不變


def _is_key(led, key):
    return next(r for r in led.rows if r.statement == "is" and r.key == key)


@pytest.mark.parametrize("ticker", ["2882", "2887"])
def test_q2_xxxx_code_net_revenue_row_parsed(ticker) -> None:
    row = _is_key(_ledger(ticker, "fh"), "net_revenue")
    assert row.code == "4xxxx"
    assert row.label == "淨收益"
    assert row.current is not None and row.prior is not None


def test_q2_non_fh_does_not_recognise_xxxx_code() -> None:
    assert not any(r.key == "net_revenue" for r in _ledger("2882", None).rows)


@pytest.mark.parametrize("ticker", ["2882", "2887"])
def test_q3_two_line_header_is_periods_match_data_order(ticker) -> None:
    led = _ledger(ticker, "fh")
    cols = led.column_periods["is"]
    assert cols == ["115-04-01~115-06-30", "114-04-01~114-06-30", "115-01-01~115-06-30", "114-01-01~114-06-30"]
    assert cols[led.current_col["is"]] == "115-01-01~115-06-30"
    assert cols[led.prior_col["is"]] == "114-01-01~114-06-30"
    # 資料欄序驗證：利息收入第 3 欄（H1 本年）> 第 4 欄對不上時 current 會取到上年
    assert _is_key(led, "interest_income").current == _is_key(led, "interest_income").columns[2]


def test_q3_2882_two_line_header_bs_current_first() -> None:
    led = _ledger("2882", "fh")
    assert led.column_periods["bs"] == ["115-06-30", "114-12-31", "114-06-30", "114-01-01"]


def test_q3_one_line_header_order_untouched() -> None:
    assert _ledger("2881", "fh").column_periods["is"] == [
        "115-04-01~115-06-30", "114-04-01~114-06-30", "115-01-01~115-06-30", "114-01-01~114-06-30"
    ]


def test_q4_2891_note_fragment_stripped_total_liabilities_mapped() -> None:
    row = next(r for r in _ledger("2891", "fh").rows if r.key == "total_liabilities")
    assert row.label == "負債總計"
    assert row.current == 9521518922.0 and row.prior == 8783337458.0


@pytest.mark.parametrize("section", [
    "淨利(淨損)歸屬於", "淨利(損)歸屬於", "本期稅後淨利(損失)歸屬於", "本期淨利歸屬於", "淨利歸屬於",
])
def test_q5_fh_net_income_section_variants(section) -> None:
    assert map_key("is", "母公司業主", section, "fh") == "net_income_parent"
    assert map_key("is", "非控制權益", section, "fh") == "net_income_nci"
    assert map_key("is", "本公司業主", section, "fh") == "net_income_parent"


def test_q5_fh_tci_section_variants() -> None:
    assert map_key("is", "本公司業主", "綜合損益總額歸屬於", "fh") == "tci_parent"
    assert map_key("is", "非控制權益", "本期稅後綜合損益總額歸屬於", "fh") == "tci_nci"


def test_q5_non_fh_unchanged() -> None:
    assert map_key("is", "本公司業主", "淨利歸屬於") is None
    assert map_key("is", "母公司業主", "淨利(損)歸屬於") is None
    assert map_key("is", "母公司業主", "淨利歸屬於") == "net_income_parent"
