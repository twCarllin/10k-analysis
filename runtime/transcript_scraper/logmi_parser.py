"""
logmi_parser.py — Structure a raw logmi Finance transcript into Presentation / Q&A sections.

Public API:
    parse_logmi_transcript(raw_text, speakers) -> dict
"""
from __future__ import annotations

import re
from typing import Any

# ─── Section markers ──────────────────────────────────────────────────────────
# Presentation start: lines whose stripped content is one of these keywords
_PRESENTATION_MARKERS = [
    "プレゼンテーション",
    "決算ハイライト",
    "業績概要",
    "会社説明",
]

# Q&A start: lines whose stripped content is one of these keywords
_QA_MARKERS = [
    "質疑応答",
    "質問と回答",
    "Q&A",
]

# Speaker line: Japanese name followed by full-width or half-width colon.
# Excludes: speakers containing "/" (URLs), all-digit speakers (timestamps like "10:30"),
# and speakers shorter than 2 characters.
# Examples matched: "田中 太郎：", "田中："
# Examples rejected: "10：", "https://example.com/path：", "Q："  (length < 2)
_SPEAKER_LINE_RE = re.compile(
    r"^(?P<speaker>[^/\d:：]{2,}?)[：:]\s*(?P<body>.*)?$",
    re.MULTILINE,
)

# Minimum text length for a speaker label (prevents matching short punctuation)
_MIN_SPEAKER_LEN = 2


def _is_section_marker(line: str, markers: list[str]) -> bool:
    """Return True if the stripped line exactly matches one of the given markers."""
    stripped = line.strip()
    return stripped in markers


def _split_qa_turns(qa_text: str, speakers: list[dict]) -> list[dict]:
    """Parse Q&A section text into a list of {question, answer, asker, answerer} turns.

    Note: Assumes Q-A-Q-A alternation. Multi-question follow-ups (Q-Q-A) or
    management supplements (A-A) may be mis-paired. Speaker role can be used
    to improve this when available.

    Strategy:
    - A turn starts when a new speaker line is encountered.
    - We collect consecutive speaker turns and pair them as (question, answer).
    - If the section is unparseable, returns a single entry with the full text as the question.
    """
    lines = qa_text.split("\n")
    turns: list[dict[str, str]] = []

    # Accumulate all (speaker, body) segments first
    segments: list[dict[str, str]] = []
    current_speaker = "Unknown"
    current_body_lines: list[str] = []

    for line in lines:
        m = _SPEAKER_LINE_RE.match(line)
        if m and len(m.group("speaker").strip()) >= _MIN_SPEAKER_LEN:
            # Flush previous segment
            if current_body_lines or current_speaker != "Unknown":
                segments.append(
                    {"speaker": current_speaker, "body": "\n".join(current_body_lines).strip()}
                )
            current_speaker = m.group("speaker").strip()
            body_after_colon = (m.group("body") or "").strip()
            current_body_lines = [body_after_colon] if body_after_colon else []
        else:
            current_body_lines.append(line)

    # Flush last segment
    if current_body_lines or current_speaker != "Unknown":
        segments.append(
            {"speaker": current_speaker, "body": "\n".join(current_body_lines).strip()}
        )

    # Remove empty/header-only segments at the top (e.g., the "質疑応答" line itself)
    segments = [s for s in segments if s["body"].strip()]

    if not segments:
        return []

    # Pair segments as (question, answer) — best effort
    # If only one segment, treat it as a question with no answer
    i = 0
    while i < len(segments):
        question_seg = segments[i]
        answer_seg = segments[i + 1] if i + 1 < len(segments) else None

        if answer_seg:
            turns.append(
                {
                    "question": question_seg["body"],
                    "answer": answer_seg["body"],
                    "asker": question_seg["speaker"],
                    "answerer": answer_seg["speaker"],
                }
            )
            i += 2
        else:
            turns.append(
                {
                    "question": question_seg["body"],
                    "answer": "",
                    "asker": question_seg["speaker"],
                    "answerer": "Unknown",
                }
            )
            i += 1

    return turns


def parse_logmi_transcript(raw_text: str, speakers: list[dict]) -> dict[str, Any]:
    """Split a logmi transcript into Presentation and Q&A sections.

    Detection logic:
    1. Scan lines for Presentation markers and Q&A markers.
    2. The earliest matched Q&A marker determines the split point.
    3. Everything before the Q&A marker is the Presentation section.
    4. Everything after (including the marker line) is the Q&A section.
    5. If no Q&A marker is found, the entire text is the Presentation and qa=[].

    Args:
        raw_text: Full transcript text as scraped from logmi.
        speakers: List of speaker dicts from the Node script (name/role/company).
                  Currently used for future speaker resolution; not required for parsing.

    Returns:
        {
            "presentation": str,   # Presentation section text
            "qa": [                # List of Q&A turns
                {
                    "question": str,
                    "answer": str,
                    "asker": str,    # Speaker name or "Unknown"
                    "answerer": str, # Speaker name or "Unknown"
                }
            ]
        }
    """
    lines = raw_text.split("\n")

    qa_start_idx: int | None = None

    for i, line in enumerate(lines):
        if _is_section_marker(line, _QA_MARKERS):
            qa_start_idx = i
            break

    if qa_start_idx is None:
        # Fallback: no Q&A marker found — entire text is presentation
        return {
            "presentation": raw_text,
            "qa": [],
        }

    presentation_text = "\n".join(lines[:qa_start_idx]).strip()
    qa_text = "\n".join(lines[qa_start_idx + 1:]).strip()  # skip the marker line itself

    qa_turns = _split_qa_turns(qa_text, speakers)

    return {
        "presentation": presentation_text,
        "qa": qa_turns,
    }
