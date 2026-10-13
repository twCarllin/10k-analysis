"""B2/B3/B4 through model-produced snapshots and public Node exports."""

import json
from pathlib import Path
import subprocess

from runtime.industry_map.model import entity, evidence, observation, relation, snapshot

APP = Path(__file__).resolve().parents[1] / "runtime/industry_map/assets/app.js"
PERIOD = "2026-01-01~2026-06-30"


def producer():
    company = entity("測試公司", market="TW", ticker="1234")
    return snapshot(entities=[company]), company["id"]


def add_ratio(data, company_id, metric, value, period=PERIOD, basis="H1"):
    proof = evidence(
        "producer.json", locator={"pointer": f"/{period}/{metric}"}, quote=str(value)
    )
    data["evidence"].append(proof)
    data["observations"].append(
        observation(
            company_id,
            metric,
            value,
            period=period,
            basis=basis,
            scope="company",
            unit="%",
            evidence_ids=[proof["id"]],
            formula="fcf / revenue * 100" if metric == "fcf_margin" else None,
            inputs={"fcf": value, "revenue": 100} if metric == "fcf_margin" else None,
        )
    )


def share(data, value, period=PERIOD, kind="sales_share", **overrides):
    proof = evidence(
        "t8.json",
        locator={"pointer": f"/{kind}/{period}/{value}/pct"},
        quote=str(value),
    )
    data["evidence"].append(proof)
    return dict(
        kind=kind,
        value=value,
        period=period,
        unit="%",
        currency=None,
        evidence_ids=[proof["id"]],
        **overrides,
    )


def run_node(data, assertions):
    result = subprocess.run(
        [
            "node",
            "-e",
            """
const assert=require('node:assert/strict'), api=require(process.argv[1]);
const snapshot=JSON.parse(process.argv[2]), index=api.createIndex(snapshot), id=snapshot.entities[0].id;
const selection={period:'2026-01-01~2026-06-30',basis:'H1',scope:'company'};
""" + assertions,
            str(APP),
            json.dumps(data),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_financial_trend_period_budget_gaps_and_sources():  # testlint: allow
    data, company_id = producer()
    for year in range(2016, 2028):
        add_ratio(
            data,
            company_id,
            "gross_margin",
            None if year == 2023 else year - 2000,
            f"{year}-01-01~{year}-06-30",
        )
    add_ratio(data, company_id, "gross_margin", 90, "2026-04-01~2026-06-30")
    add_ratio(data, company_id, "gross_margin", 91, "2026-01-01~2026-06-30", basis="FY")
    run_node(
        data,
        """
const trend=api.financialTrend(index,id,'gross_margin',selection);
assert.equal(trend.points.length,8,'B2 最多8期');
assert.equal(trend.points[0].period,'2019-01-01~2019-06-30','B2 最後8期');
assert.equal(trend.points.at(-1).value,26,'B2 不混口徑/長度/未來資料');
const gap=trend.points.find(p=>p.period.startsWith('2023'));
assert.equal(gap.value,null,'B2 缺值斷線');
assert.ok(gap.reason);
assert.equal(gap.evidenceIds.length,1,'B2 缺值保留來源');
assert.equal(trend.points.at(-1).evidenceIds.length,1,'B2 值保留來源');
const single=api.financialTrend(index,id,'gross_margin',{...selection,period:'2016-01-01~2016-06-30'});
assert.equal(single.points.length,1);
assert.match(single.reason,/僅一個期別/,'B2 不造季度');
assert.equal(api.financialTrend(index,'missing','gross_margin',selection).points.length,0);
for(const item of snapshot.observations) item.value=null;
assert.match(api.financialTrend(index,id,'gross_margin',selection).reason,/無有效比率/,'B2 多期全缺不能判趨勢');
snapshot.observations.find(o=>o.period===selection.period&&o.basis==='H1').value=26;
assert.match(api.financialTrend(index,id,'gross_margin',selection).reason,/僅一個有效值/,'B2 多期只有一個有效值');
""",
    )


def test_research_signals_facts_threshold_and_provenance():  # testlint: allow
    data, company_id = producer()
    for metric, prior, current in [
        ("gross_margin", 40, 35),
        ("operating_margin", 10, 12),
        ("net_margin", 8, 10),
        ("fcf_margin", 4, 4.05),
    ]:
        add_ratio(data, company_id, metric, prior, "2025-01-01~2025-06-30")
        add_ratio(data, company_id, metric, current)
    run_node(
        data,
        """
const tips=api.researchSignals(index,id,selection);
assert.equal(tips.length,2,'B3 組合提示最多3且不重複');
assert.match(tips[0].text,/下降 5.00 百分點.*上升 2.00 百分點.*可追查費用率或業務組合/);
assert.match(tips[1].text,/可追查營運資金與資本支出/);
assert.equal(tips[1].threshold.absoluteDeltaBelow,0.1,'B3 明示持平門檻');
for(const tip of tips) {assert.equal(tip.current.length,2);assert.equal(tip.prior.length,2);assert.equal(tip.evidenceIds.length,4,'B3 本期與去年來源');}
assert.equal(api.researchSignals(index,'missing',selection)[0].followup,'補資料','B3 缺資料不產生數字結論');
snapshot.observations.find(o=>o.metric==='fcf_margin'&&o.period===selection.period).value=4.2;
snapshot.observations.find(o=>o.metric==='fcf_margin'&&o.period===selection.period).inputs.fcf=4.2;
assert.ok(!api.researchSignals(index,id,selection).some(t=>t.threshold),'B3 超過門檻不能持平');
snapshot.observations.find(o=>o.metric==='fcf_margin'&&o.period===selection.period).value=4.1;
snapshot.observations.find(o=>o.metric==='fcf_margin'&&o.period===selection.period).inputs.fcf=4.1;
assert.ok(!api.researchSignals(index,id,selection).some(t=>t.threshold),'B3 等於0.1門檻不能持平');
snapshot.observations.find(o=>o.metric==='gross_margin'&&o.period===selection.period).quality={conflict:'unresolved'};
assert.ok(!api.researchSignals(index,id,selection).some(t=>t.followup==='可追查費用率或業務組合'),'B3 衝突不能結論');
""",
    )


def test_relation_strength_latest_kind_conflicts_and_unknown():  # testlint: allow
    data, company_id = producer()
    disclosures = [
        share(data, 25),
        share(data, 25, period="ROC115-01-01~115-06-30"),
        share(data, 80, kind="purchase_share"),
        share(data, 99, period="2025-01-01~2025-06-30"),
    ]
    data["relations"].append(
        relation(company_id, "supplies_to", "buyer", disclosures=disclosures)
    )
    run_node(
        data,
        """
const edge=snapshot.relations[0], strength=()=>api.relationStrength(index,edge);
assert.equal(strength().value,25,'B4 不加總多來源同值');
assert.equal(strength().width,5,'B4 平方根線寬');
assert.equal(strength().evidenceIds.length,2,'B4 合併同值來源');
assert.match(strength().denominator,/供應商/,'B4 sales優先');
const tips=api.researchSignals(index,id,selection);
assert.match(tips[0].text,/25%.*2026.*供應商/,'B3 占比期間分母');
edge.source_id='supplier';edge.target_id=id;
assert.ok(!api.researchSignals(index,id,selection).some(t=>t.metrics.includes('sales_share')),'B1 incoming sales不是中心營收占比');
assert.match(api.researchSignals(index,id,selection)[0].text,/進貨占比 80%/,'B3 混合kind買方讀自身purchase');
edge.source_id=id;edge.target_id='buyer';
edge.disclosures[1].value=26;
assert.equal(api.relationStrength(index,edge,'sales_share').value,null,'B4 最新衝突不回退舊值');
assert.equal(strength().value,80,'B4 sales衝突仍可用合法purchase');
edge.disclosures[1].value=25;edge.disclosures[0].evidence_ids=['missing'];
assert.equal(api.relationStrength(index,edge,'sales_share').value,null,'B4 最新缺來源不回退');
edge.disclosures=edge.disclosures.filter(d=>d.kind==='purchase_share');
assert.match(strength().denominator,/買方同期總進貨/,'B4 purchase不称營收');
assert.ok(!api.researchSignals(index,id,selection).some(t=>t.metrics.includes('purchase_share')),'B1 outgoing purchase不是中心進貨占比');
edge.source_id='supplier';edge.target_id=id;
assert.ok(api.researchSignals(index,id,selection).some(t=>t.metrics.includes('purchase_share')),'B1 incoming purchase為中心進貨占比');
edge.disclosures[0].value=0;
assert.equal(strength().value,0,'B4 零為已揭露');assert.equal(strength().width,2);
edge.disclosures[0].value=101;
assert.equal(strength().value,null,'B4 限定0..100');
edge.disclosures[0].value=Infinity;
assert.equal(strength().value,null,'B4 非有限值不決定線寬');
edge.disclosures[0].value=10;edge.disclosures[0].unit='unknown';
assert.equal(strength().value,null,'B4 未知單位不決定線寬');
edge.disclosures[0].unit='%';edge.disclosures[0].period=null;
assert.equal(strength().value,null,'B4 缺期別不猜');
edge.disclosures=[];
assert.equal(strength().value,null,'B4 未知非零');assert.equal(strength().width,2);assert.ok(strength().reason);
""",
    )


def test_relation_strength_legal_kind_fallback_and_latest_unknown():  # testlint: allow
    data, company_id = producer()
    data["relations"].append(
        relation(
            company_id,
            "supplies_to",
            "buyer",
            disclosures=[
                share(data, 101),
                share(data, 80, kind="purchase_share"),
                share(data, 25, period="2025-01-01~2025-06-30"),
            ],
        )
    )
    run_node(
        data,
        """
const edge=snapshot.relations[0];
assert.equal(api.relationStrength(index,edge).value,80,'B4 非法sales不能阻擋合法purchase');
assert.equal(api.relationStrength(index,edge).kind,'purchase_share');
assert.equal(api.relationStrength(index,edge,'sales_share').value,null,'B4 sales最新非法不回退25');
assert.equal(api.relationStrength(index,edge,'sales_share').period,selection.period);
""",
    )
    data["relations"][0]["disclosures"].append(
        share(data, None, period="2027-01-01~2027-06-30", kind="purchase_share")
    )
    run_node(
        data,
        """
const edge=snapshot.relations[0], result=api.relationStrength(index,edge);
assert.equal(result.value,null,'B4 purchase更新unknown不能回退80');
assert.equal(api.relationStrength(index,edge,'purchase_share').period,'2027-01-01~2027-06-30');
assert.ok(api.relationStrength(index,edge,'purchase_share').reason);
""",
    )
