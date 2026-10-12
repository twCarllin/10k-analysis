"""Black-box contracts for industry-map items 1.1–1.3."""

import json
import sqlite3

import pytest

from runtime.industry_map import (
    coverage,
    disclosure_changes,
    entity,
    evidence,
    merge,
    observation,
    relation,
    role,
    snapshot,
    validate_snapshot,
)
from runtime.industry_map.store import load, save


@pytest.fixture
def producer_sources():
    # 依據 runtime/tw_equity/pdf_doc.py:21-25：Page.number 為 1-based，text 為字串。
    pages = {1: "甲公司供應設備給乙公司。甲公司製造設備。"}
    # 依據 runtime/tw_equity/batch.py:48-52：批次輸出 company_name/fs_period。
    batch = {"company_name": "甲公司", "fs_period": None}
    return {"annual.pdf": pages, "batch.json": batch}


def test_company_aliases_anonymous_scope_and_serialization():
    # 依據 runtime/industry_map/model.py:39-73：entity 建立身份與 aliases。
    company = entity("甲", market="TW", ticker="1234")
    renamed = entity("甲公司", market="TW", ticker="1234", aliases=["甲股份"])
    assert company["id"] == renamed["id"] == "company:TW:1234"
    combined = merge([snapshot(entities=[company]), snapshot(entities=[renamed])])
    assert combined["entities"][0]["aliases"] == ["甲", "甲公司", "甲股份"]
    # 依據 runtime/industry_map/model.py:58-66：匿名身份由 owner 與 period 限定。
    anonymous = [
        entity("客戶A", anonymous=True, owner_id=owner, period=period)
        for owner, period in [("甲", "2024"), ("乙", "2024"), ("甲", "2025")]
    ]
    assert len({item["id"] for item in anonymous}) == 3
    unknown = entity("客戶A", anonymous=True, owner_id="甲")
    assert unknown["ticker"] is None and unknown["market"] is None
    assert unknown["id"] != entity("客戶A", anonymous=True, owner_id="甲")["id"]
    assert unknown["id"] != anonymous[0]["id"]
    for kind in ("product", "technology", "material", "application"):
        named = entity("設備", kind=kind)
        assert named["id"] == entity("設備", kind=kind)["id"]
        assert named["kind"] == kind
    # 依據 runtime/industry_map/model.py:132-163：observation 保留 null 與 unknown。
    obs = observation(company["id"], "revenue")
    assert obs["value"] is None and obs["period"] is None
    assert obs["unit"] == obs["scope"] == "unknown"
    # 依據 runtime/industry_map/model.py:30-36、166-177：snapshot 與 coverage 集合。
    result = snapshot(
        entities=[company],
        observations=[obs],
        coverage=[coverage(company["id"], missing=["period"])],
    )
    assert json.loads(json.dumps(result)) == result
    assert set(result) == {
        "schema_version",
        "entities",
        "roles",
        "relations",
        "observations",
        "evidence",
        "coverage",
        "changes",
    }
    assert result["schema_version"] == 1
    assert result["coverage"][0]["missing"] == ["period"]


def test_named_external_company_identity_across_periods():
    for market in (None, "US"):
        old = entity("具名公司", market=market, period="2024")
        new = entity("具名公司", market=market, period="2025")
        assert old["id"] == new["id"] == entity("具名公司", market=market)["id"]
        assert merge([snapshot(entities=[old, new]), snapshot(entities=[old])])[
            "entities"
        ] == [old]


def test_primary_evidence_and_pending_validation(producer_sources):
    primary = evidence(
        "annual.pdf",
        locator={"page": 1},
        quote="甲公司供應設備給乙公司。",
        source_type="primary",
        period="2024",
    )
    analysis = evidence(
        "batch.json", locator={"pointer": "/company_name"}, quote="甲公司"
    )
    invalid = evidence(
        "annual.pdf", locator={"page": 1}, quote="不存在的摘錄", source_type="primary"
    )
    claims = [
        relation(
            "甲",
            "supplies_to",
            "乙",
            period=str(index),
            status="confirmed",
            evidence_ids=ids,
        )
        for index, ids in enumerate(
            [[primary["id"]], [analysis["id"]], [], [invalid["id"]]]
        )
    ]
    fragment = snapshot(
        evidence=[primary, analysis, invalid],
        relations=claims,
        roles=[
            role(
                "甲", "設備", "製造", status="confirmed", evidence_ids=[primary["id"]]
            ),
            role("乙", "設備", "使用", status="confirmed"),
        ],
    )
    checked = validate_snapshot(fragment, producer_sources)
    assert [item["status"] for item in checked["relations"]] == [
        "confirmed",
        "pending",
        "pending",
        "pending",
    ]
    assert [item["status"] for item in checked["roles"]] == ["confirmed", "pending"]
    assert json.loads(json.dumps(checked)) == checked
    assert checked["evidence"] == fragment["evidence"]
    assert primary["checked_at"] is None and primary["document_hash"] is None
    assert analysis["source_type"] == "analysis"
    assert fragment["relations"][1]["status"] == "confirmed"
    # 依據 runtime/industry_map/model.py:180-204：JSON pointer 可定位解碼陣列文字。
    sources = {"primary.json": ["甲公司供應設備給乙公司。"] * 2}
    # 依據 runtime/industry_map/model.py:76-95、110-129：定位證據與具證據關係。
    for token in ("0", "1", "-1", "+1", "01", "١", "1.0", ""):
        proof = evidence(
            "primary.json",
            locator={"pointer": "/" + token},
            quote="甲公司供應設備給乙公司。",
            source_type="primary",
        )
        claim = relation(
            "甲", "supplies_to", "乙", status="confirmed", evidence_ids=[proof["id"]]
        )
        checked = validate_snapshot(
            snapshot(evidence=[proof], relations=[claim]), sources
        )
        expected = "confirmed" if token in ("0", "1") else "pending"
        assert (
            checked["relations"][0]["status"] == expected
        ), f"JSON pointer index {token!r}"


def test_merge_idempotency_period_history_and_disclosure():
    # 依據 runtime/industry_map/model.py:39-73：entity 建立公司固定 ID。
    companies = [
        entity(name, market="TW", ticker=ticker)
        for name, ticker in [("甲", "1"), ("乙", "2"), ("丙", "3")]
    ]
    a, b, c = [item["id"] for item in companies]
    # 依據 runtime/industry_map/model.py:30-36、110-129：snapshot/relations 保留舊期。
    old = snapshot(
        entities=companies,
        relations=[
            relation(a, "supplies_to", b, period="2024"),
            relation(a, "uses", c, period="2024"),
        ],
    )
    # 依據 runtime/industry_map/model.py:30-73、110-129：新期保留身份、別名與關係。
    new = snapshot(
        entities=[entity("甲公司", market="TW", ticker="1")],
        relations=[
            relation(a, "supplies_to", b, period="2025"),
            relation(b, "uses", c, period="2025"),
        ],
    )
    result = merge([old, new, old, new], previous_period="2024", current_period="2025")
    assert json.loads(json.dumps(result)) == result
    assert len(result["entities"]) == 3
    assert len(result["relations"]) == 4
    assert {item["period"] for item in result["relations"]} == {"2024", "2025"}
    statuses = {item["relation_id"]: item["status"] for item in result["changes"]}
    assert statuses == {
        new["relations"][0]["id"]: "unchanged",
        old["relations"][1]["id"]: "not_disclosed_this_period",
        new["relations"][1]["id"]: "newly_disclosed",
    }
    assert all(
        item["status"] != "terminated"
        for item in result["relations"] + result["changes"]
    )
    assert (
        merge([result, result], previous_period="2024", current_period="2025") == result
    )
    assert disclosure_changes(result, None, "2025") == []


def test_store_roundtrip_all_collections_and_null(tmp_path):
    # 依據 runtime/industry_map/model.py:29-35：snapshot 收集全部 v1 集合。
    company = entity("甲", market="TW", ticker="1")
    proof = evidence("annual.pdf", period=None)
    fragment = snapshot(
        entities=[company],
        roles=[role(company["id"], "設備", "製造")],
        relations=[relation(company["id"], "produces", "設備")],
        observations=[observation(company["id"], "revenue")],
        evidence=[proof],
        coverage=[coverage(company["id"], missing=["period"])],
    )
    # 依據 runtime/industry_map/model.py:276-316：changes 由 merge 公開輸出建立。
    fragment = merge([fragment], previous_period="2024", current_period="2025")
    historical = snapshot(
        relations=[relation(company["id"], "produces", "設備", period="2024")]
    )
    fragment = merge(
        [fragment, historical], previous_period="2024", current_period="2025"
    )
    assert all(fragment[name] for name in fragment if name != "schema_version")
    database = tmp_path / "map.sqlite"
    save(fragment, database)
    assert load(database) == fragment


def test_store_upsert_preserves_old_period(tmp_path):
    # 依據 runtime/industry_map/model.py:109-162：relation/observation 包含 period。
    company = entity("甲", market="TW", ticker="1")

    def period_fragment(period, value):
        return snapshot(
            entities=[company],
            relations=[relation(company["id"], "uses", "設備", period=period)],
            observations=[observation(company["id"], "revenue", value, period=period)],
        )

    database = tmp_path / "map.sqlite"
    old = period_fragment("2024", 1)
    new = period_fragment("2025", 2)
    save(old, database)
    save(new, database)
    updated = period_fragment("2025", 3)
    save(updated, database)
    result = load(database)
    assert result["entities"] == [company]
    assert result["relations"] == old["relations"] + updated["relations"]
    assert result["observations"] == old["observations"] + updated["observations"]


@pytest.mark.parametrize("foreign", [True, False])
def test_store_rejects_foreign_or_wrong_version_without_changes(tmp_path, foreign):
    database = tmp_path / "map.sqlite"
    if foreign:
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE original (value TEXT)")
            connection.execute("INSERT INTO original VALUES ('保留')")
    else:
        save(snapshot(), database)
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version=2")
    original = database.read_bytes()
    for operation in (lambda: save(snapshot(), database), lambda: load(database)):
        with pytest.raises(ValueError):
            operation()
        assert database.read_bytes() == original
    with pytest.raises(ValueError):
        save({"schema_version": 2}, database)
    assert database.read_bytes() == original
