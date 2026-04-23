import re

from agent_runner import run_agent, truncate_with_notice

TARGET_SECTIONS = [
    "item1", "item1a", "item1c", "item7",
    "item8", "item9a", "item10", "item11", "item13",
]

HEADER_PATTERNS = {
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


def split_sections(md_text: str) -> dict[str, str]:
    # Layer 1: header-based
    sections = _split_by_patterns(md_text, HEADER_PATTERNS)
    if _is_valid(sections):
        return sections

    # Layer 2: TOC-guided
    sections = _toc_guided_split(md_text)
    if _is_valid(sections):
        return sections

    # Layer 3: LLM fallback
    return _llm_fallback(md_text)


def _split_by_patterns(text, patterns) -> dict[str, str]:
    lines = text.split("\n")
    positions = {}
    for name, pattern in patterns.items():
        matches = [
            i for i, l in enumerate(lines) if re.match(pattern, l, re.IGNORECASE)
        ]
        if matches:
            positions[name] = matches[-1]
    sorted_pos = sorted(positions.items(), key=lambda x: x[1])
    result = {}
    for i, (name, start) in enumerate(sorted_pos):
        if name not in TARGET_SECTIONS:
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


def _toc_guided_split(md_text) -> dict[str, str]:
    lines = md_text.split("\n")
    toc_end = _detect_toc_end(lines)
    item_titles = {}
    toc_re = re.compile(
        r"(item\s+\d+[abc]?)\s*[.\-\u2013]?\s*(.+?)(?:\s+\.{2,}|\s+\d+\s*$|\s*$)",
        re.IGNORECASE,
    )
    for line in lines[:toc_end]:
        m = toc_re.search(line)
        if m:
            key = "item" + m.group(1).lower().split()[-1]
            raw_title = m.group(2).strip()
            title = _strip_md_formatting(raw_title)[:40]
            if key in TARGET_SECTIONS and len(title) >= 3:
                item_titles[key] = title

    # Also try well-known section names as fallback anchors
    KNOWN_TITLES = {
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
    for key, fallback in KNOWN_TITLES.items():
        if key not in item_titles:
            item_titles[key] = fallback

    positions = {}
    for key, title in item_titles.items():
        item_num = key.replace("item", "")
        # Primary: match "Item N. <title>" at start of cleaned line (skip inline refs)
        pat_strict = re.compile(
            rf"^\s*item\s+{re.escape(item_num)}[.\s]+{re.escape(title[:20])}",
            re.IGNORECASE,
        )
        # Fallback: "Item N." at start of line
        pat_loose = re.compile(
            rf"^\s*item\s+{re.escape(item_num)}\s*\.",
            re.IGNORECASE,
        )
        for pat in [pat_strict, pat_loose]:
            for i, line in enumerate(lines[toc_end:], start=toc_end):
                clean_line = _strip_md_formatting(line)
                if pat.search(clean_line):
                    positions[key] = i
                    break
            if key in positions:
                break
    sorted_pos = sorted(positions.items(), key=lambda x: x[1])
    result = {}
    for i, (name, start) in enumerate(sorted_pos):
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


def _is_valid(sections) -> bool:
    critical = ["item1a", "item7", "item8"]
    return (
        len(sections) >= 3
        and any(k in sections for k in critical)
        and all(len(v) >= 1000 for v in sections.values())
    )


def validate_sections(sections) -> list[str]:
    warnings = []
    for name, min_c in {"item1a": 3000, "item7": 5000, "item8": 5000}.items():
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
