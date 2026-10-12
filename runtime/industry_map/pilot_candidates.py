"""Pure PDF evidence, role and T8 candidates used by the local pilot."""

import re
import unicodedata

from runtime.tw_equity.tables import find_table

from .adapters import is_placeholder
from .model import entity, evidence, relation, role

PRODUCT_STAGES = {
    "半導體設備": "設備",
    "半導體材料": "材料",
    "封裝": "封裝",
    "測試設備": "測試",
    "晶圓製造": "製造",
    "量測儀器設備": "量測",
    "探針卡": "測試",
    "矽晶圓": "材料",
    "檢測設備": "測試",
    "晶圓代工": "製造",
    "銅箔基板": "材料",
    "IC載板": "載板",
    "積體電路載板": "載板",
    "廠務工程": "廠務",
    "無塵室": "廠務",
    "半導體測試": "測試",
    "分選設備": "測試",
}

PRODUCT_HEADING = r"主要產品|目前(?:之)?商品(?:[（(]服務[）)])?(?:項目)?|營業比重"
COUNTERPARTY_HEADERS = {
    "名稱",
    "客戶名稱",
    "廠商名稱",
    "廠商代號",
    "排名",
    "金額",
    "比率",
    "占比",
    "百分比",
    "進貨淨額",
    "銷貨淨額",
    "進(銷)貨淨額",
    "進貨總額",
    "銷貨總額",
    "與發行人",
    "之關係",
    "與發行人之關係",
    "關係",
    "合計",
    "總計",
    "小計",
}


def _annual_period(label):
    match = re.search(r"(?<!\d)(\d{2,4})\s*年", label)
    if not match:
        return None
    year = int(match[1])
    if year < 1911:
        year += 1911
    return f"{year}-01-01~{year}-12-31"


def _anonymous(name):
    code = r"(?:[A-Za-z][0-9]*|[甲乙丙丁戊己庚辛壬癸][0-9]*)"
    designation = r"(?:公司|集團|集团|客戶|客户|廠商|厂商|供應商|供应商)"
    return bool(
        re.fullmatch(
            rf"(?:{code}\s*{designation}?|{designation}\s*(?:{code}|[0-9]+))",
            name,
        )
    )


def _invalid_counterparty(name):
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))
    numeric = re.fullmatch(
        r"\(?[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?\)?%?", compact
    )
    annual = re.fullmatch(r"(?:民國)?(?:[0-9]{2,4}[/~-])?[0-9]{2,4}年(?:度)?", compact)
    heading = re.fullmatch(
        r"(?:\([一二三四五六七八九十]+\)|[一二三四五六七八九十]+[、.])最近(?:二|兩|2)年度.*",
        compact,
    )
    return (
        not compact
        or compact in COUNTERPARTY_HEADERS
        or bool(numeric or annual or heading)
    )


def _pdf_proof(doc, page, quote, period, digest):
    return evidence(
        str(doc.path),
        document_hash=digest,
        locator={"page": page.number},
        quote=quote,
        period=period,
        source_type="primary",
    )


def _candidate_roles(fragment, ar, anchors, company_id, period, digest):
    seen_pages = set()
    for key in ("ar_business", "ar_market"):
        section = anchors.get(key)
        if section is None:
            continue
        for page in ar.pages:
            if (
                page.number in seen_pages
                or not section.start <= page.number <= section.end
            ):
                continue
            seen_pages.add(page.number)
            lines = page.text.splitlines()
            for index, sentence in enumerate(lines):
                explicit = re.search(
                    r"(?:本公司|本集團)\s*(?:主要|專注於)?\s*(?:製造|生產|提供|研發)|主要產品(?:為|包括|包含)",
                    sentence,
                )
                context_start = next(
                    (
                        position
                        for position in range(index, max(-1, index - 12), -1)
                        if re.search(
                            PRODUCT_HEADING, re.sub(r"\s+", "", lines[position])
                        )
                    ),
                    None,
                )
                business_context = key == "ar_business" and context_start is not None
                if not explicit and not business_context:
                    continue
                if re.search(r"競爭者|競爭對手", sentence):
                    continue
                quote = (
                    "\n".join(lines[context_start : index + 1])
                    if business_context
                    else sentence
                )
                product_text = (
                    "".join(lines[max(context_start, index - 1) : index + 1])
                    if business_context
                    else sentence
                )
                product_text = re.sub(r"\s+", "", product_text)
                for product, stage in PRODUCT_STAGES.items():
                    if product not in product_text:
                        continue
                    proof = _pdf_proof(ar, page, quote, period, digest)
                    fragment["evidence"].append(proof)
                    fragment["roles"].append(
                        role(
                            company_id,
                            "半導體設備與材料",
                            stage,
                            product=product,
                            evidence_ids=[proof["id"]],
                            status="pending",
                        )
                    )


def _t8_candidates(
    fragment, bundle, ar, anchors, company_id, source_path, digest, source_hash
):
    section = anchors.get("ar_customers")
    pages = [
        page
        for page in ar.pages
        if section and section.start <= page.number <= section.end
    ]
    market = anchors.get("ar_market")
    tables = []
    if section:
        start_page = min(market.start, section.start) if market else section.start
        tables = ar.tables_of(start_page, section.end)
    for collection, kind in (
        ("customers_sales", "sales"),
        ("customers_purchase", "purchase"),
    ):
        table = bundle.get(collection) or {}
        # Match the producer's selected table, then inspect only its header.
        # A data cell containing 進貨 must not turn a sales table into purchases.
        selected = find_table(
            tables,
            header_keywords=["年度"],
            row_keywords=["銷貨" if kind == "sales" else "進貨"],
        )
        header = unicodedata.normalize(
            "NFKC", " ".join(cell or "" for row in (selected or [])[:2] for cell in row)
        )
        header_kinds = {label for label in ("銷貨", "進貨") if label in header}
        direction_verified = header_kinds == {"銷貨" if kind == "sales" else "進貨"}
        for year_index, year in enumerate(table.get("years") or []):
            period = _annual_period(year.get("label") or "")
            for entry_index, entry in enumerate(year.get("entries") or []):
                name = entry.get("name") or ""
                pointer = f"/bundle/{collection}/years/{year_index}/entries/{entry_index}/name"
                if _invalid_counterparty(name):
                    fragment["coverage"][0]["excluded"].append(
                        dict(pointer=pointer, name=name, reason="invalid_counterparty")
                    )
                    continue
                if is_placeholder(name):
                    fragment["coverage"][0]["excluded"].append(
                        dict(pointer=pointer, name=name, reason="placeholder")
                    )
                    continue
                anonymous = _anonymous(name)
                target = entity(
                    name,
                    anonymous=anonymous,
                    owner_id=company_id if anonymous else None,
                    period=period,
                    scope_id=digest + pointer,
                )
                fragment["entities"].append(target)
                match = next(
                    (
                        (page, line)
                        for page in pages
                        for line in page.text.splitlines()
                        if name in line
                    ),
                    None,
                )
                if match:
                    proof = _pdf_proof(ar, match[0], match[1], period, digest)
                else:
                    proof = evidence(
                        str(source_path),
                        document_hash=source_hash,
                        locator={"pointer": pointer},
                        quote=name,
                        period=period,
                        source_type="analysis",
                    )
                    fragment["coverage"][0]["warnings"].append(
                        "t8_original_text_missing"
                    )
                fragment["evidence"].append(proof)
                if period is None:
                    fragment["coverage"][0]["missing"].append("t8_period")
                if not direction_verified:
                    fragment["coverage"][0]["missing"].append("t8_direction")
                    fragment["coverage"][0]["warnings"].append(
                        dict(
                            reason="t8_direction_unverified",
                            pointer=pointer,
                            evidence_id=proof["id"],
                            source=str(source_path),
                        )
                    )
                    continue
                source, destination = (
                    (company_id, target["id"])
                    if kind == "sales"
                    else (target["id"], company_id)
                )
                fragment["relations"].append(
                    relation(
                        source,
                        "supplies_to",
                        destination,
                        period=period,
                        status="pending",
                        evidence_ids=[proof["id"]],
                    )
                )
