"""Real producer → renderer → Chrome contracts for A5–A8."""

import inspect

from playwright.sync_api import sync_playwright, expect

from runtime.industry_map.model import (
    entity,
    evidence,
    observation,
    relation,
    role,
    snapshot,
)
from runtime.industry_map.render import render

PERIOD = "2026-01-01~2026-06-30"
PRIOR = "2025-01-01~2025-06-30"


def analysis_snapshot():
    assert "disclosures" in inspect.signature(relation).parameters
    supplier = entity("供應公司", market="TW", ticker="100")
    buyers = [entity(f"客戶{i}", market="TW", ticker=str(200 + i)) for i in range(7)]
    proof = evidence(
        "annual.pdf",
        locator={"page": 8},
        quote="<script>來源原文</script>",
        period=PERIOD,
    )
    proof_ids = [proof["id"]]
    rows = []
    for company in [supplier, buyers[0]]:
        for period, values in [(PERIOD, [40, 20, 10, -5]), (PRIOR, [35, 18, 8, -8])]:
            for metric, value in zip(
                ["gross_margin", "operating_margin", "net_margin", "fcf_margin"], values
            ):
                rows.append(
                    observation(
                        company["id"],
                        metric,
                        value,
                        unit="%",
                        period=period,
                        basis="consolidated",
                        scope="company",
                        formula=(
                            "(cfo-capex)/revenue*100"
                            if metric == "fcf_margin"
                            else "profit/revenue*100"
                        ),
                        inputs={
                            "cfo": 5,
                            "capex": 10 if period == PERIOD else 13,
                            "revenue": 100,
                        },
                        evidence_ids=proof_ids,
                    )
                )
    disclosures = [
        {
            "kind": "order_quantity",
            "value": 0,
            "unit": "台",
            "currency": None,
            "period": PERIOD,
            "evidence_ids": proof_ids,
        },
        {
            "kind": "sales_amount",
            "value": 120,
            "unit": "千元",
            "currency": "TWD",
            "period": PERIOD,
            "evidence_ids": proof_ids,
        },
    ]
    edges = [
        relation(
            supplier["id"],
            "supplies_to",
            buyer["id"],
            status="confirmed" if i < 6 else "pending",
            evidence_ids=proof_ids,
            disclosures=disclosures if i == 0 else [],
        )
        for i, buyer in enumerate(buyers)
    ]
    return snapshot(
        entities=[supplier, *buyers],
        evidence=[proof],
        relations=edges,
        observations=rows,
    )


def test_automatic_four_ratios_period_sources_and_orders(tmp_path):
    data = analysis_snapshot()
    buyer = data["entities"][1]
    peer = entity("同業公司", market="TW", ticker="300")
    data["entities"].append(peer)
    data["relations"].append(
        relation(buyer["id"], "competes_with", peer["id"], status="confirmed")
    )
    data["roles"].extend(
        role(company["id"], "比較產業", "製造", product="比較產品", status="confirmed")
        for company in (buyer, peer)
    )
    render(data, tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((tmp_path / "index.html").as_uri())
        page.locator("#search").fill("供應公司")
        page.locator("#search-results button").click()
        panel = page.locator("#analysis-comparison")
        expect(panel).to_be_visible()
        rows = panel.locator("tbody tr")
        assert rows.count() == 6, "A6 自動中心與五個可見下游；不需加入"
        supplier = rows.filter(
            has=page.get_by_role("rowheader", name="供應公司", exact=True)
        )
        assert [
            supplier.locator(f'[data-metric="{metric}"] button').inner_text()
            for metric in [
                "gross_margin",
                "operating_margin",
                "net_margin",
                "fcf_margin",
            ]
        ] == ["40.00%", "20.00%", "10.00%", "-5.00%"], "A8 四率一眼可見"
        assert "同比 +5.00 百分點" in supplier.inner_text(), "A5 同期同比pp"
        assert supplier.locator(".negative").count() == 1, "A8 負值中性bar"
        assert (
            "缺資料：未匯入"
            in rows.filter(
                has=page.get_by_role("rowheader", name="客戶1", exact=True)
            ).inner_text()
        ), "A6 無財務仍保留公司"
        assert (
            "最新：" in page.locator("#analysis-period option:checked").inner_text()
        ), "A5 預設最新共用口徑"
        assert "公司整體；不代表單筆交易" in panel.inner_text(), "A6 明示整體"
        supplier.locator('[data-metric="gross_margin"] button').click()
        source = page.locator("#evidence")
        assert (
            "公式：profit/revenue*100" in source.inner_text()
            and "輸入：" in source.inner_text()
        ), "A6 公式與輸入可讀"
        assert (
            PERIOD in source.inner_text() and PRIOR in source.inner_text()
        ), "A5 當期與去年來源"
        assert (
            "<script>來源原文</script>" in source.inner_text()
            and source.locator("script").count() == 0
        ), "A7 原文安全"
        page.locator("#analysis-period").select_option("1")
        assert (
            supplier.locator('[data-metric="gross_margin"] button').inner_text()
            == "35.00%"
        ), "A5 全體共用選定期別"
        assert "同比 —" in supplier.inner_text(), "A5 無去年不猜"
        labels = page.locator("#map .supply-label").all_text_contents()
        assert any(
            "下單量：0 台" in label and PERIOD in label for label in labels
        ), "A7 零下單量與期別"
        assert any("已實現銷貨" in label for label in labels), "A7 實現交易分開標示"
        assert any("下單量未揭露" in label for label in labels), "A7 缺訂單明示"
        page.locator("#map .edge-hit").first.press("Enter")
        detail = page.locator("#detail")
        assert "已實現銷貨：120 千元 TWD" in detail.inner_text(), "A7 連線完整揭露"
        detail.get_by_role("button", name="查看來源", exact=True).first.click()
        expect(source).to_contain_text("來源原文")
        page.locator('#section-more [data-zone="downstream"]').click()
        assert rows.count() == 8, "A8 更多同步比較"
        page.locator("#pending").uncheck()
        assert rows.count() == 7, "A8 篩選同步比較"
        page.locator("#direction").select_option("upstream")
        assert rows.count() == 1, "A8 沒可見下游時保留中心"
        page.locator("#direction").select_option("")
        page.locator('[data-node-id="' + data["entities"][1]["id"] + '"]').press(
            "Enter"
        )
        assert (
            rows.first.locator("th").inner_text() == "供應公司"
        ), "A8 點卡不改比較中心"
        page.locator("#analysis-period").select_option("1")
        expected_supplier_ids = {company["id"] for company in data["entities"][:7]}
        page.locator('[data-node-id="' + buyer["id"] + '"]').press("Enter")
        assert (
            set(rows.evaluate_all("nodes => nodes.map(node => node.dataset.companyId)"))
            == expected_supplier_ids
        ), "A6 詳情選取不改自動比較公司集合"
        assert (
            PRIOR in page.locator("#analysis-period option:checked").inner_text()
        ), "A5 詳情選取不改局部共同期別"
        page.locator("#detail").get_by_role(
            "button", name="以此為中心", exact=True
        ).click()
        expected_peer_ids = {buyer["id"], peer["id"]}
        assert (
            set(rows.evaluate_all("nodes => nodes.map(node => node.dataset.companyId)"))
            == expected_peer_ids
        ), "A6 無下游公司中心自動比較可見同業；不納入上游"
        assert (
            PERIOD in page.locator("#analysis-period option:checked").inner_text()
        ), "A5 換中心使用新群組最新期別"
        page.locator("#analysis-period").select_option("1")
        page.locator('[data-node-id="' + peer["id"] + '"]').press("Enter")
        assert (
            set(rows.evaluate_all("nodes => nodes.map(node => node.dataset.companyId)"))
            == expected_peer_ids
        ), "A6 同業詳情不改比較集合"
        assert (
            PRIOR in page.locator("#analysis-period option:checked").inner_text()
        ), "A5 同業詳情不改已選期別"
        for center_name in ("比較產業", "比較產品"):
            page.locator("#search").fill(center_name)
            page.locator("#search-results button").click()
            assert (
                set(
                    rows.evaluate_all(
                        "nodes => nodes.map(node => node.dataset.companyId)"
                    )
                )
                == expected_peer_ids
            ), f"A6 {center_name}中心自動比較全部可見公司"
            assert (
                PERIOD in page.locator("#analysis-period option:checked").inner_text()
            ), f"A5 {center_name}中心預設最新期別"
            page.locator("#analysis-period").select_option("1")
            page.locator('[data-node-id="' + buyer["id"] + '"]').press("Enter")
            assert (
                set(
                    rows.evaluate_all(
                        "nodes => nodes.map(node => node.dataset.companyId)"
                    )
                )
                == expected_peer_ids
            ), f"A6 {center_name}公司詳情不改集合"
            assert (
                PRIOR in page.locator("#analysis-period option:checked").inner_text()
            ), f"A5 {center_name}公司詳情不改共同期別"
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        ), "A8 手機無外部溢出"
        page.locator("#reset-map").click()
        expect(panel).to_contain_text("請選產業或公司")
        assert errors == [], "A8 保留圖狀態且無瀏覽器錯誤"
        browser.close()


def test_order_conflict_and_incomplete_are_explicit(tmp_path):
    data = analysis_snapshot()
    records = data["relations"][0]["disclosures"]
    records.append({**records[0], "value": 9})
    data["relations"][1]["disclosures"] = [{**records[0], "unit": None, "value": 999}]
    render(data, tmp_path)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto((tmp_path / "index.html").as_uri())
        page.locator("#search").fill("供應公司")
        page.locator("#search-results button").click()
        labels = page.locator(".supply-label").all_text_contents()
        assert any("下單量：揭露衝突" in label for label in labels), "A7 不擇一衝突數值"
        assert any("資料不完整" in label for label in labels), "A7 缺單位不造裸值"
        assert not any("999" in label for label in labels), "A7 不顯不完整訂單數字"
        page.locator(".edge-hit").first.press("Enter")
        detail = page.locator("#detail")
        assert "交易揭露衝突" in detail.inner_text(), "A7 點線保留衝突說明"
        assert (
            "下單量：0 台" in detail.inner_text()
            and "下單量：9 台" in detail.inner_text()
        ), "A7 所有原揭露可讀"
        browser.close()
