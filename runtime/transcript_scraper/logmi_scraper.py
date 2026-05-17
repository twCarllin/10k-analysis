"""
logmi_scraper.py — Python wrapper around the Node scrape-logmi.ts subprocess.

Public API:
    scrape_logmi_transcript(jpx_code, company_name_ja, ...) -> dict | None

Exception hierarchy (shared with scraper.py):
    ScraperError (base)
    ├── NodeScriptError        — Node subprocess exited non-zero
    ├── ScraperProtocolError   — JSON parse failure / stdout protocol violation
    ├── ScraperDataError       — Data quality issue (short text, etc.)
    ├── ScraperTimeoutError    — Subprocess exceeded timeout
    └── ScraperAuthError       — Auth wall / paywall detected

Note: No tenacity retry here — Stagehand is not run in TC2 validation.
Retry logic can be added in TC3 if needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from .scraper import (
    NodeScriptError,
    ScraperAuthError,
    ScraperDataError,
    ScraperError,
    ScraperProtocolError,
    ScraperTimeoutError,
    _load_api_key,
)

logger = logging.getLogger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────
_PKG_DIR = Path(__file__).parent
_NODE_DIR = _PKG_DIR / "node"

_SUBPROCESS_TIMEOUT = 120  # seconds — same as scraper.py
_MIN_RAW_TEXT = 500        # logmi transcripts are usually >5000 chars; 500 is a loose lower bound


# ─── Subprocess invocation ────────────────────────────────────────────────────
async def _run_logmi_node_script(
    jpx_code: str,
    company_name_ja: str,
    headless: bool,
    api_key: str,
) -> tuple[str, str, int]:
    """Spawn Node scrape-logmi.ts and return (stdout_text, stderr_text, returncode).

    Reads both streams concurrently to avoid single-stream buffer deadlock.
    """
    env = {**os.environ, "ANTHROPIC_API_KEY": api_key}

    proc = await asyncio.create_subprocess_exec(
        "npx", "tsx", "src/scrape-logmi.ts",
        jpx_code, company_name_ja, str(headless).lower(),
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
            f"(jpx_code={jpx_code!r} company={company_name_ja!r})"
        )

    returncode = await proc.wait()
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    return stdout_text, stderr_text, returncode


# ─── Public API ───────────────────────────────────────────────────────────────
async def scrape_logmi_transcript(
    jpx_code: str,
    company_name_ja: str,
    headless: bool = True,
) -> Optional[dict]:
    """Run scrape-logmi.ts subprocess and return the transcript dict.

    Args:
        jpx_code: JPX 4-digit code, e.g. "6315".
        company_name_ja: Japanese company name for logmi search, e.g. "ＴＯＷＡ".
        headless: Run Chromium in headless mode (default True).

    Returns:
        dict with keys: url, title, date, raw_text, speakers, scraped_at
        Returns None if the transcript is genuinely not found (ScraperDataError).

    Raises:
        NodeScriptError: Node subprocess exited non-zero for non-auth reasons.
        ScraperProtocolError: stdout could not be parsed as JSON.
        ScraperTimeoutError: Subprocess exceeded _SUBPROCESS_TIMEOUT.
        ScraperAuthError: Auth wall or paywall detected.
        ScraperError: Other hard failures (config missing, etc.).
    """
    api_key = _load_api_key()

    stdout_text, stderr_text, returncode = await _run_logmi_node_script(
        jpx_code, company_name_ja, headless, api_key
    )

    if returncode != 0:
        stderr_lower = stderr_text.lower()
        # Auth / paywall detection
        if "auth" in stderr_lower or "login" in stderr_lower or "paywall" in stderr_lower:
            raise ScraperAuthError(
                f"Auth wall or paywall detected for {jpx_code!r}: {stderr_text[:500]}"
            )
        # Not-found is a data-level permanent failure — return None so caller can skip
        if "no 決算説明会 article found" in stderr_text:
            logger.warning(
                "scrape_logmi_transcript: no transcript found for jpx_code=%s company=%s",
                jpx_code, company_name_ja,
            )
            return None
        raise NodeScriptError(
            f"Node script exited {returncode} for jpx_code={jpx_code!r}: "
            f"{stderr_text.strip()[:1000]}"
        )

    # Parse JSON from stdout
    lines = [ln for ln in stdout_text.splitlines() if ln.strip()]
    if not lines:
        raise ScraperProtocolError(
            f"No stdout from Node script (jpx_code={jpx_code!r}). "
            f"stderr: {stderr_text.strip()[:500]}"
        )

    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise ScraperProtocolError(
            f"Invalid JSON from Node (jpx_code={jpx_code!r}): {stdout_text[:200]}"
        ) from e

    # Data quality check
    raw_text: str = data.get("raw_text", "")
    if len(raw_text) < _MIN_RAW_TEXT:
        raise ScraperDataError(
            f"raw_text too short ({len(raw_text)} chars) for jpx_code={jpx_code!r}, "
            "possible scrape failure or short notification article"
        )

    # Check for auth keywords in raw_text
    raw_lower = raw_text.lower()
    if any(kw in raw_lower for kw in ("auth", "login", "paywall")):
        raise ScraperAuthError(
            f"Auth/paywall keyword found in raw_text for jpx_code={jpx_code!r}"
        )

    logger.info(
        "scrape_logmi_transcript: success jpx_code=%s url=%s raw_text_len=%d",
        jpx_code, data.get("url", ""), len(raw_text),
    )
    return data
