"""Validate and preserve content-addressed versions with failure isolation."""

import json
import logging
from pathlib import Path
from .model import digest, utc_now
from .sources import resolve_download
from .transport import Transport

logger = logging.getLogger(__name__)


def validate_bytes(data, format):
    if format == "pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("PDF magic missing; possible HTTP 200 error HTML")
        import fitz

        with fitz.open(stream=data, filetype="pdf") as pdf:
            if not len(pdf):
                raise ValueError("PDF has no readable pages")
            pdf[0].get_text()
    elif format == "json":
        value = json.loads(data)
        if not isinstance(value, (list, dict)):
            raise ValueError("JSON must contain an object or list")
    elif format == "html":
        from bs4 import BeautifulSoup

        page = BeautifulSoup(data, "html.parser")
        title = page.title.get_text(" ", strip=True).lower() if page.title else ""
        for element in page(["script", "style"]):
            element.decompose()
        visible = page.get_text(" ", strip=True).lower()
        challenge_title = any(
            term in title
            for term in (
                "captcha",
                "just a moment",
                "security check",
                "attention required",
                "robot check",
            )
        )
        blocked = any(
            term in visible
            for term in (
                "access denied",
                "request rejected",
                "查詢過於頻繁",
                "verify you are human",
                "verify that you are human",
                "complete the security check",
                "please solve the captcha",
                "請完成驗證",
                "請驗證您不是機器人",
            )
        )
        if len(data) < 1000 or challenge_title or blocked:
            raise ValueError("Blocked or empty HTML response")
    else:
        raise ValueError("Unsupported document format")


def collect(manifest, root="data/industry_collection", transport=None, refresh=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    index = root / "index.json"
    previous = json.loads(index.read_text()) if index.exists() else []
    transport = transport or Transport()
    records = list(previous)
    current_path = root / "current.json"
    current = (
        json.loads(current_path.read_text())
        if current_path.exists()
        else [item for item in previous if item.get("status") == "downloaded"]
    )
    outcomes = []
    payloads = {}
    for source in manifest:
        row = dict(source)
        if not row.get("url") or row.get("status") == "missing":
            row.setdefault("reason", "No official URL supplied")
            row["status"] = "missing"
            outcomes.append(row)
            continue
        versions = [
            item
            for item in current
            if all(
                item.get(key) == row.get(key)
                for key in ("ticker", "doc_type", "period")
            )
            and item.get("status") == "downloaded"
        ]
        prior = [
            item
            for item in current
            if all(
                item.get(key) == row.get(key)
                for key in ("ticker", "doc_type", "period", "url", "source_filename")
            )
            and item.get("status") == "downloaded"
        ]
        try:
            if prior and not refresh:
                cached = prior[-1]
                data = Path(cached["local_path"]).read_bytes()
                validate_bytes(data, row.get("format", "pdf"))
                if digest(data) != cached["sha256"]:
                    raise ValueError("Cached file hash mismatch")
                row.update(cached, status="cached")
            else:
                url = resolve_download(row, transport)
                if row.get("directory_path") and row.get("directory_sha256"):
                    data = Path(row["directory_path"]).read_bytes()
                    if digest(data) != row["directory_sha256"]:
                        raise ValueError("Discovered directory file hash mismatch")
                elif url in payloads:
                    data = payloads[url]
                else:
                    response = transport.get(url)
                    data = response.content
                validate_bytes(data, row.get("format", "pdf"))
                payloads[url] = data
                if row.get("selector"):
                    selected = [
                        value
                        for value in json.loads(data)
                        if all(
                            str(value.get(key)) == str(expected)
                            for key, expected in row["selector"].items()
                        )
                    ]
                    if not selected:
                        raise ValueError("Requested company/period missing from JSON")
                sha = digest(data)
                suffix = row.get("format", "pdf")
                path = root / "raw" / f"{sha}.{suffix}"
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and digest(path.read_bytes()) != sha:
                    quarantine = (
                        root
                        / "quarantine"
                        / f"{sha}-{digest(path.read_bytes())}.{suffix}"
                    )
                    quarantine.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(quarantine)
                    row["restored_from_quarantine"] = str(quarantine.resolve())
                if not path.exists():
                    path.write_bytes(data)
                row.update(
                    status="downloaded",
                    fetched_at=utc_now(),
                    download_url=url,
                    sha256=sha,
                    local_path=str(path.resolve()),
                    revision_of=(
                        versions[-1]["sha256"]
                        if versions and versions[-1]["sha256"] != sha
                        else None
                    ),
                )
                if not any(
                    all(
                        item.get(key) == row.get(key)
                        for key in (
                            "ticker",
                            "doc_type",
                            "period",
                            "url",
                            "source_filename",
                            "sha256",
                        )
                    )
                    and item.get("status") == "downloaded"
                    for item in records
                ):
                    records.append(row)
                with (root / "downloads.jsonl").open("a") as events:
                    events.write(json.dumps(row, ensure_ascii=False) + "\n")
            pointer = dict(row, status="downloaded")
            current = [
                item
                for item in current
                if not all(
                    item.get(key) == row.get(key)
                    for key in (
                        "ticker",
                        "doc_type",
                        "period",
                        "url",
                        "source_filename",
                    )
                )
            ]
            current.append(pointer)
            pointer_temp = current_path.with_suffix(".tmp")
            pointer_temp.write_text(json.dumps(current, ensure_ascii=False, indent=2))
            pointer_temp.replace(current_path)
            logger.info(
                "Document available",
                extra={
                    "event": "document_available",
                    "ticker": row["ticker"],
                    "period": row["period"],
                    "url": row["url"],
                },
            )
        except Exception as error:
            row.update(status="failed", reason=str(error), fetched_at=utc_now())
            records.append(row)
            logger.error(
                "Document failed: %s",
                error,
                extra={
                    "event": "document_failed",
                    "attempt": getattr(error, "request_attempt", None),
                    "ticker": row["ticker"],
                    "period": row["period"],
                    "url": row["url"],
                },
            )
        outcomes.append(row)
        temporary = index.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        temporary.replace(index)
    (root / "coverage.json").write_text(
        json.dumps(outcomes, ensure_ascii=False, indent=2)
    )
    return outcomes
