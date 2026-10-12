"""Inventory → three adapters/PDF → merge → dedicated SQLite."""

import json
from pathlib import Path

from runtime.industry_map import merge
from runtime.industry_map.adapters import normalize
from runtime.industry_map.inventory import inventory
from runtime.industry_map.pilot import build_pilot
from runtime.industry_map.store import load, save
from runtime.tw_equity.pdf_doc import load_pdf
from tests.test_industry_map_sources import pilot_inputs, producer_records


def test_inventory_json_adapters_merge_storage(tmp_path, producer_records):
    # 依據 tests/test_industry_map_sources.py:21-181：三類producer與metadata共用fixture。
    root, inputs = tmp_path / "json-records", tmp_path / "inputs"
    root.mkdir()
    inputs.mkdir()
    (inputs / "1234.json").write_text(json.dumps(producer_records["metadata"]))
    names = {
        "tw_raw": "1234_raw.json",
        "tw_batch": "1234.json",
        "us_raw": "HWM_raw.json",
    }
    for kind, filename in names.items():
        (root / filename).write_text(json.dumps(producer_records[kind]))
    discovered = inventory(root, inputs=inputs)
    assert {item["format"] for item in discovered["records"]} == set(names)
    assert len(discovered["coverage"]) == 2
    fragments = []
    for record in discovered["records"]:
        raw = json.loads(Path(record["source"]).read_text())
        metadata = (
            producer_records["metadata"]
            if record["format"] != "us_raw"
            else {"ticker": "HWM"}
        )
        fragments.append(normalize(raw, metadata, record["source"]))
    combined = merge(fragments + fragments)
    database = tmp_path / "json-map.sqlite"
    save(combined, database)
    save(combined, database)
    result = load(database)
    assert result == combined
    assert result["observations"] and result["relations"] and result["evidence"]
    assert len({item["id"] for item in result["entities"]}) == len(result["entities"])
    assert not any(
        item["name"] in {"Mock Titanium Co.", "$XX", "Placeholder Co."}
        for item in result["entities"]
    )
    assert all(item["status"] == "pending" for item in result["relations"])
    for proof in result["evidence"]:
        source = json.loads(Path(proof["document"]).read_text())
        for token in proof["locator"]["pointer"].split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            source = source[int(token)] if isinstance(source, list) else source[token]
        expected_quote = (
            source
            if isinstance(source, str)
            else json.dumps(source, ensure_ascii=False)
        )
        assert expected_quote == proof["quote"], proof["locator"]["pointer"]


def test_inventory_adapters_pdf_merge_storage(tmp_path, producer_records, pilot_inputs):
    # 依據 tests/test_industry_map_sources.py:21-181：實際producer來源fixture單一出處。
    root = tmp_path / "records"
    root.mkdir()
    names = {
        "tw_raw": "1234_raw.json",
        "tw_batch": "1234.json",
        "us_raw": "HWM_raw.json",
    }
    for kind, filename in names.items():
        (root / filename).write_text(json.dumps(producer_records[kind]))
    inventory_result = inventory(root, inputs=pilot_inputs["inputs"])
    assert len(inventory_result["records"]) == 3
    fragments = []
    for record in inventory_result["records"]:
        raw = json.loads(Path(record["source"]).read_text())
        metadata = (
            producer_records["metadata"]
            if record["format"] != "us_raw"
            else {"ticker": "HWM"}
        )
        fragments.append(normalize(raw, metadata, record["source"]))
    # 依據 tests/test_industry_map_sources.py:637-740：真實PDF由fitz系統邊界建立。
    fixture = pilot_inputs
    pilot = build_pilot(
        fixture["inputs"], ["2360"], fixture["out"], cache_dir=fixture["cache"]
    )
    doc = load_pdf(fixture["ar"], cache_dir=fixture["cache"])
    primary = {
        str(fixture["ar"].resolve()): {page.number: page.text for page in doc.pages}
    }
    combined = merge(fragments + [pilot, pilot], sources=primary)
    database = tmp_path / "map.sqlite"
    save(combined, database)
    result = load(database)
    assert result == combined
    assert not any(
        item["name"] in {"Mock Titanium Co.", "$XX", "Placeholder Co."}
        for item in result["entities"]
    )
    assert {"company:TW:1234", "company:US:HWM", "company:TW:2360"} <= {
        item["id"] for item in result["entities"]
    }
    assert result["observations"] and result["relations"] and result["roles"]
    roles = [
        item for item in result["roles"] if item["company_id"] == "company:TW:2360"
    ]
    assert len(roles) == 2 and all(item["status"] == "pending" for item in roles)
    proofs = {item["id"]: item for item in result["evidence"]}
    for role in roles:
        for identifier in role["evidence_ids"]:
            proof = proofs[identifier]
            assert proof["locator"]["page"] == 2
            assert (
                proof["quote"] in primary[proof["document"]][proof["locator"]["page"]]
            )
    for proof in result["evidence"]:
        if "pointer" not in proof["locator"]:
            continue
        source = json.loads(Path(proof["document"]).read_text())
        for token in proof["locator"]["pointer"].split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            source = source[int(token)] if isinstance(source, list) else source[token]
        assert (
            source
            if isinstance(source, str)
            else json.dumps(source, ensure_ascii=False)
        ) == proof["quote"]

    anonymous = [
        item
        for item in result["entities"]
        if item["name"] == "A" and item["owner_id"] == "company:TW:2360"
    ]
    assert (
        len(anonymous) == 2 and len({item["id"] for item in anonymous}) == 2
    ), "PDF annual anonymous entities stay distinct after storage"
