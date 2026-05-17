"""
jp_tdnet_scraper.py — TDNET (東証適時開示) scraper + local index

Scrapes https://www.release.tdnet.info/inbs/I_list_{NNN}_{YYYYMMDD}.html,
stores results in master.duckdb (tdnet_index table), and provides local query
and PDF download helpers.

Public API:
    scrape_tdnet_index(d: date) -> list[dict]
    scan_tdnet_range(start: date, end: date) -> None
    find_tdnet_local(jpx_code, since, title_pattern, category) -> list[dict]
    classify_tdnet_title(title: str) -> tuple[str, bool]
    download_tdnet_pdf(pdf_url: str, out_dir: Path | None) -> Path
"""

import json
import logging
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import requests
from bs4 import BeautifulSoup

try:
    from jp_data_fetcher import _init_tdnet_schema  # runtime/ on sys.path
except ModuleNotFoundError:
    from runtime.jp_data_fetcher import _init_tdnet_schema  # project root import  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "cache" / "jp" / "master.duckdb"
TDNET_SCANNED_PATH = BASE_DIR / "data" / "cache" / "jp" / "_tdnet_scanned_dates.json"
TDNET_PDF_DIR = BASE_DIR / "data" / "cache" / "jp" / "tdnet"

TDNET_BASE = "https://www.release.tdnet.info/inbs"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

log = logging.getLogger(__name__)


# ── Classifier ────────────────────────────────────────────────────────────────

# Ordered rules: (compiled_regex, category_string)
_CLASSIFY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"決算短信"), "earnings_flash"),
    (re.compile(r"業績予想.{0,5}修正"), "guidance_revision"),
    (re.compile(r"月次"), "monthly_revenue"),
    (re.compile(r"(自己|自社).{0,1}株式.{0,5}取得"), "share_buyback"),
    (re.compile(r"(株式)?(分割|併合)"), "share_split"),
    (re.compile(r"(株式|新株予約権).{0,5}発行"), "equity_issuance"),
    (re.compile(r"(資本|資本金).{0,5}業務提携|資本提携"), "capital_alliance"),
    (re.compile(r"(M&A|合併|買収|株式交換|株式譲渡)"), "ma"),
    (re.compile(r"業績(の|に関する)(お知らせ|前提)|業績.{0,5}関する"), "earnings_other"),
]

_AMENDMENT_PREFIX = re.compile(r"^[（(](訂正|更正)[）)]")


def classify_tdnet_title(title: str) -> tuple[str, bool]:
    """Return (category, is_amendment).

    Step 1: detect amendment prefix （訂正）/（更正）→ is_amendment=True,
            then classify the remaining text.
    Step 2: match category rules in order; default "other".

    Example:
        classify_tdnet_title("（訂正）2026年3月期 決算短信") == ("earnings_flash", True)
    """
    stripped = title.strip()
    is_amendment = False

    m = _AMENDMENT_PREFIX.match(stripped)
    if m:
        is_amendment = True
        stripped = stripped[m.end():].strip()

    for pattern, category in _CLASSIFY_RULES:
        if pattern.search(stripped):
            return (category, is_amendment)

    # fallback
    if is_amendment:
        return ("amendment", True)
    return ("other", False)


# ── HTML parser ───────────────────────────────────────────────────────────────

def _parse_tdnet_page(html: str, d: date) -> list[dict]:
    """Parse one TDNET listing page and return disclosure dicts."""
    soup = BeautifulSoup(html, "lxml")
    rows = soup.find_all("tr")

    results: list[dict] = []
    # Track seen (date_str, jpx_code, hhmm) keys for collision-avoidance
    seen_keys: dict[str, int] = {}

    date_str = d.strftime("%Y%m%d")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        time_text = cells[0].get_text(strip=True)
        # Validate time format HH:MM
        if not re.match(r"^\d{2}:\d{2}$", time_text):
            continue

        code_text = cells[1].get_text(strip=True)
        # TDNET code is 5 digits (trailing 0); strip to 4 for jpx_code
        code_5 = re.sub(r"\D", "", code_text)
        if len(code_5) < 4:
            continue
        jpx_code = code_5[:4]

        company_name = cells[2].get_text(strip=True)

        # Title + PDF URL from <a> in cells[3]
        title_cell = cells[3]
        link = title_cell.find("a", href=True)
        if link is None:
            continue
        title = link.get_text(strip=True)
        pdf_rel = link["href"]
        # Build absolute PDF URL
        if pdf_rel.startswith("http"):
            pdf_url = pdf_rel
        else:
            pdf_url = f"{TDNET_BASE}/{pdf_rel}"

        # Build disclosure_id: YYYYMMDD_jpxcode_HHMM[_NN]
        hhmm = time_text.replace(":", "")
        base_key = f"{date_str}_{jpx_code}_{hhmm}"
        if base_key in seen_keys:
            seen_keys[base_key] += 1
            n = seen_keys[base_key]
            disclosure_id = f"{base_key}_{n:02d}"
        else:
            seen_keys[base_key] = 0
            disclosure_id = base_key

        category, is_amendment = classify_tdnet_title(title)

        results.append({
            "disclosure_id": disclosure_id,
            "disclosure_date": d.isoformat(),
            "time": time_text,            # user-facing key per spec
            "disclosure_time": time_text, # DB column key
            "jpx_code": jpx_code,
            "company_name": company_name,
            "title": title,
            "category": category,
            "pdf_url": pdf_url,
            "is_amendment": is_amendment,
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        })

    return results


def _has_page(html: str, page: int) -> bool:
    """Return True if the HTML contains a pagerLink for the given page number.

    TDNET uses onclick='pagerLink(\"I_list_NNN_YYYYMMDD.html\")' divs for pagination.
    """
    page_str = f"{page:03d}"
    # Look for pagerLink referencing the page
    return bool(re.search(rf"pagerLink\(['\"]I_list_{page_str}_", html))


# ── Public: scrape one day ────────────────────────────────────────────────────

def scrape_tdnet_index(d: date) -> list[dict]:
    """Scrape TDNET listing for date d, all pages.

    Returns list of disclosure dicts.  Empty list on holiday / no data.
    Rate limit: 1 req/sec sleep AFTER each page request (inside this function,
    per retro lesson: sleep in the caller of network, not inside scan loop).
    """
    date_str = d.strftime("%Y%m%d")
    all_records: list[dict] = []
    page = 1

    while True:
        page_str = f"{page:03d}"
        url = f"{TDNET_BASE}/I_list_{page_str}_{date_str}.html"
        log.debug("TDNET fetch: %s", url)

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            # TDNET pages are UTF-8 but requests may mis-detect encoding; use .content
            html = resp.content.decode("utf-8", errors="replace")
        except requests.RequestException as exc:
            log.warning("TDNET request failed for %s page %d: %s", date_str, page, exc)
            break

        records = _parse_tdnet_page(html, d)
        all_records.extend(records)

        # Rate limit sleep after each page request
        time.sleep(1)

        # Stop if no records (holiday / empty day) or no next page
        if not records:
            break
        if not _has_page(html, page + 1):
            break

        page += 1

    log.info("TDNET %s: %d records across %d page(s)", date_str, len(all_records), page)
    return all_records


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def _load_scanned_dates() -> set[str]:
    if TDNET_SCANNED_PATH.exists():
        data = json.loads(TDNET_SCANNED_PATH.read_text())
        return set(data.get("scanned_dates", []))
    return set()


def _save_scanned_dates(scanned: set[str]) -> None:
    TDNET_SCANNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    TDNET_SCANNED_PATH.write_text(
        json.dumps({"scanned_dates": sorted(scanned)}, ensure_ascii=False)
    )


# ── Public: scan range ────────────────────────────────────────────────────────

def scan_tdnet_range(start: date, end: date) -> None:
    """Scrape TDNET for each date in [start, end] and write to tdnet_index.

    Uses _tdnet_scanned_dates.json checkpoint; already-scanned dates are skipped.
    """
    from datetime import timedelta

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    scanned = _load_scanned_dates()

    current = start
    while current <= end:
        date_str = current.isoformat()
        if date_str in scanned:
            log.debug("TDNET skip (cached): %s", date_str)
            current += timedelta(days=1)
            continue

        records = scrape_tdnet_index(current)

        with duckdb.connect(str(DB_PATH)) as con:
            _init_tdnet_schema(con)
            if records:
                # Batch upsert: insert or ignore existing PK
                for rec in records:
                    con.execute("""
                        INSERT OR REPLACE INTO tdnet_index
                            (disclosure_id, disclosure_date, disclosure_time,
                             jpx_code, company_name, title, category,
                             pdf_url, is_amendment, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        rec["disclosure_id"],
                        rec["disclosure_date"],
                        rec["disclosure_time"],
                        rec["jpx_code"],
                        rec["company_name"],
                        rec["title"],
                        rec["category"],
                        rec["pdf_url"],
                        rec["is_amendment"],
                        rec["fetched_at"],
                    ])

        scanned.add(date_str)
        _save_scanned_dates(scanned)
        log.info("TDNET scanned %s: %d records", date_str, len(records))
        current += timedelta(days=1)


# ── Public: local query ───────────────────────────────────────────────────────

def find_tdnet_local(
    jpx_code: str | None = None,
    since: date | None = None,
    title_pattern: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Query tdnet_index in DuckDB. No network calls."""
    if not DB_PATH.exists():
        return []

    conditions: list[str] = []
    params: list = []

    if jpx_code is not None:
        conditions.append("jpx_code = ?")
        params.append(jpx_code)
    if since is not None:
        conditions.append("disclosure_date >= ?")
        params.append(since.isoformat())
    if category is not None:
        conditions.append("category = ?")
        params.append(category)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT disclosure_id, disclosure_date, disclosure_time, jpx_code,
               company_name, title, category, pdf_url, is_amendment, fetched_at
        FROM tdnet_index
        {where_clause}
        ORDER BY disclosure_date DESC, disclosure_time DESC
    """

    with duckdb.connect(str(DB_PATH)) as con:
        _init_tdnet_schema(con)
        rows = con.execute(sql, params).fetchall()
        cols = [
            "disclosure_id", "disclosure_date", "disclosure_time", "jpx_code",
            "company_name", "title", "category", "pdf_url", "is_amendment", "fetched_at",
        ]
        results = [dict(zip(cols, row)) for row in rows]

    # Apply title_pattern filter in Python (DuckDB REGEXP support varies)
    if title_pattern is not None:
        pat = re.compile(title_pattern)
        results = [r for r in results if pat.search(r["title"] or "")]

    return results


# ── Public: PDF download ──────────────────────────────────────────────────────

MAX_PDF_TEXT = 12000


def parse_tdnet_pdf(pdf_path: Path) -> str:
    """Extract text content from a TDNET PDF using markitdown.

    Returns plain text (mostly Japanese). No OCR — assumes the PDF is
    text-based, which is true for 決算短信 / 業績予想 / share buyback notices.

    Graceful failure: raises if len(text.strip()) < 200 (image or encrypted PDF).
    Truncates to MAX_PDF_TEXT (12000 chars) to fit LLM context.
    """
    from markitdown import MarkItDown

    result = MarkItDown().convert(str(pdf_path))
    text = result.text_content or ""
    if len(text.strip()) < 200:
        raise ValueError(
            f"parse_tdnet_pdf: extracted text too short ({len(text.strip())} chars) "
            f"— likely image-based or encrypted PDF: {pdf_path}"
        )
    if len(text) > MAX_PDF_TEXT:
        text = text[:MAX_PDF_TEXT] + "\n\n[…後續內容已截斷…]"
    return text


def download_tdnet_pdf(pdf_url: str, out_dir: Path | None = None) -> Path:
    """Download a TDNET PDF.  Idempotent: returns existing path without re-download.

    Default output: data/cache/jp/tdnet/{YYYYMMDD}/{filename}
    """
    filename = Path(pdf_url.rstrip("/").split("/")[-1]).name

    if out_dir is None:
        # Derive date from filename prefix if possible (first 8 chars after '1401')
        # Filename pattern: 1401YYYYMMDDXXXXXXXX.pdf
        date_part = ""
        m = re.search(r"1401(\d{8})", filename)
        if m:
            date_part = m.group(1)
        else:
            date_part = "unknown"
        out_dir = TDNET_PDF_DIR / date_part

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    if out_path.exists():
        log.debug("TDNET PDF already cached: %s", out_path)
        return out_path

    log.info("Downloading TDNET PDF: %s", pdf_url)
    resp = requests.get(pdf_url, headers=_HEADERS, timeout=60)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    log.info("Saved TDNET PDF: %s (%d bytes)", out_path, len(resp.content))
    return out_path
