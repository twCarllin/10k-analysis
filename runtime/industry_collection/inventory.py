"""Read-only inventory of existing company PDFs."""

from pathlib import Path
import re
from .model import digest, document, targets


def inventory(root="tw_report", tickers=None):
    tickers = set(tickers or [])
    result = []
    for path in sorted(Path(root).glob("*.pdf")):
        match = re.match(r"(\d+)_(\d{4})(?:Q([1-4]))?", path.name)
        if not match or (tickers and match[1] not in tickers):
            continue
        kind = "annual_report" if "年報" in path.name else "financial_report"
        period = match[2] + (f"Q{match[3]}" if match[3] else "")
        row = document(match[1], kind, period)
        row.update(
            status="existing",
            local_path=str(path.resolve()),
            sha256=digest(path.read_bytes()),
            origin="local_existing",
        )
        result.append(row)
    return result


def plan(tickers, existing):
    available = {(row["ticker"], row["doc_type"], row["period"]) for row in existing}
    rows = targets(tickers)
    for row in rows:
        row["status"] = (
            "existing"
            if (row["ticker"], row["doc_type"], row["period"]) in available
            else "missing"
        )
    return rows
