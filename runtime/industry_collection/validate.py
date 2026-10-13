"""Offline source checks. Program checks never imply human approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import re
import unicodedata
from datetime import datetime, timezone

from runtime.tw_equity.doc_anchor import (
    FS_HEADING_ANCHORS,
    find_annual_report_sections,
    find_heading_sections,
)
from runtime.tw_equity.pdf_doc import load_pdf
from runtime.tw_equity.statements import (
    extract_statements,
    detect_header,
    parse_statement_lines,
    SECTION_HEADERS,
)
from runtime.tw_equity.tables import parse_customer_table, line_amounts
from runtime.industry_map.adapters import is_placeholder
from runtime.industry_map.pilot_candidates import _anonymous, _invalid_counterparty

LOG = logging.getLogger(__name__)


def _full_period(label):
    """Convert producer ROC dates while preserving point versus flow periods."""

    def convert(match):
        year = int(match[1])
        return str(year + 1911 if year < 1911 else year)

    return re.sub(r"(?<!\d)(\d{3,4})(?=-\d{2}-\d{2})", convert, label or "")


def _financial(doc, group):
    anchors = find_heading_sections(doc, FS_HEADING_ANCHORS, required=set())
    ledger = extract_statements(doc, anchors, group=group)
    if ledger is None:
        return [], [], ["statements_missing"], None
    samples = []
    pages = {page.number: page for page in doc.pages}
    for row in ledger.rows:
        if row.current is None:
            continue
        page = pages.get(row.page)
        col = ledger.current_col.get(row.statement)
        periods = ledger.column_periods.get(row.statement, [])
        period = periods[col] if col is not None and col < len(periods) else None
        quote = (
            page.lines[row.line_idx]
            if page and 0 <= row.line_idx < len(page.lines)
            else None
        )
        if page and quote:
            next_line = min(
                (
                    other.line_idx
                    for other in ledger.rows
                    if other.page == row.page and other.line_idx > row.line_idx
                ),
                default=len(page.lines),
            )
            quote = "\n".join(page.lines[row.line_idx : next_line])
        # Reparse the actual page with its own header and column order. This
        # rejects matching numbers in another column, page, or period.
        verified = False
        header_quote = None
        if page and quote and col is not None and period:
            header = detect_header(page.lines, fh=ledger.schema == "fh")
            header_quote = "\n".join(page.lines[:14])
            reparsed, _, _ = parse_statement_lines(
                [(page.number, i, line) for i, line in enumerate(page.lines)],
                row.statement,
                section_headers=SECTION_HEADERS[row.statement],
                schema=ledger.schema,
            )
            verified = (
                col < len(header.periods)
                and header.periods[col] == period
                and any(
                    check.line_idx == row.line_idx
                    and check.label == row.label
                    and check.columns == row.columns
                    and check.current == row.current
                    for check in reparsed
                )
                and col < len(row.columns)
                and row.columns[col] == row.current
                and bool(ledger.unit)
                and row.current in line_amounts(quote)
            )
        samples.append(
            dict(
                statement=row.statement,
                key=row.key,
                label=row.label,
                value=row.current,
                current_column=col,
                columns=row.columns,
                page=row.page,
                line_idx=row.line_idx,
                quote=quote,
                header_quote=header_quote,
                period=_full_period(period),
                basis=ledger.basis,
                unit=ledger.unit,
                source_check="matched" if verified else "blocked",
                human_check="pending",
            )
        )
    checks = [check.to_dict() for check in ledger.checks]
    gaps = []
    if any(sample["source_check"] == "blocked" for sample in samples):
        gaps.append("source_page_period_column_or_unit_unverified")
    if any(check["passed"] is False for check in checks):
        gaps.append("cross_check_failed")
    if any(check["passed"] is None for check in checks):
        gaps.append("cross_check_incomplete")
    if not samples:
        gaps.append("financial_values_missing")
    return samples, checks, gaps, ledger.to_dict()


def _counterparty_exclusion(name):
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))
    if not compact or re.fullmatch(r"[\W_]+", compact):
        return "missing_name"
    if compact in {
        "其他",
        "其它",
        "其他客戶",
        "其他廠商",
        "其他供應商",
        "合計",
        "總計",
        "小計",
    }:
        return "aggregate_or_other"
    if _invalid_counterparty(name):
        return "invalid_counterparty"
    if is_placeholder(name):
        return "placeholder"
    return None


def _relationships(doc, group):
    anchors = find_annual_report_sections(doc, required=set(), group=group)
    section = anchors.get("ar_customers")
    if section is None:
        return [], ["t8_section_missing"], []
    results = []
    excluded = []
    for page in doc.pages:
        if not section.start <= page.number <= section.end:
            continue
        for kind, word in (("sales", "銷貨"), ("purchase", "進貨")):
            for raw in page.tables:
                header = " ".join(str(cell or "") for row in raw[:2] for cell in row)
                if (
                    word not in header
                    or ("進貨" if kind == "sales" else "銷貨") in header
                ):
                    continue
                table = parse_customer_table([raw], kind=kind)
                if table is None:
                    continue
                for source_row in raw[2:]:
                    for column in (1, 5):
                        if column >= len(source_row):
                            continue
                        raw_name = str(source_row[column] or "").strip()
                        reason = _counterparty_exclusion(raw_name)
                        if reason and raw_name:
                            excluded.append(
                                dict(
                                    name=raw_name,
                                    reason=reason,
                                    page=page.number,
                                    kind=kind,
                                    quote=" | ".join(
                                        str(cell or "") for cell in source_row
                                    ),
                                )
                            )
                for year in table.years:
                    found = re.search(r"(\d{2,4})\s*年", year.label)
                    if not found:
                        continue
                    number = int(found[1])
                    number += 1911 if number < 1911 else 0
                    for entry in year.entries:
                        name = entry.name.strip()
                        if _counterparty_exclusion(name):
                            continue
                        source_row = next(
                            (
                                row
                                for row in raw[2:]
                                if any(name == str(cell or "").strip() for cell in row)
                            ),
                            None,
                        )
                        if source_row is None:
                            continue
                        anonymous = _anonymous(name)
                        results.append(
                            dict(
                                name=name,
                                anonymous=anonymous,
                                kind=kind,
                                page=page.number,
                                quote=" | ".join(
                                    str(cell or "") for cell in source_row
                                ),
                                header_quote=header,
                                period=f"{number}-01-01~{number}-12-31",
                                status="pending",
                                human_check="pending",
                            )
                        )
    return results, [] if results else ["t8_candidates_missing"], excluded


def _local_documents(root, tickers, inputs_dir):
    from .inventory import inventory

    documents = inventory(Path(root) / "tw_report", tickers)
    metadata = {}
    for ticker in tickers or sorted({str(row["ticker"]) for row in documents}):
        path = inputs_dir / f"{ticker}.json"
        if path.is_file():
            try:
                metadata[ticker] = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                LOG.warning(
                    "input_metadata_failed: %s %s",
                    ticker,
                    exc,
                    extra={"event": "input_metadata_failed"},
                )
    return documents, metadata


def _source_state(record):
    if record.get("status") == "failed":
        return "failed"
    if record.get("status") in {"missing", "not_fetched", "not_disclosed"}:
        return "missing"
    remote = (
        record.get("status") == "downloaded" or record.get("origin") == "downloaded"
    )
    if not record.get("local_path"):
        return "failed" if remote else "missing"
    return "downloaded" if remote else "local_existing"


def _write_immutable_json(path, values):
    encoded = json.dumps(values, ensure_ascii=False, indent=2)
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != values:
            raise ValueError(f"input_version_content_conflict: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(encoded)


def validate_collection(
    root=".",
    tickers=None,
    out="data/industry_collection/validation",
    *,
    documents=None,
    inputs_dir=None,
):
    """Validate explicit document records or discover local PDFs and saved indexes.

    Records use ticker, doc_type, period, local_path, sha256 and origin/status.
    All records are isolated; no network, OCR, model or map database is used.
    """
    root, out = Path(root).resolve(), Path(out).resolve()
    tickers = [str(ticker) for ticker in (tickers or [])]
    inputs_dir = Path(inputs_dir) if inputs_dir else root / "tw_equity_inputs"
    local, metadata = _local_documents(root, tickers, inputs_dir)
    if documents is None:
        documents = local
        index = root / "data/industry_collection/index.json"
        if index.is_file():
            saved = json.loads(index.read_text(encoding="utf-8"))
            documents += (
                saved if isinstance(saved, list) else saved.get("documents", [])
            )
    out.mkdir(parents=True, exist_ok=True)
    report = dict(
        documents=[],
        financial_samples=[],
        relationship_samples=[],
        anonymous_candidates=[],
        excluded_relationships=[],
        usable_sources=[],
        input_files=[],
        input_sources=[],
        counts=dict(local_existing=0, downloaded=0, failed=0, missing=0),
        gaps=[],
        human_check="pending",
    )
    seen = set()
    for record in documents:
        ticker = str(record.get("ticker", ""))
        if tickers and ticker not in tickers:
            continue
        identity = (
            ticker,
            record.get("doc_type"),
            record.get("period"),
            record.get("local_path"),
            record.get("sha256"),
            record.get("status"),
            record.get("origin"),
            record.get("url"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        result = dict(record, validation="blocked", gaps=[])
        report["documents"].append(result)
        state = _source_state(record)
        result["source_state"] = state
        report["counts"][state] += 1
        if state in {"failed", "missing"}:
            result["gaps"].append(
                record.get("reason") or f"source_{state}: no usable original file"
            )
            continue
        try:
            path = Path(record["local_path"])
            path = path if path.is_absolute() else root / path
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result["source_sha256"] = digest
            if record.get("sha256") and digest != record["sha256"]:
                raise ValueError("source_hash_mismatch")
            if record.get("doc_type") not in {"financial_report", "annual_report"}:
                raise ValueError("unsupported_local_parser")
            if path.suffix.lower() != ".pdf":
                raise ValueError("unsupported_file_type")
            doc = load_pdf(path, cache_dir=out / "cache", ocr=None)
            if not doc.pages:
                raise ValueError("pdf_pages_missing")
            result["pdf_warnings"] = dict(
                garbled_pages=doc.garbled_pages, image_pages=doc.image_pages
            )

            group = metadata.get(ticker, {}).get("group")
            if record["doc_type"] == "financial_report":
                samples, checks, gaps, ledger = _financial(doc, group)
                result["checks"] = checks
                result["ledger"] = ledger
                if ledger:
                    result["full_periods"] = {
                        key: _full_period(value)
                        for key, value in ledger["periods"].items()
                    }
                    result["period_basis"] = ledger["basis"]
                    result["basis"] = record.get("basis") or "consolidated"
                    result["unit"] = ledger["unit"]
                    result["currency"] = (
                        "TWD"
                        if "新台幣" in ledger["unit"] or "新臺幣" in ledger["unit"]
                        else record.get("currency")
                    )
                    declared = str(record.get("period", ""))
                    quarter = re.fullmatch(r"(\d{4})Q([1-4])", declared)
                    expected_end = None
                    if quarter:
                        expected_end = (
                            quarter[1]
                            + ("-03-31", "-06-30", "-09-30", "-12-31")[
                                int(quarter[2]) - 1
                            ]
                        )
                    elif re.fullmatch(r"\d{4}", declared):
                        expected_end = declared + "-12-31"
                    flow = result["full_periods"].get("flow_current")
                    if not expected_end or not flow or not flow.endswith(expected_end):
                        gaps.append("declared_period_mismatch_or_missing")
                collection = report["financial_samples"]
            else:
                samples, gaps, excluded = _relationships(doc, group)
                for item in excluded:
                    item.update(
                        ticker=ticker, source_path=str(path), source_sha256=digest
                    )
                report["excluded_relationships"].extend(excluded)
                result["excluded_relationships"] = excluded
                year = int(str(record.get("period", "0"))[:4])
                titles = "\n".join(page.text for page in doc.pages[:3])
                title_years = re.findall(r"(\d{2,4})\s*年?\s*(?:度)?\s*年報", titles)
                title_years = {
                    int(value) + (1911 if int(value) < 1911 else 0)
                    for value in title_years
                }
                candidate_years = {int(sample["period"][:4]) for sample in samples}
                if year not in title_years and (
                    not candidate_years or max(candidate_years) != year
                ):
                    gaps.append("annual_period_unverified")
                result["full_period"] = f"{year}-01-01~{year}-12-31"
                collection = report["relationship_samples"]
            affected = set(doc.garbled_pages + doc.image_pages)
            if any(sample["page"] in affected for sample in samples):
                gaps.append("source_page_needs_manual_review_no_ocr")
            result["gaps"] = gaps
            for sample in samples:
                if record["doc_type"] == "financial_report":
                    sample["period_basis"] = sample["basis"]
                    sample["basis"] = result["basis"]
                    sample["currency"] = result.get("currency")
                if sample["page"] in affected:
                    sample["source_check"] = "blocked"

                sample.update(
                    ticker=ticker, source_path=str(path), source_sha256=digest
                )
                if sample.get("anonymous"):
                    report["anonymous_candidates"].append(sample)
                else:
                    collection.append(sample)
            if not gaps or (
                record["doc_type"] == "annual_report"
                and "annual_period_unverified" not in gaps
                and "source_page_needs_manual_review_no_ocr" not in gaps
            ):
                result["validation"] = "program_checked_human_pending"
                report["usable_sources"].append(dict(result, local_path=str(path)))
        except Exception as exc:
            result["gaps"].append(f"{type(exc).__name__}: {exc}")
            LOG.warning(
                "document_validation_failed: %s %s",
                ticker,
                exc,
                extra={"event": "document_validation_failed"},
            )
    for ticker in tickers or sorted({str(row.get("ticker")) for row in documents}):
        sources = [
            row for row in report["usable_sources"] if str(row["ticker"]) == ticker
        ]
        for source in sources:
            if source["doc_type"] != "financial_report":
                continue
            fiscal_year = int(source["period"][:4]) - (
                0 if source["ledger"]["basis"] == "FY" else 1
            )
            annuals = [
                row
                for row in sources
                if row["doc_type"] == "annual_report"
                and str(row["period"]) == str(fiscal_year)
            ]
            if not annuals:
                report["gaps"].append(
                    f"compatible_annual_report_missing: {ticker}/{source['period']}"
                )
                continue
            for annual in annuals:
                values = dict(
                    company_name=metadata.get(ticker, {}).get("company_name", ticker),
                    group=metadata.get(ticker, {}).get("group"),
                    parent_fs_path=None,
                    ticker=ticker,
                    consolidated_fs_path=source["local_path"],
                    annual_report_path=annual["local_path"],
                    fs_period=source["period"][:4] + source["ledger"]["basis"],
                    fiscal_year=int(annual["period"][:4]),
                )
                version_id = source["source_sha256"] + "_" + annual["source_sha256"]
                folder = out / "inputs" / str(source["period"]) / version_id
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{ticker}.json"
                manifest = dict(
                    ticker=ticker,
                    period=source["period"],
                    version_id=version_id,
                    input_path=str(target),
                    sources=[
                        dict(
                            doc_type=row["doc_type"],
                            period=row["period"],
                            local_path=row["local_path"],
                            sha256=row["source_sha256"],
                        )
                        for row in (source, annual)
                    ],
                )
                try:
                    _write_immutable_json(target, values)
                    _write_immutable_json(folder / f"{ticker}.sources.json", manifest)
                except (OSError, ValueError) as exc:
                    report["gaps"].append(str(exc))
                    continue
                report["input_files"].append(str(target))
                report["input_sources"].append(manifest)
    report["all_financial_samples"] = list(report["financial_samples"])
    report["blocked_financial_samples"] = [
        sample
        for sample in report["financial_samples"]
        if sample["source_check"] != "matched"
    ]
    report["financial_samples_total"] = len(report["financial_samples"])
    buckets = {}
    for sample in report["financial_samples"]:
        if sample["source_check"] != "matched":
            continue
        buckets.setdefault(sample["ticker"], {}).setdefault(
            sample["statement"], []
        ).append(sample)
    ordered = {}
    for ticker, statements in buckets.items():
        ordered[ticker] = []
        while any(statements.values()):
            for statement in ("bs", "is", "cf"):
                if statements.get(statement):
                    ordered[ticker].append(statements[statement].pop(0))
    report["financial_samples"] = []
    while any(ordered.values()):
        for ticker in sorted(ordered):
            if ordered[ticker]:
                report["financial_samples"].append(ordered[ticker].pop(0))
    for key, minimum in (("financial_samples", 20), ("relationship_samples", 10)):
        report[key + "_available"] = len(report[key])
        if len(report[key]) < minimum:
            report["gaps"].append(
                f"{key}_insufficient: {len(report[key])}/{minimum}; all sampled"
            )
        report[key] = report[key][:minimum]
    report["gaps"].extend(
        dict(ticker=row.get("ticker"), period=row.get("period"), reasons=row["gaps"])
        for row in report["documents"]
        if row["gaps"]
    )
    if not report["documents"]:
        report["gaps"].append("documents_missing")
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "usable_sources.json").write_text(
        json.dumps(report["usable_sources"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def validate(root="data/industry_collection", *, tickers=None, out=None, repo_root="."):
    """Validate a collection directory index together with existing local PDFs."""
    root = Path(root).resolve()
    repo_root = Path(repo_root).resolve()
    from .inventory import inventory

    records = inventory(repo_root / "tw_report", tickers)
    index = root / "index.json"
    if index.is_file():
        saved = json.loads(index.read_text(encoding="utf-8"))
        records += saved if isinstance(saved, list) else saved.get("documents", [])
    return validate_collection(
        repo_root, tickers, out or root / "validation", documents=records
    )


class _LogFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            dict(
                timestamp=datetime.fromtimestamp(
                    record.created, timezone.utc
                ).isoformat(),
                level=record.levelname,
                logger=record.name,
                event=getattr(record, "event", "validation"),
                message=record.getMessage(),
            ),
            ensure_ascii=False,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--out", default="data/industry_collection/validation")
    parser.add_argument("--root", default=".")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-format", choices=["json"], default="json")
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(_LogFormatter())
    logging.basicConfig(level=args.log_level, handlers=[handler], force=True)
    print(
        json.dumps(
            validate_collection(args.root, args.tickers, args.out), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
