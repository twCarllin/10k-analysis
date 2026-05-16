"""
jp_ixbrl_parser.py — iXBRL / XBRL instance parser for EDINET 有価証券報告書

Extracts the 5-year summary of business results (主要な経営指標等の推移) from
a yuho ZIP file downloaded via jp_data_fetcher.download_filing().

Public API:
    find_xbrl_instance(zip_path: Path) -> Path
    extract_five_year_summary(zip_path: Path) -> dict
"""

import logging
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
EXTRACTED_DIR = BASE_DIR / "data" / "cache" / "jp" / "extracted"

log = logging.getLogger(__name__)

# ── Element maps ──────────────────────────────────────────────────────────────

# JGAAP: jpcrp_cor namespace
JGAAP_ELEMENT_MAP = {
    "net_sales": [
        "jpcrp_cor:NetSalesSummaryOfBusinessResults",
    ],
    "ordinary_income": [
        "jpcrp_cor:OrdinaryIncomeLossSummaryOfBusinessResults",
    ],
    "net_income": [
        "jpcrp_cor:ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults",
        "jpcrp_cor:NetIncomeLossSummaryOfBusinessResults",  # fallback for older taxonomy
    ],
    "comprehensive_income": [
        "jpcrp_cor:ComprehensiveIncomeSummaryOfBusinessResults",
    ],
    "net_assets": [
        "jpcrp_cor:NetAssetsSummaryOfBusinessResults",
    ],
    "total_assets": [
        "jpcrp_cor:TotalAssetsSummaryOfBusinessResults",
    ],
    "operating_cash_flow": [
        "jpcrp_cor:NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults",
    ],
    "eps_yen": [
        # taxonomy uses "EarningsLoss" variant in recent years
        "jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults",
        "jpcrp_cor:BasicEarningsPerShareSummaryOfBusinessResults",
    ],
    "bps_yen": [
        "jpcrp_cor:NetAssetsPerShareSummaryOfBusinessResults",
    ],
    "roe_pct": [
        "jpcrp_cor:RateOfReturnOnEquitySummaryOfBusinessResults",
    ],
    "per": [
        "jpcrp_cor:PriceEarningsRatioSummaryOfBusinessResults",
    ],
    "equity_ratio_pct": [
        "jpcrp_cor:EquityToAssetRatioSummaryOfBusinessResults",
    ],
    "employees": [
        "jpcrp_cor:NumberOfEmployees",
    ],
}

# IFRS: jpigp_cor namespace (None means element has no IFRS equivalent)
IFRS_ELEMENT_MAP = {
    "net_sales": [
        "jpigp_cor:RevenueIFRSSummaryOfBusinessResults",
    ],
    "ordinary_income": None,  # IFRS has no 経常利益 concept
    "net_income": [
        "jpigp_cor:ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
    ],
    "comprehensive_income": [
        "jpigp_cor:ComprehensiveIncomeIFRSSummaryOfBusinessResults",
    ],
    "net_assets": [
        "jpigp_cor:EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
    ],
    "total_assets": [
        "jpigp_cor:TotalAssetsIFRSSummaryOfBusinessResults",
    ],
    "operating_cash_flow": [
        "jpigp_cor:NetCashProvidedByUsedInOperatingActivitiesIFRSSummaryOfBusinessResults",
    ],
    "eps_yen": [
        "jpigp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
        "jpigp_cor:BasicEarningsPerShareIFRSSummaryOfBusinessResults",
    ],
    "bps_yen": [
        "jpigp_cor:EquityAttributableToOwnersOfParentPerShareIFRSSummaryOfBusinessResults",
    ],
    "roe_pct": [
        "jpigp_cor:RateOfReturnOnEquityIFRSSummaryOfBusinessResults",
    ],
    "per": [
        "jpigp_cor:PriceEarningsRatioIFRSSummaryOfBusinessResults",
    ],
    "equity_ratio_pct": [
        "jpigp_cor:EquityToAssetRatioIFRSSummaryOfBusinessResults",
    ],
    "employees": [
        "jpcrp_cor:NumberOfEmployees",  # shared across both standards
    ],
}

# Keys whose values should NOT have unit_scale applied (ratios & per-share amounts)
_NO_SCALE_KEYS = {"eps_yen", "bps_yen", "roe_pct", "per", "equity_ratio_pct", "employees"}


# ── find_xbrl_instance ────────────────────────────────────────────────────────

def find_xbrl_instance(zip_path: Path) -> Path:
    """Locate and extract the main XBRL instance file from a yuho ZIP.

    Extraction target: data/cache/jp/extracted/{doc_id}/
    Idempotent: if already extracted, returns the cached path.

    Selection rules:
      1. Filter ZipInfo to paths containing 'XBRL/PublicDoc/' with .xbrl extension.
      2. Exclude paths containing 'AuditDoc'.
      3. If 1 candidate → return it.  If multiple → take the largest by file_size.
      4. If 0 candidates → raise FileNotFoundError.

    Args:
        zip_path: Path to the downloaded ZIP (e.g. data/cache/jp/raw/E01708/S100W53I.zip)

    Returns:
        Path to the extracted .xbrl file.

    Raises:
        FileNotFoundError: No XBRL instance found in the ZIP.
    """
    doc_id = zip_path.stem
    extract_dir = EXTRACTED_DIR / doc_id

    # Idempotent: if already extracted, find and return
    if extract_dir.exists():
        candidates = list(extract_dir.rglob("*.xbrl"))
        candidates = [p for p in candidates if "AuditDoc" not in str(p)]
        if candidates:
            best = max(candidates, key=lambda p: p.stat().st_size)
            log.debug("find_xbrl_instance: cache hit %s", best)
            return best

    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, metadata_encoding="cp932") as zf:
        infos = zf.infolist()

        # Filter to PublicDoc .xbrl files, excluding AuditDoc
        candidates = [
            info for info in infos
            if "XBRL/PublicDoc/" in info.filename
            and info.filename.endswith(".xbrl")
            and "AuditDoc" not in info.filename
        ]

        if not candidates:
            raise FileNotFoundError(f"No XBRL instance found in {zip_path}")

        # Pick largest by file_size
        best_info = max(candidates, key=lambda i: i.file_size)

        # Extract all files (needed to resolve relative links) — but only PublicDoc
        for info in infos:
            if "AuditDoc" not in info.filename:
                _safe_extract_member(zf, info, extract_dir)

    extracted_path = extract_dir / best_info.filename
    log.info("find_xbrl_instance: extracted %s → %s", zip_path.name, extracted_path.name)
    return extracted_path


# ── extract_five_year_summary ─────────────────────────────────────────────────

def extract_five_year_summary(zip_path: Path) -> dict:
    """Extract the 5-year summary of business results from a yuho ZIP.

    Does not require an API key or LLM — pure local XBRL parsing.

    Args:
        zip_path: Path to the downloaded ZIP.

    Returns:
        Dict conforming to the schema documented in task/2026-05-17.md §TA3.
    """
    doc_id = zip_path.stem
    xbrl_path = find_xbrl_instance(zip_path)

    log.info("extract_five_year_summary: parsing %s", xbrl_path.name)
    xml_bytes = xbrl_path.read_bytes()
    soup = BeautifulSoup(xml_bytes, features="lxml-xml")

    warnings: list[str] = []

    # ── 1. Build context id → end-date mapping ────────────────────────────────
    context_dates = _build_context_dates(soup)

    # ── 2. Detect accounting standard ────────────────────────────────────────
    accounting_standard = _detect_accounting_standard(soup, warnings)

    # ── 3. Select element map ─────────────────────────────────────────────────
    element_map = IFRS_ELEMENT_MAP if accounting_standard == "IFRS" else JGAAP_ELEMENT_MAP

    # ── 4. Extract DEI metadata ───────────────────────────────────────────────
    edinet_code = _dei_text(soup, "jpdei_cor:EDINETCodeDEI") or ""
    filer_name_ja = _dei_text(soup, "jpdei_cor:FilerNameInJapaneseDEI") or ""

    # fiscal_year_end from CurrentYearDuration or CurrentYearInstant context
    fiscal_year_end = (
        context_dates.get("CurrentYearDuration")
        or context_dates.get("CurrentYearInstant")
        or ""
    )

    # ── 5. Extract facts for each metric ─────────────────────────────────────
    five_year: dict[str, dict[str, object]] = {}
    all_decimals: list[int] = []

    for key, candidates in element_map.items():
        if candidates is None:
            # IFRS element with no equivalent (e.g. ordinary_income under IFRS)
            warnings.append(f"{key}: not applicable under {accounting_standard}")
            continue

        facts = _collect_facts(soup, candidates, context_dates)

        if not facts:
            warnings.append(f"{key}: no facts found (elements tried: {candidates})")
            continue

        year_values: dict[str, float] = {}
        for ctx_id, (raw_value, decimals) in facts.items():
            date = context_dates.get(ctx_id)
            if not date:
                continue
            if key in _NO_SCALE_KEYS:
                year_values[date] = raw_value
            else:
                year_values[date] = raw_value
                all_decimals.append(decimals)

        if year_values:
            five_year[key] = year_values

    # ── 6. Compute unit_scale ─────────────────────────────────────────────────
    unit_scale = _compute_unit_scale(all_decimals)

    return {
        "doc_id": doc_id,
        "edinet_code": edinet_code,
        "filer_name_ja": filer_name_ja,
        "fiscal_year_end": fiscal_year_end,
        "accounting_standard": accounting_standard,
        "currency": "JPY",
        "unit_scale": unit_scale,
        "five_year_summary": five_year,
        "_extracted_at": datetime.now(tz=timezone.utc).isoformat(),
        "_warnings": warnings,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_extract_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, extract_dir: Path) -> None:
    """Extract a single ZIP member only if its resolved destination is inside extract_dir.

    Guards against path traversal attacks where a malicious ZIP entry contains
    '../' sequences or absolute paths that would escape the extraction root.
    """
    dest = (extract_dir / info.filename).resolve()
    extract_root = extract_dir.resolve()
    if not dest.is_relative_to(extract_root):
        log.warning("Skipping suspicious ZIP entry: %s", info.filename)
        return
    zf.extract(info, extract_dir)

def _build_context_dates(soup: BeautifulSoup) -> dict[str, str]:
    """Build mapping from context id to fiscal year end date (YYYY-MM-DD).

    For Duration contexts: use endDate.
    For Instant contexts: use instant date.
    """
    mapping: dict[str, str] = {}
    for ctx in soup.find_all("xbrli:context"):
        ctx_id = ctx.get("id", "")
        period = ctx.find("xbrli:period")
        if not period:
            continue
        end_tag = period.find("xbrli:endDate")
        instant_tag = period.find("xbrli:instant")
        date_str = (end_tag.text.strip() if end_tag else
                    instant_tag.text.strip() if instant_tag else None)
        if date_str:
            mapping[ctx_id] = date_str
    return mapping


def _detect_accounting_standard(soup: BeautifulSoup, warnings: list[str]) -> str:
    """Return 'JGAAP', 'IFRS', or 'USGAAP'.  Defaults to 'JGAAP' if not found."""
    tag = soup.find("jpdei_cor:AccountingStandardsDEI")
    if tag is None:
        warnings.append("AccountingStandardsDEI not found; defaulting to JGAAP")
        return "JGAAP"
    raw = tag.text.strip()
    if raw == "IFRS":
        return "IFRS"
    if raw in ("US GAAP", "US-GAAP", "USGAAP"):
        return "USGAAP"
    if raw == "Japan GAAP":
        return "JGAAP"
    warnings.append(f"Unknown AccountingStandardsDEI value: {raw!r}; defaulting to JGAAP")
    return "JGAAP"


def _dei_text(soup: BeautifulSoup, tag_name: str) -> str | None:
    """Return stripped text of a DEI element, or None if not found."""
    tag = soup.find(tag_name)
    return tag.text.strip() if tag else None


def _collect_facts(
    soup: BeautifulSoup,
    candidates: list[str],
    context_dates: dict[str, str],
) -> dict[str, tuple[float, int]]:
    """Collect consolidated facts for a metric from the first matching element list.

    Returns {ctx_id: (raw_value, decimals_int)} for consolidated contexts only.
    Falls back to NonConsolidated if no consolidated facts found.

    Consolidated = contextRef does NOT contain 'NonConsolidated' (case-insensitive).
    """
    all_facts: dict[str, tuple[float, int]] = {}  # ctx_id → (value, decimals)

    for elem_name in candidates:
        tags = soup.find_all(elem_name)
        if tags:
            for tag in tags:
                ctx_id = tag.get("contextRef", "")
                text = tag.text.strip()
                decimals_str = tag.get("decimals", "0")
                try:
                    raw = float(text)
                except (ValueError, TypeError):
                    continue
                if decimals_str == "INF":
                    decimals = 0
                else:
                    try:
                        decimals = int(decimals_str)
                    except (ValueError, TypeError):
                        continue
                # Only keep contexts that map to a known date
                if ctx_id not in context_dates:
                    continue
                all_facts[ctx_id] = (raw, decimals)
            break  # stop at first matching element name

    if not all_facts:
        return {}

    # Separate consolidated vs non-consolidated
    consolidated = {
        ctx_id: v
        for ctx_id, v in all_facts.items()
        if "nonconsolidated" not in ctx_id.lower()
    }
    non_consolidated = {
        ctx_id: v
        for ctx_id, v in all_facts.items()
        if "nonconsolidated" in ctx_id.lower()
    }

    if consolidated:
        return _pick_best_per_date(consolidated, context_dates)

    # Fallback: no consolidated data — company has no subsidiaries
    log.debug("Falling back to NonConsolidated facts")
    return _pick_best_per_date(non_consolidated, context_dates, is_fallback=True)


def _pick_best_per_date(
    facts: dict[str, tuple[float, int]],
    context_dates: dict[str, str],
    is_fallback: bool = False,
) -> dict[str, tuple[float, int]]:
    """When multiple facts map to the same date (same fiscal year end), keep the one
    with the shortest context id (least specific / base context).

    Returns one entry per unique date.
    """
    from collections import defaultdict
    by_date: dict[str, list[str]] = defaultdict(list)
    for ctx_id in facts:
        date = context_dates.get(ctx_id)
        if date:
            by_date[date].append(ctx_id)

    result: dict[str, tuple[float, int]] = {}
    for date, ctx_ids in by_date.items():
        # Pick shortest ctx_id as base context (less specific = less qualified);
        # lexicographic tie-breaker ensures deterministic selection when lengths are equal.
        best_ctx = min(ctx_ids, key=lambda x: (len(x), x))
        result[best_ctx] = facts[best_ctx]
    return result


def _compute_unit_scale(decimals_list: list[int]) -> int:
    """Compute unit_scale from the most common decimals value.

    unit_scale = 10^(-most_common_decimals)  (for negative decimals)
    Examples:
      decimals=-3 → unit_scale=1000  (千円)
      decimals=-6 → unit_scale=1000000  (百万円)
      decimals=0  → unit_scale=1  (円)
    """
    if not decimals_list:
        return 1
    most_common_decimals = Counter(decimals_list).most_common(1)[0][0]
    if most_common_decimals < 0:
        return 10 ** (-most_common_decimals)
    return 1
