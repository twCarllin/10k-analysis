"""JSON results on stdout, UTC structured diagnostics on stderr."""

import argparse
import json
import logging
import sys
from pathlib import Path
from .model import utc_now
from .inventory import inventory, plan
from .sources import discover, discover_monthly
from .collect import collect
from .transport import Transport


class DiagnosticFormatter(logging.Formatter):
    def __init__(self, format):
        super().__init__()
        self.format_name = format

    def format(self, record):
        fields = dict(
            timestamp=utc_now(),
            level=record.levelname,
            logger=record.name,
            event=getattr(record, "event", "diagnostic"),
            message=record.getMessage(),
        )
        for key in ("ticker", "period", "url", "attempt"):
            if hasattr(record, key):
                fields[key] = getattr(record, key)
        if self.format_name == "json":
            return json.dumps(fields, ensure_ascii=False)
        return " ".join(f"{key}={value}" for key, value in fields.items())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "inventory",
            "plan",
            "discover",
            "discover-monthly",
            "collect",
            "validate",
        ],
    )
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--root", default="data/industry_collection")
    parser.add_argument("--local-root", default="tw_report")
    parser.add_argument("--manifest")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    parser.add_argument("--log-format", default="json", choices=["text", "json"])
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--max-downloads", type=int, default=300)
    args = parser.parse_args(argv)
    if (
        args.timeout <= 0
        or not 1 <= args.attempts <= 5
        or args.interval < 0.5
        or args.max_downloads < 1
    ):
        parser.error(
            "timeout must be positive; attempts 1-5; interval >=0.5; max-downloads >=1"
        )
    transport = Transport(args.timeout, args.attempts, args.interval)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(DiagnosticFormatter(args.log_format))
    logger = logging.getLogger("runtime.industry_collection")
    logger.handlers = [handler]
    logger.setLevel(args.log_level)
    logger.propagate = False
    if args.tickers:
        tickers = args.tickers
    else:
        from runtime.industry_map.pilot import PILOT_TICKERS

        tickers = PILOT_TICKERS
    root = Path(args.root)
    if args.command == "inventory":
        result = inventory(args.local_root, tickers)
    elif args.command == "plan":
        result = plan(tickers, inventory(args.local_root, tickers))
    elif args.command == "discover":
        result = discover(tickers, root, transport)
        root.mkdir(parents=True, exist_ok=True)
        (root / "source-manifest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    elif args.command == "discover-monthly":
        result = discover_monthly(tickers, root, transport)
        root.mkdir(parents=True, exist_ok=True)
        (root / "monthly-source-manifest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    elif args.command == "collect":
        manifest = (
            Path(args.manifest) if args.manifest else root / "source-manifest.json"
        )
        rows = json.loads(manifest.read_text())
        eligible = sum(
            bool(row.get("url")) and row.get("status") != "missing" for row in rows
        )
        if eligible > args.max_downloads:
            parser.error(
                f"{eligible} downloads exceed --max-downloads {args.max_downloads}"
            )
        result = collect(rows, root, transport, refresh=args.refresh)
    else:
        from .validate import validate

        result = validate(root, tickers=tickers)
    failed = (
        sum(row.get("status") == "failed" for row in result)
        if isinstance(result, list)
        else 0
    )
    logger.info(
        "Command complete; failed=%s",
        failed,
        extra={"event": "command_partial" if failed else "command_complete"},
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
