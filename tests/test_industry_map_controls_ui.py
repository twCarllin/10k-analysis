"""Native map tool disclosure preserves the existing map interaction state."""

import pytest

from runtime.industry_map.model import coverage, entity, snapshot
from runtime.industry_map.render import render


@pytest.mark.parametrize(
    "viewport", [{"width": 1400, "height": 1000}, {"width": 390, "height": 844}]
)
def test_map_tools_disclosure_preserves_controls_and_map(viewport, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    company = entity("控制測試公司", market="TW", ticker="8046")
    other = entity("另一測試公司", market="TW", ticker="2330")
    scene = snapshot(
        entities=[company, other],
        coverage=[coverage(company["id"]), coverage(other["id"])],
    )
    render(scene, tmp_path)
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport=viewport)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())
        tools = page.locator("#map-tools")
        toggle = tools.locator("summary")
        assert tools.evaluate("el => el.open") is True
        playwright.expect(page.locator("#fit-map")).to_be_visible()
        page.fill("#search", "8046")
        page.locator("#search-results button").first.click()
        page.locator("#direction").select_option("upstream")
        page.locator("#pending").uncheck()
        page.locator("#zoom-in").click()
        camera = page.locator("#map > g").first.get_attribute("transform")
        center = page.locator("#map .center").get_attribute("data-node-id")
        toggle.click()
        assert tools.evaluate("el => el.open") is False
        for control in (
            "zoom-in",
            "zoom-out",
            "fit-map",
            "back-center",
            "collapse-node",
            "reset-map",
            "direction",
            "pending",
        ):
            playwright.expect(page.locator("#" + control)).not_to_be_visible()
        playwright.expect(page.locator("#map")).to_be_visible()
        assert page.locator("#map .center").get_attribute("data-node-id") == center
        assert page.locator("#map > g").first.get_attribute("transform") == camera
        assert page.locator("#direction").input_value() == "upstream"
        assert page.locator("#pending").is_checked() is False
        toggle.focus()
        toggle.press("Enter")
        assert tools.evaluate("el => el.open") is True
        playwright.expect(page.locator("#fit-map")).to_be_visible()
        assert page.locator("#map > g").first.get_attribute("transform") == camera
        assert page.locator("#map .center").get_attribute("data-node-id") == center
        assert page.locator("#direction").input_value() == "upstream"
        assert page.locator("#pending").is_checked() is False
        toggle.click()
        page.locator("#map .center").click()
        playwright.expect(page.locator("#detail")).to_contain_text("控制測試公司")
        # Search retains the disclosure state; its existing filter reset is unchanged.
        page.fill("#search", "2330")
        page.locator("#search-results button").first.click()
        assert tools.evaluate("el => el.open") is False
        assert page.locator("#map .center").get_attribute("data-node-id") == other["id"]
        toggle.focus()
        toggle.press("Enter")
        playwright.expect(page.locator("#fit-map")).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1"
        )
        assert errors == []
        browser.close()
