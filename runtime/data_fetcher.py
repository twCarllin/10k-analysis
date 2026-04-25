import json
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent

_config = json.loads((BASE_DIR / "config.json").read_text())
EDGAR_BASE = "https://www.sec.gov"
HEADERS = {"User-Agent": _config.get("edgar_user_agent", "10k-research user@example.com")}

KNOWN_CIKS = {
    "HWM": "0000004281",
}


def get_cik(ticker: str) -> str:
    ticker = ticker.upper()
    if ticker in KNOWN_CIKS:
        return KNOWN_CIKS[ticker]
    cache = BASE_DIR / f"data/cache/xbrl/cik_{ticker}.json"
    if cache.exists():
        return json.loads(cache.read_text())["cik"]
    r = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    for entry in r.json().values():
        if entry["ticker"].upper() == ticker:
            cik = str(entry["cik_str"]).zfill(10)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"cik": cik}))
            return cik
    raise ValueError(f"找不到 ticker: {ticker}")


def download_filing(ticker: str, year: int, filing_type: str = "10-K",
                    quarter: str | None = None) -> Path:
    """
    流程：
    1. submissions API 找 accession number
    2. filing index JSON 找主文件 URL
    3. 下載並快取到 data/cache/htm/

    filing_type: "10-K" 或 "10-Q"
    quarter: 10-Q 時必須指定 "Q1"/"Q2"/"Q3"
    """
    cache_dir = BASE_DIR / "data/cache/htm"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cik = get_cik(ticker)
    r = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers=HEADERS,
        timeout=45,
    )
    r.raise_for_status()
    recent = r.json()["filings"]["recent"]

    target_forms = {filing_type, f"{filing_type}/A"}

    for i, form in enumerate(recent["form"]):
        if form not in target_forms:
            continue
        if int(recent["filingDate"][i][:4]) not in (year, year + 1):
            continue
        # 10-Q: match fiscal period (Q1/Q2/Q3)
        if filing_type == "10-Q" and quarter:
            fp = recent.get("reportDate", recent.get("filingDate", []))
            if i < len(fp):
                report_month = int(fp[i][5:7])
                report_q = f"Q{(report_month - 1) // 3 + 1}"
                if report_q != quarter:
                    continue

        acc_no = recent["accessionNumber"][i]
        acc_clean = acc_no.replace("-", "")
        filename = recent["primaryDocument"][i]
        ext = filename.split(".")[-1].lower()
        url = (
            f"{EDGAR_BASE}/Archives/edgar/data/"
            f"{int(cik)}/{acc_clean}/{filename}"
        )
        label = f"{filing_type.replace('-', '')}"
        if quarter:
            label += f"_{quarter}"
        cache_path = cache_dir / f"{ticker}_{year}_{label}.{ext}"
        if not cache_path.exists():
            r2 = requests.get(url, headers=HEADERS, timeout=120)
            r2.raise_for_status()
            cache_path.write_bytes(r2.content)
        return cache_path

    q_hint = f" {quarter}" if quarter else ""
    raise FileNotFoundError(f"找不到 {ticker} {year}{q_hint} {filing_type} 主文件")


# Backward compatibility alias
def download_10k_htm(ticker: str, year: int) -> Path:
    return download_filing(ticker, year, filing_type="10-K")


XBRL_CONCEPTS = {
    "Revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "GrossProfit": ["GrossProfit"],
    "OperatingIncome": ["OperatingIncomeLoss"],
    "NetIncome": ["NetIncomeLoss"],
    "OperatingCashFlow": ["NetCashProvidedByUsedInOperatingActivities"],
    "CapEx": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "LongTermDebt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "SharesOutstanding": ["CommonStockSharesOutstanding"],
}


def get_xbrl_facts(ticker: str) -> dict:
    cik = get_cik(ticker)
    cache = BASE_DIR / f"data/cache/xbrl/xbrl_{ticker}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    r = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        headers=HEADERS,
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return data


def extract_key_metrics(xbrl_facts: dict, filing_type: str = "10-K") -> dict:
    """取 form==filing_type 的數字。10-K 取 fp==FY 最近 5 年；10-Q 取最近 5 季。"""
    us_gaap = xbrl_facts.get("facts", {}).get("us-gaap", {})

    def annual(concepts, unit="USD"):
        all_rows = []
        for concept in concepts:
            units_dict = us_gaap.get(concept, {}).get("units", {})
            values = units_dict.get(unit, [])
            if not values and unit == "USD":
                values = units_dict.get("shares", [])
            if filing_type == "10-K":
                target_forms = ("10-K", "10-K/A")
                target_fp = ("FY",)
            else:
                target_forms = ("10-Q", "10-Q/A", "10-K", "10-K/A")
                target_fp = ("Q1", "Q2", "Q3", "Q4", "FY")
            entries = [
                {"year": e["fy"], "val": e["val"], "filed": e.get("filed", ""),
                 "fp": e.get("fp", "")}
                for e in values
                if e.get("form") in target_forms and e.get("fp") in target_fp
            ]
            all_rows.extend(entries)
        if not all_rows:
            return []
        # Dedup: same (year, fp) → keep latest filed
        deduped = {}
        for row in sorted(all_rows, key=lambda x: x["filed"]):
            key = (row["year"], row["fp"]) if filing_type == "10-Q" else row["year"]
            deduped[key] = row
        rows = sorted(deduped.values(), key=lambda x: x["filed"])[-5:]
        return [{"year": r["year"], "val": r["val"]} for r in rows]

    result = {}
    for k, v in XBRL_CONCEPTS.items():
        if k == "SharesOutstanding":
            result[k] = annual(v, unit="shares")
        else:
            result[k] = annual(v)
    return result


QUARTERLY_CONCEPTS = {
    "Revenue": [
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "OperatingIncome": ["OperatingIncomeLoss"],
    "NetIncome": ["NetIncomeLoss"],
}


def extract_quarterly_metrics(xbrl_facts: dict, num_quarters: int = 5) -> list[dict]:
    """Extract last N single-quarter metrics for chart: revenue growth, gross margin, net margin."""
    from datetime import datetime

    us_gaap = xbrl_facts.get("facts", {}).get("us-gaap", {})

    def _get_single_quarters(concepts):
        """Get single-quarter values by filtering on date span ~60-100 days."""
        for concept in concepts:
            entries = us_gaap.get(concept, {}).get("units", {}).get("USD", [])
            quarters = []
            for e in entries:
                if e.get("form") not in ("10-Q", "10-K"):
                    continue
                start = e.get("start", "")
                end = e.get("end", "")
                if not start or not end:
                    continue
                d0 = datetime.strptime(start, "%Y-%m-%d")
                d1 = datetime.strptime(end, "%Y-%m-%d")
                span = (d1 - d0).days
                if 60 <= span <= 100:  # single quarter
                    quarters.append({
                        "end": end,
                        "label": f"{d1.year}Q{(d1.month - 1) // 3 + 1}",
                        "val": e["val"],
                    })
                elif 340 <= span <= 380 and e.get("fp") == "FY":
                    # Annual: treat as Q4 by subtracting prior 3 quarters later
                    quarters.append({
                        "end": end,
                        "label": f"{d1.year}Q4",
                        "val": e["val"],
                        "_annual": True,
                    })
            if quarters:
                # Deduplicate by (label, val)
                seen = set()
                unique = []
                for q in quarters:
                    key = (q["label"], q["val"])
                    if key not in seen:
                        seen.add(key)
                        unique.append(q)
                return sorted(unique, key=lambda x: x["end"])
        return []

    raw = {}
    for metric, concepts in QUARTERLY_CONCEPTS.items():
        raw[metric] = _get_single_quarters(concepts)

    # Build quarterly table, excluding _annual entries (Q4 from 10-K is full year)
    rev_by_q = {q["label"]: q["val"] for q in raw.get("Revenue", []) if not q.get("_annual")}
    oi_by_q = {q["label"]: q["val"] for q in raw.get("OperatingIncome", []) if not q.get("_annual")}
    ni_by_q = {q["label"]: q["val"] for q in raw.get("NetIncome", []) if not q.get("_annual")}

    all_labels = sorted(set(rev_by_q.keys()) & set(ni_by_q.keys()))
    if not all_labels:
        return []

    # Take last N quarters
    labels = all_labels[-num_quarters:]

    result = []
    for label in labels:
        rev = rev_by_q.get(label)
        oi = oi_by_q.get(label)
        ni = ni_by_q.get(label)
        if rev is None:
            continue

        # YoY revenue growth: find same quarter last year
        year = int(label[:4])
        qn = label[4:]  # e.g. "Q2"
        prev_label = f"{year - 1}{qn}"
        prev_rev = rev_by_q.get(prev_label)
        rev_growth = ((rev - prev_rev) / prev_rev * 100) if prev_rev else None

        op_margin = (oi / rev * 100) if (oi is not None and rev) else None
        net_margin = (ni / rev * 100) if (ni is not None and rev) else None

        result.append({
            "quarter": label,
            "revenue": rev,
            "rev_growth_yoy": round(rev_growth, 1) if rev_growth is not None else None,
            "op_margin": round(op_margin, 1) if op_margin is not None else None,
            "net_margin": round(net_margin, 1) if net_margin is not None else None,
        })

    return result
