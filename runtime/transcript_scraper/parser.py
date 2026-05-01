import re
import difflib
from .models import Participant, SpeakerSegment, TranscriptSections

_QA_PATTERNS = [
    r"Question[s]?\s*(?:and|&)\s*Answer[s]?\s*(?:Session)?",
    r"Q\s*&\s*A\s*Session",
    r"Q&A",
]

_FUZZY_THRESHOLD = 0.85


def _build_alias_index(participants: list[Participant]) -> dict[str, Participant]:
    """Build a mapping from name aliases (lowercased) to Participant.

    Full-name aliases are always added. Short aliases (firstname-only,
    lastname-only) are only added when they are unambiguous — if two
    participants share the same first or last name, neither gets that
    short alias, preventing silent mis-attribution.
    """
    from collections import defaultdict

    # Map each candidate short alias to all participants that claim it.
    short_alias_candidates: dict[str, list[Participant]] = defaultdict(list)

    index: dict[str, Participant] = {}
    for p in participants:
        full = p.name.strip()
        # Full name is always authoritative — no conflict possible.
        index[full.lower()] = p

        tokens = full.split()
        if len(tokens) >= 2:
            short_alias_candidates[tokens[0].lower()].append(p)  # firstname
            short_alias_candidates[tokens[-1].lower()].append(p)  # lastname

    # Only add short aliases that map to exactly one participant.
    for alias, claimants in short_alias_candidates.items():
        if len(claimants) == 1:
            index[alias] = claimants[0]

    return index


def _lookup_participant(
    name_raw: str,
    alias_index: dict[str, Participant],
    participants: list[Participant],
) -> Participant | None:
    """Resolve a raw speaker name to a Participant via alias or fuzzy match."""
    key = name_raw.strip().lower()
    if key in alias_index:
        return alias_index[key]

    # fuzzy match against full names
    best_ratio = 0.0
    best_participant: Participant | None = None
    for p in participants:
        ratio = difflib.SequenceMatcher(None, key, p.name.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_participant = p

    if best_ratio >= _FUZZY_THRESHOLD:
        return best_participant

    return None


def _split_by_speakers(
    text: str, participants: list[Participant]
) -> list[SpeakerSegment]:
    """Split a transcript section by speaker turns.

    Uses regex to detect lines of the form "Speaker Name:" or a standalone
    name line, then resolves each speaker against the participant list.
    """
    alias_index = _build_alias_index(participants)

    # Pattern: a line that starts (possibly after whitespace) with a name
    # followed by a colon. Captures everything up to the colon as the speaker.
    # We allow letters, spaces (non-newline), dots, hyphens in names.
    # Using [^\S\n] to match spaces/tabs but NOT newlines, so each match
    # stays within a single line.
    speaker_line_re = re.compile(
        r"(?:^|\n)([^\S\n]*)([\w][\w\t .\-']*?)[ \t]*:\s*",
        re.MULTILINE,
    )

    segments: list[SpeakerSegment] = []
    matches = list(speaker_line_re.finditer(text))

    if not matches:
        # No speaker markers found — return whole text as Unknown
        stripped = text.strip()
        if stripped:
            segments.append(
                SpeakerSegment(speaker="Unknown", role=None, affiliation=None, text=stripped)
            )
        return segments

    # Text before the first speaker match (e.g. a header line)
    preamble = text[: matches[0].start()].strip()
    if preamble:
        segments.append(
            SpeakerSegment(speaker="Unknown", role=None, affiliation=None, text=preamble)
        )

    for i, match in enumerate(matches):
        speaker_raw = match.group(2).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        participant = _lookup_participant(speaker_raw, alias_index, participants)
        if participant is not None:
            segment = SpeakerSegment(
                speaker=participant.name,
                role=participant.role,
                affiliation=participant.affiliation,
                text=body,
            )
        else:
            segment = SpeakerSegment(
                speaker="Unknown",
                role=None,
                affiliation=None,
                text=body,
            )

        if body or speaker_raw:
            segments.append(segment)

    return segments


def parse_transcript(
    raw_text: str, participants: list[Participant]
) -> TranscriptSections:
    """Parse a raw transcript string into prepared remarks and Q&A sections.

    Splits at the first Q&A marker found. If no marker is present, the entire
    text is treated as prepared remarks with an empty Q&A list.
    """
    qa_split_idx = len(raw_text)
    for pattern in _QA_PATTERNS:
        m = re.search(pattern, raw_text, re.IGNORECASE)
        if m and m.start() < qa_split_idx:
            qa_split_idx = m.start()

    prepared_text = raw_text[:qa_split_idx]
    qa_text = raw_text[qa_split_idx:]

    prepared_remarks = _split_by_speakers(prepared_text, participants)
    qa = _split_by_speakers(qa_text, participants)

    return TranscriptSections(prepared_remarks=prepared_remarks, qa=qa)
