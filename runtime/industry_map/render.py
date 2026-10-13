"""Pure screen queries over one snapshot; no file access or implicit ranking."""

from copy import deepcopy
from datetime import date
import re


def query_map(snapshot, *, search="", stage=None, include_pending=True):
    """Return eligible companies, roles and relations matching combined filters.

    Product matches on a relationship also select its eligible endpoints. Unknown
    counterparties remain available in company_detail, outside the overview.
    """
    query = search.casefold().strip()

    def matches(item, fields):
        return not query or any(
            query in str(item.get(field) or "").casefold() for field in fields
        )

    def visible(item):
        return include_pending or item.get("status") != "pending"

    roles = [
        item
        for item in snapshot["roles"]
        if visible(item) and (stage is None or item.get("stage") == stage)
    ]
    eligible = {item["company_id"] for item in snapshot["coverage"]} | {
        item["company_id"] for item in snapshot["roles"]
    }
    stage_ids = {item["company_id"] for item in roles}
    companies = [
        item
        for item in snapshot["entities"]
        if item["kind"] == "company"
        and item["id"] in eligible
        and (stage is None or item["id"] in stage_ids)
    ]
    company_ids = {item["id"] for item in companies}
    relations = [
        item
        for item in snapshot["relations"]
        if visible(item)
        and matches(item, ("product", "predicate"))
        and {item["source_id"], item["target_id"]} & company_ids
    ]
    matching_ids = {
        item["company_id"] for item in roles if matches(item, ("product", "stage"))
    } | {
        endpoint
        for item in relations
        for endpoint in (item["source_id"], item["target_id"])
    }
    companies = [
        item
        for item in companies
        if matches(item, ("name", "ticker", "aliases")) or item["id"] in matching_ids
    ]
    selected = {item["id"] for item in companies}
    return deepcopy(
        dict(
            companies=companies,
            roles=[
                item
                for item in roles
                if item["company_id"] in selected
                and matches(item, ("product", "stage"))
            ],
            relations=[
                item
                for item in relations
                if {item["source_id"], item["target_id"]} & selected
            ],
        )
    )


def company_detail(snapshot, company_id):
    """Return original records and evidence IDs, plus incoming/outgoing direction."""
    company = next(item for item in snapshot["entities"] if item["id"] == company_id)
    roles = [item for item in snapshot["roles"] if item["company_id"] == company_id]
    relations = [
        dict(
            item,
            direction="outgoing" if item["source_id"] == company_id else "incoming",
        )
        for item in snapshot["relations"]
        if company_id in (item["source_id"], item["target_id"])
    ]
    financials = [
        item for item in snapshot["observations"] if item["company_id"] == company_id
    ]
    evidence_ids = {
        identifier
        for item in roles + relations + financials
        for identifier in item["evidence_ids"]
    }
    endpoints = {
        endpoint
        for item in relations
        for endpoint in (item["source_id"], item["target_id"])
    }
    return deepcopy(
        dict(
            company=company,
            roles=roles,
            relations=relations,
            financials=financials,
            counterparties=[
                item
                for item in snapshot["entities"]
                if item["id"] in endpoints - {company_id}
            ],
            evidence=[
                item for item in snapshot["evidence"] if item["id"] in evidence_ids
            ],
            coverage=[
                item
                for item in snapshot["coverage"]
                if item["company_id"] == company_id
            ],
        )
    )


def _complete_period(period):
    if not isinstance(period, str):
        return None
    match = re.fullmatch(
        r"(ROC)?([0-9]{3,4})-([0-9]{2})-([0-9]{2})~(?:ROC)?([0-9]{3,4})-([0-9]{2})-([0-9]{2})",
        period,
    )
    if not match:
        return None
    roc, start_year, start_month, start_day, end_year, end_month, end_day = (
        match.groups()
    )
    offset = 1911 if roc else 0
    try:
        start = date(int(start_year) + offset, int(start_month), int(start_day))
        end = date(int(end_year) + offset, int(end_month), int(end_day))
        return (start.isoformat(), end.isoformat()) if start <= end else None
    except ValueError:
        return None


def compare_financials(snapshot, company_ids, *, metric, period=None):
    """Return comparable/reasons/rows without ranks or choosing a latest record.

    period optionally selects an explicit complete period; otherwise all metric
    observations are checked. More than one row per company blocks comparison.
    """
    company_ids = set(company_ids)
    rows = [
        item
        for item in snapshot["observations"]
        if item["company_id"] in company_ids and item["metric"] == metric
    ]
    reasons = []
    if not metric or str(metric).casefold() == "unknown":
        reasons.append("metric: missing")
    if period is not None:
        selected_period = _complete_period(period)
        if selected_period is None:
            reasons.append("period: incomplete selection")
        else:
            rows = [
                item
                for item in rows
                if _complete_period(item.get("period")) == selected_period
            ]
    for company_id in sorted(company_ids):
        count = sum(item["company_id"] == company_id for item in rows)
        if count != 1:
            reasons.append(f"rows: {company_id} has {count} observations")
    if not company_ids:
        reasons.append("rows: no companies selected")
    for field in ("period", "basis", "currency", "unit", "scope"):
        values = [
            _complete_period(item.get(field)) if field == "period" else item.get(field)
            for item in rows
        ]
        if any(
            value is None or str(value).strip().casefold() in {"", "unknown", "null"}
            for value in values
        ):
            reasons.append(f"{field}: missing or incomplete")
        if len(set(values)) > 1:
            reasons.append(f"{field}: incompatible")
    if any(item.get("value") is None for item in rows):
        reasons.append("value: missing")
    return deepcopy(dict(comparable=not reasons, reasons=reasons, rows=rows))


def render(snapshot, out):
    """Write a self-contained offline view from the same snapshot as graph.json."""
    import json
    from pathlib import Path

    destination = Path(out)
    destination.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
    # Trust boundary: source documents are untrusted. Escape the HTML script
    # delimiter even inside an inert JSON script; JS renders all values as text.
    embedded = serialized.replace("<", "\\u003c")
    page = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>產業地圖</title><link rel="stylesheet" href="style.css"></head>
<body><header><h1>產業地圖</h1>
<p>點節點查看詳情；按「以此為中心」切換一層關係。拖動其他節點或背景，使用滾輪縮放。</p>
<label for="search">搜尋公司、產業或產品／服務</label>
<input id="search" type="search" autocomplete="off" placeholder="輸入名稱或代號">
<div id="search-results" aria-label="搜尋結果" aria-live="polite"></div></header>
<main><section class="map-panel" aria-label="產業關係地圖">
<div class="map-toolbar" aria-label="畫布操作">
<button id="zoom-in" type="button" aria-label="放大">＋</button>
<button id="zoom-out" type="button" aria-label="縮小">−</button>
<span id="zoom-level" aria-live="polite">100%</span>
<button id="fit-map" type="button">適合畫面</button>
<button id="back-center" type="button" disabled>返回前中心</button>
<button id="collapse-node" type="button">收合中心一層</button>
<button id="reset-map" type="button">重置</button>
<label>關係方向 <select id="direction"><option value="">全部</option>
<option value="upstream">上游供應商</option><option value="downstream">下游客戶</option>
<option value="competitor">競爭者</option></select></label>
<label><input id="pending" type="checkbox" checked>顯示待查核</label></div>
<div id="section-more" aria-label="各區更多鄰居" aria-live="polite"></div>
<nav id="center-path" aria-label="中心路徑"></nav>
<div id="analysis-panel" aria-label="公司四率比較">
<h2>公司四率比較</h2><label>共同期別 <select id="analysis-period"></select></label>
<div id="analysis-comparison" aria-live="polite"></div>
</div>
<div id="change-panel" aria-label="變化重點"><h2>變化重點</h2><button id="clear-highlight" type="button" disabled>清除突出</button><div id="change-highlights" aria-live="polite"></div></div>
<svg id="map" viewBox="0 0 1000 650" role="group" aria-label="產業節點與連線；Tab 選取，Enter 或空白鍵查看詳情"></svg>
<p id="map-empty" class="empty" hidden>尚無產業資料。可使用 Tab 選取起點，或使用重置按鈕。</p>
<div class="map-legend" aria-label="圖例">
<span class="legend-industry">● 產業</span><span>□ 公司</span>
<span class="legend-product">● 產品／服務</span><span>→ 供貨</span>
<span>線寬：最新銷貨／營收占比，無合法銷貨占比時採進貨占比；未知不是零</span><span>─ · ─ 競爭</span><span>┄┄ 待查核</span><span>── 分類／提供</span></div>
<div id="overview" hidden></div></section>
<aside aria-label="節點與連線詳情"><div id="supply-trace" aria-label="供應關係追查" aria-live="polite" hidden></div>
<div id="research-panel" aria-label="研究重點"><h2>研究重點</h2>
<label>研究公司 <select id="research-company"></select></label>
<div id="research-signals" aria-live="polite"></div></div>
<h2>詳情</h2><div id="detail">請選取節點或連線</div>
<div hidden><label>環節 <select id="stage"><option value="">全部</option></select></label></div>
<details id="finance-panel"><summary>公司財務（展開後讀取）</summary><div id="financials"></div></details>
<details id="comparison-panel"><summary>財務比較</summary>
<p>在公司詳情加入比較。僅比較目前圖中可見公司。</p>
<label>指標 <select id="metric"></select></label>
<label>完整期別 <select id="period"></select></label><div id="comparison"></div></details>
<h2>證據</h2><div id="evidence">請選取來源</div></aside></main>
<script id="snapshot" type="application/json">SNAPSHOT</script>
<script src="app.js"></script></body></html>""".replace("SNAPSHOT", embedded)
    (destination / "index.html").write_text(page, encoding="utf-8")
    (destination / "graph.json").write_text(serialized, encoding="utf-8")
    assets = Path(__file__).with_name("assets")
    for filename in ("app.js", "style.css"):
        (destination / filename).write_bytes((assets / filename).read_bytes())
    return destination
