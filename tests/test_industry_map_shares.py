"""T8 percentages retain their actual denominator and numeric source."""

import json
from pathlib import Path

from runtime.industry_map.model import merge
from runtime.industry_map.pilot import build_pilot
from runtime.industry_map.store import load, save
from tests.test_industry_map_sources import pilot_inputs  # noqa: F401


def test_t8_shares_keep_source_denominator_and_storage(pilot_inputs, tmp_path):
    result = build_pilot(
        pilot_inputs["inputs"],
        ["2360"],
        pilot_inputs["out"],
        cache_dir=pilot_inputs["cache"],
    )
    proofs = {item["id"]: item for item in result["evidence"]}
    shares = [
        item
        for edge in result["relations"]
        for item in edge.get("disclosures", [])
        if item["kind"] in {"sales_share", "purchase_share"}
    ]
    assert shares
    assert {item["kind"] for item in shares} == {"sales_share", "purchase_share"}
    for item in shares:
        assert 0 <= item["value"] <= 100
        assert item["unit"] == "%" and item["currency"] is None
        proof = proofs[item["evidence_ids"][0]]
        pointer = proof["locator"]["pointer"]
        assert pointer.endswith("/pct")
        collection = (
            "customers_sales" if item["kind"] == "sales_share" else "customers_purchase"
        )
        assert pointer.startswith("/bundle/" + collection + "/")
        source = json.loads(Path(proof["document"]).read_text())
        for token in pointer.split("/")[1:]:
            source = source[int(token)] if isinstance(source, list) else source[token]
        assert source == item["value"] == json.loads(proof["quote"])
        assert proof["period"] == item["period"]
    combined = merge([result, result])
    assert combined["relations"] == result["relations"]
    database = tmp_path / "shares.sqlite"
    save(combined, database)
    assert load(database) == combined
    anonymous = [node for node in result["entities"] if node.get("owner_id")]
    assert len({node["id"] for node in anonymous}) > 1, "匿名名稱跨期不可合併"
