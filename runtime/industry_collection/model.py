"""Document metadata and fixed, explicitly completed collection periods."""

from datetime import datetime, timezone
import hashlib


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def document(ticker, doc_type, period, **values):
    result = dict(
        ticker=str(ticker),
        market=None,
        doc_type=doc_type,
        period=period,
        basis="consolidated" if doc_type == "financial_report" else None,
        currency=None,
        unit=None,
        announced_at=None,
        fetched_at=None,
        url=None,
        sha256=None,
        local_path=None,
        revision_of=None,
        status="not_fetched",
    )
    result.update(values)
    return result


def targets(tickers):
    rows = []
    for ticker in tickers:
        rows.extend(
            document(ticker, "annual_report", str(year)) for year in range(2023, 2026)
        )
        for year, quarters in ((2024, (3, 4)), (2025, (1, 2, 3, 4)), (2026, (1, 2))):
            for quarter in quarters:
                period = f"{year}Q{quarter}"
                rows.append(document(ticker, "financial_report", period))
                rows.append(document(ticker, "investor_presentation", period))
        for offset in range(36):
            year, month = divmod(2023 * 12 + 9 + offset, 12)
            rows.append(document(ticker, "monthly_revenue", f"{year}-{month + 1:02d}"))
        rows.append(document(ticker, "material_announcement", "2024-10-13/2026-10-13"))
        rows.append(document(ticker, "company_product", "as-of-2026-10-13"))
    return rows
