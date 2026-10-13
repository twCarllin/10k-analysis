"""Local-only CLI assembly for the industry map."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import sys

from .adapters import normalize
from .inventory import inventory, write_inventory
from .model import merge
from .pilot import PILOT_TICKERS, build_pilot
from .render import render
from .store import load, save

LOGGER = logging.getLogger(__name__)
OUTPUTS = (
    "inventory.json",
    "inventory.md",
    "industry_map.sqlite",
    "snapshot.json",
    "graph.json",
    "index.html",
    "app.js",
    "style.css",
    "review_queue.json",
    "review_queue.md",
    "coverage.json",
)
MARKER = ".industry-map-ownership.json"


class DiagnosticFormatter(logging.Formatter):
    def __init__(self, style):
        super().__init__()
        self.style = style

    def format(self, record):
        fields = dict(
            timestamp=datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            level=record.levelname,
            logger=record.name,
            event=record.event,
            message=record.getMessage(),
        )
        if record.exc_info:
            fields["traceback"] = self.formatException(record.exc_info)
        if self.style == "json":
            return json.dumps(fields, ensure_ascii=False)
        return " ".join(f"{key}={value}" for key, value in fields.items())


def _json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def _prepare_output(out):
    owned = {}
    marker = out / MARKER
    if marker.exists():
        owned = json.loads(marker.read_text())
        if owned.get("application") != "industry_map" or not isinstance(
            owned.get("files"), dict
        ):
            raise ValueError("invalid ownership marker")
    for filename in OUTPUTS:
        path = out / filename
        if (
            filename == "industry_map.sqlite"
            and path.is_file()
            and not path.is_symlink()
            and filename in owned.get("files", {})
        ):
            # The public store API may record manual checks; validate DB ownership.
            load(path)
            continue
        if path.exists() and (
            path.is_symlink()
            or not path.is_file()
            or owned.get("files", {}).get(filename)
            != hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise ValueError(f"output is not owned or was modified: {filename}")
    if (out / "sources").is_symlink():
        raise ValueError("sources must not be a symlink")
    out.mkdir(parents=True, exist_ok=True)


def _version_source(source, out):
    encoded = source.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    destination = out / "sources" / f"{digest}.json"
    destination.parent.mkdir(exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or destination.read_bytes() != encoded:
            raise ValueError("versioned source collision")
    else:
        destination.write_bytes(encoded)
    return json.loads(encoded), str(destination.resolve())


def _confirmed_sources(fragments):
    """Reload evidence only for formal claims; never trust persisted status alone."""
    from runtime.tw_equity.pdf_doc import load_pdf

    sources = {}
    for fragment in fragments:
        identifiers = {
            identifier
            for name in ("roles", "relations")
            for item in fragment[name]
            if item["status"] in ("confirmed", "terminated")
            for identifier in item["evidence_ids"]
        }
        for proof in fragment["evidence"]:
            document = proof["document"]
            if proof["id"] not in identifiers or document in sources:
                continue
            path = Path(document)
            try:
                if (
                    proof.get("document_hash")
                    and hashlib.sha256(path.read_bytes()).hexdigest()
                    != proof["document_hash"]
                ):
                    continue
                if "page" in proof["locator"]:
                    doc = load_pdf(path, ocr=None)
                    sources[document] = {page.number: page.text for page in doc.pages}
                else:
                    sources[document] = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
    return sources


def _refresh_analysis_relations(previous, fragments):
    """Recompute pending relations for an imported immutable source version."""
    documents = {
        proof["document"] for fragment in fragments for proof in fragment["evidence"]
    }
    proofs = {proof["id"]: proof for proof in previous["evidence"]}

    def replaced(item):
        ids = item.get("evidence_ids") or []
        return (
            item.get("status") == "pending"
            and bool(ids)
            and all(
                identifier in proofs
                and proofs[identifier].get("source_type") == "analysis"
                and proofs[identifier]["document"] in documents
                and (
                    proofs[identifier].get("locator", {}).get("pointer") or ""
                ).startswith("/results/")
                for identifier in ids
            )
        )

    return {
        **previous,
        "relations": [item for item in previous["relations"] if not replaced(item)],
    }


def _build(args, discovered):
    fragments, xbrl = [], {}
    for record in discovered["records"]:
        if args.tickers and record["ticker"] not in args.tickers:
            continue
        if record["format"] == "jp_unsupported":
            continue
        source = Path(record["source"])
        raw, source_path = _version_source(source, args.out)
        metadata = {"ticker": record["ticker"]}
        input_path = args.inputs / f"{record['ticker']}.json"
        if record["market"] == "TW" and input_path.exists():
            metadata.update(json.loads(input_path.read_text()))
        if record["market"] == "US" and args.xbrl_dir:
            ticker = record["ticker"]
            facts_path = args.xbrl_dir / f"xbrl_{ticker}.json"
            if facts_path.exists():
                if ticker not in xbrl:
                    xbrl[ticker] = _version_source(facts_path, args.out)
                metadata["xbrl_facts"], metadata["xbrl_source_path"] = xbrl[ticker]
        fragments.append(normalize(raw, metadata, source_path))
    if args.pilot:
        candidates = args.tickers or PILOT_TICKERS
        tw = [
            ticker
            for ticker in candidates
            if ticker.isdigit() or (args.inputs / f"{ticker}.json").exists()
        ]
        fragments.append(build_pilot(args.inputs, tw, args.out))
    database = args.out / "industry_map.sqlite"
    if database.exists():
        fragments.append(_refresh_analysis_relations(load(database), fragments))
    combined = merge(fragments, sources=_confirmed_sources(fragments))
    save(combined, database)
    combined = load(database)
    _json(args.out / "snapshot.json", combined)
    render(combined, args.out)
    queue = {
        name: [item for item in combined[name] if item["status"] == "pending"]
        for name in ("roles", "relations")
    }
    _json(args.out / "review_queue.json", queue)
    _json(args.out / "coverage.json", combined["coverage"])
    (args.out / "review_queue.md").write_text(
        "# 待查核清單\n\n"
        + "\n".join(
            f"- {name}: {item['id']}" for name, items in queue.items() for item in items
        )
        + "\n",
        encoding="utf-8",
    )
    return dict(
        database=str(database), companies=len(combined["coverage"]), out=str(args.out)
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "build"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=Path("tw_equity_inputs"))
    parser.add_argument("--tickers")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--xbrl-dir", type=Path)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
    )
    parser.add_argument("--log-format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(DiagnosticFormatter(args.log_format))
    LOGGER.handlers = [handler]
    LOGGER.propagate = False
    LOGGER.setLevel(args.log_level)
    try:
        if not args.root.is_dir():
            raise ValueError(f"root directory does not exist: {args.root}")
        args.tickers = (
            tuple(filter(None, (item.strip() for item in args.tickers.split(","))))
            if args.tickers
            else None
        )
        _prepare_output(args.out)
        discovered = inventory(args.root, inputs=args.inputs, exclude=(args.out,))
        result = _build(args, discovered) if args.command == "build" else discovered
        write_inventory(discovered, args.out)
        files = {
            name: hashlib.sha256((args.out / name).read_bytes()).hexdigest()
            for name in OUTPUTS
            if (args.out / name).is_file()
        }
        _json(args.out / MARKER, dict(application="industry_map", files=files))
        LOGGER.info("local output complete", extra={"event": "industry_map.completed"})
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        LOGGER.error(str(error), extra={"event": "industry_map.input_failed"})
        return 1
    except Exception:
        LOGGER.exception("build failed", extra={"event": "industry_map.failed"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
