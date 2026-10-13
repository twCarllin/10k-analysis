"""The primary view fills the screen; optional details reserve no column."""

import pytest
from runtime.industry_map.render import render
from tests.test_industry_map_analysis_ui import analysis_snapshot


@pytest.mark.parametrize(
    "viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}]
)
def test_roomy_views_and_optional_details(viewport, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    render(analysis_snapshot(), tmp_path)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport=viewport)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())
        assert (
            page.locator("#change-panel, #clear-highlight, #center-path").count() == 0
        )
        assert page.locator("#details-panel").evaluate("e=>e.open") is False
        graph = page.locator("#map").bounding_box()
        assert graph["width"] >= viewport["width"] * 0.95
        assert graph["height"] >= (600 if viewport["width"] > 760 else 400)
        page.fill("#search", "供應公司")
        page.locator("#search-results button").click()
        page.locator("#map .center").click()
        playwright.expect(page.locator("#detail")).to_be_visible()
        page.locator("#details-panel > summary").click()
        page.locator("#table-tab").click()
        comparison = page.locator("#analysis-comparison")
        playwright.expect(comparison).to_be_visible()
        assert comparison.bounding_box()["height"] >= (
            650 if viewport["width"] > 760 else 500
        )
        assert comparison.evaluate("e=>getComputedStyle(e).maxHeight") == "none"
        source = comparison.locator('td[data-metric="gross_margin"] button').first
        source.click()
        playwright.expect(page.locator("#evidence")).to_be_visible()
        assert page.locator("#details-panel").evaluate("e=>e.open") is True
        page.locator("#details-panel > summary").click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        assert errors == []
        browser.close()
