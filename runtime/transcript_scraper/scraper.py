"""
scraper.py — Python wrapper around the Node scrape.ts subprocess.

Public API:
    scrape_transcript(ticker, quarter, year, ...) -> Transcript | None

Exception hierarchy:
    ScraperError (base)
    ├── NodeScriptError        — Node subprocess exited non-zero
    ├── ScraperProtocolError   — JSON parse failure / stdout protocol violation
    ├── ScraperDataError       — Data quality issue (short text, empty participants)
    ├── ScraperTimeoutError    — Subprocess exceeded timeout
    └── ScraperAuthError       — Auth wall detected
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .models import Participant, Transcript, TranscriptSections
from .parser import parse_transcript

logger = logging.getLogger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────
_PKG_DIR = Path(__file__).parent
_NODE_DIR = _PKG_DIR / "node"
_CONFIG_PATH = _PKG_DIR.parent.parent / "config.json"

_SUBPROCESS_TIMEOUT = 120  # seconds
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
_QUARTER_RE = re.compile(r"^Q[1-4]$", re.IGNORECASE)
_YEAR_RE = re.compile(r"^\d{4}$")
_MIN_RAW_TEXT = 1000


# ─── Exceptions ───────────────────────────────────────────────────────────────
class ScraperError(Exception):
    """Base class for all scraper errors."""


class NodeScriptError(ScraperError):
    """Node subprocess exited with non-zero returncode."""


class ScraperProtocolError(ScraperError):
    """Stdout from Node could not be parsed as valid JSON, or protocol violated."""


class ScraperDataError(ScraperError):
    """Scraped data failed quality checks (short text, empty participants, etc.)."""


class ScraperTimeoutError(ScraperError):
    """Node subprocess timed out."""


class ScraperAuthError(ScraperError):
    """Yahoo Finance returned an auth wall; login required."""


# ─── Config loading ───────────────────────────────────────────────────────────
def _load_api_key() -> str:
    """Load anthropic_api_key from config.json (hard failure if missing)."""
    if not _CONFIG_PATH.exists():
        raise ScraperError(
            f"config.json not found at {_CONFIG_PATH}. "
            "Ensure you are running from the project root and config.json exists."
        )
    try:
        config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ScraperError(f"config.json is not valid JSON: {e}") from e

    api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ScraperError(
            "anthropic_api_key not found in config.json and ANTHROPIC_API_KEY env var not set."
        )
    return api_key


# ─── Subprocess invocation ────────────────────────────────────────────────────
async def _run_node_script(
    ticker: str,
    quarter: str,
    year: str,
    headless: bool,
    api_key: str,
) -> tuple[str, str, int]:
    """Spawn Node scrape.ts and return (stdout_text, stderr_text, returncode).

    Uses asyncio.gather to read both streams concurrently, then waits for the
    process to exit — avoids single-stream buffer deadlock.
    """
    env = {**os.environ, "ANTHROPIC_API_KEY": api_key}

    proc = await asyncio.create_subprocess_exec(
        "npx", "tsx", "src/scrape.ts",
        ticker, quarter, year, str(headless).lower(),
        cwd=str(_NODE_DIR),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            asyncio.gather(proc.stdout.read(), proc.stderr.read()),  # type: ignore[arg-type]
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ScraperTimeoutError(
            f"Node script timed out after {_SUBPROCESS_TIMEOUT}s "
            f"({ticker} {quarter} {year})"
        )

    returncode = await proc.wait()
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    return stdout_text, stderr_text, returncode


# ─── Retry logic (soft failures only) ────────────────────────────────────────
@retry(
    retry=retry_if_exception_type((NodeScriptError, ScraperTimeoutError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
async def _scrape_with_retry(
    ticker: str,
    quarter: str,
    year: str,
    headless: bool,
    api_key: str,
) -> dict:
    """Run the Node subprocess and return parsed JSON dict. Retries on soft failures."""
    stdout_text, stderr_text, returncode = await _run_node_script(
        ticker, quarter, year, headless, api_key
    )

    if returncode != 0:
        # Check for auth wall indicators in stderr
        if "auth wall" in stderr_text.lower() or "sign in" in stderr_text.lower():
            raise ScraperAuthError(
                f"Auth wall detected for {ticker}: {stderr_text[:500]}"
            )
        # Transcript not found is a data-level soft failure, not a transient error;
        # raise ScraperDataError so the retry decorator does NOT retry it.
        if "transcript not found" in stderr_text.lower():
            raise ScraperDataError(
                f"Transcript not found for {ticker} {quarter} {year}: "
                f"{stderr_text.strip()[:500]}"
            )
        raise NodeScriptError(
            f"Node script exited {returncode} for {ticker} {quarter} {year}: "
            f"{stderr_text.strip()[:1000]}"
        )

    # Parse JSON
    lines = [ln for ln in stdout_text.splitlines() if ln.strip()]
    if not lines:
        if not stderr_text.strip():
            raise ScraperProtocolError(
                f"No stdout from Node script and stderr is empty "
                f"(ticker={ticker} {quarter} {year})"
            )
        raise NodeScriptError(
            f"Node script produced no stdout. stderr: {stderr_text.strip()[:500]}"
        )

    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        if not stderr_text.strip():
            # Hard failure: protocol broken and no error info from Node
            raise ScraperProtocolError(
                f"Invalid JSON from Node (and empty stderr): {stdout_text[:200]}"
            ) from e
        # Node had error output — treat as transient; allow retry / skip_on_failure
        raise NodeScriptError(
            f"Node failed and stdout JSON unparseable: {stderr_text.strip()[:500]}"
        ) from e

    return data


# ─── Filter helper (sub-task 2 #4 inline fix) ────────────────────────────────
def _filter_empty_unknown_segments(sections: TranscriptSections) -> TranscriptSections:
    """Drop Unknown segments whose text body is empty (header-only false positives)."""
    def _keep(seg):
        if seg.speaker == "Unknown" and not seg.text.strip():
            return False
        return True

    return TranscriptSections(
        prepared_remarks=[s for s in sections.prepared_remarks if _keep(s)],
        qa=[s for s in sections.qa if _keep(s)],
    )


# ─── Public API ───────────────────────────────────────────────────────────────
async def scrape_transcript(
    ticker: str,
    quarter: str,
    year: str | int,
    headless: bool = True,
    save_json: bool = False,
    output_dir: Optional[str | Path] = None,
    skip_on_failure: bool = False,
) -> Transcript | None:
    """Scrape an earnings call transcript from Yahoo Finance.

    Args:
        ticker: Stock ticker symbol (e.g. "INTC"). Must be 1-5 uppercase letters.
        quarter: Quarter identifier (e.g. "Q1", "Q2", "Q3", "Q4").
        year: Fiscal year (e.g. 2026 or "2026").
        headless: Run Chromium in headless mode (default True).
        save_json: If True, save raw JSON output to output_dir.
        output_dir: Directory for saved JSON files (defaults to cwd).
        skip_on_failure: If True, soft failures return None instead of raising.
                         Hard failures always raise regardless.

    Returns:
        Transcript object on success, or None if skip_on_failure=True and a
        soft failure occurred.

    Raises:
        ScraperError (and subclasses) on hard failures, or on any failure
        when skip_on_failure=False.
    """
    year_str = str(year).strip()

    # ── Hard failure: invalid inputs (validated before any subprocess call) ───
    ticker_clean = ticker.strip().upper()
    if not ticker_clean or not _TICKER_RE.match(ticker_clean):
        raise ValueError(
            f"Invalid ticker: {ticker!r}. Must be 1–5 uppercase letters."
        )
    if not _QUARTER_RE.match(quarter):
        raise ValueError(
            f"Invalid quarter: {quarter!r}. Must be Q1-Q4."
        )
    if not _YEAR_RE.match(year_str):
        raise ValueError(
            f"Invalid year: {year!r}. Must be a 4-digit year."
        )

    # ── Hard failure: config / environment errors ─────────────────────────────
    api_key = _load_api_key()  # raises ScraperError (hard) if missing

    try:
        data = await _scrape_with_retry(
            ticker_clean, quarter, year_str, headless, api_key
        )
    except ScraperProtocolError:
        # Protocol error with empty stderr → hard failure, always raise
        raise
    except (NodeScriptError, ScraperTimeoutError, ScraperDataError, ScraperAuthError) as exc:
        if skip_on_failure:
            logger.warning(
                "scrape_transcript soft failure — ticker=%s quarter=%s year=%s reason=%s",
                ticker_clean, quarter, year_str, exc,
            )
            return None
        raise

    # ── Data quality checks ───────────────────────────────────────────────────
    raw_text: str = data.get("raw_text", "")
    participants_raw: list[dict] = data.get("participants", [])

    if len(raw_text) < _MIN_RAW_TEXT:
        exc = ScraperDataError(
            f"raw_text too short ({len(raw_text)} chars), "
            "possible bot block or page error"
        )
        if skip_on_failure:
            logger.warning(
                "scrape_transcript soft failure — ticker=%s quarter=%s year=%s reason=%s",
                ticker_clean, quarter, year_str, exc,
            )
            return None
        raise exc

    if not participants_raw:
        exc = ScraperDataError(
            f"No participants extracted for {ticker_clean} {quarter} {year_str}"
        )
        if skip_on_failure:
            logger.warning(
                "scrape_transcript soft failure — ticker=%s quarter=%s year=%s reason=%s",
                ticker_clean, quarter, year_str, exc,
            )
            return None
        raise exc

    # ── Build Participant list ─────────────────────────────────────────────────
    participants = [
        Participant(
            name=p["name"],
            role=p.get("role"),
            affiliation=p.get("affiliation"),
        )
        for p in participants_raw
        if p.get("name")
    ]

    # ── Parse transcript into sections ────────────────────────────────────────
    sections = parse_transcript(raw_text, participants)
    sections = _filter_empty_unknown_segments(sections)

    # ── Assemble Transcript ───────────────────────────────────────────────────
    transcript = Transcript(
        ticker=ticker_clean,
        quarter=quarter,
        year=year_str,
        date=data.get("date", ""),
        url=data.get("url", ""),
        participants=participants,
        sections=sections,
        raw_text=raw_text,
        scraped_at=data.get("scraped_at", datetime.now(timezone.utc).isoformat()),
    )

    # ── Optional JSON save ────────────────────────────────────────────────────
    if save_json:
        out_dir = Path(output_dir) if output_dir else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{ticker_clean}_{quarter}_{year_str}.json"
        (out_dir / filename).write_text(
            transcript.model_dump_json(indent=2), encoding="utf-8"
        )
        logger.info("Saved transcript JSON to %s/%s", out_dir, filename)

    return transcript
