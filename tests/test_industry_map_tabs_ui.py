"""View tabs hide inactive controls without resetting map state."""

import pytest

from runtime.industry_map.model import coverage, entity, evidence, observation, snapshot
from runtime.industry_map.render import render


@pytest.mark.parametrize(
    "viewport", [{"width": 1400, "height": 1000}, {"width": 390, "height": 844}]
)
def test_map_table_tabs_keep_state_and_search(viewport, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    companies = [
        entity("第一公司", market="TW", ticker="8046"),
        entity("第二公司", market="TW", ticker="2330"),
    ]
    proof = evidence("fixture.json", locator={"pointer": "/margin"}, quote="margin")
    observations = [
        observation(
            c["id"],
            "gross_margin",
            30,
            period=period,
            basis="consolidated",
            scope="company",
            unit="%",
            evidence_ids=[proof["id"]],
        )
        for c in companies
        for period in ("2025-01-01~2025-12-31", "2024-01-01~2024-12-31")
    ]
    render(
        snapshot(
            entities=companies,
            coverage=[coverage(c["id"]) for c in companies],
            observations=observations,
            evidence=[proof],
        ),
        tmp_path,
    )
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport=viewport)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto((tmp_path / "index.html").as_uri())
        graph = page.locator("#graph-view")
        table = page.locator("#table-view")
        playwright.expect(graph).to_be_visible()
        playwright.expect(table).not_to_be_visible()
        page.fill("#search", "8046")
        page.locator("#search-results button").first.click()
        page.locator("#direction").select_option("upstream")
        page.locator("#zoom-in").click()
        camera = page.locator("#map > g").first.get_attribute("transform")
        page.locator("#map-tools summary").click()
        page.locator("#table-tab").click()
        playwright.expect(table).to_be_visible()
        playwright.expect(graph).not_to_be_visible()
        playwright.expect(page.locator("#analysis-comparison")).to_contain_text(
            "第一公司"
        )
        page.locator("#analysis-period").select_option("1")
        period = page.locator("#analysis-period").input_value()
        assert period == "1"
        page.locator("#table-tab").press("ArrowLeft")
        playwright.expect(page.locator("#graph-tab")).to_be_focused()
        assert page.locator("#graph-tab").get_attribute("aria-selected") == "true"
        assert page.locator("#table-tab").get_attribute("tabindex") == "-1"
        assert page.locator("#map > g").first.get_attribute("transform") == camera
        assert (
            page.locator("#map .center").get_attribute("data-node-id")
            == companies[0]["id"]
        )
        assert page.locator("#direction").input_value() == "upstream"
        assert page.locator("#map-tools").evaluate("e => e.open") is False
        page.locator("#graph-tab").press("End")
        playwright.expect(page.locator("#table-tab")).to_be_focused()
        assert page.locator("#analysis-period").input_value() == period
        page.fill("#search", "2330")
        page.locator("#search-results button").first.click()
        assert page.locator("#table-tab").get_attribute("aria-selected") == "true"
        playwright.expect(page.locator("#analysis-comparison")).to_contain_text(
            "第二公司"
        )
        page.locator("#table-tab").focus()
        page.locator("#table-tab").press("Home")
        playwright.expect(graph).to_be_visible()
        assert (
            page.locator("#map .center").get_attribute("data-node-id")
            == companies[1]["id"]
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1"
        )
        assert errors == []
        browser.close()
