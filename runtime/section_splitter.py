import re

from agent_runner import run_agent, truncate_with_notice

# ── 10-K sections ──
TARGET_SECTIONS_10K = [
    "item1", "item1a", "item1c", "item7",
    "item8", "item9a", "item10", "item11", "item13",
]

HEADER_PATTERNS_10K = {
    "item1":  r"^#{1,3}\s*item\s+1[\.\s]+business(?!\s*[abc])",
    "item1a": r"^#{1,3}\s*item\s+1a[\.\s]+risk",
    "item1c": r"^#{1,3}\s*item\s+1c[\.\s]+cyber",
    "item7":  r"^#{1,3}\s*item\s+7[\.\s]+management",
    "item7a": r"^#{1,3}\s*item\s+7a",
    "item8":  r"^#{1,3}\s*item\s+8[\.\s]+financial",
    "item9a": r"^#{1,3}\s*item\s+9a",
    "item10": r"^#{1,3}\s*item\s+10",
    "item11": r"^#{1,3}\s*item\s+11",
    "item13": r"^#{1,3}\s*item\s+13",
}

# ── 10-Q sections ──
# 10-Q Part I: Item 1 (Financial Statements), Item 2 (MD&A), Item 3 (Market Risk), Item 4 (Controls)
# 10-Q Part II: Item 1 (Legal), Item 1A (Risk Factors, optional), Item 6 (Exhibits)
TARGET_SECTIONS_10Q = [
    "item1", "item2", "item3", "item4",
]

HEADER_PATTERNS_10Q = {
    "item1":  r"(?:^#{1,3}\s*|^\|?\s*)item\s+1[\.\s]+.*financial",
    "item1a": r"(?:^#{1,3}\s*|^\|?\s*)item\s+1a[\.\s]+.*risk",
    "item2":  r"(?:^#{1,3}\s*|^\|?\s*)item\s+2[\.\s]+.*management",
    "item3":  r"(?:^#{1,3}\s*|^\|?\s*)item\s+3[\.\s]+.*quantitative",
    "item4":  r"(?:^#{1,3}\s*|^\|?\s*)item\s+4[\.\s]+.*controls",
}

# Default alias (backward compatible)
TARGET_SECTIONS = TARGET_SECTIONS_10K
HEADER_PATTERNS = HEADER_PATTERNS_10K


def _get_config(filing_type: str = "10-K"):
    if filing_type == "10-Q":
        return TARGET_SECTIONS_10Q, HEADER_PATTERNS_10Q
    return TARGET_SECTIONS_10K, HEADER_PATTERNS_10K


def split_sections(md_text: str, filing_type: str = "10-K") -> dict[str, str]:
    target_sections, header_patterns = _get_config(filing_type)

    # Layer 1: header-based
    sections = _split_by_patterns(md_text, header_patterns, target_sections)
    if _is_valid(sections, filing_type):
        return sections

    # Layer 2: TOC-guided
    sections = _toc_guided_split(md_text, filing_type)
    if _is_valid(sections, filing_type):
        return sections

    # Layer 3: LLM fallback
    return _llm_fallback(md_text)


# Plain-text patterns (no markdown # headers) for BS4/iXBRL extracted text
_PLAIN_PATTERNS_10K = {
    "item1":  r"^\s*ITEM\s+1\s*[\.\s]+BUSINESS\s*$",
    "item1a": r"^\s*ITEM\s+1A\s*[\.\s]+RISK",
    "item1c": r"^\s*ITEM\s+1C\s*[\.\s]+CYBER",
    "item7":  r"^\s*ITEM\s+7\s*[\.\s]+MANAGEMENT",
    "item7a": r"^\s*ITEM\s+7A\s*[\.\s]",
    "item8":  r"^\s*ITEM\s+8\s*[\.\s]+FINANCIAL",
    "item9a": r"^\s*ITEM\s+9A\s*[\.\s]",
    "item10": r"^\s*ITEM\s+10\s*[\.\s]",
    "item11": r"^\s*ITEM\s+11\s*[\.\s]",
    "item13": r"^\s*ITEM\s+13\s*[\.\s]",
}

_PLAIN_PATTERNS_10Q = {
    "item1":  r"^\s*ITEM\s+1\s*[\.\s]+.*FINANCIAL",
    "item1a": r"^\s*ITEM\s+1A\s*[\.\s]+.*RISK",
    "item2":  r"^\s*ITEM\s+2\s*[\.\s]+.*MANAGEMENT",
    "item3":  r"^\s*ITEM\s+3\s*[\.\s]+.*QUANTITATIVE",
    "item4":  r"^\s*ITEM\s+4\s*[\.\s]+.*CONTROLS",
}


def _split_by_patterns(text, patterns, target_sections=None) -> dict[str, str]:
    if target_sections is None:
        target_sections = TARGET_SECTIONS_10K
    lines = text.split("\n")
    positions = {}
    for name, pattern in patterns.items():
        matches = [
            i for i, l in enumerate(lines) if re.match(pattern, l, re.IGNORECASE)
        ]
        if matches:
            positions[name] = matches[-1]
    # If markdown-header patterns found very few sections, try plain-text patterns
    if len(positions) < 3:
        plain = _PLAIN_PATTERNS_10Q if "item2" in target_sections else _PLAIN_PATTERNS_10K
        for name, pattern in plain.items():
            if name in positions:
                continue  # already found via markdown pattern
            matches = [
                i for i, l in enumerate(lines) if re.match(pattern, l, re.IGNORECASE)
            ]
            if matches:
                positions[name] = matches[-1]
    sorted_pos = sorted(positions.items(), key=lambda x: x[1])
    result = {}
    for i, (name, start) in enumerate(sorted_pos):
        if name not in target_sections:
            continue
        end = sorted_pos[i + 1][1] if i + 1 < len(sorted_pos) else len(lines)
        result[name] = "\n".join(lines[start:end]).strip()
    return result


def _strip_md_formatting(text: str) -> str:
    """Remove markdown links, pipes, and extra whitespace from TOC text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [text](link) -> text
    text = re.sub(r"[|]", " ", text)  # pipes
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_hierarchical_toc(lines, toc_end, known_titles, target_sections):
    """Parse hierarchical TOC table. Returns {item_key: anchor_id}.

    Handles two patterns:
    - Parent rows: first cell has text (e.g. "| Financial Statements... |")
    - Child rows: first cell is empty (e.g. "|  | | | Statements of Operations | ...")

    For parents without anchors, uses the first child's anchor.
    Children can also directly match a section (e.g. Risk Factors -> item1a).
    """
    anchor_re = re.compile(r"\[.*?\]\(#([^)]+)\)")
    result = {}
    current_parent_key = None

    for line in lines[:toc_end]:
        if "|" not in line:
            continue

        # Determine hierarchy: child row starts with "| " then immediately another "|"
        is_child = bool(re.match(r"\|\s*\|", line))

        # Extract title text (strip markdown formatting, pipes, whitespace)
        title_text = _strip_md_formatting(line).strip()
        if not title_text:
            continue

        # Extract anchor if present
        anchor_match = anchor_re.search(line)
        anchor_id = anchor_match.group(1) if anchor_match else None

        if not is_child:
            # Parent row: try to match known_titles
            current_parent_key = None
            for skey, known in known_titles.items():
                if known[:15].lower() in title_text.lower():
                    current_parent_key = skey
                    if anchor_id and skey not in result and skey in target_sections:
                        result[skey] = anchor_id
                    break
        else:
            # Child row: first give anchor to parent if parent has no anchor yet
            if (current_parent_key is not None
                    and anchor_id
                    and current_parent_key not in result
                    and current_parent_key in target_sections):
                result[current_parent_key] = anchor_id

            # Also try to match child row directly against known_titles
            if anchor_id:
                for skey, known in known_titles.items():
                    if known[:15].lower() in title_text.lower():
                        if skey not in result and skey in target_sections:
                            result[skey] = anchor_id
                        break

    return result


def _detect_toc_end(lines, max_scan=300) -> int:
    """Find where TOC ends by detecting the dense cluster of Item references.
    TOC has many Item refs close together; body text has sparse ones.
    We find the end of the dense cluster (gap > 10 lines = no longer TOC)."""
    item_lines = []
    for i, line in enumerate(lines[:max_scan]):
        if re.search(r"item\s+\d+[abc]?\b", line, re.IGNORECASE):
            item_lines.append(i)
    if not item_lines:
        return min(130, len(lines))
    # Find where the gap between consecutive Item refs exceeds 10 lines
    cluster_end = item_lines[0]
    for j in range(1, len(item_lines)):
        if item_lines[j] - item_lines[j - 1] > 10:
            break
        cluster_end = item_lines[j]
    return cluster_end + 3


KNOWN_TITLES_10K = {
    "item1":  "Business",
    "item1a": "Risk Factors",
    "item1c": "Cybersecurity",
    "item7":  "Management's Discussion and Analysis",
    "item8":  "Financial Statements and Supplementary Data",
    "item9a": "Controls and Procedures",
    "item10": "Directors",
    "item11": "Executive Compensation",
    "item13": "Certain Relationships",
}

KNOWN_TITLES_10Q = {
    "item1":  "Financial Statements",
    "item1a": "Risk Factors",
    "item2":  "Management's Discussion and Analysis",
    "item3":  "Quantitative and Qualitative Disclosures About Market Risk",
    "item4":  "Controls and Procedures",
}


def _toc_guided_split(md_text, filing_type: str = "10-K") -> dict[str, str]:
    target_sections, _ = _get_config(filing_type)
    known_titles = KNOWN_TITLES_10Q if filing_type == "10-Q" else KNOWN_TITLES_10K

    lines = md_text.split("\n")
    toc_end = _detect_toc_end(lines)

    # ── Step 1: Parse TOC for item keys and anchors ──
    item_anchors = _parse_hierarchical_toc(lines, toc_end, known_titles, target_sections)
    item_titles = {k: known_titles.get(k, "") for k in target_sections}

    # ── Step 2: Locate positions using anchors first, then text patterns ──
    positions = {}

    # Strategy A: anchor-based (most reliable for files with TOC links)
    # MarkItDown escapes _ → \_ in text but not in URLs,
    # so normalize the line before matching
    for key, anchor_id in item_anchors.items():
        marker = f"[anchor:{anchor_id}]"
        for i, line in enumerate(lines):
            if marker in line.replace("\\_", "_"):
                positions[key] = i
                break

    # Strategy B: text-based fallback for items without anchors
    for key, title in item_titles.items():
        if key in positions:
            continue
        item_num = key.replace("item", "")
        pat_strict = re.compile(
            rf"^\s*item\s+{re.escape(item_num)}[.\s]+{re.escape(title[:20])}",
            re.IGNORECASE,
        )
        pat_loose = re.compile(
            rf"^\s*item\s+{re.escape(item_num)}\s*\.",
            re.IGNORECASE,
        )
        pat_title_only = re.compile(
            rf"^\s*{re.escape(title[:20])}",
            re.IGNORECASE,
        )
        for pat in [pat_strict, pat_loose, pat_title_only]:
            for i, line in enumerate(lines[toc_end:], start=toc_end):
                if "|" in line:
                    continue
                clean_line = _strip_md_formatting(line)
                if pat.search(clean_line):
                    positions[key] = i
                    break
            if key in positions:
                break

    target_sections, _ = _get_config(filing_type)
    sorted_pos = sorted(positions.items(), key=lambda x: x[1])
    result = {}
    for i, (name, start) in enumerate(sorted_pos):
        if name not in target_sections:
            continue
        end = sorted_pos[i + 1][1] if i + 1 < len(sorted_pos) else len(lines)
        result[name] = "\n".join(lines[start:end]).strip()
    return result


def _llm_fallback(md_text) -> dict[str, str]:
    result = run_agent(
        "analyst_agent",
        "section_splitter",
        {
            "document_preview": truncate_with_notice(md_text, 8000),
            "full_text_length": str(len(md_text)),
        },
        task_label="section_splitter.llm_fallback",
    )
    lines = md_text.split("\n")
    anchors = result.get("item_anchors", {})
    positions = {}
    for key, anchor in anchors.items():
        for i, line in enumerate(lines):
            if anchor[:30].lower() in line.lower():
                positions[key] = i
                break
    sorted_pos = sorted(positions.items(), key=lambda x: x[1])
    result2 = {}
    for i, (name, start) in enumerate(sorted_pos):
        end = sorted_pos[i + 1][1] if i + 1 < len(sorted_pos) else len(lines)
        result2[name] = "\n".join(lines[start:end]).strip()
    return result2


def _is_valid(sections, filing_type: str = "10-K") -> bool:
    if filing_type == "10-Q":
        critical = ["item1", "item2"]
        return (
            len(sections) >= 2
            and all(k in sections for k in critical)
            and all(len(sections[k]) >= 500 for k in critical if k in sections)
        )
    critical = ["item1a", "item7"]
    # item8 can legitimately be short (e.g. "presented following Item 15")
    return (
        len(sections) >= 3
        and any(k in sections for k in critical + ["item8"])
        and all(len(sections[k]) >= 200 for k in critical if k in sections)
    )


def validate_sections(sections, filing_type: str = "10-K") -> list[str]:
    warnings = []
    if filing_type == "10-Q":
        thresholds = {"item1": 2000, "item2": 3000}
    else:
        thresholds = {"item1a": 3000, "item7": 5000, "item8": 5000}
    for name, min_c in thresholds.items():
        if len(sections.get(name, "")) < min_c:
            warnings.append(
                f"{name}: {len(sections.get(name, ''))} 字（預期 >{min_c}），可能切割不完整"
            )
    return warnings


def extract_footnotes(item8_text: str) -> str:
    m = re.search(
        r"notes?\s+to\s+(?:consolidated\s+)?financial\s+statements",
        item8_text,
        re.IGNORECASE,
    )
    return item8_text[m.start() :] if m else item8_text


def extract_fs_tables(item8_text: str) -> str:
    """三張報表（Notes 之前的部分），供 financial_agent 讀取脈絡。"""
    m = re.search(
        r"notes?\s+to\s+(?:consolidated\s+)?financial\s+statements",
        item8_text,
        re.IGNORECASE,
    )
    return item8_text[: m.start()] if m else item8_text[:5000]


# --- Footnotes sub-section splitting ---

FOOTNOTES_GROUPS = {
    "fn_revenue":      ["A", "B"],
    "fn_segment":      ["C", "D"],
    "fn_receivables":  ["L", "Q"],
    "fn_assets":       ["M", "N", "O", "R"],
    "fn_risk":         ["U", "V", "P"],
    "fn_pension":      ["G"],
    "fn_compensation": ["I", "J", "K"],
    "fn_tax":          ["H"],
}


def split_footnotes(item8_text: str) -> dict[str, str]:
    """Split footnotes into sub-sections by Note letter (A-V)."""
    footnotes_text = extract_footnotes(item8_text)
    lines = footnotes_text.split("\n")

    # Find Note boundaries: lines like "A. Summary of ..."
    note_starts = {}
    for i, line in enumerate(lines):
        m = re.match(r"^([A-V])\.\s+\S", line.strip())
        if m:
            note_starts[m.group(1)] = i

    if not note_starts:
        # Fallback: return full text as fn_revenue
        return {"fn_revenue": footnotes_text}

    sorted_notes = sorted(note_starts.items(), key=lambda x: x[1])

    # Extract text for each Note letter
    note_texts = {}
    for idx, (letter, start) in enumerate(sorted_notes):
        end = sorted_notes[idx + 1][1] if idx + 1 < len(sorted_notes) else len(lines)
        note_texts[letter] = "\n".join(lines[start:end]).strip()

    # Group into sub-sections
    result = {}
    for group_key, letters in FOOTNOTES_GROUPS.items():
        parts = [note_texts[l] for l in letters if l in note_texts]
        if parts:
            result[group_key] = "\n\n".join(parts)

    # Include ungrouped notes (D, E, F, S, T) in a catch-all
    grouped_letters = set()
    for letters in FOOTNOTES_GROUPS.values():
        grouped_letters.update(letters)
    ungrouped = [note_texts[l] for l in sorted(note_texts) if l not in grouped_letters]
    if ungrouped:
        result["fn_other"] = "\n\n".join(ungrouped)

    return result
