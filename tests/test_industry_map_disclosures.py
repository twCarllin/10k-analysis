"""Transaction and XBRL contracts through actual producers and storage."""

from copy import deepcopy
import json
from pathlib import Path

from runtime.industry_map.adapters import normalize
from runtime.industry_map.model import entity, evidence, merge, relation, snapshot
from runtime.industry_map.pilot import build_pilot
from runtime.industry_map.store import load, save
from tests.test_industry_map_sources import pilot_inputs  # noqa: F401


def test_disclosures_roundtrip_and_old_snapshot(tmp_path):
    supplier, buyer = entity("設備"), entity("客戶")
    proof = evidence("orders.json", locator={"pointer": "/quantity"}, quote="120")
    detail = dict(
        kind="order_quantity",
        value=120,
        unit="台",
        currency=None,
        period="2026-01-01~2026-06-30",
        evidence_ids=[proof["id"]],
    )
    edge = relation(
        supplier["id"],
        "supplies_to",
        buyer["id"],
        period=detail["period"],
        evidence_ids=[proof["id"]],
        disclosures=[detail],
    )
    detail["value"] = 999
    assert edge["disclosures"][0]["value"] == 120
    old = relation(supplier["id"], "supplies_to", buyer["id"], period=edge["period"])
    assert "disclosures" not in old
    first = snapshot(entities=[supplier, buyer], relations=[old])
    second = snapshot(entities=[supplier, buyer], relations=[edge], evidence=[proof])
    combined = merge([first, second, second])
    assert combined["relations"][0]["disclosures"] == edge["disclosures"]
    database = tmp_path / "map.sqlite"
    save(combined, database)
    assert load(database) == combined
    assert merge([second, first])["relations"][0]["disclosures"] == edge["disclosures"]


def test_actual_t8_amount_is_sales_or_purchase_not_order(pilot_inputs):
    result = build_pilot(
        pilot_inputs["inputs"],
        ["2360"],
        pilot_inputs["out"],
        cache_dir=pilot_inputs["cache"],
    )
    proofs = {proof["id"]: proof for proof in result["evidence"]}
    disclosures = [
        item
        for edge in result["relations"]
        for item in edge.get("disclosures", [])
        if item["kind"] in {"sales_amount", "purchase_amount"}
    ]
    assert disclosures
    assert {item["kind"] for item in disclosures} == {"sales_amount", "purchase_amount"}
    for item in disclosures:
        assert item["period"] and item["unit"] == "unknown"
        assert item["currency"] is None
        proof = proofs[item["evidence_ids"][0]]
        assert proof["source_type"] == "analysis"
        assert proof["locator"]["pointer"].endswith("/amount")
        source = json.loads(Path(proof["document"]).read_text())
        for token in proof["locator"]["pointer"].split("/")[1:]:
            source = source[int(token)] if isinstance(source, list) else source[token]
        assert source == item["value"]
        assert json.loads(proof["quote"]) == source


def test_xbrl_income_inputs_keep_latest_filing_and_pointers():
    record = {"results": {}, "eval": {}, "synthesis": {}, "ticker": "INTEST"}
    old = dict(
        start="2025-01-01",
        end="2025-12-31",
        form="10-K",
        fp="FY",
        filed="2026-01-20",
        val=30,
    )
    new = dict(old, filed="2026-02-20", val=40)
    facts = {
        "facts": {
            "us-gaap": {
                "GrossProfit": {"units": {"USD": [old, new]}},
                "OperatingIncomeLoss": {
                    "units": {"USD": [dict(old, val=15), dict(new, val=20)]}
                },
            }
        }
    }
    first = merge(
        [normalize(record, {"xbrl_facts": facts, "xbrl_source_path": "facts.json"})]
    )
    reverse = deepcopy(facts)
    for concept in reverse["facts"]["us-gaap"].values():
        concept["units"]["USD"].reverse()
    second = merge(
        [normalize(record, {"xbrl_facts": reverse, "xbrl_source_path": "facts.json"})]
    )
    for fragment in (first, second):
        rows = {row["metric"]: row for row in fragment["observations"]}
        assert rows["gross_profit"]["value"] == 40
        assert rows["operating_income"]["value"] == 20
        proofs = {proof["id"]: proof for proof in fragment["evidence"]}
        for row in rows.values():
            assert row["quality"]["filed"] == "2026-02-20"
            assert json.loads(proofs[row["evidence_ids"][0]]["quote"]) == row["value"]
