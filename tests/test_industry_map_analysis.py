"""A3/A4/A5 black-box checks through model-produced snapshots and Node."""

import json
from pathlib import Path
import subprocess

from runtime.industry_map.model import entity, evidence, observation, snapshot

APP = Path(__file__).resolve().parents[1] / "runtime/industry_map/assets/app.js"
PERIOD = "2026-01-01~2026-06-30"
PRIOR = "2025-01-01~2025-06-30"


def producer():
    company = entity("測試公司", market="TW", ticker="1234")
    return snapshot(entities=[company]), company["id"]


def add(data, company_id, metric, value, **options):
    pointer = options.pop("pointer", "/bundle/statements/rows/0/current")
    proof = evidence("producer.json", locator={"pointer": pointer}, quote=str(value))
    data["evidence"].append(proof)
    defaults = dict(
        period=PERIOD, basis="H1", scope="company", unit="仟元", currency="TWD"
    )
    defaults.update(options)
    data["observations"].append(
        observation(company_id, metric, value, evidence_ids=[proof["id"]], **defaults)
    )


def run_node(data, assertions):
    script = """
const assert = require('node:assert/strict');
const api = require(process.argv[1]);
const snapshot = JSON.parse(process.argv[2]);
const index = api.createIndex(snapshot), id = snapshot.entities[0].id;
const summary = () => api.financialSummary(index,id,'2026-01-01~2026-06-30','H1','company');
"""
    result = subprocess.run(
        ["node", "-e", script + assertions, str(APP), json.dumps(data)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_analysis_amounts_capex_and_same_period_delta():  # testlint: allow
    data, company_id = producer()
    for metric, value in dict(
        revenue=100,
        gross_profit=40,
        operating_income=20,
        net_income=10,
        cfo=5,
        capex=-15,
    ).items():
        add(data, company_id, metric, value)
    add(data, company_id, "gross_margin", 30, unit="%", period=PRIOR)
    add(data, company_id, "net_income_parent", 99)
    add(data, company_id, "revenue", 999, unit="unknown")
    run_node(
        data,
        """
const cells=summary().cells;
assert.deepEqual(Object.values(cells).map(c=>c.value),[40,20,10,-10],'A3 四率；整體淨利；A4 FCF可負');
assert.equal(cells.gross_margin.delta,10,'A5 去年同期百分點');
assert.equal(cells.gross_margin.priorPeriod,'2025-01-01~2025-06-30');
assert.equal(cells.gross_margin.currentPeriod,'2026-01-01~2026-06-30');
assert.equal(cells.gross_margin.priorEvidenceIds.length,1,'A5 去年來源可查');
assert.equal(cells.net_margin.delta,null,'A5 無同期');
assert.equal(cells.fcf_margin.inputs.capex_outflow,15,'A4 ledger負值转支出');
assert.equal(cells.fcf_margin.formula,'(cfo - capex_outflow) / revenue * 100');
assert.equal(cells.fcf_margin.evidenceIds.length,3,'A3 保留全部金額來源');
assert.equal(summary().deltaUnit,'百分點');
""",
    )


def test_analysis_direct_ratio_and_local_selection():  # testlint: allow
    data, company_id = producer()
    add(
        data,
        company_id,
        "gross_margin",
        61,
        unit="%",
        formula="gross_profit / revenue * 100",
        inputs={"gross_profit": 61, "revenue": 100},
        period="115-01-01~115-06-30",
    )
    add(data, company_id, "gross_margin", 99, unit="unknown")
    add(data, company_id, "gross_margin", 50, unit="%", period=PRIOR, basis="FY")
    add(
        data,
        company_id,
        "fcf_margin",
        -4,
        unit="%",
        formula="fcf / revenue * 100",
        inputs={"fcf": -4, "revenue": 100},
    )
    unrelated = entity("不相關公司", market="TW", ticker="9999")
    data["entities"].append(unrelated)
    add(data, unrelated["id"], "revenue", 1, period="2029-01-01~2029-12-31", basis="FY")
    add(data, company_id, "revenue", 1, period="2028")
    run_node(
        data,
        """
const result=api.analysisComparison(index,[id,'company:TW:missing']);
assert.equal(result.period,'2026-01-01~2026-06-30','A5 最新局部期間');
assert.equal(result.periods.length,2,'A5 排除不相關公司與不完整期間');
assert.equal(result.rows.length,2,'A5 缺公司保留');
assert.equal(result.rows[1].cells.gross_margin.reason,'未匯入');
const cell=result.rows[0].cells.gross_margin;
assert.equal(cell.value,61,'A3 unknown單位不污染有效原百分比');
assert.equal(cell.delta,null,'A5 不混FY與H1');
assert.deepEqual(cell.inputs,{gross_profit:61,revenue:100});
assert.equal(cell.evidenceIds.length,1,'A3 保留原比率來源');
assert.equal(result.rows[0].cells.fcf_margin.value,-4,'A3 完整直接FCF');
assert.equal(api.completePeriod('ROC115-01-01~115-06-30'),result.period);
assert.equal(api.completePeriod('2026-02-30~2026-06-30'),null);
assert.equal(api.analysisComparison(index,[id],{period:'2027-01-01~2027-06-30',basis:'H1',scope:'company'}).rows[0].cells.gross_margin.value,null,'A5 不回退期別');
""",
    )


def test_analysis_blocks_invalid_values_and_sources():  # testlint: allow
    data, company_id = producer()
    add(data, company_id, "revenue", 0)
    add(data, company_id, "gross_profit", 20)
    add(data, company_id, "operating_margin", 10, unit="%")
    add(data, company_id, "operating_margin", 11, unit="%")
    add(data, company_id, "net_margin", 5, unit="%")
    data["observations"][-1]["evidence_ids"] = ["missing"]
    add(data, company_id, "fcf_margin", 8, unit="%")
    run_node(
        data,
        """
const cells=summary().cells;
assert.equal(cells.gross_margin.reason,'營收為零','A3 零營收阻擋');
assert.equal(cells.operating_margin.value,null,'A3 矛盾原百分比阻擋');
assert.equal(cells.net_margin.reason,'來源缺漏','A3 來源缺漏阻擋');
assert.equal(cells.fcf_margin.value,null,'A3 不完整FCF公式阻擋');
const direct=snapshot.observations.find(o=>o.metric==='fcf_margin');
direct.value=25;
direct.formula='(cfo + capex) / revenue * 100';
direct.inputs={fcf:25,cfo:20,capex:5,revenue:100};
assert.equal(summary().cells.fcf_margin.value,null,'A4 正支出不能被fcf捷徑接受');
direct.formula='(cfo + capex) / revenue * 100 + 1';
direct.inputs={cfo:20,capex:-5,revenue:100};
direct.value=15;
assert.equal(summary().cells.fcf_margin.value,null,'A3 不接受額外公式項');
direct.formula='fcf / revenue * 100';
direct.inputs={fcf:25,cfo:20,capex:5,revenue:100};
direct.value=25;
assert.equal(summary().cells.fcf_margin.value,null,'A3 fcf與原現金流矛盾阻擋');
direct.inputs={fcf:15,cfo:20,capex:5,revenue:100};
direct.value=15;
assert.equal(summary().cells.fcf_margin.value,15,'A3 fcf與原現金流一致');
direct.formula='(cfo - capex) / revenue * 100';
assert.equal(summary().cells.fcf_margin.value,15,'A4 正支出合法減項');
direct.formula='(cfo + capex) / revenue * 100';
direct.inputs={fcf:15,cfo:20,capex:-5,revenue:100};
assert.equal(summary().cells.fcf_margin.value,15,'A4 TW負支出合法加項');
direct.formula='fcf / revenue * 100';
direct.inputs={fcf:5044105,revenue:25389128};
direct.value=5044105/25389128*100;
assert.equal(summary().cells.fcf_margin.value,direct.value,'A3 真TW直接FCF保留');

""",
    )


def test_analysis_xbrl_and_incompatible_amounts():  # testlint: allow
    data, company_id = producer()
    add(data, company_id, "revenue", 100, unit="USD", currency="USD")
    add(data, company_id, "cfo", 20, unit="USD", currency="USD")
    add(
        data,
        company_id,
        "capex",
        5,
        unit="USD",
        currency="USD",
        pointer="/facts/us-gaap/PaymentsToAcquirePropertyPlantAndEquipment/units/USD/0/val",
        quality={
            "source": "xbrl",
            "concept": "PaymentsToAcquirePropertyPlantAndEquipment",
        },
    )
    add(data, company_id, "gross_profit", 40)
    add(data, company_id, "net_income", 2, basis="unknown")
    run_node(
        data,
        """
assert.equal(summary().cells.fcf_margin.value,15,'A4 XBRL正支出');
assert.equal(summary().cells.gross_margin.value,null,'A3 不相容金額');
assert.equal(summary().cells.net_margin.value,null,'A3 unknown basis不能混用');
snapshot.observations.find(o=>o.metric==='capex').value=-5;
assert.equal(summary().cells.fcf_margin.value,null,'A4 矛盾符號阻擋');
snapshot.observations.find(o=>o.metric==='capex').quality=null;
assert.equal(summary().cells.fcf_margin.value,null,'A4 無來源不能猜符號');
snapshot.observations.find(o=>o.metric==='revenue').value=Infinity;
assert.equal(summary().cells.fcf_margin.value,null,'A3 非有限值阻擋');
""",
    )


def test_analysis_defaults_to_latest_usable_local_period():  # testlint: allow
    data, company_id = producer()
    for metric, value in dict(
        revenue=100,
        gross_profit=40,
        operating_income=20,
        net_income=10,
        cfo=5,
        capex=-15,
    ).items():
        add(data, company_id, metric, value)
    august = "2026-01-01~2026-08-31"
    add(data, company_id, "revenue", 200, period=august, basis="other")
    add(data, company_id, "gross_margin", 50, period=august, basis="other", unit="%")
    data["observations"][-1]["evidence_ids"] = ["missing"]
    run_node(
        data,
        """
const result=api.analysisComparison(index,[id]);
assert.equal(result.period,'2026-01-01~2026-06-30','A5 更新期別無可用比率時選H1');
assert.equal(result.periods[0].period,result.period,'A5 最新可用位於選單首項');
assert.equal(result.periods.length,1,'A5 缺來源比率不算可用');
assert.deepEqual(Object.values(result.rows[0].cells).map(c=>c.value),[40,20,10,-10],'A5 H1資料不變');
const explicit=api.analysisComparison(index,[id],{period:'2026-01-01~2026-08-31',basis:'other',scope:'company'});
assert.equal(explicit.period,'2026-01-01~2026-08-31','A5 明確手選不回退');
assert.equal(explicit.rows[0].cells.gross_margin.reason,'來源缺漏');
""",
    )
    add(data, company_id, "net_margin", 12, period=august, basis="other", unit="%")
    run_node(
        data,
        """
const result=api.analysisComparison(index,[id]);
assert.equal(result.period,'2026-01-01~2026-08-31','A5 最新期別只有一率有效仍可預設');
assert.equal(result.rows[0].cells.net_margin.value,12);
assert.equal(result.rows[0].cells.operating_margin.value,null,'A5 不混H1數值');
""",
    )
    empty, empty_id = producer()
    add(empty, empty_id, "revenue", 100, period=august, basis="other")
    run_node(
        empty,
        """
const result=api.analysisComparison(index,[id]);
assert.equal(result.period,'2026-01-01~2026-08-31','A5 全無可用比率保留候選');
assert.equal(result.periods.length,1);
assert.equal(result.rows[0].cells.net_margin.reason,'缺資料','A5 保留缺資料原因');
""",
    )
