"""C1-C5: public offline renderer and actual keyboard/browser operations."""

from playwright.sync_api import expect, sync_playwright

from runtime.industry_map.model import observation, entity, relation
from runtime.industry_map.render import render
from tests.test_industry_map_signals_ui import signals_snapshot
from tests.test_industry_map_analysis_ui import PERIOD, PRIOR


def test_change_highlights_and_supply_trace(tmp_path):
    data = signals_snapshot()
    supplier, buyer = data["entities"][:2]
    peer = entity("競爭公司", market="TW", ticker="999")
    data["entities"].append(peer)
    data["relations"].append(
        relation(supplier["id"], "competes_with", peer["id"], status="confirmed")
    )
    proof_ids = [data["evidence"][0]["id"]]
    for company, metric, value in [
        (supplier, "revenue", 1000),
        (buyer, "capex", 200),
    ]:
        data["observations"].append(
            observation(
                company["id"],
                metric,
                value,
                unit="千元",
                currency="TWD",
                period=PERIOD,
                basis="consolidated",
                scope="company",
                evidence_ids=proof_ids,
                quality={
                    "source": "xbrl",
                    "concept": "PaymentsToAcquirePropertyPlantAndEquipment",
                },
            )
        )
    data["relations"][1]["disclosures"] = [
        {
            "kind": "sales_amount",
            "value": 9999,
            "unit": "unknown",
            "currency": "TWD",
            "period": PERIOD,
            "evidence_ids": [],
        }
    ]
    data["observations"].append(
        observation(
            supplier["id"],
            "cfo",
            7777,
            unit="千元",
            currency="TWD",
            period=PERIOD,
            basis="standalone",
            scope="company",
            evidence_ids=proof_ids,
        )
    )
    render(data, tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())
        expect(page.locator("#change-highlights")).to_contain_text(
            "沒有可核對的同比變化"
        )
        expect(page.locator("#supply-trace")).to_be_hidden()
        page.locator("#search").fill("供應公司")
        page.locator("#search-results button").click()
        highlights = page.locator("#change-highlights article")
        assert (
            highlights.count() == 3
        ), "C1 visible-company delta signals limited to three"
        assert (
            "同比" in highlights.first.inner_text()
        ), "C1 actual delta, not static values"
        highlights.first.locator("button").first.press("Enter")
        assert (
            page.locator(".map-node.change-muted").count() > 0
        ), "C2 unrelated nodes fade"
        assert (
            page.locator(
                '.map-node[data-node-id="' + supplier["id"] + '"].change-muted'
            ).count()
            == 0
        ), "C2 company remains visible"
        assert (
            page.locator(".map-edge.competing.change-muted").count() == 1
        ), "C2 competitor edge fades"
        unrelated_before_drag = page.locator(".map-node.change-muted").count()
        point = page.locator("#map .map-node:not(.center)").first.bounding_box()
        page.mouse.move(
            point["x"] + point["width"] / 2, point["y"] + point["height"] / 2
        )
        page.mouse.down()
        page.mouse.move(
            point["x"] + point["width"] / 2 + 32,
            point["y"] + point["height"] / 2 + 18,
            steps=4,
        )
        page.mouse.up()
        assert (
            page.locator(".map-node.change-muted").count() == unrelated_before_drag
        ), "C2 drag preserves emphasis"
        page.locator("#clear-highlight").click()
        assert page.locator(".change-muted").count() == 0, "C2 clear restores graph"
        highlights.first.locator("button").first.click()
        page.locator("#pending").uncheck()
        assert (
            page.locator(".change-muted").count() == 0
        ), "C2 filter clears stale emphasis"
        highlights.first.locator("button").first.click()
        page.locator("#search").fill("客戶0")
        page.locator("#search-results button").click()
        assert (
            page.locator(".change-muted").count() == 0
        ), "C2 new center clears stale emphasis"
        page.locator("#search").fill("供應公司")
        page.locator("#search-results button").click()
        assert (
            page.evaluate("getComputedStyle(document.documentElement).backgroundColor")
            == "rgb(5, 5, 5)"
        ), "DoD dark theme remains active"
        edge = page.locator("#map .map-edge").first
        edge.locator(".edge-hit").press("Space")
        trace = page.locator("#supply-trace")
        expect(trace).to_be_visible()
        assert trace.locator(".trace-step").count() == 4, "C3 four steps"
        demand = trace.locator(".trace-step").nth(0)
        assert "下單量：0 台" in demand.inner_text(), "C3 zero order is retained"
        assert (
            "已實現銷貨：120 千元 TWD" in demand.inner_text()
        ), "C3 actual sale separate"
        assert (
            "客戶資本支出：200 千元 TWD" in demand.inner_text()
        ), "C3 actual customer capex"
        assert (
            "不能代替" in demand.inner_text() and "不是訂單" in demand.inner_text()
        ), "C3 explicit scope"
        assert "公司：客戶0" in demand.inner_text(), "C4 demand company"
        assert (
            "營業現金流金額：缺口：缺資料" in trace.inner_text()
        ), "C4 incompatible basis amount gap"
        assert "7777" not in trace.inner_text(), "C4 incompatible basis value not used"
        assert (
            "公司整體營收：1000 千元 TWD" in trace.inner_text()
        ), "C4 revenue value and unit"
        assert (
            "毛利率：30.00 %" in trace.inner_text()
            and "自由現金流／營收：-5.00 %" in trace.inner_text()
        ), "C4 ratios keep percent units"
        assert (
            PERIOD in trace.inner_text() and "交易獨立標期" in trace.inner_text()
        ), "C4 periods independent"
        demand.get_by_role("button", name="追查來源").first.press("Enter")
        expect(page.locator("#evidence")).to_contain_text("<script>來源原文</script>")
        assert page.locator("#evidence script").count() == 0, "C5 source safe text"
        page.locator('#section-more [data-zone="downstream"]').click()
        expect(trace).to_be_visible()
        page.locator("#pending").check()
        expect(trace).to_be_visible()
        page.locator("#analysis-period").select_option("1")
        expect(trace).to_contain_text(PRIOR)
        expect(trace).to_contain_text("缺口：缺資料")
        assert (
            "1000 千元 TWD" not in trace.inner_text()
        ), "C5 financial selection updates"
        assert (
            "120 千元 TWD" in trace.inner_text()
        ), "C4 transaction keeps original period"
        expect(page.locator("#change-highlights")).to_contain_text(
            "沒有可核對的同比變化"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        ), "C5 mobile no page overflow"
        page.locator("#direction").select_option("upstream")
        expect(trace).to_be_hidden()
        page.locator("#direction").select_option("")
        page.locator("#map .map-edge").nth(1).locator(".edge-hit").press("Enter")
        expect(trace).to_contain_text("訂單：未揭露")
        expect(trace).to_contain_text("已實現銷貨：資料不完整")
        assert (
            "9999" not in trace.inner_text()
        ), "C4 unknown unit and missing evidence block value"
        expect(trace).to_contain_text("缺口")
        page.locator("#search").fill("客戶1")
        page.locator("#search-results button").click()
        expect(trace).to_be_visible()
        page.locator("#search").fill("客戶6")
        page.locator("#search-results button").click()
        expect(trace).to_be_hidden()
        assert errors == [], "C5 no browser error"
        browser.close()
