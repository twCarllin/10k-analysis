"""Producer-shaped fixtures for inventory and local source adapters."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import fitz
import pytest

from runtime.industry_map.adapters import normalize
from runtime.industry_map.inventory import inventory, write_inventory
from runtime.industry_map.pilot import build_pilot
from runtime.tw_equity.pdf_doc import load_pdf
from runtime.tw_equity.metrics import MetricResult, MetricsPack
from runtime.tw_equity.statements import CrossCheck, StatementLedger, StatementRow
from runtime.tw_equity.tables import TablesBundle


@pytest.fixture
def producer_records():
    # 依據 runtime/tw_equity/statements.py:34-52、74-99：使用實際帳本 producer。
    ledger = StatementLedger(
        unit="新台幣仟元",
        period_current="2025",
        period_prior="2024",
        rows=[
            StatementRow(
                statement="is",
                section=None,
                label="營收",
                key="revenue",
                note=None,
                current=10,
                prior=None,
                current_pct=None,
                prior_pct=None,
                page=7,
                line_idx=3,
            )
        ],
        checks=[CrossCheck("收入", "current", 10, 11, False)],
        unmapped_labels=[],
        basis="H1",
        periods={
            "flow_current": "2025-01-01~2025-06-30",
            "flow_prior": "2024-01-01~2024-06-30",
        },
    )
    # 依據 runtime/tw_equity/metrics.py:43-59、140-170：簡略年度與公式輸出。
    metrics = MetricsPack(
        "2025",
        "2024",
        metrics=[
            MetricResult(
                "fcf",
                "自由現金流",
                "cfo + capex",
                "仟元",
                "current",
                6,
                {"cfo": 8, "capex": -2},
            )
        ],
        basis="H1",
    )
    # 依據 runtime/tw_equity/tables.py:1509-1582：實際 bundle.to_dict 輸出。
    bundle = TablesBundle(
        fin_position=None,
        fin_performance=None,
        customers_sales=None,
        customers_purchase=None,
        production_sales=None,
        expense_nature=None,
        inventory=None,
        cost_detail_cogs=None,
        cost_detail_mfg=None,
        cost_detail_opex=None,
        consolidated_key_lines={},
        parent_key_lines={},
        parent_cost_coverage=None,
        missing_tables=[],
        unit_notes={},
        statements=ledger,
        metrics=metrics,
    )
    # 依據 runtime/tw_equity/report.py:846-872：TW raw 無公司 metadata。
    raw = {
        "bundle": bundle.to_dict(),
        "skill_results": {},
        "eval_results": {},
        "anchors_summary": {},
        "garbled_pages": [],
        "ocr_pages": [],
        "ocr_checks": [],
        "prior": None,
        "cross_year": None,
        "cross_year_compare": None,
    }
    # 依據 runtime/tw_equity/batch.py:48-55、76-111：batch 不輸出 unit 或逐列 page。
    batch = {
        "schema_version": 2,
        "ticker": "1234",
        "company_name": "甲公司",
        "group": "industrial",
        "fs_period": "H12025",
        "status": "ok",
        "error": None,
        "elapsed_seconds": 1,
        "inputs": None,
        "basis": "H1",
        "assurance": "reviewed",
        "periods": ledger.periods,
        "checks": {"passed": 0, "failed": 1, "none": 0, "not_passed": ["收入/current"]},
        "n_unmapped": 0,
        "values": {"revenue": {"current": 10, "prior": None}},
        "metrics": {"fcf": {"current": 6, "prior": None}},
        "ttm": None,
        "fy_income_usable": None,
        "bridges": [],
        "schema": "industrial",
        "ifrs17_break": None,
    }
    # 依據 runtime/report_writer.py:1074-1082、skills/us/supply_chain_analysis.md:124-140、skills/us/competitor_mapping.md:54-61。
    us = {
        "results": {
            "supply_chain": {
                "named_suppliers": [
                    {
                        "name": "Real Materials",
                        "material_or_service": "Titanium",
                        "single_source": True,
                        "yoy_status": "existing",
                    },
                    {
                        "name": "Mock Titanium Co.",
                        "material_or_service": "Titanium",
                        "single_source": False,
                        "yoy_status": "new",
                    },
                    {
                        "name": "Mockingbird Industries",
                        "material_or_service": "Parts",
                        "single_source": False,
                        "yoy_status": "existing",
                    },
                    {
                        "name": "$XX",
                        "material_or_service": "",
                        "single_source": False,
                        "yoy_status": "new",
                    },
                    {
                        "name": "Placeholder Co.",
                        "material_or_service": "",
                        "single_source": False,
                        "yoy_status": "new",
                    },
                ]
            },
            "competitor_mapping": {
                "named_competitors": [
                    {
                        "name": "Real Competitor",
                        "ticker": "REAL",
                        "markets": [],
                        "yoy_status": "unchanged",
                        "note": "",
                    }
                ]
            },
            "financial": {"metrics": {"Revenue": [{"year": 2025, "value": 999}]}},
        },
        "eval": {},
        "synthesis": {},
    }
    # 依據 runtime/jp_report_writer.py:855-868：JP 的 four-key raw 與 US 不同。
    jp = {"five_year": {}, "skill_results": {}, "eval_results": {}, "recent_events": []}
    # 依據 runtime/tw_equity/inputs.py:112-153：公司 metadata 由 ticker input 取得。
    metadata = {"ticker": "1234", "company_name": "甲公司", "fs_period": "H12025"}
    return dict(tw_raw=raw, tw_batch=batch, us_raw=us, jp=jp, metadata=metadata)


def test_inventory_known_formats_unknown_period_and_isolation(
    tmp_path, producer_records
):
    root, inputs = tmp_path / "sources", tmp_path / "inputs"
    root.mkdir()
    inputs.mkdir()
    (inputs / "1234.json").write_text(json.dumps(producer_records["metadata"]))
    for filename, key in (
        ("1234_raw.json", "tw_raw"),
        ("batch.json", "tw_batch"),
        ("HWM_raw.json", "us_raw"),
        ("6315_raw.json", "jp"),
    ):
        (root / filename).write_text(json.dumps(producer_records[key]))
    (root / "broken_raw.json").write_text("{")
    (root / "config.json").write_text("{")
    (root / "unknown.json").write_text('{"other": true}')
    result = inventory(root, inputs=inputs)
    assert {item["format"] for item in result["records"]} == {
        "tw_raw",
        "tw_batch",
        "us_raw",
        "jp_unsupported",
    }
    by_id = {item["company_id"]: item for item in result["coverage"]}
    assert len(by_id["company:TW:1234"]["sources"]) == 2
    assert {source["format"] for source in by_id["company:TW:1234"]["sources"]} == {
        "tw_raw",
        "tw_batch",
    }
    assert "period" in by_id["company:US:HWM"]["missing"]
    assert (
        next(item for item in result["records"] if item["ticker"] == "HWM")["period"]
        is None
    )
    assert by_id["company:JP:6315"]["warnings"] == ["unsupported_format"]
    assert all("mtime" not in item for item in result["records"])
    reasons = {warning["reason"] for warning in result["warnings"]}
    assert {"invalid_json", "placeholder", "unsupported_format"} <= reasons
    assert not any(
        item["source"].endswith("config.json") for item in result["warnings"]
    )
    out = root / "generated"
    write_inventory(result, out)
    assert json.loads((out / "inventory.json").read_text()) == result
    markdown = (out / "inventory.md").read_text()
    assert "unknown" in markdown and "甲公司" in markdown and "invalid_json" in markdown
    assert inventory(root, inputs=inputs, exclude=[out]) == result
    assert inventory(root, inputs=inputs) == result


def test_tw_raw_preserves_ledger_metrics_and_json_page_provenance(producer_records):
    result = normalize(
        producer_records["tw_raw"], producer_records["metadata"], "tw.json"
    )
    current, prior, metric = result["observations"]
    assert (
        current["metric"],
        current["value"],
        current["unit"],
        current["currency"],
        current["period"],
        current["basis"],
    ) == ("revenue", 10, "新台幣仟元", "TWD", "2025-01-01~2025-06-30", "H1")
    assert prior["value"] is None and prior["period"] == "2024-01-01~2024-06-30"
    assert (
        metric["value"],
        metric["formula"],
        metric["inputs"],
        metric["unit"],
        metric["period"],
    ) == (6, "cfo + capex", {"cfo": 8, "capex": -2}, "仟元", "2025-01-01~2025-06-30")
    assert current["quality"]["checks"][0]["passed"] is False
    assert result["evidence"][0]["locator"] == {
        "pointer": "/bundle/statements/rows/0/current",
        "source_page": 7,
    }
    assert result["evidence"][2]["locator"] == {
        "pointer": "/bundle/metrics/metrics/0/value"
    }
    assert all(
        item["document"] == "tw.json" and item["source_type"] == "analysis"
        for item in result["evidence"]
    )
    assert "missing_values" in result["coverage"][0]["warnings"]
    # 依據 runtime/tw_equity/statements.py:794及74-99：raw prior用prior_col選欄。
    three_columns = deepcopy(producer_records["tw_raw"])
    ledger = three_columns["bundle"]["statements"]
    ledger["column_periods"]["bs"] = ["115-06-30", "114-12-31", "114-06-30"]
    ledger["current_col"]["bs"], ledger["prior_col"]["bs"] = 0, 1
    ledger["periods"].update(
        bs_current="115-06-30", bs_prior_same="114-06-30", bs_prior_fy_end="114-12-31"
    )
    ledger["rows"][0].update(
        statement="bs", key="cash", current=110, prior=99, columns=[110, 99, 88]
    )
    selected = normalize(
        three_columns, producer_records["metadata"], "three-columns.json"
    )
    assert [
        (item["value"], item["period"])
        for item in selected["observations"]
        if item["metric"] == "cash"
    ] == [(110, "115-06-30"), (99, "114-12-31")]
    incomplete = deepcopy(producer_records["tw_raw"])
    incomplete["bundle"]["statements"]["periods"] = {}
    fallback = normalize(incomplete, producer_records["metadata"], "tw.json")
    assert fallback["observations"][-1]["period"] == "2025"
    assert "complete_period" in fallback["coverage"][0]["missing"]


def test_tw_batch_preserves_basis_pointer_unknown_unit_and_errors(producer_records):
    result = normalize(producer_records["tw_batch"], source_path="batch.json")
    observations = result["observations"]
    assert [item["value"] for item in observations] == [10, None, 6, None]
    assert [item["period"] for item in observations] == [
        "2025-01-01~2025-06-30",
        "2024-01-01~2024-06-30",
    ] * 2
    assert all(
        item["unit"] == "unknown" and item["currency"] is None and item["basis"] == "H1"
        for item in observations
    )
    assert all(item["quality"]["failed"] == 1 for item in observations)
    assert [item["locator"] for item in result["evidence"]] == [
        {"pointer": "/values/revenue/current"},
        {"pointer": "/values/revenue/prior"},
        {"pointer": "/metrics/fcf/current"},
        {"pointer": "/metrics/fcf/prior"},
    ]
    # 依據 runtime/tw_equity/batch.py:33-35、97-105：FH values含四種BS值。
    financial = deepcopy(producer_records["tw_batch"])
    financial.update(schema="fh", group="fh", fh_notes=None, fh_notes_error=None)
    financial["periods"] = dict(
        financial["periods"], bs_current="2025-06-30", bs_prior_same="2024-06-30"
    )
    financial["values"] = {
        key: {"current": 10, "prior": 9}
        for key in (
            "net_interest_income",
            "non_interest_income",
            "net_revenue",
            "provision",
            "total_opex",
            "pretax_income",
            "net_income",
            "net_income_parent",
            "total_assets",
            "total_equity",
            "loans_net",
            "deposits",
        )
    }
    # 依據 runtime/tw_equity/metrics.py:312及batch.py:106-109：比例metrics保留流量期。
    financial["metrics"] = {"cost_income_ratio": {"current": 1, "prior": 2}}
    converted = normalize(financial, source_path="financial-batch.json")
    for key in ("total_assets", "total_equity", "loans_net", "deposits"):
        assert [
            item["period"]
            for item in converted["observations"]
            if item["metric"] == key
        ] == ["2025-06-30", "2024-06-30"], key
    assert [
        item["period"]
        for item in converted["observations"]
        if item["metric"] == "cost_income_ratio"
    ] == ["2025-01-01~2025-06-30", "2024-01-01~2024-06-30"]
    error = deepcopy(producer_records["tw_batch"])
    error.update(
        status="error",
        values=None,
        metrics=None,
        periods=None,
        fs_period=None,
        basis=None,
    )
    failed = normalize(error, source_path="batch.json")
    assert failed["observations"] == []
    assert "batch_error" in failed["coverage"][0]["warnings"]
    assert set(failed["coverage"][0]["missing"]) == {"period", "financial_raw"}


def test_us_pending_relations_placeholders_and_no_llm_finance(producer_records):
    result = normalize(
        producer_records["us_raw"], {"ticker": "HWM", "fs_period": "2025"}, "us.json"
    )
    assert {item["name"] for item in result["entities"]} == {
        "HWM",
        "Real Materials",
        "Mockingbird Industries",
        "Real Competitor",
    }
    assert len(result["relations"]) == 3
    assert all(
        item["status"] == "pending" and item["period"] == "2025"
        for item in result["relations"]
    )
    assert [item["predicate"] for item in result["relations"]] == [
        "supplies_to",
        "supplies_to",
        "competes_with",
    ]
    assert result["relations"][0]["target_id"] == "company:US:HWM"
    assert result["relations"][-1]["target_id"] == "company:US:REAL"
    name_proofs = [
        item
        for item in result["evidence"]
        if item["locator"]["pointer"].endswith("/name")
    ]
    assert [item["locator"]["pointer"] for item in name_proofs] == [
        "/results/supply_chain/named_suppliers/0/name",
        "/results/supply_chain/named_suppliers/2/name",
        "/results/competitor_mapping/named_competitors/0/name",
    ]
    assert [item["quote"] for item in name_proofs] == [
        "Real Materials",
        "Mockingbird Industries",
        "Real Competitor",
    ]
    assert all(item["source_type"] == "analysis" for item in result["evidence"])
    assert result["observations"] == []
    assert "financial_raw" in result["coverage"][0]["missing"]
    assert {item["name"] for item in result["coverage"][0]["excluded"]} == {
        "Mock Titanium Co.",
        "$XX",
        "Placeholder Co.",
    }
    empty = deepcopy(producer_records["us_raw"])
    empty["results"] = {}
    excluded = normalize(empty, {"ticker": "HWM"}, "us.json")
    assert excluded["relations"] == [] and excluded["evidence"] == []
    assert len(excluded["entities"]) == 1
    assert all(
        item["reason"] == "empty_analysis"
        for item in excluded["coverage"][0]["excluded"]
    )


def test_us_attached_xbrl_preserves_original_ytd_and_requires_source(producer_records):
    # 依據 runtime/sec_data_fetcher.py:130-159：SEC companyfacts 的 facts/us-gaap/tag/units。
    facts = {
        "cik": 4281,
        "entityName": "Howmet Aerospace",
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "label": "Net income",
                    "description": "Net income",
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01",
                                "end": "2025-06-30",
                                "val": 123,
                                "accn": "0001",
                                "fy": 2025,
                                "fp": "Q2",
                                "form": "10-Q",
                                "filed": "2025-08-01",
                            },
                            {
                                "end": "2024-12-31",
                                "val": 98,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            },
                        ]
                    },
                }
            }
        },
    }
    metadata = {
        "ticker": "HWM",
        "xbrl_facts": facts,
        "xbrl_source_path": "companyfacts.json",
    }
    result = normalize(producer_records["us_raw"], metadata, "us.json")
    current, unknown = result["observations"]
    assert (
        current["metric"],
        current["value"],
        current["unit"],
        current["currency"],
        current["period"],
        current["basis"],
    ) == ("net_income", 123, "USD", "USD", "2025-01-01~2025-06-30", "10-Q:Q2")
    assert current["inputs"] == {
        "start": "2025-01-01",
        "end": "2025-06-30",
        "fp": "Q2",
        "form": "10-Q",
    }
    assert (
        unknown["value"] == 98
        and unknown["period"] is None
        and unknown["basis"] is None
    )
    proof = next(
        item for item in result["evidence"] if item["id"] == current["evidence_ids"][0]
    )
    assert (
        proof["document"] == "companyfacts.json" and proof["source_type"] == "primary"
    )
    assert proof["locator"] == {
        "pointer": "/facts/us-gaap/NetIncomeLoss/units/USD/0/val"
    }
    assert "financial_raw" not in result["coverage"][0]["missing"]
    # 依據 runtime/sec_data_fetcher.py:130-159：同期間facts可由不同filed重複揭露。
    amended = deepcopy(metadata)
    old = dict(
        facts["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][0],
        start="2020-12-27",
        end="2021-12-25",
        fp="FY",
        form="10-K",
        val=29991000000,
        filed="2022-01-27",
    )
    newest = dict(old, val=29456000000, filed="2024-01-26")
    amended["xbrl_facts"]["facts"]["us-gaap"] = {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [old, newest]}}
    }
    entries = amended["xbrl_facts"]["facts"]["us-gaap"][
        "NetCashProvidedByUsedInOperatingActivities"
    ]["units"]["USD"]
    for ordered in ([old, newest], [newest, old]):
        entries[:] = ordered
        checked = normalize(producer_records["us_raw"], amended, "us.json")
        assert len(checked["observations"]) == 1
        selected = checked["observations"][0]
        assert (
            selected["metric"],
            selected["value"],
            selected["period"],
            selected["quality"]["filed"],
        ) == ("cfo", 29456000000, "2020-12-27~2021-12-25", "2024-01-26")
        selected_proof = next(
            item
            for item in checked["evidence"]
            if item["id"] == selected["evidence_ids"][0]
        )
        latest_index = ordered.index(newest)
        assert (
            selected_proof["locator"]["pointer"]
            == f"/facts/us-gaap/NetCashProvidedByUsedInOperatingActivities/units/USD/{latest_index}/val"
        )
        assert selected_proof["quote"] == "29456000000"
    # 同值不需要猜重編值，即使日期未知仍保留原值。
    entries[:] = [old, dict(old, filed=None)]
    identical = normalize(producer_records["us_raw"], amended, "us.json")[
        "observations"
    ]
    assert len(identical) == 1 and identical[0]["value"] == 29991000000
    for invalid in (None, "2024-1-26", "2024-02-30", "not-a-date", "20240126"):
        entries[:] = [dict(old, filed=invalid), newest]
        checked = normalize(producer_records["us_raw"], amended, "us.json")
        unresolved = checked["observations"][0]
        assert (
            unresolved["value"] is None
            and unresolved["quality"]["conflict"] == "unresolved"
        ), invalid
        candidates = unresolved["quality"]["candidates"]
        assert [(item["value"], item["filed"]) for item in candidates] == [
            (29991000000, invalid),
            (29456000000, "2024-01-26"),
        ]
        proofs = {item["id"]: item for item in checked["evidence"]}
        for index, candidate in enumerate(candidates):
            assert candidate["evidence_id"] in unresolved["evidence_ids"]
            assert candidate["source"] == {
                "document": "companyfacts.json",
                "locator": {
                    "pointer": f"/facts/us-gaap/NetCashProvidedByUsedInOperatingActivities/units/USD/{index}/val"
                },
            }
            assert proofs[candidate["evidence_id"]]["quote"] == str(candidate["value"])
    entries[:] = [dict(old, filed="2024-01-26"), newest]
    same_day = normalize(producer_records["us_raw"], amended, "us.json")[
        "observations"
    ][0]
    assert same_day["value"] is None and same_day["quality"]["conflict"] == "unresolved"
    assert {item["value"] for item in same_day["quality"]["candidates"]} == {
        29991000000,
        29456000000,
    }
    metadata.pop("xbrl_source_path")
    missing = normalize(producer_records["us_raw"], metadata, "us.json")
    assert (
        missing["observations"] == []
        and "financial_raw" in missing["coverage"][0]["missing"]
    )


def _write_local_pdf(path, pages):
    # 依據 runtime/tw_equity/pdf_doc.py:183-247：真實 PDF 邊界，無內部函式 mock。
    with fitz.open() as document:
        for lines in pages:
            page = document.new_page(width=1100, height=842)
            for index, line in enumerate(lines):
                page.insert_text(
                    (30, 40 + index * 22), line, fontname="china-t", fontsize=11
                )
        document.save(path)


def _draw_t8(page, y, kind, prior_name, current_name, *, labels=("113年度", "114年度")):
    # 依據 runtime/tw_equity/tables.py:349-443：年度並排9欄，銷貨/進貨欄頭。
    rows = [
        ["排名", labels[0], "", "", "", labels[1], "", "", ""],
        ["", kind, "金額", "比率", "關係", kind, "金額", "比率", "關係"],
        ["1", prior_name, "10", "10", "無", current_name, "20", "20", "無"],
        ["2", "RealCo", "30", "30", "無", "RealCo", "40", "40", "無"],
    ]
    names = [
        "A",
        "A公司",
        "A集團",
        "T2",
        "甲",
        "甲公司",
        "丙公司",
        "客戶1",
        "3M",
        "南亞塑膠公司",
        "甲山林公司",
        "100",
        "13,371,181",
        "114年度",
        "名稱",
        "進貨淨額",
        "與發行人",
        "之關係",
        "(四)最近二年度...",
        "合計",
    ]
    rows.extend(
        [str(index + 3), name, "1", "1", "無", name, "2", "2", "無"]
        for index, name in enumerate(names)
    )
    height = 13 * len(rows)
    for column in range(10):
        page.draw_line((30 + column * 110, y), (30 + column * 110, y + height))
    for row in range(len(rows) + 1):
        page.draw_line((30, y + row * 13), (1020, y + row * 13))
    for row_index, row in enumerate(rows):
        for column, text in enumerate(row):
            page.insert_text(
                (34 + column * 110, y + row_index * 13 + 10),
                text,
                fontname="china-t",
                fontsize=7,
            )


@pytest.fixture
def pilot_inputs(tmp_path):
    inputs = tmp_path / "tw_equity_inputs"
    inputs.mkdir()
    ar, fs = tmp_path / "annual.pdf", tmp_path / "financial.pdf"
    # 依據 runtime/tw_equity/doc_anchor.py:47-55：業務、市場、客戶、MDNA及風險錨點。
    _write_local_pdf(
        ar,
        [
            ["114年度年報"],
            [
                "一、業務內容",
                "本公司製造半導體設備。",
                "公司目前之商品(服務)項目",
                "晶圓探針卡",
            ],
            ["二、市場及產銷概況", "主要進銷貨客戶"],
            ["財務狀況及財務績效之檢討分析"],
            ["風險事項分析評估", "競爭者製造半導體材料。"],
        ],
    )
    with fitz.open(ar) as document:
        _draw_t8(document[2], 110, "進貨廠商", "甲廠商", "甲廠商")
        _draw_t8(document[2], 450, "銷貨客戶", "Ａ客戶", "Ａ客戶")
        document.saveIncr()
    # 依據 runtime/tw_equity/statements.py:34-99及doc_anchor.py:313-319：三表原始行/完整H1期間。
    _write_local_pdf(
        fs,
        [
            [
                "甲公司",
                "合併資產負債表",
                "單位：新台幣仟元",
                "114年6月30日 113年6月30日",
                "資產",
                "流動資產",
                "現金及約當現金 $ 100 50 $ 90 45",
                "資產總計 $ 200 100 $ 200 100",
            ],
            [
                "甲公司",
                "合併綜合損益表",
                "單位：新台幣仟元",
                "114年1月1日至6月30日 113年1月1日至6月30日",
                "代碼 項目 金額 比率 金額 比率",
                "4000 營業收入 $ 100 100 $ 90 100",
                "5000 營業成本 ( 60 ) ( 60 ) ( 50 ) ( 55 )",
                "營業毛利 40 40 40 45",
            ],
            [
                "甲公司",
                "合併現金流量表",
                "單位：新台幣仟元",
                "114年1月1日至6月30日 113年1月1日至6月30日",
                "營業活動",
                "營業活動之淨現金流入 10 9",
                "投資活動",
                "取得不動產、廠房及設備 ( 2 ) ( 1 )",
            ],
        ],
    )
    # 依據 runtime/tw_equity/inputs.py:24-43、92-124：年度獨立於fs_period。
    metadata = dict(
        company_name="甲公司",
        fiscal_year=2025,
        annual_report_path="annual.pdf",
        consolidated_fs_path="financial.pdf",
        fs_period="H12025",
        group="industrial",
    )
    for ticker in ("2360", "2404"):
        (inputs / f"{ticker}.json").write_text(
            json.dumps(dict(metadata, ticker=ticker)), encoding="utf-8"
        )
    blank = tmp_path / "blank.pdf"
    _write_local_pdf(blank, [[]])
    (inputs / "6223.json").write_text(
        json.dumps(
            dict(
                metadata,
                ticker="6223",
                annual_report_path="blank.pdf",
                consolidated_fs_path=None,
            )
        )
    )
    unrelated = tmp_path / "unrelated.pdf"
    _write_local_pdf(unrelated, [["一、業務內容", "本公司主要業務為旅遊。"]])
    (inputs / "6515.json").write_text(
        json.dumps(
            dict(
                metadata,
                ticker="6515",
                annual_report_path="unrelated.pdf",
                consolidated_fs_path=None,
            )
        )
    )
    return dict(
        inputs=inputs,
        ar=ar,
        fs=fs,
        cache=tmp_path / "pdf-cache",
        out=tmp_path / "pilot",
    )


def test_local_pilot_pdf_t8_roles_finance_and_failure_isolation(pilot_inputs):
    fixture = pilot_inputs
    result = build_pilot(
        fixture["inputs"],
        ["2360", "2404", "6139", "6223", "6515"],
        fixture["out"],
        cache_dir=fixture["cache"],
    )
    roles = [
        item for item in result["roles"] if item["company_id"] == "company:TW:2360"
    ]
    assert {item["product"] for item in roles} == {"半導體設備", "探針卡"}
    assert all(
        item["status"] == "pending" for item in result["roles"] + result["relations"]
    )
    documents = {
        str(path.resolve()): load_pdf(path, cache_dir=fixture["cache"])
        for path in (fixture["ar"], fixture["fs"])
    }
    primary = [
        proof for proof in result["evidence"] if proof["source_type"] == "primary"
    ]
    analysis = [
        proof for proof in result["evidence"] if proof["source_type"] == "analysis"
    ]
    assert primary and analysis
    for proof in analysis:
        assert Path(proof["document"]).is_file()
    for proof in primary:
        page = next(
            page
            for page in documents[proof["document"]].pages
            if page.number == proof["locator"]["page"]
        )
        assert proof["quote"] in page.text
        assert (
            proof["document_hash"]
            == hashlib.sha256(Path(proof["document"]).read_bytes()).hexdigest()
        )
    evidence_by_id = {item["id"]: item for item in result["evidence"]}
    assert all(
        evidence_by_id[identifier]["locator"]["page"] == 2
        for item in roles
        for identifier in item["evidence_ids"]
    )
    assert all(
        evidence_by_id[identifier]["period"] == "2025-01-01~2025-12-31"
        for item in roles
        for identifier in item["evidence_ids"]
    )
    anonymous = [item for item in result["entities"] if item["owner_id"]]
    assert len(anonymous) == 40 and len({item["id"] for item in anonymous}) == 40
    assert {item["owner_id"] for item in anonymous} == {
        "company:TW:2360",
        "company:TW:2404",
    }
    for name in ("A", "A公司", "A集團", "T2", "甲", "甲公司", "丙公司", "客戶1"):
        scoped = [item for item in anonymous if item["name"] == name]
        assert len(scoped) == 4 and {item["owner_id"] for item in scoped} == {
            "company:TW:2360",
            "company:TW:2404",
        }, name
    assert len([item for item in result["entities"] if item["name"] == "RealCo"]) == 1
    for name in ("3M", "南亞塑膠公司", "甲山林公司"):
        named = [item for item in result["entities"] if item["name"] == name]
        assert len(named) == 1 and named[0]["owner_id"] is None, name
    entities = {item["id"]: item for item in result["entities"]}
    for relationship in result["relations"]:
        assert relationship["predicate"] == "supplies_to"
        assert relationship["period"] in {
            "2024-01-01~2024-12-31",
            "2025-01-01~2025-12-31",
        }
    purchase = [
        item
        for item in result["relations"]
        if entities[item["source_id"]]["name"] == "甲廠商"
    ]
    sales = [
        item
        for item in result["relations"]
        if entities[item["target_id"]]["name"] == "A客戶"
    ]
    assert purchase and sales
    for relationship in purchase:
        assert (
            relationship["target_id"] == entities[relationship["source_id"]]["owner_id"]
        )
    for relationship in sales:
        assert (
            relationship["source_id"] == entities[relationship["target_id"]]["owner_id"]
        )
    revenues = [
        item
        for item in result["observations"]
        if item["company_id"] == "company:TW:2360" and item["metric"] == "revenue"
    ]
    assert {item["value"] for item in revenues} == {100, 90}
    assert all("~" in item["period"] and item["basis"] == "H1" for item in revenues)
    coverage_by_id = {item["company_id"]: item for item in result["coverage"]}
    invalid = {
        "100",
        "13,371,181",
        "114年度",
        "名稱",
        "進貨淨額",
        "與發行人",
        "之關係",
        "(四)最近二年度...",
        "合計",
    }
    assert invalid.isdisjoint(item["name"] for item in result["entities"])
    excluded = coverage_by_id["company:TW:2360"]["excluded"]
    assert {item["name"] for item in excluded} == invalid
    for item in excluded:
        assert item["reason"] == "invalid_counterparty"
        assert item["pointer"].startswith("/bundle/customers_") and item[
            "pointer"
        ].endswith("/name")
        original = json.loads(
            Path(coverage_by_id["company:TW:2360"]["sources"][0]["source"]).read_text()
        )
        for token in item["pointer"].split("/")[1:]:
            original = (
                original[int(token)] if isinstance(original, list) else original[token]
            )
        assert original == item["name"]
    assert "pilot_extraction" in coverage_by_id["company:TW:6139"]["missing"]
    assert "pdf_needs_manual_review" in coverage_by_id["company:TW:6223"]["warnings"]
    assert "business_evidence" in coverage_by_id["company:TW:6515"]["missing"]
    assert "t8_original_text_missing" in coverage_by_id["company:TW:2360"]["warnings"]
    for relationship in sales:
        assert all(
            evidence_by_id[identifier]["source_type"] == "analysis"
            for identifier in relationship["evidence_ids"]
        )
    source_files = sorted((fixture["out"] / "sources").glob("*.json"))
    original_bytes = {path: path.read_bytes() for path in source_files}
    assert (
        build_pilot(
            fixture["inputs"],
            ["2360", "2404", "6139", "6223", "6515"],
            fixture["out"],
            cache_dir=fixture["cache"],
        )
        == result
    )
    assert {path: path.read_bytes() for path in source_files} == original_bytes
    with fitz.open(fixture["ar"]) as document:
        for index, text in enumerate(
            [
                "目前之商品項目",
                "晶圓代工",
                "銅箔",
                "基板",
                "IC載板",
                "積體電路載板",
                "廠務工程",
                "無塵室",
                "半導體測試",
                "分選設備",
                "檢測設備",
            ]
        ):
            document[1].insert_text(
                (30, 300 + index * 18), text, fontname="china-t", fontsize=11
            )
        document.saveIncr()
    # 依據 runtime/tw_equity/statements.py:34-99：同ticker新期間/數值由真實PDF重解析。
    next_fs = fixture["fs"].with_name("financial-v2.pdf")
    old_fs = load_pdf(fixture["fs"], cache_dir=fixture["cache"])
    _write_local_pdf(
        next_fs,
        [
            [
                line.replace("114年", "115年")
                .replace("113年", "114年")
                .replace("4000 營業收入 $ 100 100", "4000 營業收入 $ 150 100")
                for line in page.text.splitlines()
            ]
            for page in old_fs.pages
        ],
    )
    input_path = fixture["inputs"] / "2360.json"
    next_metadata = json.loads(input_path.read_text())
    next_metadata.update(consolidated_fs_path=next_fs.name, fs_period="H12026")
    input_path.write_text(json.dumps(next_metadata))
    updated = build_pilot(
        fixture["inputs"], ["2360"], fixture["out"], cache_dir=fixture["cache"]
    )
    assert {
        "晶圓代工",
        "銅箔基板",
        "IC載板",
        "積體電路載板",
        "廠務工程",
        "無塵室",
        "半導體測試",
        "分選設備",
        "檢測設備",
    } <= {item["product"] for item in updated["roles"]}
    updated_page = load_pdf(fixture["ar"], cache_dir=fixture["cache"]).pages[1]
    role_ids = {
        identifier for item in updated["roles"] for identifier in item["evidence_ids"]
    }
    role_proofs = [proof for proof in updated["evidence"] if proof["id"] in role_ids]
    assert role_proofs and all(item["status"] == "pending" for item in updated["roles"])
    assert all(proof["quote"] in updated_page.text for proof in role_proofs)
    assert any("銅箔\n基板" in proof["quote"] for proof in role_proofs)
    assert (
        len(list((fixture["out"] / "sources").glob("*.json"))) == len(source_files) + 1
    )
    assert {path: path.read_bytes() for path in source_files} == original_bytes

    new_revenues = [
        item for item in updated["observations"] if item["metric"] == "revenue"
    ]
    assert {(item["period"], item["value"]) for item in new_revenues} == {
        ("115-01-01~115-06-30", 150),
        ("114-01-01~114-06-30", 90),
    }
    assert {item["id"] for item in new_revenues} != {item["id"] for item in revenues}
    proofs = {item["id"]: item for item in result["evidence"] + updated["evidence"]}
    for observation in revenues + new_revenues:
        proof = proofs[observation["evidence_ids"][0]]
        original = json.loads(Path(proof["document"]).read_text())
        for token in proof["locator"]["pointer"].split("/")[1:]:
            original = (
                original[int(token)] if isinstance(original, list) else original[token]
            )
        assert original == observation["value"]
    assert (
        build_pilot(
            fixture["inputs"], ["2360"], fixture["out"], cache_dir=fixture["cache"]
        )
        == updated
    )
    assert (
        len(list((fixture["out"] / "sources").glob("*.json"))) == len(source_files) + 1
    )


@pytest.mark.parametrize("unknown_year", [False, True])
def test_pilot_t8_actual_sales_first_direction_and_unknown_scope(
    pilot_inputs, unknown_year
):
    fixture = pilot_inputs
    # 依據 runtime/tw_equity/tables.py:355-443/1661-1675：第一張含關鍵字表會被兩種kind選取。
    # 銷貨表資料列含進貨淨額；保留真正順序觸發，不mock producer。
    alternate = fixture["ar"].with_name("sales-first.pdf")
    _write_local_pdf(
        alternate,
        [
            ["114年度年報"],
            ["一、業務內容", "本公司製造半導體設備。"],
            ["二、市場及產銷概況", "主要進銷貨客戶"],
            ["財務狀況及財務績效之檢討分析"],
        ],
    )
    labels = ("前期年度", "本期年度") if unknown_year else ("113年度", "114年度")
    with fitz.open(alternate) as document:
        _draw_t8(document[2], 110, "銷貨客戶", "A", "A", labels=labels)
        _draw_t8(document[2], 450, "進貨廠商", "甲廠商", "甲廠商", labels=labels)
        document.saveIncr()
    for ticker in ("2360", "2404"):
        path = fixture["inputs"] / f"{ticker}.json"
        metadata = json.loads(path.read_text())
        metadata["annual_report_path"] = alternate.name
        path.write_text(json.dumps(metadata))
    result = build_pilot(
        fixture["inputs"], ["2360", "2404"], fixture["out"], cache_dir=fixture["cache"]
    )
    entities = {item["id"]: item for item in result["entities"]}
    assert result["relations"]
    assert all(
        item["source_id"] in {"company:TW:2360", "company:TW:2404"}
        for item in result["relations"]
    ), "sales-first must not create reverse purchases"
    for coverage in result["coverage"]:
        assert "t8_direction" in coverage["missing"]
        warnings = [
            item
            for item in coverage["warnings"]
            if isinstance(item, dict)
            and item.get("reason") == "t8_direction_unverified"
        ]
        assert warnings
        proofs = {item["id"]: item for item in result["evidence"]}
        for warning in warnings:
            assert warning["pointer"].startswith("/bundle/customers_purchase/")
            assert Path(warning["source"]).is_file()
            assert warning["evidence_id"] in proofs
        assert ("t8_period" in coverage["missing"]) == unknown_year
    expected_periods = (
        {None} if unknown_year else {"2024-01-01~2024-12-31", "2025-01-01~2025-12-31"}
    )
    assert {item["period"] for item in result["relations"]} == expected_periods
    relation_evidence_ids = {
        identifier
        for item in result["relations"]
        for identifier in item["evidence_ids"]
    }
    assert {
        proof["period"]
        for proof in result["evidence"]
        if proof["id"] in relation_evidence_ids
    } == expected_periods
    scoped = [item for item in entities.values() if item["name"] == "A"]
    expected_count = 16 if unknown_year else 4
    assert (
        len(scoped) == expected_count
        and len({item["id"] for item in scoped}) == expected_count
    ), "anonymous entities remain isolated by owner and annual/source scope"
    assert {item["owner_id"] for item in scoped} == {
        "company:TW:2360",
        "company:TW:2404",
    }
