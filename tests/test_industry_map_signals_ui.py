"""B4/B5 real producer → renderer → Chrome boundary."""

from playwright.sync_api import expect, sync_playwright

from runtime.industry_map.model import evidence, observation
from runtime.industry_map.render import render
from tests.test_industry_map_analysis_ui import analysis_snapshot, PERIOD, PRIOR

ANNUAL = "2025-01-01~2025-12-31"


def signals_snapshot():
    data = analysis_snapshot()
    proof = evidence(
        "shares.json",
        locator={"pointer": "/customers/0/pct"},
        quote="占比原文",
        period=ANNUAL,
    )
    data["evidence"].append(proof)
    share = {
        "kind": "sales_share",
        "value": 18.02,
        "unit": "%",
        "currency": None,
        "period": ANNUAL,
        "evidence_ids": [proof["id"]],
    }
    data["relations"][0]["disclosures"].append(share)
    data["relations"][1]["disclosures"] = [{**share, "value": 0}]
    data["relations"][3]["disclosures"] = [
        {**share, "kind": "purchase_share", "value": 10}
    ]
    for row in data["observations"]:
        if row["metric"] == "gross_margin" and row["period"] == PERIOD:
            row["value"] = 30.123456789
        if row["metric"] == "fcf_margin" and row["period"] == PRIOR:
            row["value"] = -5.05
            row["inputs"]["capex"] = 10.05
    return data


def test_share_width_trend_research_and_navigation(tmp_path):
    data = signals_snapshot()
    data["evidence"][0]["quote"] = "30.123456789"
    data["evidence"][0]["source_type"] = "analysis"
    render(data, tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())
        page.locator("#search").fill("供應公司")
        page.locator("#search-results button").click()
        groups = page.locator("#map .map-edge")
        widths = groups.locator(".edge-line").evaluate_all(
            "nodes => nodes.map(node => Number(getComputedStyle(node).strokeWidth.replace('px','')))"
        )
        assert (
            widths[0] > widths[3] > widths[1] == widths[2] == 2
        ), "B4 線寬依合法占比；零已揭露，未知非零"
        labels = page.locator(".share-label").all_text_contents()
        assert "銷貨／營收占比18.02%｜2025全年" in labels[0], "B4 占比及實際年度"
        assert "銷貨／營收占比0%" in labels[1], "B4 零占比不當缺值"
        assert "占比未揭露，未知不是零" in labels[2], "B4 未揭露不造零"
        assert "進貨占比10%" in labels[3], "B4 買方進貨口徑獨立"
        assert (
            "下單量：0 台" in groups.first.locator(".supply-label").first.text_content()
        ), "B4 訂單量保留"
        groups.first.locator(".edge-hit").press("Enter")
        detail = page.locator("#detail")
        assert (
            "披露供應商同期總銷貨／營收" in detail.inner_text()
            and "披露公司：供應公司" in detail.inner_text()
        ), "B4 分母與披露公司"
        assert (
            "銷貨／營收占比：18.02 %" in detail.inner_text()
        ), "B4 share不要求金額幣別"
        groups.nth(3).locator(".edge-hit").press("Space")
        assert (
            "披露買方同期總進貨" in detail.inner_text()
            and "披露公司：客戶3" in detail.inner_text()
        ), "B4 進貨分母屬買方"
        page.locator("#table-tab").click()
        row = page.locator("#analysis-comparison tbody tr").first
        gross = row.locator('[data-metric="gross_margin"]')
        expect(gross.locator(".sparkline")).to_be_visible()
        assert (
            gross.locator(".trend-point").count() == 2
            and "2期 H1" in gross.inner_text()
        ), "B5 兩個H1真實點不稱四季"
        gross.locator(".trend-point").first.press("Enter")
        source = page.locator("#evidence")
        expect(source).to_be_visible()
        assert (
            PRIOR in source.inner_text()
            and "公式：profit/revenue*100" in source.inner_text()
        ), "B5 鍵盤趨勢點來源"
        gross.locator(".trend-point").last.click()
        assert (
            PERIOD in source.inner_text() and "輸入：" in source.inner_text()
        ), "B5 點擊趨勢點來源"
        research = page.locator("#research-signals")
        expect(research).to_be_visible()
        assert 1 <= research.locator("article").count() <= 3, "B5 最多三條常開提示"
        assert (
            "毛利率同比下降" in research.inner_text()
            and "營業利益率同比上升" in research.inner_text()
        ), "B5 客觀組合提示"
        assert "0.1 百分點" in research.inner_text(), "B5 持平門檻明示"
        research.locator("article").filter(has_text="毛利率同比下降").get_by_role(
            "button", name="提示來源"
        ).click()
        assert (
            "當期：" in source.inner_text()
            and "去年：" in source.inner_text()
            and PRIOR in source.inner_text()
            and PERIOD in source.inner_text()
        ), "B5 提示當期與去年來源"
        text = source.inner_text()
        assert "毛利率：30.12%" in text and "毛利率：35.00%" in text
        assert "下降 4.88 百分點" in text
        assert all(
            raw not in text
            for raw in ['"metric"', '"evidenceIds"', "30.123456789", "文件："]
        )
        source.get_by_text("查看原始資料與定位", exact=True).click()
        assert "30.123456789" in source.inner_text()
        assert "文件：annual.pdf" in source.inner_text()
        assert "不代表因果、預測或投資排序" in source.inner_text(), "B5 不宣稱因果"
        company_ids = page.locator("#research-company option").evaluate_all(
            "nodes => nodes.map(node => node.value)"
        )
        assert set(company_ids) == {
            company["id"] for company in data["entities"][:6]
        }, "B5 公司選單限比較群組"
        page.locator("#graph-tab").click()
        page.locator('#section-more [data-zone="downstream"]').click()
        assert (
            page.locator("#research-company option").count() == 8
        ), "B5 更多同步研究公司群組"
        page.locator("#graph-tab").click()
        page.locator("#pending").uncheck()
        assert (
            page.locator("#research-company option").count() == 7
        ), "B5 篩選移除不可見待查核公司"
        page.locator("#graph-tab").click()
        page.locator("#pending").check()
        page.locator("#research-company").select_option(data["entities"][2]["id"])
        expect(research).to_contain_text("缺少可核對資料")
        page.locator("#research-company").select_option(data["entities"][0]["id"])
        page.locator("#table-tab").click()
        page.locator("#analysis-period").select_option("1")
        assert gross.locator(".trend-point").count() == 1, "B5 歷史選期不納入未來點"
        assert "僅1期；無法判趨勢" in gross.inner_text(), "B5 一期無法判趨勢"
        assert "同比下降" not in research.inner_text(), "B5 不沿用未來提示"
        page.locator("#graph-tab").click()
        page.locator('[data-node-id="' + data["entities"][1]["id"] + '"]').press(
            "Enter"
        )
        assert (
            PRIOR in page.locator("#analysis-period option:checked").inner_text()
        ), "B5 詳情不改選期"
        assert (
            page.locator("#research-company").input_value() == data["entities"][0]["id"]
        ), "B5 詳情不改研究公司"
        page.locator("#detail").get_by_role(
            "button", name="以此為中心", exact=True
        ).click()
        assert (
            page.locator("#research-company option").count() == 1
        ), "B5 新中心同步群組"
        assert (
            page.locator("#research-company").input_value() == data["entities"][1]["id"]
        ), "B5 中心為預設研究公司"
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        ), "B5 手機無頁面溢出"
        assert errors == [], "B5 無瀏覽器錯誤"
        browser.close()


def test_trend_null_gap_future_cutoff_and_latest_share_conflict(tmp_path):
    data = signals_snapshot()
    supplier = data["entities"][0]["id"]
    data["observations"] = [
        row
        for row in data["observations"]
        if not (
            row["company_id"] == supplier
            and row["metric"] == "gross_margin"
            and row["period"] == PRIOR
        )
    ]
    for period, value in [("2024-01-01~2024-06-30", 40), ("2027-01-01~2027-06-30", 60)]:
        data["observations"].append(
            observation(
                supplier,
                "gross_margin",
                value,
                unit="%",
                period=period,
                basis="consolidated",
                scope="company",
                formula="profit/revenue*100",
                inputs={"profit": value, "revenue": 100},
                evidence_ids=[data["evidence"][0]["id"]],
            )
        )
    share = data["relations"][0]["disclosures"][-1]
    data["relations"][0]["disclosures"].extend(
        [
            {**share, "value": 50},
            {**share, "value": 12, "period": "2024-01-01~2024-12-31"},
        ]
    )
    render(data, tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto((tmp_path / "index.html").as_uri())
        page.locator("#search").fill("供應公司")
        page.locator("#search-results button").click()
        page.locator("#table-tab").click()
        page.locator("#analysis-period").select_option("1")
        gross = page.locator("#analysis-comparison tbody tr").first.locator(
            '[data-metric="gross_margin"]'
        )
        assert gross.locator(".trend-point").count() == 3, "B5 真實三期含缺值不補季度"
        assert gross.locator(".trend-point.missing").count() == 1, "B5 缺值明示"
        assert gross.locator(".trend-segment").count() == 0, "B5 null斷線不插值"
        assert all(
            "2027" not in period
            for period in gross.locator(".trend-point").evaluate_all(
                "nodes => nodes.map(node => node.dataset.period)"
            )
        ), "B5 截止選期不顯未来"
        gross.locator(".trend-point.missing").press("Enter")
        expect(page.locator("#evidence")).to_contain_text("缺資料")
        first_edge = page.locator("#map .map-edge").first
        assert (
            first_edge.locator(".edge-line").evaluate(
                "node => getComputedStyle(node).strokeWidth"
            )
            == "2px"
        ), "B4 最新衝突不回退舊占比"
        assert (
            "最新占比揭露衝突" in first_edge.locator(".share-label").text_content()
        ), "B4 衝突原因可見"
        browser.close()
