"""Node black-box graph contracts; model and screen_snapshot are producers."""

# Node asserts are enforced by run_node/assert returncode; lint cannot inspect JS strings.

import json
from pathlib import Path
import subprocess

import pytest

from runtime.industry_map.model import coverage, entity, relation, role
from tests.test_industry_map_ui import (
    screen_snapshot,
)  # noqa: F401: shared producer fixture

APP = Path(__file__).resolve().parents[1] / "runtime/industry_map/assets/app.js"


@pytest.fixture
def graph_snapshot(screen_snapshot):
    # Extend the real model-produced screen snapshot; never imitate internal APIs.
    supplier, buyer, anonymous = screen_snapshot["entities"]
    second = entity(
        "甲公司", anonymous=True, owner_id=buyer["id"], period="2026-01-01~2026-06-30"
    )
    uncovered = entity("未分類公司", aliases=["別稱"])
    screen_snapshot["entities"].extend([second, uncovered])
    screen_snapshot["coverage"].append(coverage(uncovered["id"]))
    screen_snapshot["roles"].append(
        role(buyer["id"], "半導體", "製造", product="量測", status="confirmed")
    )
    screen_snapshot["relations"].extend(
        [
            relation(buyer["id"], "supplies_to", second["id"], status="confirmed"),
            relation(supplier["id"], "competes_with", second["id"], status="confirmed"),
        ]
    )
    return screen_snapshot


def run_node(snapshot, assertions):
    script = """
const assert = require('node:assert/strict');
const api = require(process.argv[1]);
const snapshot = JSON.parse(process.argv[2]);
const original = JSON.stringify(snapshot);
const graph = api.createGraph(api.createIndex(snapshot));
const supplier = snapshot.entities[0].id, buyer = snapshot.entities[1].id;
const industry = graph.nodes.find(n => n.kind === 'industry' && n.name === '半導體').id;
const product = graph.nodes.find(n => n.kind === 'product' && n.name === '量測').id;
const ids = view => view.nodes.map(n => n.id);
"""
    result = subprocess.run(
        ["node", "-e", script + assertions, str(APP), json.dumps(snapshot)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fixed_graph_identity_and_records(graph_snapshot):  # testlint: allow
    run_node(
        graph_snapshot,
        """
assert.equal(graph.nodes.filter(n => n.id === product).length, 1, '共用產品固定 ID');
for (const role of snapshot.roles) {
  const classification = graph.edges.find(e => e.kind === 'classification' && e.company_id === role.company_id && e.product === role.product);
  assert.equal(classification.source_id, industry, '產業直接連公司');
  assert.equal(classification.target_id, role.company_id);
  assert.deepEqual(classification.evidence_ids, role.evidence_ids, '分類證據完整');
  const offering = graph.edges.find(e => e.kind === 'offering' && e.company_id === role.company_id && e.product === role.product);
  assert.equal(offering.source_id, role.company_id);
  assert.equal(graph.nodes.find(n => n.id === offering.target_id).name, role.product);
  assert.deepEqual(offering.evidence_ids, role.evidence_ids, '提供證據完整');
}
assert.deepEqual(graph.edges.filter(e => e.kind === 'relation'), snapshot.relations.map(e => ({...e, kind:'relation'})), '原方向/期間/狀態/證據，不推定競爭');
const anonymous = snapshot.entities.filter(e => e.name === '甲公司');
assert.equal(new Set(anonymous.map(e => e.id)).size, 2, 'owner 不合併');
for (const entity of anonymous) assert.deepEqual(graph.nodes.find(n => n.id === entity.id), entity);
const uncovered = snapshot.entities.at(-1);
assert.equal(graph.edges.find(e => e.target_id === uncovered.id).source_id, 'map:unclassified');
assert.equal(JSON.stringify(snapshot), original, '純函式不修改輸入');
for (const key of ['createIndex','filter','select','compare','selectEvidence','completePeriod']) assert.equal(typeof api[key], 'function');
assert.equal(api.select(api.createIndex(snapshot),supplier).company.id, supplier);
""",
    )


def test_expand_collapse_reset_and_shared_reachability(  # testlint: allow
    graph_snapshot,
):  # testlint: allow
    run_node(
        graph_snapshot,
        """
const initial = api.createGraphState();
assert.deepEqual(ids(api.visibleGraph(graph, initial)), ['map:root', industry, 'map:unclassified']);
let state = api.expandGraph(initial, industry);
assert.ok(ids(api.visibleGraph(graph,state)).includes(supplier));
assert.ok(!ids(api.visibleGraph(graph,state)).includes(product));
state = api.expandGraph(state,supplier);
assert.ok(ids(api.visibleGraph(graph,state)).includes(product), '逐層保留前層');
assert.ok(ids(api.visibleGraph(graph,state)).includes(industry));
assert.ok(ids(api.visibleGraph(graph,state)).includes(snapshot.entities[2].id), '關係展開匿名');
state = api.expandGraph(state,buyer);
assert.deepEqual(api.expandGraph(state,buyer), state, '重複展開無變更');
state = api.collapseGraph(state,supplier);
assert.ok(ids(api.visibleGraph(graph,state)).includes(product), '其他分支保留共用產品');
assert.deepEqual(api.collapseGraph(state,supplier),state, '重複收合');
state = api.collapseGraph(state,buyer);
assert.ok(!ids(api.visibleGraph(graph,state)).includes(product));
assert.deepEqual(api.resetGraph(state),initial);
assert.deepEqual(initial,api.createGraphState(), '原 state 不變');
const view = api.visibleGraph(graph,api.expandGraph(api.expandGraph(state,supplier),buyer));
assert.equal(new Set(ids(view)).size,view.nodes.length);
assert.equal(new Set(view.edges.map(e=>e.id)).size,view.edges.length);
""",
    )


def test_direction_pending_filters_and_detail_agree(graph_snapshot):  # testlint: allow
    run_node(
        graph_snapshot,
        """
let state = api.createGraphState();
for (const companyId of [supplier,buyer]) {
  state = api.focusGraph(graph,state,companyId);
  for (const id of [industry,supplier,buyer,'map:unclassified']) state = api.expandGraph(state,id);
  for (const direction of ['upstream','downstream','competitor']) {
    const options = {companyId,direction,includePending:false};
    const expected = snapshot.relations.filter(e => e.status !== 'pending' && (
      direction === 'upstream' ? e.predicate === 'supplies_to' && e.target_id === companyId :
      direction === 'downstream' ? e.predicate === 'supplies_to' && e.source_id === companyId :
      e.predicate === 'competes_with' && [e.source_id,e.target_id].includes(companyId)));
    const detail = api.graphRelations(graph,companyId,options);
    assert.deepEqual(detail,expected.map(e=>({...e,kind:'relation',direction:e.source_id===companyId?'outgoing':'incoming'})), '詳情方向依公司');
    const view = api.visibleGraph(graph,state,options);
    assert.deepEqual(view.edges.filter(e=>e.kind==='relation').map(e=>e.id).sort(),expected.map(e=>e.id).sort(), '圖與詳情一致');
    const allowed = new Set([companyId,...expected.flatMap(e=>[e.source_id,e.target_id])]);
    assert.ok(view.nodes.filter(n=>n.kind==='company').every(n=>allowed.has(n.id)), '連續聚焦後 roots 與分類不得重新引入排除對象');
    assert.ok(ids(view).includes(companyId), '方向篩選保留選取公司');
    assert.ok(ids(view).includes('map:root') && ids(view).includes(industry), '方向篩選保留導航');
    const selectedDetail = api.graphDetail(api.createIndex(snapshot),graph,view,companyId);
    assert.deepEqual(selectedDetail.relations.map(e=>e.id).sort(),view.edges.filter(e=>e.kind==='relation' && [e.source_id,e.target_id].includes(companyId)).map(e=>e.id).sort(),'搜尋聚焦/方向/pending後詳情只含圖中可見關係');
    assert.equal(selectedDetail.counts[direction],expected.length,'詳情篩選計數');

  }
}
const pending = api.graphRelations(graph,supplier);
assert.ok(pending.some(e=>e.status==='pending'), '可包含 pending');
assert.ok(!api.graphRelations(graph,supplier,{includePending:false}).some(e=>e.status==='pending'));
""",
    )


def test_search_focus_and_empty_relationships(graph_snapshot):  # testlint: allow
    run_node(
        graph_snapshot,
        """
const initial = api.createGraphState();
for (const [query,id] of [['1',supplier],['別稱',snapshot.entities.at(-1).id],['量測',product],['甲公司',snapshot.entities[2].id]]) {
  assert.ok(api.searchGraph(graph,query).some(n=>n.id===id), '全圖名稱/ticker/別名/產品搜尋');
  const state = api.focusGraph(graph,initial,id);
  assert.equal(state.focus,id);
  assert.ok(ids(api.visibleGraph(graph,state)).includes(id), '聚焦初始不可見節點');
}
assert.deepEqual(api.searchGraph(graph,'不存在'),[]);
assert.deepEqual(api.searchGraph(graph,''),[]);
const isolated = snapshot.entities.at(-1).id;
assert.deepEqual(api.graphRelations(graph,isolated),[], '無關係不猜測');
const state = api.expandGraph(api.focusGraph(graph,initial,isolated),isolated);
assert.equal(api.visibleGraph(graph,state).edges.filter(e=>e.kind==='relation').length,0);
""",
    )


def test_canvas_layout_drag_and_viewport(graph_snapshot):  # testlint: allow
    run_node(
        graph_snapshot,
        """
let state = api.createGraphState();
let view = api.visibleGraph(graph,state);
let positions = api.layoutGraph(view);
const initial = JSON.parse(JSON.stringify(positions));
state = api.expandGraph(state,industry);
view = api.visibleGraph(graph,state);
positions = api.layoutGraph(view,positions,industry);
for (const [id,point] of Object.entries(initial)) assert.deepEqual(positions[id],point,'既有位置穩定');
const added = view.nodes.filter(n=>!initial[n.id]);
assert.ok(added.length > 0,'產業展開子圖');
assert.equal(new Set(added.map(n=>JSON.stringify(positions[n.id]))).size,added.length,'新節點分散');
for (const n of added) assert.ok(Math.hypot(positions[n.id].x-positions[industry].x,positions[n.id].y-positions[industry].y)<2000,'在產業附近');
const before = api.edgeGeometry(positions[industry],positions[supplier]);
const moved = {...positions,[supplier]:{x:positions[supplier].x+80,y:positions[supplier].y+40}};
assert.notEqual(api.edgeGeometry(moved[industry],moved[supplier]),before,'拖動後連線更新');
assert.deepEqual(api.layoutGraph(view,moved,industry)[supplier],moved[supplier],'保留拖動位置');
assert.equal(api.edgeGeometry({x:0,y:0},{x:300,y:0}),'M 90 0 L 202 0','箭頭終點留在卡片外');
const camera = api.fitGraph(view,positions);
for (const n of view.nodes) {
  const p=positions[n.id];
  assert.ok(p.x*camera.scale+camera.x>=0 && p.x*camera.scale+camera.x<=1000,'適合画面横向');
  assert.ok(p.y*camera.scale+camera.y>=0 && p.y*camera.scale+camera.y<=650,'適合画面縱向');
}
const zoomed = api.zoomGraph(camera,2,{x:500,y:325});
assert.ok(zoomed.scale>camera.scale,'放大');
assert.equal(api.zoomGraph(camera,1e8).scale,2.5,'放大上限');
assert.equal(api.zoomGraph(camera,1e-8).scale,.15,'縮小下限');
assert.deepEqual(api.fitGraph({nodes:[]},{}),{x:500,y:325,scale:1},'空圖視野');
const collapsed = api.visibleGraph(graph,api.collapseGraph(state,industry));
assert.deepEqual(api.layoutGraph(collapsed,positions)[industry],initial[industry],'收合不移動');
const resetView=api.visibleGraph(graph,api.resetGraph());
assert.deepEqual(api.layoutGraph(resetView),initial,'重置回起點');
""",
    )


def test_canvas_html_keyboard_and_safe_labels(graph_snapshot, tmp_path):
    from html.parser import HTMLParser

    from runtime.industry_map.render import render

    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.by_id = {}
            self.parents = {}
            self.stack = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.by_id[attrs["id"]] = (tag, attrs)
                self.parents[attrs["id"]] = list(self.stack)
            if tag not in {"input", "meta", "link", "br"}:
                self.stack.append((tag, attrs))

        def handle_endtag(self, tag):
            for number in range(len(self.stack) - 1, -1, -1):
                if self.stack[number][0] == tag:
                    del self.stack[number:]
                    break

    render(graph_snapshot, tmp_path)
    page = (tmp_path / "index.html").read_text()
    elements = Elements()
    elements.feed(page)
    assert elements.by_id["map"][0] == "svg", "主畫面為 SVG"
    assert "Tab" in elements.by_id["map"][1]["aria-label"], "鍵盤操作指引"
    assert elements.by_id["map-empty"][0] == "p", "可讀空狀態"
    for action in ("zoom-in", "zoom-out", "fit-map", "collapse-node", "reset-map"):
        assert elements.by_id[action][0] == "button", f"可用鍵盤操作：{action}"
    assert "hidden" in elements.by_id["overview"][1], "公司清單非主畫面"
    for panel_id in ("finance-panel", "comparison-panel"):
        tag, attrs = elements.by_id[panel_id]
        assert tag == "details" and "open" not in attrs, f"次要入口預設收合：{panel_id}"
    for control_id in ("pending", "direction", "evidence"):
        assert not any(
            "hidden" in attrs for _, attrs in elements.parents[control_id]
        ), f"可見控制：{control_id}"
    assert any(
        attrs.get("class") == "map-toolbar" for _, attrs in elements.parents["pending"]
    ), "待查核在工具列"
    assert elements.by_id["direction"][0] == "select", "方向可選取"

    # The original render test owns full embedded-JSON escape assertions.
    # Here the graph API owns preservation of names before safe DOM rendering.
    graph_snapshot["entities"].append(entity("長名稱" * 20 + "<img onerror=alert(1)>"))
    run_node(
        graph_snapshot,
        """
const name = snapshot.entities.at(-1).name;
assert.equal(api.searchGraph(graph,'onerror').at(-1).name,name,'長名稱與惡意字串保留為文字');
assert.ok(api.visibleGraph(graph,api.focusGraph(graph,api.createGraphState(),snapshot.entities.at(-1).id)).nodes.some(n=>n.name===name),'搜尋帶入長名稱');
""",
    )


def test_graph_detail_sources_providers_and_boundary(graph_snapshot):  # testlint: allow
    uncovered = graph_snapshot["entities"][-1]
    graph_snapshot["coverage"][-1] = coverage(
        uncovered["id"],
        warnings=[{"reason": "資料缺失", "error": "<script>不可信原文</script>"}],
    )
    run_node(
        graph_snapshot,
        """
const index = api.createIndex(snapshot);
let state=api.expandGraph(api.expandGraph(api.createGraphState(),industry),supplier);
state=api.expandGraph(state,product);
const view=api.visibleGraph(graph,state);
const industryDetail=api.graphDetail(index,graph,view,industry);
assert.ok(industryDetail.neighbors.some(entry=>entry.node.id===supplier),'產業列目前可展開公司');
const offering=api.graphDetail(index,graph,view,product);
assert.deepEqual(offering.neighbors.map(entry=>entry.node.id).sort(),[supplier,buyer].sort(),'共享服務列提供公司');
assert.ok(offering.neighbors.every(entry=>entry.edge.kind==='offering'),'共享產品只表提供關係');
const sourceRecord=snapshot.relations[0];
const edge=api.graphDetail(index,graph,view,sourceRecord.id);
assert.equal(edge.isEdge,true,'點連線取得連線詳情');
assert.deepEqual(edge.item,{...sourceRecord,kind:'relation'},'兩端/期別/狀態保留原紀錄');
assert.deepEqual(edge.evidence,snapshot.evidence.filter(proof=>sourceRecord.evidence_ids.includes(proof.id)),'真正來源與原文定位');
assert.deepEqual(edge.evidenceIds,sourceRecord.evidence_ids,'證據ID不推造');
const anonymous=api.graphDetail(index,graph,view,snapshot.entities[2].id);
assert.equal(anonymous.owner.id,supplier,'匿名保留披露公司');
const isolatedView=api.visibleGraph(graph,api.expandGraph(api.focusGraph(graph,state,snapshot.entities.at(-1).id),snapshot.entities.at(-1).id));
const missing=api.graphDetail(index,graph,isolatedView,snapshot.entities.at(-1).id);
assert.deepEqual(missing.counts,{upstream:0,downstream:0,competitor:0},'無記錄不杜撰');
assert.deepEqual(missing.evidence,[],'無證據不造來源');
assert.deepEqual(missing.coverage[0].warnings,snapshot.coverage.at(-1).warnings,'dict reason/error 原文保存');
const unknown=api.graphDetail(index,graph,view,snapshot.relations.at(-1).id);
assert.equal(unknown.item.period,null,'未知期間不補猜');
assert.deepEqual(unknown.evidence,[],'競爭候選缺證據');
assert.equal(api.graphDetail(index,graph,view,'not-visible'),null,'不展示不可見資料');
""",
    )


def test_chrome_click_collapse_search_and_empty_direction(graph_snapshot, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    from runtime.industry_map.render import render

    # Real producer fixture -> offline renderer -> installed Chrome DOM boundary.
    isolated = entity("IN局部公司", market="US", ticker="INLOCAL")
    graph_snapshot["entities"].append(isolated)
    graph_snapshot["coverage"].append(coverage(isolated["id"]))
    render(graph_snapshot, tmp_path)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())

        def click_node(label):
            page.locator("#fit-map").click()
            page.locator("#map").get_by_role("button", name=label, exact=True).click()

        industry = "產業：半導體，展開"
        click_node(industry)
        click_node("公司：設備公司，展開")
        click_node("產品／服務：量測，展開")
        assert page.locator("#map .company").count() > 0, "跨層展開公司"
        assert page.locator("#map .product").count() > 0, "跨層展開產品"
        click_node(industry)
        page.locator("#collapse-node").click()
        assert page.locator("#map .company").count() == 0, "產業收合隱藏公司"
        assert page.locator("#map .product").count() == 0, "產業收合隱藏產品"
        assert page.locator("#map .edge-hit").count() == 2, "僅剩產業／待分類導航"

        # Direction anchoring must not turn ordinary selection into a search root.
        click_node(industry)
        click_node("公司：設備公司，展開")
        page.locator("#direction").select_option("upstream")
        assert page.locator("#map .company.selected").count() == 1, "空上游保留選取公司"
        assert "目前沒有已記錄關係" in page.locator("#detail").inner_text()
        page.locator("#direction").select_option("")
        click_node(industry)
        page.locator("#collapse-node").click()
        assert page.locator("#map .company").count() == 0, "方向入口不污染收合層級"

        page.locator("#reset-map").click()
        page.locator("#search").fill("INLOCAL")
        page.locator("#search-results").get_by_role(
            "button", name="公司：IN局部公司", exact=True
        ).click()
        page.locator("#direction").select_option("competitor")
        page.locator("#pending").uncheck()
        assert (
            page.locator("#map .company.selected").count() == 1
        ), "搜尋獨立入口保留公司"
        assert "無證據／待查核" in page.locator("#detail").inner_text(), "空證據明示"
        assert "競爭者：0" in page.locator("#detail").inner_text(), "空競爭不杜撰"
        page.get_by_role("button", name="全部相關來源", exact=True).click()
        assert "無證據／待查核" in page.locator("#evidence").inner_text()
        page.locator("#reset-map").click()
        assert page.locator("#map .company").count() == 0, "重置移除搜尋入口"
        assert errors == [], "Chrome 不得有 pageerror"
        browser.close()
