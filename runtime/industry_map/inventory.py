"""Inventory known local producer files without ranking by file timestamps."""

import json
from pathlib import Path

from .adapters import classify, describe, normalize
from .model import coverage, entity, merge, snapshot


def inventory(root, *, inputs="tw_equity_inputs", exclude=()):
    """inventory(root: path, *, inputs: path, exclude: paths) -> dict.

    Return records, merged company coverage, and isolated file warnings. Unknown
    JSON is ignored; JP is reported as unsupported. Generated inventory files
    are always skipped. exclude can omit an output directory beneath root.
    """
    root = Path(root)
    excluded_paths = [Path(path).resolve() for path in exclude]
    records, fragments, warnings = [], [], []
    for source in sorted(root.rglob("*.json")):
        if source.name in {"config.json", "inventory.json", "manifest.json"}:
            continue
        if any(source.resolve().is_relative_to(path) for path in excluded_paths):
            continue
        try:
            record = json.loads(source.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            warnings.append(
                dict(
                    source=str(source),
                    reason="invalid_json",
                    error=type(error).__name__,
                )
            )
            continue
        kind = classify(record)
        if kind is None:
            continue
        ticker = record.get("ticker") or source.name.split("_")[0].split(".")[0]
        metadata = {"ticker": ticker}
        if kind == "tw_raw" and inputs is not None:
            metadata_path = Path(inputs) / f"{ticker}.json"
            if metadata_path.exists():
                try:
                    metadata.update(
                        json.loads(metadata_path.read_text(encoding="utf-8"))
                    )
                except (ValueError, OSError) as error:
                    warnings.append(
                        dict(
                            source=str(metadata_path),
                            reason="invalid_metadata",
                            error=type(error).__name__,
                        )
                    )
        details = describe(record, metadata, source)
        records.append(details)
        if kind == "jp_unsupported":
            company = entity(details["company"], market="JP", ticker=details["ticker"])
            fragments.append(
                snapshot(
                    coverage=[
                        coverage(
                            company["id"],
                            sources=[details],
                            warnings=["unsupported_format"],
                            excluded=[
                                dict(source=str(source), reason="unsupported_format")
                            ],
                        )
                    ]
                )
            )
            warnings.append(dict(source=str(source), reason="unsupported_format"))
            continue
        fragment = normalize(record, metadata, source)
        fragments.append(fragment)
        for item in fragment["coverage"]:
            warnings.extend(
                dict(source=str(source), reason=reason) for reason in item["warnings"]
            )
            warnings.extend(
                dict(source=str(source), **excluded) for excluded in item["excluded"]
            )
    return dict(
        records=records, coverage=merge(fragments)["coverage"], warnings=warnings
    )


def write_inventory(result, out):
    """write_inventory(result: dict, out: path) -> None; write inventory.json/md."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 資料盤點",
        "",
        "| 公司 | 格式 | 期間 | 來源 |",
        "| --- | --- | --- | --- |",
    ]
    for record in result["records"]:
        cells = [
            record["company"],
            record["format"],
            record["period"] or "unknown",
            record["source"],
        ]
        lines.append(
            "| "
            + " | ".join(
                str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells
            )
            + " |"
        )
    lines.extend(["", "## 警告與排除", ""])
    lines.extend(f"- {item['source']}: {item['reason']}" for item in result["warnings"])
    (out / "inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
