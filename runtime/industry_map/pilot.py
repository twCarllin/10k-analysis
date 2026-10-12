"""Local PDF pilot. Candidate roles and T8 relationships remain pending."""

import hashlib
import json
from pathlib import Path

from runtime.tw_equity.doc_anchor import (
    FS_HEADING_ANCHORS,
    find_annual_report_sections,
    find_heading_sections,
)
from runtime.tw_equity.pdf_doc import load_pdf
from runtime.tw_equity.tables import extract_tables

from .adapters import normalize
from .model import coverage, entity, merge, snapshot
from .pilot_candidates import _candidate_roles, _pdf_proof, _t8_candidates

PILOT_TICKERS = (
    "2360",
    "2404",
    "6139",
    "6223",
    "6515",
    "7769",
    "6488",
    "3532",
    "2383",
    "6213",
    "6274",
    "3037",
    "3189",
    "8046",
    "2303",
    "2330",
    "2449",
    "3711",
    "6239",
    "6770",
)


def _resolve_pdf(value, inputs_dir):
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    project_path = inputs_dir.parent / path
    return project_path if project_path.exists() else Path.cwd() / path


def _build_company(metadata, inputs_dir, out_dir, cache_dir):
    ar_path = _resolve_pdf(metadata.get("annual_report_path"), inputs_dir)
    if ar_path is None or not ar_path.is_file():
        raise FileNotFoundError("annual_report_path")
    ar = load_pdf(ar_path.resolve(), cache_dir=cache_dir, ocr=None)
    anchors = find_annual_report_sections(
        ar, required=set(), group=metadata.get("group")
    )
    fs_path = _resolve_pdf(metadata.get("consolidated_fs_path"), inputs_dir)
    fs = (
        load_pdf(fs_path.resolve(), cache_dir=cache_dir, ocr=None)
        if fs_path and fs_path.is_file()
        else None
    )
    fs_anchors = (
        find_heading_sections(fs, FS_HEADING_ANCHORS, required=set()) if fs else None
    )
    fiscal_year = metadata.get("fiscal_year")
    if type(fiscal_year) is not int:
        raise ValueError("fiscal_year")
    bundle = extract_tables(
        ar,
        anchors,
        fs,
        fs_anchors,
        None,
        None,
        roc_year=fiscal_year - 1911,
        group=metadata.get("group"),
    ).to_dict()
    digest = hashlib.sha256(ar_path.read_bytes()).hexdigest()
    documents = [{"document": str(ar.path), "document_hash": digest}]
    if fs:
        documents.append(
            {
                "document": str(fs.path),
                "document_hash": hashlib.sha256(fs_path.read_bytes()).hexdigest(),
            }
        )
    raw = dict(
        bundle=bundle,
        skill_results={},
        company_name=metadata.get("company_name"),
        ticker=metadata["ticker"],
        pilot_documents=documents,
    )
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    source_path = (
        out_dir
        / "sources"
        / f"{metadata['ticker']}_{hashlib.sha256(encoded.encode()).hexdigest()[:24]}_raw.json"
    )
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(encoded, encoding="utf-8")
    fragment = normalize(raw, metadata, source_path.resolve())
    source_hash = hashlib.sha256(encoded.encode()).hexdigest()
    for proof in fragment["evidence"]:
        proof["document_hash"] = source_hash
    if fs:
        fs_hash = documents[-1]["document_hash"]
        by_page = {page.number: page for page in fs.pages}
        by_evidence = {proof["id"]: proof for proof in fragment["evidence"]}
        for item in fragment["observations"]:
            proof = by_evidence[item["evidence_ids"][0]]
            page = by_page.get(proof["locator"].get("source_page"))
            if page is None:
                continue
            row_index = int(proof["locator"]["pointer"].split("/")[-2])
            label = bundle["statements"]["rows"][row_index]["label"]
            line = next(
                (
                    line
                    for line in page.text.splitlines()
                    if label.replace(" ", "") in line.replace(" ", "")
                ),
                None,
            )
            if line:
                pdf_proof = _pdf_proof(fs, page, line, item["period"], fs_hash)
                fragment["evidence"].append(pdf_proof)
                item["evidence_ids"].append(pdf_proof["id"])
    company_id = fragment["entities"][0]["id"]
    period = f"{fiscal_year}-01-01~{fiscal_year}-12-31"
    _candidate_roles(fragment, ar, anchors, company_id, period, digest)
    _t8_candidates(
        fragment,
        bundle,
        ar,
        anchors,
        company_id,
        source_path.resolve(),
        digest,
        source_hash,
    )
    for document in documents:
        fragment["coverage"][0]["sources"].append(document)
    fragment["coverage"][0]["missing"].extend(bundle.get("missing_tables") or [])
    if not fs:
        fragment["coverage"][0]["missing"].append("consolidated_fs_pdf")
    if not fragment["roles"]:
        fragment["coverage"][0]["missing"].append("business_evidence")
    if (
        ar.garbled_pages
        or ar.image_pages
        or not any(page.text.strip() for page in ar.pages)
    ):
        fragment["coverage"][0]["warnings"].append("pdf_needs_manual_review")
    excerpts = {str(ar.path): {page.number: page.text for page in ar.pages}}
    if fs:
        excerpts[str(fs.path)] = {page.number: page.text for page in fs.pages}
    return fragment, excerpts


def build_pilot(inputs_dir, tickers, out_dir, *, cache_dir=None):
    """build_pilot(inputs_dir, tickers, out_dir, *, cache_dir=None) -> snapshot.

    Read local ticker inputs and PDFs only; None selects the 20 Spec candidates.
    Relative PDF paths resolve against the input project's root, then cwd.
    Save versioned content-hash raw JSON for real financial pointers. Return
    pending candidates and per-company coverage; one failure does not stop others.
    OCR is disabled; None reuses load_pdf's existing cache. Tests can isolate it.
    The caller owns final snapshot/SQLite/report output.
    """
    inputs_dir, out_dir = Path(inputs_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fragments, sources = [], {}
    for ticker in PILOT_TICKERS if tickers is None else tickers:
        metadata = {"ticker": str(ticker)}
        try:
            metadata.update(
                json.loads((inputs_dir / f"{ticker}.json").read_text(encoding="utf-8"))
            )
            fragment, excerpts = _build_company(
                metadata, inputs_dir, out_dir, cache_dir
            )
            fragments.append(fragment)
            sources.update(excerpts)
        except Exception as error:
            company = entity(
                metadata.get("company_name") or str(ticker),
                market="TW",
                ticker=str(ticker),
            )
            fragments.append(
                snapshot(
                    entities=[company],
                    coverage=[
                        coverage(
                            company["id"],
                            sources=[dict(document=str(inputs_dir / f"{ticker}.json"))],
                            missing=["pilot_extraction"],
                            warnings=[
                                dict(
                                    reason="pilot_company_failed",
                                    error=type(error).__name__,
                                )
                            ],
                        )
                    ],
                )
            )
    return merge(fragments, sources=sources)
