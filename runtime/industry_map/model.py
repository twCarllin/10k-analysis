"""Dictionary snapshot v1 factories, source validation and historical merge.

Sources passed to validate_snapshot map document names to PDF page dictionaries
({1: page_text}) or decoded JSON documents. No source is fetched by this module.
"""

from copy import deepcopy
import hashlib
import json
import re
from uuid import uuid4

COLLECTIONS = (
    "entities",
    "roles",
    "relations",
    "observations",
    "evidence",
    "coverage",
    "changes",
)


def stable_id(kind, *parts):
    """Hash typed, ordered identity components without delimiter ambiguity."""
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()
    return f"{kind}:{hashlib.sha256(encoded).hexdigest()[:24]}"


def snapshot(**collections):
    """Return an independent JSON-serializable v1 snapshot."""
    result = {"schema_version": 1}
    for name in COLLECTIONS:
        result[name] = deepcopy(collections.get(name, []))
    json.dumps(result, allow_nan=False)
    return result


def entity(
    name,
    *,
    kind="company",
    market=None,
    ticker=None,
    owner_id=None,
    period=None,
    aliases=(),
    anonymous=False,
    scope_id=None,
):
    """Anonymous unknown periods require an explicit fragment scope to deduplicate."""
    if kind == "company" and ticker and market and not anonymous:
        identifier = f"company:{market}:{ticker}"
    elif kind != "company" and not anonymous:
        identifier = stable_id(kind, name, owner_id)
    elif not anonymous:
        identifier = stable_id(kind, name, market, ticker, owner_id)
    else:
        scope = period if period is not None else (scope_id or str(uuid4()))
        identifier = (
            stable_id(kind, name, owner_id, scope)
            if anonymous or not ticker
            else stable_id(kind, market, ticker)
        )
    return dict(
        id=identifier,
        kind=kind,
        name=name,
        aliases=sorted(set(aliases) | {name}),
        market=market,
        ticker=ticker,
        owner_id=owner_id,
    )


def evidence(
    document,
    *,
    document_hash=None,
    locator=None,
    quote=None,
    period=None,
    source_type="analysis",
    checked_at=None,
):
    return dict(
        id=stable_id("evidence", document, document_hash, locator, quote, period),
        document=document,
        document_hash=document_hash,
        locator=locator,
        quote=quote,
        period=period,
        source_type=source_type,
        checked_at=checked_at,
    )


def role(company_id, theme, stage, *, product=None, evidence_ids=(), status="pending"):
    return dict(
        id=stable_id("role", company_id, theme, stage, product),
        company_id=company_id,
        theme=theme,
        stage=stage,
        product=product,
        evidence_ids=sorted(set(evidence_ids)),
        status=status,
    )


def relation(
    source_id,
    predicate,
    target_id,
    *,
    product=None,
    period=None,
    status="pending",
    evidence_ids=(),
    disclosures=(),
):
    result = dict(
        id=stable_id("relation", source_id, predicate, target_id, product, period),
        source_id=source_id,
        predicate=predicate,
        target_id=target_id,
        product=product,
        period=period,
        status=status,
        evidence_ids=sorted(set(evidence_ids)),
    )
    if disclosures:
        result["disclosures"] = deepcopy(list(disclosures))
    return result


def observation(
    company_id,
    metric,
    value=None,
    *,
    currency=None,
    unit="unknown",
    period=None,
    basis=None,
    scope="unknown",
    formula=None,
    inputs=None,
    evidence_ids=(),
    quality=None,
):
    return dict(
        id=stable_id(
            "observation", company_id, metric, period, basis, scope, currency, unit
        ),
        company_id=company_id,
        metric=metric,
        value=value,
        currency=currency,
        unit=unit,
        period=period,
        basis=basis,
        scope=scope,
        formula=formula,
        inputs=deepcopy(inputs),
        evidence_ids=sorted(set(evidence_ids)),
        quality=quality,
    )


def coverage(
    company_id, *, sources=(), available=(), missing=(), warnings=(), excluded=()
):
    return dict(
        id=stable_id("coverage", company_id),
        company_id=company_id,
        sources=list(sources),
        available=list(available),
        missing=list(missing),
        warnings=list(warnings),
        excluded=list(excluded),
    )


def _source_excerpt(item, sources):
    locator = item.get("locator") or {}
    source = sources.get(item.get("document"))
    try:
        if "page" in locator:
            page = locator["page"]
            if type(page) is not int or page < 1:
                return None
            return source[page]
        pointer = locator["pointer"]
        if pointer == "":
            return source
        if not pointer.startswith("/"):
            return None
        for token in pointer[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(source, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", token):
                    return None
                source = source[int(token)]
            else:
                source = source[token]
        return source
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def validate_snapshot(fragment, sources=None):
    """Downgrade unsupported formal claims to pending, preserving their evidence.

    A checked primary excerpt is necessary for confirmation; the caller remains
    responsible for checking that its meaning supports the role or relationship.
    """
    if fragment.get("schema_version") != 1:
        raise ValueError("unsupported snapshot schema_version")
    result = snapshot(**fragment)
    sources = sources or {}
    supported = set()
    for item in result["evidence"]:
        excerpt = _source_excerpt(item, sources)
        quote = item.get("quote")
        if (
            item.get("source_type") == "primary"
            and isinstance(quote, str)
            and quote.strip()
            and isinstance(excerpt, str)
            and quote in excerpt
        ):
            supported.add(item["id"])
    for collection in ("roles", "relations"):
        for item in result[collection]:
            if item.get("status") in ("confirmed", "terminated"):
                if not supported.intersection(item.get("evidence_ids", [])):
                    item["status"] = "pending"
    return result


def disclosure_changes(fragment, previous_period, current_period):
    """Compare explicit comparable periods; absence never implies termination."""
    if (
        previous_period is None
        or current_period is None
        or previous_period == current_period
    ):
        return []
    by_period = {previous_period: {}, current_period: {}}
    anonymous = {item["id"] for item in fragment["entities"] if item.get("owner_id")}
    for item in fragment["relations"]:
        period = item.get("period")
        if (
            period not in by_period
            or {item["source_id"], item["target_id"]} & anonymous
        ):
            continue
        key = (
            item["source_id"],
            item["predicate"],
            item["target_id"],
            item.get("product"),
        )
        by_period[period][key] = item
    previous, current = by_period[previous_period], by_period[current_period]
    changes = []
    for key in sorted(previous.keys() | current.keys(), key=repr):
        status = (
            "unchanged"
            if key in previous and key in current
            else ("newly_disclosed" if key in current else "not_disclosed_this_period")
        )
        item = current.get(key) or previous[key]
        changes.append(
            dict(
                id=stable_id("change", key, previous_period, current_period),
                relation_id=item["id"],
                previous_period=previous_period,
                current_period=current_period,
                status=status,
            )
        )
    return changes


def merge(fragments, *, sources=None, previous_period=None, current_period=None):
    """Union fixed IDs, preserving periods; validate claims against local sources."""
    indexed = {name: {} for name in COLLECTIONS}
    for fragment in fragments:
        checked = validate_snapshot(fragment, sources)
        for name in COLLECTIONS:
            for item in checked[name]:
                existing = indexed[name].get(item["id"])
                if existing is None:
                    indexed[name][item["id"]] = deepcopy(item)
                    continue
                for field in (
                    "aliases",
                    "evidence_ids",
                    "sources",
                    "available",
                    "missing",
                    "warnings",
                    "excluded",
                    "disclosures",
                ):
                    if field in item:
                        values = existing.get(field, []) + item[field]
                        existing[field] = list(
                            {
                                json.dumps(value, sort_keys=True): value
                                for value in values
                            }.values()
                        )
                if name == "entities":
                    existing["aliases"] = sorted(
                        set(existing["aliases"]) | {item["name"]}
                    )
                if (
                    item.get("status") == "confirmed"
                    and existing.get("status") == "pending"
                ):
                    existing["status"] = "confirmed"
    result = snapshot(**{name: list(items.values()) for name, items in indexed.items()})
    if previous_period is not None and current_period is not None:
        result["changes"] = disclosure_changes(result, previous_period, current_period)
    return result
