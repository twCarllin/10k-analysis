"""Relations keep their product and time context instead of a single company label."""

import json
from pathlib import Path

from runtime.industry_map.adapters import normalize
from runtime.industry_map.model import merge


def test_customer_supplier_and_competitor_context():
    record = {
        "results": {
            "supply_chain": {
                "named_suppliers": [
                    {
                        "name": "Foundry",
                        "ticker": "TSM",
                        "material_or_service": "CPU tiles",
                    }
                ]
            },
            "competitor_mapping": {
                "named_competitors": [
                    {
                        "name": "Apple",
                        "ticker": "AAPL",
                        "markets": ["PC ARM processors"],
                        "note": "Own silicon competes only in PC",
                        "period": "2025",
                    }
                ]
            },
            "footnotes_segment": {
                "major_customers": [
                    {
                        "name": "Apple",
                        "ticker": "AAPL",
                        "material_or_service": "Mac CPUs (historical customer)",
                        "period": "2020",
                    },
                    "Actual Client",
                    "Customer A",
                ]
            },
        },
        "eval": {},
        "synthesis": {},
    }
    result = merge([normalize(record, {"ticker": "INTC"}, "input.json")])
    customers = [
        r
        for r in result["relations"]
        if r["source_id"] == "company:US:INTC" and r["predicate"] == "supplies_to"
    ]
    assert len(customers) == 2
    apple = next(r for r in customers if r["target_id"] == "company:US:AAPL")
    assert apple["period"] == "2020" and "historical" in apple["product"]
    competitor = next(
        r for r in result["relations"] if r["predicate"] == "competes_with"
    )
    assert (
        competitor["product"] == "PC ARM processors" and competitor["period"] == "2025"
    )
    supplier = next(
        r for r in result["relations"] if r["source_id"] == "company:US:TSM"
    )
    assert supplier["target_id"] == "company:US:INTC" and supplier["period"] is None
    assert all(r["status"] == "pending" for r in result["relations"])
    proofs = [e for e in result["evidence"] if e["id"] in competitor["evidence_ids"]]
    assert {e["locator"]["pointer"].split("/")[-1] for e in proofs} >= {
        "name",
        "note",
        "markets",
        "period",
    }
    assert not any(e["name"] == "Customer A" for e in result["entities"])


def test_intel_reviewed_roles_are_multiple_and_historical():
    record = json.loads(Path("industry_map_inputs/INTC_relationships.json").read_text())
    result = normalize(record, {"ticker": "INTC"}, "INTC_relationships.json")
    apple = [r for r in result["relations"] if r["target_id"] == "company:US:AAPL"]
    assert {r["predicate"] for r in apple} == {"supplies_to", "competes_with"}
    historical = next(r for r in apple if r["predicate"] == "supplies_to")
    assert historical["period"] == "2020-06-22" and "歷史" in historical["product"]
    assert any(
        r["source_id"] == "company:US:TSM"
        and r["target_id"] == "company:US:INTC"
        and r["predicate"] == "supplies_to"
        for r in result["relations"]
    )
    assert all(r["status"] == "pending" for r in result["relations"])


def test_reimport_replaces_only_same_source_generated_relations():
    from runtime.industry_map.__main__ import _refresh_analysis_relations
    from runtime.industry_map.model import evidence, relation, snapshot

    generated = evidence(
        "version.json",
        locator={"pointer": "/results/competitor_mapping/named_competitors/0/name"},
        quote="Apple",
    )
    manual = evidence(
        "version.json",
        locator={"pointer": "/results/manual"},
        source_type="primary",
        quote="Apple",
    )
    other = evidence(
        "other-version.json",
        locator={"pointer": "/results/competitor_mapping/named_competitors/0/name"},
        quote="Apple",
    )
    edges = [
        relation(
            "company:US:INTC",
            "competes_with",
            "company:US:AAPL",
            product=str(i),
            evidence_ids=[proof["id"]],
            status=status,
        )
        for i, (proof, status) in enumerate(
            [
                (generated, "pending"),
                (manual, "pending"),
                (generated, "confirmed"),
                (other, "pending"),
            ]
        )
    ]
    before = snapshot(relations=edges, evidence=[generated, manual, other])
    after = _refresh_analysis_relations(before, [snapshot(evidence=[generated])])
    assert after["relations"] == edges[1:]
    assert before["relations"] == edges
