"""Local JSON/PDF → CLI → storage → safe offline view."""

import json
from pathlib import Path
import re
import subprocess

from runtime.industry_map.render import compare_financials
from runtime.industry_map.store import load, save
from tests.test_industry_map_sources import pilot_inputs, producer_records
from tests.test_industry_map_ui import cli_command


def test_cli_pdf_build_history_and_safe_comparison(
    tmp_path, producer_records, pilot_inputs
):
    # 依據 tests/test_industry_map_sources.py:21/637：實際 JSON producer 與小型 PDF，共用唯一 fixture。
    root, out = tmp_path / "raw", tmp_path / "map"
    root.mkdir()
    raw = producer_records["tw_raw"]
    raw["company_name"] = "</script><img src=x onerror=attack()>"
    path = root / "1234_raw.json"
    path.write_text(json.dumps(raw))
    args = (
        "build",
        "--root",
        root,
        "--out",
        out,
        "--inputs",
        pilot_inputs["inputs"],
        "--tickers",
        "1234,2360",
        "--pilot",
    )
    first = cli_command(*args)
    assert first.returncode == 0, first.stderr
    old = load(out / "industry_map.sqlite")
    assert {"company:TW:1234", "company:TW:2360"} == {
        item["company_id"] for item in old["coverage"]
    }
    assert old["roles"] and old["observations"] and old["evidence"]
    checked_role = old["roles"][0]
    checked_role["status"] = "confirmed"
    save(old, out / "industry_map.sqlite")
    raw["bundle"]["statements"]["rows"][0]["current"] = 999
    path.write_text(json.dumps(raw))
    rerun = cli_command(*args)
    assert rerun.returncode == 0, rerun.stderr
    current = load(out / "industry_map.sqlite")
    assert (
        next(item for item in current["roles"] if item["id"] == checked_role["id"])[
            "status"
        ]
        == "confirmed"
    ), "原PDF仍有效時保留手工確認"
    changed = [
        item
        for item in current["observations"]
        if item["company_id"] == "company:TW:1234" and item["metric"] == "revenue"
    ]
    assert any(item["value"] == 999 for item in changed), "重跑同ID優先當次值"
    raw["bundle"]["statements"]["periods"]["flow_current"] = "2026-01-01~2026-06-30"
    path.write_text(json.dumps(raw))
    assert cli_command(*args).returncode == 0
    current = load(out / "industry_map.sqlite")
    assert {item["id"] for item in old["observations"]} <= {
        item["id"] for item in current["observations"]
    }, "不同舊期仍存在"
    assert (
        current
        == json.loads((out / "snapshot.json").read_text())
        == json.loads((out / "graph.json").read_text())
    )
    embedded = re.search(
        r'<script id="snapshot" type="application/json">(.*?)</script>',
        (out / "index.html").read_text(),
        re.S,
    ).group(1)
    assert "<" not in embedded, "HTML安全escape"
    assert json.loads(embedded) == current
    comparison = compare_financials(
        current, ["company:TW:1234", "company:TW:2360"], metric="revenue"
    )
    assert (
        comparison["comparable"] is False and comparison["reasons"]
    ), "口徑差異必須阻擋"
    browser = subprocess.run(
        [
            "node",
            "-e",
            "const assert=require('node:assert/strict');"
            + "const api=require("
            + json.dumps(str((out / "app.js").resolve()))
            + ");"
            + "const snapshot="
            + json.dumps(current)
            + ";"
            + "const result=api.compare(api.createIndex(snapshot),['company:TW:1234','company:TW:2360'],'revenue','2025-01-01~2025-06-30');"
            + "assert.equal(result.comparable,true,'ROC114 and ISO2025 same period and H1 basis');"
            + "const mixed=structuredClone(snapshot);"
            + "mixed.observations.filter(o=>o.company_id==='company:TW:2360').forEach(o=>{o.basis='FY'});"
            + "const blocked=api.compare(api.createIndex(mixed),['company:TW:1234','company:TW:2360'],'revenue','2025-01-01~2025-06-30');"
            + "assert.equal(blocked.comparable,false,'mixed basis blocked');assert.ok(blocked.reasons.includes('basis: incompatible'));",
        ],
        capture_output=True,
        text=True,
    )
    assert browser.returncode == 0, browser.stderr
    queue = json.loads((out / "review_queue.json").read_text())
    assert queue["roles"] and (out / "review_queue.md").is_file()
    assert json.loads((out / "coverage.json").read_text()) == current["coverage"]


def test_cli_local_xbrl_versions_and_latest_values(tmp_path, producer_records):
    # 依據 tests/test_industry_map_sources.py:111 US raw producer；SEC companyfacts形狀依 adapters.py:315。
    root, out, facts_dir = tmp_path / "raw", tmp_path / "out", tmp_path / "facts"
    root.mkdir()
    facts_dir.mkdir()
    (root / "HWM_raw.json").write_text(json.dumps(producer_records["us_raw"]))
    facts = {
        "entityName": "HWM",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "val": 10,
                                "filed": "2026-01-01",
                                "form": "10-K",
                                "fp": "FY",
                            }
                        ]
                    }
                }
            }
        },
    }
    source = facts_dir / "xbrl_HWM.json"
    source.write_text(json.dumps(facts))
    args = (
        "build",
        "--root",
        root,
        "--out",
        out,
        "--xbrl-dir",
        facts_dir,
        "--tickers",
        "HWM",
        "--pilot",
    )
    first = cli_command(*args)
    assert first.returncode == 0, first.stderr
    original = load(out / "industry_map.sqlite")
    assert {item["company_id"] for item in original["coverage"]} == {
        "company:US:HWM"
    }, "US不得送TW解析"
    proof = next(
        item
        for item in original["evidence"]
        if item["locator"]["pointer"].startswith("/facts/")
    )
    archived = Path(proof["document"])
    assert archived.is_relative_to(out) and json.loads(archived.read_text()) == facts
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {
            "start": "2025-01-01",
            "end": "2025-12-31",
            "val": 20,
            "filed": "2026-02-01",
            "form": "10-K",
            "fp": "FY",
        }
    )
    source.write_text(json.dumps(facts))
    second = cli_command(*args)
    assert second.returncode == 0, second.stderr
    current = load(out / "industry_map.sqlite")
    assert current["observations"][0]["value"] == 20, "重編值不能被舊DB覆蓋"
    assert json.loads(archived.read_text()) != facts, "快取更新不破壞舊pointer"
