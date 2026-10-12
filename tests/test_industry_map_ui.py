"""Screen-query contracts using the snapshot producer as the single fixture source."""

from copy import deepcopy

import pytest

from runtime.industry_map.model import (
    coverage,
    entity,
    evidence,
    observation,
    relation,
    role,
    snapshot,
)
from runtime.industry_map.render import company_detail, compare_financials, query_map

PERIOD = "2026-01-01~2026-06-30"


@pytest.fixture
def screen_snapshot():
    # 依據 runtime/industry_map/model.py:39 entity producer，匿名對象帶 owner_id。
    supplier = entity("設備公司", market="TW", ticker="1")
    buyer = entity("晶圓公司", market="TW", ticker="2")
    anonymous = entity("甲公司", anonymous=True, owner_id=supplier["id"], period=PERIOD)
    # 依據 runtime/industry_map/model.py:76 evidence producer，原文與頁碼同筆保存。
    proof = evidence(
        "annual.pdf",
        locator={"page": 3},
        quote="設備",
        period=PERIOD,
        source_type="primary",
    )
    ids = [proof["id"]]
    # 依據 runtime/industry_map/model.py:98 role producer，stage/product/status。
    roles = [
        role(
            supplier["id"],
            "半導體",
            "設備",
            product="量測",
            status="confirmed",
            evidence_ids=ids,
        ),
        role(buyer["id"], "半導體", "製造", product="晶圓", evidence_ids=ids),
    ]
    # 依據 runtime/industry_map/model.py:110 relation producer，方向由兩端 ID 保存。
    relations = [
        relation(
            supplier["id"],
            "supplies_to",
            buyer["id"],
            product="量測",
            period=PERIOD,
            status="confirmed",
            evidence_ids=ids,
        ),
        relation(
            supplier["id"],
            "supplies_to",
            anonymous["id"],
            product="量測",
            period=PERIOD,
            evidence_ids=ids,
        ),
    ]
    # 依據 runtime/industry_map/model.py:132 observation producer，完整比較口徑。
    financials = [
        observation(
            company["id"],
            "revenue",
            value,
            currency="TWD",
            unit="千元",
            period=PERIOD,
            basis="consolidated",
            scope="company",
            evidence_ids=ids,
        )
        for company, value in ((supplier, 100), (buyer, 200))
    ]
    # 依據 runtime/industry_map/model.py:166 coverage producer。
    coverages = [
        coverage(company["id"], sources=["annual.pdf"]) for company in (supplier, buyer)
    ]
    # 依據 runtime/industry_map/model.py:30 snapshot producer，實際測試只載入此 fixture。
    return snapshot(
        entities=[supplier, buyer, anonymous],
        roles=roles,
        relations=relations,
        observations=financials,
        evidence=[proof],
        coverage=coverages,
    )


def test_company_detail_preserves_records_and_evidence(screen_snapshot):
    original = deepcopy(screen_snapshot)
    detail = company_detail(screen_snapshot, "company:TW:1")
    assert (
        detail["roles"] == screen_snapshot["roles"][:1]
    ), "公司選取：角色及 evidence ID"
    assert (
        detail["financials"] == screen_snapshot["observations"][:1]
    ), "公司選取：財務及 evidence ID"
    assert detail["relations"] == [
        dict(item, direction="outgoing") for item in screen_snapshot["relations"]
    ], "公司選取：方向/產品/期間/狀態及 evidence ID"
    assert (
        detail["evidence"] == screen_snapshot["evidence"]
    ), "來源回查使用同一 snapshot"
    assert (
        detail["counterparties"] == screen_snapshot["entities"][1:]
    ), "匿名交易對象保留在詳情"
    incoming = company_detail(screen_snapshot, "company:TW:2")
    assert incoming["relations"][0]["direction"] == "incoming"
    detail["evidence"][0]["quote"] = "changed"
    assert screen_snapshot == original, "查詢結果不得修改 snapshot"


def test_product_search_excludes_pending_in_companies_and_relations(screen_snapshot):
    result = query_map(screen_snapshot, search="量測", include_pending=False)
    assert [item["id"] for item in result["companies"]] == [
        "company:TW:1",
        "company:TW:2",
    ], "產品搜尋：confirmed 關係兩端可見，匿名對象不在總覽"
    assert result["roles"] == screen_snapshot["roles"][:1], "角色排除 pending"
    assert (
        result["relations"] == screen_snapshot["relations"][:1]
    ), "關係同時符合產品與狀態篩選"
    pending_only = query_map(screen_snapshot, search="晶圓", include_pending=False)
    assert pending_only["roles"] == []
    assert pending_only["relations"] == []
    staged = query_map(screen_snapshot, stage="設備")
    assert [item["id"] for item in staged["companies"]] == ["company:TW:1"], "環節篩選"
    assert (
        len(query_map(screen_snapshot)["companies"]) == 2
    ), "總覽限定 coverage 或 roles 主體"


def test_comparison_keeps_values_and_equivalent_complete_periods(screen_snapshot):
    screen_snapshot["observations"][0]["period"] = "ROC115-01-01~115-06-30"
    result = compare_financials(
        screen_snapshot,
        ["company:TW:1", "company:TW:2"],
        metric="revenue",
        period=PERIOD,
    )
    assert result == dict(
        comparable=True, reasons=[], rows=screen_snapshot["observations"]
    ), "相同口徑與等價完整期間可比較，原數值保留"


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("currency", "USD"),
        ("unit", "元"),
        ("period", "2025-01-01~2025-06-30"),
        ("basis", "standalone"),
        ("scope", "segment"),
        ("currency", None),
        ("unit", "unknown"),
        ("period", "115"),
        ("period", "114"),
        ("period", "2025年度"),
        ("period", "current"),
        ("period", "2026-02-30~2026-06-30"),
        ("basis", None),
        ("scope", "unknown"),
        ("value", None),
    ],
)
def test_comparison_explains_incompatible_or_missing_values(
    screen_snapshot, field, replacement
):
    screen_snapshot["observations"][1][field] = replacement
    result = compare_financials(
        screen_snapshot, ["company:TW:1", "company:TW:2"], metric="revenue"
    )
    assert result["comparable"] is False, f"{field} 差異或缺值不得比較"
    assert any(
        reason.startswith(field + ":") for reason in result["reasons"]
    ), f"必須說明 {field} 差異"
    assert (
        result["rows"] == screen_snapshot["observations"]
    ), "不換匯、不年化、不排名；原值及來源不變"


def test_comparison_requires_metric_and_unambiguous_observations(screen_snapshot):
    missing = compare_financials(screen_snapshot, ["company:TW:1"], metric="")
    assert not missing["comparable"] and "metric: missing" in missing["reasons"]
    screen_snapshot["observations"].append(
        dict(screen_snapshot["observations"][0], period="2025-01-01~2025-06-30")
    )
    ambiguous = compare_financials(screen_snapshot, ["company:TW:1"], metric="revenue")
    assert not ambiguous["comparable"]
    assert (
        "rows: company:TW:1 has 2 observations" in ambiguous["reasons"]
    ), "不得隱性選最新"
    incomplete = compare_financials(
        screen_snapshot, ["company:TW:1"], metric="revenue", period="115"
    )
    assert (
        not incomplete["comparable"]
        and "period: incomplete selection" in incomplete["reasons"]
    )


def test_offline_render_reuses_snapshot_and_escapes_source(screen_snapshot, tmp_path):
    import json
    import re

    from runtime.industry_map.render import render

    screen_snapshot["evidence"][0]["quote"] = '</script><img src=x onerror="attack()">'
    render(screen_snapshot, tmp_path)
    assert {path.name for path in tmp_path.iterdir()} == {
        "index.html",
        "app.js",
        "style.css",
        "graph.json",
    }, "離線檔案集合"
    first = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    render(screen_snapshot, tmp_path)
    assert first == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    page = (tmp_path / "index.html").read_text()
    embedded = re.search(
        r'<script id="snapshot" type="application/json">(.*?)</script>', page, re.S
    ).group(1)
    assert "<" not in embedded, "不可信來源跨 HTML 邊界時逃逸 <"
    assert (
        json.loads(embedded)
        == json.loads((tmp_path / "graph.json").read_text())
        == screen_snapshot
    ), "頁面及 graph 使用同一 snapshot"
    assert 'src="app.js"' in page and 'href="style.css"' in page
    assert "https://" not in page and "http://" not in page, "無 CDN"


def run_browser_script(screen_snapshot, script):
    """Run the public JS API with real producer output, without internal mocks."""
    import json
    from pathlib import Path
    import subprocess

    asset = Path("runtime/industry_map/assets/app.js").resolve()
    result = subprocess.run(
        [
            "node",
            "-e",
            "const assert=require('node:assert/strict');"
            + "const api=require("
            + json.dumps(str(asset))
            + ");"
            + "const snapshot="
            + json.dumps(screen_snapshot)
            + ";"
            + "const index=api.createIndex(snapshot);"
            + script,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# Node assertions are checked by run_browser_script's subprocess exit assertion.
def test_js_company_relation_and_source_selection(screen_snapshot):  # testlint: allow
    run_browser_script(
        screen_snapshot,
        r"""
const detail=api.select(index, 'company:TW:1');
assert.deepEqual(detail.roles, snapshot.roles.slice(0,1), 'company roles');
assert.deepEqual(detail.financials, snapshot.observations.slice(0,1), 'company numbers');
assert.deepEqual(detail.relations, snapshot.relations.map(item=>({...item,direction:'outgoing'})), 'relationship direction and metadata');
assert.deepEqual(api.select(index,'company:TW:2').relations[0].direction,'incoming');
assert.deepEqual(detail.evidence, snapshot.evidence, 'company source selection');
assert.deepEqual(api.selectEvidence(index, detail.relations[0].evidence_ids), snapshot.evidence, 'relationship quote/document/locator/type/date');
""",
    )


def test_js_combined_filters_update_all_views(screen_snapshot):  # testlint: allow
    run_browser_script(
        screen_snapshot,
        r"""
const view=api.filter(index,{search:'量測',stage:'設備',includePending:false});
assert.deepEqual(view.companies.map(item=>item.id), ['company:TW:1'], 'combined overview');
const detail=api.select(index,'company:TW:1',view);
assert.deepEqual(detail.roles,snapshot.roles.slice(0,1),'detail roles follow filters');
assert.deepEqual(detail.relations.map(item=>item.id),[snapshot.relations[0].id],'detail pending excluded');
assert.equal(api.select(index,'company:TW:2',view),null,'hidden company detail');
const comparison=api.compare(index,['company:TW:1','company:TW:2'],'revenue','2026-01-01~2026-06-30',view);
assert.deepEqual(comparison,{comparable:true,reasons:[],rows:snapshot.observations.slice(0,1)},'comparison follows same visible companies');
const all=api.compare(index,['company:TW:1','company:TW:2'],'revenue','2026-01-01~2026-06-30');
assert.equal(all.comparable,true);
snapshot.observations[1].currency='USD';
const blocked=api.compare(api.createIndex(snapshot),['company:TW:1','company:TW:2'],'revenue','2026-01-01~2026-06-30');
assert.equal(blocked.comparable,false,'mixed basis blocked');
assert.ok(blocked.reasons.includes('currency: incompatible'),'explain mismatch');
""",
    )


def test_js_empty_state_and_untrusted_text(screen_snapshot):  # testlint: allow
    # 依據 runtime/industry_map/model.py:76 evidence producer；惡意文字仍是來源資料。
    screen_snapshot["evidence"][0]["quote"] = '<img src=x onerror="attack()">'
    # 依據 runtime/industry_map/pilot.py:204-208 結構化警告及 :159 字串警告。
    screen_snapshot["coverage"][0]["warnings"] = [
        "pdf_needs_manual_review",
        {"reason": "pilot_company_failed", "error": "FileNotFoundError"},
        {
            "reason": '<img src=x onerror="attack()">',
            "error": "<script>attack()</script>",
        },
    ]
    run_browser_script(
        screen_snapshot,
        r"""
const empty=api.filter(index,{search:'不存在'});
assert.deepEqual(empty,{companies:[],roles:[],relations:[]},'empty query');
assert.equal(api.select(index,'company:TW:1',empty),null);
assert.equal(api.compare(index,['company:TW:1'],'revenue','2026-01-01~2026-06-30',empty).comparable,false);
// The DOM is the system boundary: this small host records observable text and
// fails immediately if a source is assigned to an HTML sink.
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.listeners={}; this.value=''; this.checked=false; this._text=''; }
  set textContent(value) { this._text=String(value); this.children=[]; }
  get textContent() { return this._text+this.children.map(child=>child.textContent).join(''); }
  set innerHTML(value) { throw Error('unsafe HTML sink: '+value); }
  append(...children) { const first=this.children.length===0; this.children.push(...children); if(this.tag==='select'&&first&&children[0]) this.value=children[0].value; }
  replaceChildren(...children) { this._text=''; this.children=[...children]; }
  addEventListener(event,callback) { this.listeners[event]=callback; }
}
const elements=Object.fromEntries(['snapshot','search','stage','pending','overview','detail','evidence','metric','period','comparison'].map(id=>[id,new Element(['stage','metric','period'].includes(id)?'select':'div')]));
// 依據 runtime/industry_map/render.py:212 HTML producer 的預設全部選項。
const allOption=new Element('option'); allOption.value=''; elements.stage.append(allOption);
elements.snapshot.textContent=JSON.stringify(snapshot); elements.pending.checked=true;
global.document={getElementById:id=>elements[id],createElement:tag=>new Element(tag)};
delete require.cache[require.resolve('./runtime/industry_map/assets/app.js')];
require('./runtime/industry_map/assets/app.js');
assert.equal(elements.detail.textContent.includes('revenue'),false,'initial DOM does not expand finances');
function find(root,label) { if(root.tag==='button'&&root.textContent===label)return root; for(const child of root.children){const found=find(child,label);if(found)return found;} }
find(elements.overview,'設備公司 (1)').listeners.click();
assert.ok(elements.detail.textContent.includes('pdf_needs_manual_review'),'string warning readable');
assert.ok(elements.detail.textContent.includes('pilot_company_failed / FileNotFoundError'),'structured warning reason and error readable');
assert.equal(elements.detail.textContent.includes('[object Object]'),false,'no opaque object warning');
assert.ok(elements.detail.textContent.includes('<img src=x onerror="attack()"> / <script>attack()</script>'),'warning HTML remains literal text');
assert.ok(elements.detail.children.some(child=>child.tag==='p'&&child.textContent.includes('pilot_company_failed')),'warnings are text paragraphs');
find(elements.detail,'關係證據').listeners.click();
assert.ok(elements.evidence.textContent.includes('<img src=x onerror="attack()">'),'source displayed as literal text');
assert.ok(elements.evidence.textContent.includes('annual.pdf'));
assert.ok(elements.evidence.textContent.includes('"page":3'));
assert.ok(elements.evidence.textContent.includes('primary'));
assert.ok(elements.evidence.textContent.includes('查核日期：未知'));
assert.ok(elements.evidence.textContent.includes('2026-01-01~2026-06-30'));
assert.equal(elements.evidence.children[0].children[0].tag,'pre','quote is a text element');
elements.search.value='不存在'; elements.search.listeners.input();
assert.ok(elements.overview.textContent.includes('無符合資料'),'visible empty state');
assert.ok(elements.detail.textContent.includes('無符合資料'),'clear hidden detail');
assert.ok(elements.evidence.textContent.includes('請選取來源'),'clear stale evidence');
""",
    )


# 依據 tests/test_industry_map_sources.py:21 producer_records；共用實際 producer fixture。
from tests.test_industry_map_sources import producer_records


def cli_command(*arguments):
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-m", "runtime.industry_map", *map(str, arguments)],
        capture_output=True,
        text=True,
    )


def test_cli_inventory_logging_and_output_protection(tmp_path, producer_records):
    import json

    root, out = tmp_path / "root", tmp_path / "out"
    root.mkdir()
    (root / "1234_raw.json").write_text(json.dumps(producer_records["tw_raw"]))
    result = cli_command(
        "inventory", "--root", root, "--out", out, "--log-format", "json"
    )
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["records"]) == 1
    diagnostic = json.loads(result.stderr)
    assert {"timestamp", "level", "logger", "event", "message"} <= diagnostic.keys()
    assert (
        diagnostic["level"] == "INFO"
        and diagnostic["event"] == "industry_map.completed"
    )
    assert diagnostic["timestamp"].endswith("+00:00")
    assert (out / "inventory.md").is_file()
    (out / "unrelated.txt").write_text("keep")
    quiet = cli_command(
        "inventory", "--root", root, "--out", out, "--log-level", "ERROR"
    )
    assert quiet.returncode == 0 and quiet.stderr == ""
    assert json.loads(quiet.stdout)["records"]
    assert (out / "unrelated.txt").read_text() == "keep"
    (out / "inventory.json").write_text("foreign")
    blocked = cli_command("inventory", "--root", root, "--out", out)
    assert blocked.returncode != 0 and "industry_map.input_failed" in blocked.stderr
    assert (out / "inventory.json").read_text() == "foreign"
    missing = cli_command("inventory", "--root", root / "missing", "--out", out)
    assert missing.returncode != 0 and "root directory does not exist" in missing.stderr
    file_out = tmp_path / "not-directory"
    file_out.write_text("keep")
    unwritable = cli_command("inventory", "--root", root, "--out", file_out)
    assert (
        unwritable.returncode != 0 and "industry_map.input_failed" in unwritable.stderr
    )
    assert file_out.read_text() == "keep"
