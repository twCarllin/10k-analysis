"""Public identity → source validation → merge → SQLite contracts."""

from runtime.industry_map import entity, evidence, merge, relation, role, snapshot
from runtime.industry_map.store import load, save


def test_identity_evidence_merge_sqlite_roundtrip(tmp_path):
    # 依據 runtime/tw_equity/pdf_doc.py:21-25：頁碼為 1-based，文字為字串。
    sources = {"annual.pdf": {1: "甲公司供應設備給乙公司。"}}
    fragments = []
    for period in ("2024", "2025"):
        # 依據 runtime/industry_map/model.py:38-72：entity 提供具名身份。
        supplier = entity("甲公司", market="TW", ticker="1")
        customer = entity("乙公司", period=period)
        # 依據 runtime/industry_map/model.py:75-94：evidence 保留文件、頁碼及摘錄。
        proof = evidence(
            "annual.pdf",
            locator={"page": 1},
            quote="甲公司供應設備給乙公司。",
            source_type="primary",
            period=period,
        )
        # 依據 runtime/industry_map/model.py:97-128：role/relation 透過 evidence_ids 引用。
        fragments.append(
            snapshot(
                entities=[supplier, customer],
                evidence=[proof],
                relations=[
                    relation(
                        supplier["id"],
                        "supplies_to",
                        customer["id"],
                        period=period,
                        status="confirmed",
                        evidence_ids=[proof["id"]],
                    ),
                    relation(
                        customer["id"],
                        "uses",
                        "未知",
                        period=period,
                        status="confirmed",
                    ),
                ],
                roles=[
                    role(
                        supplier["id"],
                        "設備",
                        "製造",
                        status="confirmed",
                        evidence_ids=[proof["id"]],
                    )
                ],
            )
        )
    combined = merge(fragments + fragments, sources=sources)
    database = tmp_path / "map.sqlite"
    save(combined, database)
    save(combined, database)
    result = load(database)
    assert result == combined
    assert len(result["entities"]) == 2
    assert len(result["evidence"]) == 2
    assert len(result["relations"]) == 4
    assert {item["period"] for item in result["relations"]} == {"2024", "2025"}
    assert {item["predicate"]: item["status"] for item in result["relations"]} == {
        "supplies_to": "confirmed",
        "uses": "pending",
    }
    assert len(result["roles"]) == 1
    assert result["roles"][0]["status"] == "confirmed"
