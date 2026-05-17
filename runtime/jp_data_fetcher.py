import io
import json
import logging
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

BASE_DIR = Path(__file__).resolve().parent.parent
_config = json.loads((BASE_DIR / "config.json").read_text())

EDINET_API_KEY = _config.get("edinet_api_key", "")
EDINET_BASE = "https://api.edinet-fsa.go.jp/api/v2"
DB_PATH = BASE_DIR / "data/cache/jp/master.duckdb"
SCANNED_DATES_PATH = BASE_DIR / "data/cache/jp/_scanned_dates.json"
FAILED_DATES_PATH = BASE_DIR / "data/cache/jp/_failed_dates.json"

log = logging.getLogger(__name__)


def _ensure_db_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS ticker_map (
            jpx_code        TEXT PRIMARY KEY,
            edinet_code     TEXT NOT NULL,
            company_name_ja TEXT,
            company_name_en TEXT,
            market_segment  TEXT,
            sector_code     TEXT,
            updated_at      TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS filings_index (
            doc_id         TEXT PRIMARY KEY,
            edinet_code    TEXT NOT NULL,
            doc_type_code  TEXT NOT NULL,
            period_start   DATE,
            period_end     DATE,
            submitted_at   TIMESTAMP,
            filer_name     TEXT,
            ordinance_code TEXT,
            form_code      TEXT,
            fetched_at     TIMESTAMP DEFAULT now()
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_filings_edinet
        ON filings_index(edinet_code, doc_type_code, period_end)
    """)
    _init_tdnet_schema(con)


def _init_tdnet_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create tdnet_index table and indexes in master.duckdb if not present."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS tdnet_index (
            disclosure_id   TEXT PRIMARY KEY,
            disclosure_date DATE NOT NULL,
            disclosure_time TEXT NOT NULL,
            jpx_code        TEXT NOT NULL,
            company_name    TEXT,
            title           TEXT NOT NULL,
            category        TEXT,
            pdf_url         TEXT,
            is_amendment    BOOLEAN DEFAULT FALSE,
            fetched_at      TIMESTAMP DEFAULT now()
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_tdnet_jpx
        ON tdnet_index(jpx_code, disclosure_date)
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_tdnet_cat
        ON tdnet_index(category, disclosure_date)
    """)


def _fetch_jpx_listing() -> pd.DataFrame:
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), sheet_name=0, header=0, dtype=str)
    # Validate expected columns exist
    expected = {"コード", "銘柄名", "市場・商品区分", "33業種コード"}
    missing = expected - set(df.columns)
    assert not missing, f"JPX Excel 缺少預期欄位: {missing}"
    df = df.rename(columns={
        "コード": "jpx_code",
        "銘柄名": "company_name_ja",
        "市場・商品区分": "market_segment",
        "33業種コード": "sector_code",
    })
    # jpx_code may be 4-digit or have trailing spaces; strip and keep 4 chars
    df["jpx_code"] = df["jpx_code"].astype(str).str.strip().str[:4]
    df = df[df["jpx_code"].str.match(r"^\d{4}$")].copy()
    return df[["jpx_code", "company_name_ja", "market_segment", "sector_code"]]


def _fetch_edinet_corpcode() -> pd.DataFrame:
    # Azure CDN serving Edinetcode.zip blocks browser-style UA; curl UA is accepted
    url = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
    headers = {"User-Agent": "curl/8.4.0"}
    r = requests.get(url, timeout=60, headers=headers)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        raw = zf.read(csv_name)
    # Try cp932 first; fall back to utf-8
    try:
        df = pd.read_csv(io.BytesIO(raw), encoding="cp932", header=1, dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", header=1, dtype=str)
    # Column names after header=1 skip the description row
    df.columns = df.columns.str.strip()
    df = df.rename(columns={
        "ＥＤＩＮＥＴコード": "edinet_code",
        "提出者名": "company_name_ja",
        "提出者英語名": "company_name_en",
        "証券コード": "sec_code_5",
    })
    df["edinet_code"] = df["edinet_code"].astype(str).str.strip()
    # 5-digit security code → truncate to 4 digits
    df["jpx_code"] = df["sec_code_5"].astype(str).str.strip().str[:4]
    # Keep only rows with valid 4-digit jpx_code and valid EDINET code
    df = df[df["jpx_code"].str.match(r"^\d{4}$") & df["edinet_code"].str.match(r"^E\d{5}$")].copy()
    result_cols = ["jpx_code", "edinet_code", "company_name_en"]
    # company_name_en may be absent
    for col in result_cols:
        if col not in df.columns:
            df[col] = None
    return df[result_cols]


def ensure_ticker_map_fresh(max_age_days: int = 30, force: bool = False) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc)

    if not force and DB_PATH.exists():
        with duckdb.connect(str(DB_PATH)) as con:
            _ensure_db_schema(con)
            row = con.execute(
                "SELECT max(updated_at) FROM ticker_map"
            ).fetchone()
            if row and row[0] is not None:
                last_updated = row[0]
                # DuckDB returns naive datetime; treat as UTC
                if not last_updated.tzinfo:
                    last_updated = last_updated.replace(tzinfo=timezone.utc)
                age_days = (now - last_updated).total_seconds() / 86400
                if age_days < max_age_days:
                    return

    log.info("Fetching JPX listing...")
    jpx_df = _fetch_jpx_listing()
    log.info("Fetching EDINET corp codes...")
    edinet_df = _fetch_edinet_corpcode()

    merged = jpx_df.merge(edinet_df, on="jpx_code", how="inner")
    # company_name_ja from JPX takes priority; supplement company_name_en from EDINET
    if "company_name_ja_x" in merged.columns:
        merged["company_name_ja"] = merged["company_name_ja_x"]
    merged["updated_at"] = now.replace(tzinfo=None)

    cols = ["jpx_code", "edinet_code", "company_name_ja", "company_name_en",
            "market_segment", "sector_code", "updated_at"]
    for col in cols:
        if col not in merged.columns:
            merged[col] = None
    insert_df = merged[cols].drop_duplicates(subset=["jpx_code"])

    with duckdb.connect(str(DB_PATH)) as con:
        _ensure_db_schema(con)
        con.execute("DELETE FROM ticker_map")
        con.execute("INSERT INTO ticker_map SELECT * FROM insert_df")

    log.info("ticker_map rebuilt: %d rows", len(insert_df))


def ticker_to_edinet(jpx_code: str) -> str:
    if not DB_PATH.exists():
        raise ValueError(f"ticker_map not built; run ensure_ticker_map_fresh() first")
    with duckdb.connect(str(DB_PATH)) as con:
        row = con.execute(
            "SELECT edinet_code FROM ticker_map WHERE jpx_code = ?", [jpx_code]
        ).fetchone()
    if row is None:
        raise ValueError(f"找不到 jpx_code: {jpx_code}")
    return row[0]


# ── EDINET fetch layer ────────────────────────────────────────────────────────

class _EdinetServerError(Exception):
    """Transient server error — retryable."""


def _edinet_headers() -> dict:
    return {"Ocp-Apim-Subscription-Key": EDINET_API_KEY}


@retry(
    retry=retry_if_exception_type(_EdinetServerError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=16),
)
def _edinet_get(url: str, timeout: int = 30, **params) -> requests.Response:
    r = requests.get(url, params=params, headers=_edinet_headers(), timeout=timeout)
    if r.status_code >= 500:
        raise _EdinetServerError(f"EDINET {r.status_code} {url}")
    r.raise_for_status()
    return r


def fetch_edinet_index(d: date) -> list[dict]:
    url = f"{EDINET_BASE}/documents.json"
    r = _edinet_get(url, date=d.isoformat(), type="2")
    data = r.json()
    results = data.get("results", [])
    log.debug("fetch_edinet_index %s → %d docs (key=***)", d.isoformat(), len(results))
    return results


def _load_scanned_dates() -> set[str]:
    if SCANNED_DATES_PATH.exists():
        return set(json.loads(SCANNED_DATES_PATH.read_text()).get("scanned_dates", []))
    return set()


def _save_scanned_dates(dates: set[str]) -> None:
    SCANNED_DATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCANNED_DATES_PATH.write_text(
        json.dumps({"scanned_dates": sorted(dates)}, ensure_ascii=False)
    )


def _record_failed_date(date_str: str, exc: Exception) -> None:
    FAILED_DATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    failed: dict = {}
    if FAILED_DATES_PATH.exists():
        failed = json.loads(FAILED_DATES_PATH.read_text())
    failed[date_str] = str(exc)
    FAILED_DATES_PATH.write_text(json.dumps(failed, ensure_ascii=False, sort_keys=True))


def scan_date_range(start: date, end: date) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    scanned = _load_scanned_dates()

    current = start

    with duckdb.connect(str(DB_PATH)) as con:
        _ensure_db_schema(con)

        while current <= end:
            date_str = current.isoformat()
            if date_str in scanned:
                current += timedelta(days=1)
                continue

            log.info("Scanning EDINET %s ...", date_str)
            # Rate-limit: 1 req/sec; sleep before every API call
            time.sleep(1)
            try:
                results = fetch_edinet_index(current)
            except Exception as exc:
                log.warning("fetch_edinet_index(%s) failed: %s", date_str, exc)
                _record_failed_date(date_str, exc)
                # Do NOT mark as scanned so the next run retries this date
                current += timedelta(days=1)
                continue

            if results:
                rows = []
                for doc in results:
                    rows.append({
                        "doc_id": doc.get("docID"),
                        "edinet_code": doc.get("edinetCode"),
                        "doc_type_code": doc.get("docTypeCode"),
                        "period_start": doc.get("periodStart"),
                        "period_end": doc.get("periodEnd"),
                        "submitted_at": doc.get("submitDateTime"),
                        "filer_name": doc.get("filerName"),
                        "ordinance_code": doc.get("ordinanceCode"),
                        "form_code": doc.get("formCode"),
                        "fetched_at": datetime.now(tz=timezone.utc).replace(tzinfo=None).isoformat(),
                    })
                insert_df = pd.DataFrame(rows)
                # Upsert: replace on conflict to keep latest amendment data
                con.execute("""
                    INSERT OR REPLACE INTO filings_index
                    SELECT
                        doc_id, edinet_code, doc_type_code,
                        TRY_CAST(period_start AS DATE),
                        TRY_CAST(period_end AS DATE),
                        TRY_CAST(submitted_at AS TIMESTAMP),
                        filer_name, ordinance_code, form_code,
                        TRY_CAST(fetched_at AS TIMESTAMP)
                    FROM insert_df
                    WHERE doc_id IS NOT NULL
                      AND edinet_code IS NOT NULL
                      AND doc_type_code IS NOT NULL
                """)

            scanned.add(date_str)
            _save_scanned_dates(scanned)
            current += timedelta(days=1)


def find_filings_local(
    edinet_code: str,
    doc_types: set[str] | None = None,
    since: date | None = None,
) -> list[dict]:
    if not DB_PATH.exists():
        return []
    with duckdb.connect(str(DB_PATH)) as con:
        _ensure_db_schema(con)
        clauses = ["edinet_code = ?"]
        params: list = [edinet_code]
        if doc_types:
            placeholders = ", ".join("?" for _ in doc_types)
            clauses.append(f"doc_type_code IN ({placeholders})")
            params.extend(sorted(doc_types))
        if since is not None:
            clauses.append("period_end >= ?")
            params.append(since.isoformat())
        where = " AND ".join(clauses)
        rows = con.execute(
            f"SELECT * FROM filings_index WHERE {where} ORDER BY period_end DESC",
            params,
        ).fetchall()
        cols = [desc[0] for desc in con.description]
    return [dict(zip(cols, row)) for row in rows]


def download_filing(doc_id: str, out_dir: Path | None = None) -> Path:
    # Determine output directory from existing index if out_dir not given
    if out_dir is None:
        edinet_code = None
        if DB_PATH.exists():
            with duckdb.connect(str(DB_PATH)) as con:
                row = con.execute(
                    "SELECT edinet_code FROM filings_index WHERE doc_id = ?", [doc_id]
                ).fetchone()
                if row:
                    edinet_code = row[0]
        folder = BASE_DIR / "data/cache/jp/raw" / (edinet_code or "unknown")
    else:
        folder = out_dir
    folder.mkdir(parents=True, exist_ok=True)

    dest = folder / f"{doc_id}.zip"
    if dest.exists():
        return dest

    url = f"{EDINET_BASE}/documents/{doc_id}"
    r = _edinet_get(url, timeout=120, type="1")
    dest.write_bytes(r.content)
    log.info("Downloaded %s → %s", doc_id, dest)
    return dest
