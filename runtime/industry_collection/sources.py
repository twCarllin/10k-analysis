"""Discover filenames from official directory HTML, never infer filenames."""

import json
import logging
import re
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from .model import targets, digest, utc_now
from .transport import Transport

logger = logging.getLogger(__name__)


def log_source_failure(error, url, **context):
    logger.error(
        "Source query failed: %s",
        error,
        extra=dict(
            event="source_failed",
            url=url,
            attempt=getattr(error, "request_attempt", None),
            **context,
        ),
    )


DIRECTORY = "https://doc.twse.com.tw/server-java/t57sb01"
MONTHLY = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"


def discover(tickers, root, transport=None):
    from pathlib import Path

    transport = transport or Transport()
    evidence = Path(root) / "directories"
    evidence.mkdir(parents=True, exist_ok=True)
    result = []
    monthly = None
    monthly_error = None
    try:
        response = transport.get(MONTHLY)
        monthly = response.json()
        if not isinstance(monthly, list):
            raise ValueError("Monthly API did not return a list")
        (evidence / f"{digest(response.content)}.json").write_bytes(response.content)
    except Exception as error:
        monthly_error = str(error)
        log_source_failure(error, MONTHLY)
    for row in targets(tickers):
        kind, period = row["doc_type"], row["period"]
        if kind == "monthly_revenue":
            roc_period = f"{int(period[:4]) - 1911}{period[5:]}"
            found = [
                value
                for value in (monthly or [])
                if str(value.get("公司代號")) == row["ticker"]
                and str(value.get("資料年月")) == roc_period
            ]
            if found:
                row.update(
                    url=MONTHLY,
                    format="json",
                    selector={"公司代號": row["ticker"], "資料年月": roc_period},
                )
            else:
                row.update(
                    status="missing",
                    reason=monthly_error
                    or "Latest-month API has no matching historical period",
                    next_source="https://mops.twse.com.tw/mops/#/web/t21sc03",
                )
            result.append(row)
            continue
        if kind not in ("annual_report", "financial_report"):
            row.update(
                status="missing",
                reason="Automatic historical directory not supported; supply official source manifest",
                next_source="https://mops.twse.com.tw/",
            )
            result.append(row)
            continue
        annual = kind == "annual_report"
        year = int(period[:4]) + int(annual) - 1911
        types = ("F04", "F11", "F18") if annual else ("AI1", "AI4", "AI7")
        found = False
        for dtype in types:
            params = dict(
                step="1",
                co_id=row["ticker"],
                year=str(year),
                mtype="F" if annual else "A",
                dtype=dtype,
                seamon="" if annual else period[-1],
            )
            try:
                response = transport.get(DIRECTORY, params=params)
                path = evidence / f"{digest(response.content)}.html"
                path.write_bytes(response.content)
                if len(response.content) < 1000:
                    raise ValueError(
                        "Official directory returned short error/rejection HTML"
                    )
                matches = re.findall(
                    r'readfile2?\("([^"]+)","([^"]+)","([^"]+)"\)', response.text
                )
                for file_kind, company, filename in matches:
                    expected = (
                        period[:4] if annual else period[:4] + f"{int(period[-1]):02d}"
                    )
                    if (
                        company != row["ticker"]
                        or not filename.lower().endswith(".pdf")
                        or not filename.startswith(expected + "_")
                        or (not annual and not filename.endswith(f"_{dtype}.pdf"))
                        or (annual and not filename.endswith(f"{dtype}.pdf"))
                    ):
                        continue
                    item = dict(row)
                    for html_row in re.findall(
                        r"<tr[^>]*>(.*?)</tr>", response.text, re.S | re.I
                    ):
                        if filename not in html_row:
                            continue
                        stamp = re.search(
                            r"(\d{3})/(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2})", html_row
                        )
                        if stamp:
                            parts = list(map(int, stamp.groups()))
                            parts[0] += 1911
                            item["uploaded_at"] = datetime(
                                *parts, tzinfo=timezone(timedelta(hours=8))
                            ).isoformat()
                            item["date_type"] = "uploaded_at"
                    item.update(
                        directory_url=response.url,
                        directory_path=str(path),
                        download_params=dict(
                            step="9", kind=file_kind, co_id=company, filename=filename
                        ),
                        url=DIRECTORY,
                        format="pdf",
                        source_filename=filename,
                    )
                    result.append(item)
                    found = True
            except Exception as error:
                row["reason"] = str(error)
                log_source_failure(
                    error, DIRECTORY, ticker=row["ticker"], period=period
                )
        if not found:
            row.update(
                status="missing",
                reason=row.get("reason", "Official directory returned no matching PDF"),
                next_source=DIRECTORY,
                query_year=year,
            )
            result.append(row)
    return result


def resolve_download(row, transport):
    if not row.get("download_params"):
        return row["url"]
    response = transport.get(row["url"], params=row["download_params"])
    links = re.findall(r"href=[\'\"]([^\'\"]+\.pdf)[\'\"]", response.text, re.I)
    if not links:
        raise ValueError("Official download page returned no PDF link")
    return urljoin(response.url, links[0])


def discover_monthly(tickers, root, transport=None):
    """Query each public market/month once; persist the official historical HTML."""
    from pathlib import Path
    from bs4 import BeautifulSoup

    transport = transport or Transport()
    evidence = Path(root) / "directories"
    evidence.mkdir(parents=True, exist_ok=True)
    periods = sorted(
        {
            row["period"]
            for row in targets(tickers)
            if row["doc_type"] == "monthly_revenue"
        }
    )
    outcomes = []
    for period in periods:
        matches = {}
        errors = []
        for market in ("sii", "otc"):
            year, month = int(period[:4]) - 1911, int(period[5:])
            url = f"https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{year}_{month}_0.html"
            try:
                response = transport.get(url)
                if len(response.content) < 1000:
                    raise ValueError(
                        "Short historical revenue HTML: possible rejection"
                    )
                response.encoding = "big5"
                soup = BeautifulSoup(response.text, "html.parser")
                header = soup.get_text(" ", strip=True)
                if not re.search(rf"{year}\s*年\s*{month}\s*月", header):
                    raise ValueError("Revenue HTML period does not match query")
                path = evidence / f"{digest(response.content)}.html"
                path.write_bytes(response.content)
                for html_row in soup.find_all("tr"):
                    cells = [
                        cell.get_text(strip=True) for cell in html_row.find_all("td")
                    ]
                    if not cells or cells[0] not in tickers:
                        continue
                    row = next(
                        row
                        for row in targets([cells[0]])
                        if row["doc_type"] == "monthly_revenue"
                        and row["period"] == period
                    )
                    row.update(
                        url=url,
                        format="html",
                        market=market,
                        directory_path=str(path.resolve()),
                        directory_sha256=digest(response.content),
                        revenue_cells=cells,
                        unit="TWD thousand",
                        currency="TWD",
                    )
                    matches[cells[0]] = row
            except Exception as error:
                errors.append(f"{market}: {error}")
                log_source_failure(error, url, period=period)
        for ticker in tickers:
            if ticker in matches:
                outcomes.append(matches[ticker])
            else:
                row = next(
                    row
                    for row in targets([ticker])
                    if row["doc_type"] == "monthly_revenue" and row["period"] == period
                )
                row.update(
                    status="missing",
                    reason="; ".join(errors)
                    or "Company absent from both official market tables",
                    next_source="https://mopsov.twse.com.tw/mops/web/t21sc03",
                )
                outcomes.append(row)
    return outcomes
