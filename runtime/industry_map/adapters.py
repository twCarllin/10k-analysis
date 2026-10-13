"""Local producer adapters. Analysis JSON never confirms a relationship."""

import json
from datetime import date
from pathlib import Path
import re

from .model import coverage, entity, evidence, observation, relation, snapshot


def classify(record):
    """classify(record: dict) -> str | None; recognize only known producers."""
    if not isinstance(record, dict):
        return None
    if isinstance(record.get("five_year"), dict) and "skill_results" in record:
        return "jp_unsupported"
    if isinstance(record.get("bundle"), dict) and "skill_results" in record:
        return "tw_raw"
    if (
        isinstance(record.get("results"), dict)
        and {"eval", "synthesis"} <= record.keys()
    ):
        return "us_raw"
    if (
        record.get("schema_version") == 2
        and {"ticker", "status", "values"} <= record.keys()
    ):
        return "tw_batch"
    return None


def is_placeholder(name):
    """Exclude explicit mock tokens, without matching names such as Mockingbird."""
    return bool(re.search(r"\b(?:mock|placeholder)\b|\$XX\b", str(name), re.I))


def describe(record, metadata=None, source_path=""):
    """describe(record, metadata=None, source_path='') -> identity/format metadata."""
    metadata = metadata or {}
    kind = classify(record)
    ticker = record.get("ticker") or metadata.get("ticker")
    if ticker is None and source_path:
        ticker = Path(source_path).name.split("_")[0]
    name = (
        record.get("company_name")
        or metadata.get("company_name")
        or ticker
        or "unknown"
    )
    ledger = (record.get("bundle") or {}).get("statements") or {}
    period = (
        record.get("fs_period")
        or (ledger.get("periods") or {}).get("flow_current")
        or ledger.get("period_current")
        or metadata.get("fs_period")
    )
    return dict(
        source=str(source_path),
        format=kind,
        company=name,
        ticker=ticker,
        period=period,
        market=(
            "TW"
            if kind in ("tw_raw", "tw_batch")
            else ("JP" if kind == "jp_unsupported" else "US")
        ),
    )


def _pointer(*tokens):
    return "/" + "/".join(
        str(token).replace("~", "~0").replace("/", "~1") for token in tokens
    )


def _proof(result, source_path, tokens, value, period=None, page=None):
    locator = {"pointer": _pointer(*tokens)}
    if page is not None:
        locator["source_page"] = page  # Producer provenance, not a PDF locator.
    item = evidence(
        str(source_path),
        locator=locator,
        quote=(
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        ),
        period=period,
        source_type="analysis",
    )
    result["evidence"].append(item)
    return [item["id"]]


def _period(fields, period, statement="is"):
    tag = ("bs_" if statement == "bs" else "flow_") + (
        "current" if period == "current" else "prior"
    )
    if statement == "bs" and period == "prior":
        tag = "bs_prior_same"
    return (fields.get("periods") or {}).get(tag) or fields.get("period_" + period)


def _currency(unit):
    return "TWD" if "新台幣" in str(unit) else None


def _row_period(ledger, row, period):
    statement = row.get("statement")
    columns = (ledger.get("column_periods") or {}).get(statement) or []
    selected = (ledger.get(period + "_col") or {}).get(statement)
    if type(selected) is int and 0 <= selected < len(columns) and columns[selected]:
        return columns[selected]
    return _period(ledger, period, statement)


def _quality(checks):
    if isinstance(checks, dict):
        return dict(checks)
    return {"checks": checks or []}


def _tw_raw(record, result, company_id, source_path):
    bundle = record["bundle"]
    ledger = bundle.get("statements") or {}
    unit = ledger.get("unit") or "unknown"
    for index, row in enumerate(ledger.get("rows") or []):
        if not row.get("key"):
            continue
        for period in ("current", "prior"):
            label = _row_period(ledger, row, period)
            ids = _proof(
                result,
                source_path,
                ("bundle", "statements", "rows", index, period),
                row.get(period),
                label,
                row.get("page"),
            )
            result["observations"].append(
                observation(
                    company_id,
                    row["key"],
                    row.get(period),
                    currency=_currency(unit),
                    unit=unit,
                    period=label,
                    basis=ledger.get("basis"),
                    scope="company",
                    evidence_ids=ids,
                    quality=_quality(ledger.get("checks")),
                )
            )
    pack = bundle.get("metrics") or {}
    for index, metric in enumerate(pack.get("metrics") or []):
        period_tag = "flow_" + metric.get("period", "current")
        full_period = (ledger.get("periods") or {}).get(period_tag) or (
            pack.get("periods") or {}
        ).get(period_tag)
        label = full_period or _period(pack, metric.get("period"))
        quality = _quality(ledger.get("checks"))
        if not full_period:
            quality["incomplete_period"] = True
        ids = _proof(
            result,
            source_path,
            ("bundle", "metrics", "metrics", index, "value"),
            metric.get("value"),
            label,
        )
        result["observations"].append(
            observation(
                company_id,
                metric["key"],
                metric.get("value"),
                currency=_currency(unit),
                unit=metric.get("unit") or "unknown",
                period=label,
                basis=pack.get("basis") or ledger.get("basis"),
                scope="company",
                formula=metric.get("formula"),
                inputs=metric.get("inputs"),
                evidence_ids=ids,
                quality=quality,
            )
        )


def _tw_batch(record, result, company_id, source_path):
    for collection in ("values", "metrics"):
        for metric, values in (record.get(collection) or {}).items():
            for period in ("current", "prior"):
                if period not in values:
                    continue
                label = _period(
                    record,
                    period,
                    (
                        "bs"
                        if collection == "values"
                        and metric
                        in {"total_assets", "total_equity", "loans_net", "deposits"}
                        else "is"
                    ),
                )
                if period == "current" and label is None:
                    label = record.get("fs_period")
                ids = _proof(
                    result,
                    source_path,
                    (collection, metric, period),
                    values.get(period),
                    label,
                )
                result["observations"].append(
                    observation(
                        company_id,
                        metric,
                        values.get(period),
                        period=label,
                        basis=record.get("basis"),
                        unit="unknown",
                        scope="company",
                        evidence_ids=ids,
                        quality=_quality(record.get("checks")),
                    )
                )


def _us_relations(record, result, company_id, source_path, period, excluded):
    for section, key, predicate in (
        ("supply_chain", "named_suppliers", "supplies_to"),
        ("competitor_mapping", "named_competitors", "competes_with"),
        ("footnotes_segment", "major_customers", "supplies_to"),
    ):
        analysis = record["results"].get(section) or {}
        if not analysis and section != "footnotes_segment":
            excluded.append(
                dict(pointer=_pointer("results", section), reason="empty_analysis")
            )
        for index, candidate in enumerate(analysis.get(key) or []):
            is_name = isinstance(candidate, str)
            candidate = {"name": candidate} if is_name else candidate
            if not isinstance(candidate, dict):
                continue
            name = candidate.get("name")
            tokens = ("results", section, key, index) + (() if is_name else ("name",))
            if section == "footnotes_segment" and re.fullmatch(
                r"customer\s+[A-Z0-9]|unknown|not disclosed|未揭露", str(name), re.I
            ):
                excluded.append(
                    dict(
                        pointer=_pointer(*tokens),
                        name=name,
                        reason="anonymous_customer",
                    )
                )
                continue
            if not name or is_placeholder(name):
                excluded.append(
                    dict(
                        pointer=_pointer(*tokens),
                        name=name,
                        reason="placeholder" if name else "empty_name",
                    )
                )
                continue
            target = entity(name, market="US", ticker=candidate.get("ticker") or None)
            result["entities"].append(target)
            relationship_period = candidate.get("period") or period
            ids = _proof(result, source_path, tokens, name, relationship_period)
            for field in ("note", "markets", "material_or_service", "period"):
                if candidate.get(field):
                    ids.extend(
                        _proof(
                            result,
                            source_path,
                            ("results", section, key, index, field),
                            candidate[field],
                            relationship_period,
                        )
                    )
            markets = candidate.get("markets") or []
            product = candidate.get("material_or_service")
            if predicate == "competes_with" and isinstance(markets, list):
                product = (
                    "; ".join(
                        market
                        for market in markets
                        if isinstance(market, str) and market.strip()
                    )
                    or product
                )
            source, destination = (
                (target["id"], company_id)
                if section == "supply_chain"
                else (company_id, target["id"])
            )
            result["relations"].append(
                relation(
                    source,
                    predicate,
                    destination,
                    product=product,
                    period=relationship_period,
                    evidence_ids=ids,
                )
            )


def _filed_date(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
    ):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _resolve_xbrl_fact(candidates, proofs):
    first = candidates[0]
    if all(item["value"] == first["value"] for item in candidates):
        return first
    dates = [_filed_date(item["quality"]["filed"]) for item in candidates]
    if all(value is not None for value in dates):
        latest_date = max(dates)
        latest = [
            item for item, filed in zip(candidates, dates) if filed == latest_date
        ]
        if all(item["value"] == latest[0]["value"] for item in latest):
            return latest[0]
    unresolved = dict(
        first,
        value=None,
        quality=dict(first["quality"], filed=None, conflict="unresolved"),
    )
    unresolved["quality"]["candidates"] = [
        dict(
            value=item["value"],
            filed=item["quality"]["filed"],
            evidence_id=item["evidence_ids"][0],
            source={
                key: proofs[item["evidence_ids"][0]][key]
                for key in ("document", "locator")
            },
        )
        for item in candidates
    ]
    unresolved["evidence_ids"] = [item["evidence_ids"][0] for item in candidates]
    return unresolved


def _xbrl_observations(metadata, result, company_id):
    facts, source_path = metadata.get("xbrl_facts"), metadata.get("xbrl_source_path")
    if not facts or not source_path:
        return
    tags = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
        "Revenues": "revenue",
        "NetIncomeLoss": "net_income",
        "GrossProfit": "gross_profit",
        "OperatingIncomeLoss": "operating_income",
        "NetCashProvidedByUsedInOperatingActivities": "cfo",
        "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    }
    groups = {}
    for tag, concept in (facts.get("facts") or {}).get("us-gaap", {}).items():
        if tag not in tags:
            continue
        for unit, entries in (concept.get("units") or {}).items():
            for index, entry in enumerate(entries):
                start, end, fp, form = (
                    entry.get(key) for key in ("start", "end", "fp", "form")
                )
                complete = bool(
                    start and end and fp in {"FY", "Q1", "Q2", "Q3", "Q4"} and form
                )
                period = f"{start}~{end}" if complete else None
                basis = f"{form}:{fp}" if complete else None
                ids = _proof(
                    result,
                    source_path,
                    ("facts", "us-gaap", tag, "units", unit, index, "val"),
                    entry.get("val"),
                    period,
                )
                result["evidence"][-1]["source_type"] = "primary"
                item = observation(
                    company_id,
                    tags[tag],
                    entry.get("val"),
                    currency=unit if unit in {"USD", "TWD", "JPY", "EUR"} else None,
                    unit=unit,
                    period=period,
                    basis=basis,
                    scope="company",
                    evidence_ids=ids,
                    inputs={
                        key: entry.get(key) for key in ("start", "end", "fp", "form")
                    },
                    quality={
                        "source": "xbrl",
                        "concept": tag,
                        "filed": entry.get("filed"),
                    },
                )
                groups.setdefault(item["id"], []).append(item)
    proofs = {item["id"]: item for item in result["evidence"]}
    result["observations"].extend(
        _resolve_xbrl_fact(candidates, proofs) for candidates in groups.values()
    )


def normalize(record, metadata=None, source_path=""):
    """normalize(record: dict, metadata: dict | None, source_path: path) -> snapshot.

    TW raw identity uses explicit metadata from tw_equity_inputs. Optional US
    metadata xbrl_facts must contain original SEC companyfacts and be accompanied
    by xbrl_source_path. Only selected original US-GAAP values are retained;
    period=start~end and basis=form:fp preserve YTD without claiming a quarter.
    Missing start/end/fp leave period/basis null. No LLM financial values are used.
    Missing values and units stay null/unknown. JSON evidence preserves a pointer; source_page
    is an attributed ledger page, never a checked PDF citation.
    """
    details = describe(record, metadata, source_path)
    kind = details["format"]
    if kind is None or kind == "jp_unsupported":
        raise ValueError("unsupported industry-map source format")
    company = entity(
        details["company"], market=details["market"], ticker=details["ticker"]
    )
    result = snapshot(entities=[company])
    warnings, missing, excluded = [], [], []
    if is_placeholder(details["company"]):
        result["entities"] = []
        excluded.append(dict(name=details["company"], reason="placeholder"))
    elif kind == "tw_raw":
        _tw_raw(record, result, company["id"], source_path)
    elif kind == "tw_batch":
        _tw_batch(record, result, company["id"], source_path)
        if record.get("status") == "error":
            warnings.append("batch_error")
    else:
        _us_relations(
            record, result, company["id"], source_path, details["period"], excluded
        )
        _xbrl_observations(metadata or {}, result, company["id"])
        if not result["observations"]:
            missing.append("financial_raw")
    if details["period"] is None:
        missing.append("period")
    if not result["observations"] and kind != "us_raw":
        missing.append("financial_raw")
    if any(item["value"] is None for item in result["observations"]):
        warnings.append("missing_values")
    if any(
        (item.get("quality") or {}).get("incomplete_period")
        for item in result["observations"]
    ):
        missing.append("complete_period")
    result["coverage"] = [
        coverage(
            company["id"],
            sources=[details],
            available=[name for name in ("observations", "relations") if result[name]],
            missing=missing,
            warnings=warnings,
            excluded=excluded,
        )
    ]
    return result
