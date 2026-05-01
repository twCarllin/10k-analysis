"""Unit tests for parser.py (pure sync, no pytest-asyncio needed)."""
import pytest
from runtime.transcript_scraper.models import Participant
from runtime.transcript_scraper.parser import parse_transcript, _split_by_speakers, _build_alias_index


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def participants():
    return [
        Participant(name="Patrick Gelsinger", role="CEO", affiliation="Intel"),
        Participant(name="David Zinsner", role="CFO", affiliation="Intel"),
        Participant(name="Ross Seymore", role="Analyst", affiliation="Deutsche Bank"),
    ]


# ---------------------------------------------------------------------------
# Test 1: Normal split — prepared remarks and Q&A correctly separated
# ---------------------------------------------------------------------------

def test_normal_split(participants):
    raw_text = (
        "Operator: Good morning and welcome to the Intel Q1 2026 Earnings Call.\n"
        "Patrick Gelsinger: Thank you, Operator. We had a strong quarter.\n"
        "David Zinsner: Revenue came in at $14 billion.\n"
        "\n"
        "Questions and Answers Session\n"
        "\n"
        "Ross Seymore: Can you discuss the margin outlook?\n"
        "David Zinsner: Sure. We expect margins to expand in H2.\n"
    )

    sections = parse_transcript(raw_text, participants)

    # Prepared remarks should contain Patrick and David segments (plus Unknown Operator)
    prepared_speakers = {seg.speaker for seg in sections.prepared_remarks}
    assert "Patrick Gelsinger" in prepared_speakers
    assert "David Zinsner" in prepared_speakers
    assert len(sections.prepared_remarks) >= 1

    # Q&A should contain Ross Seymore and David Zinsner
    qa_speakers = {seg.speaker for seg in sections.qa}
    assert "Ross Seymore" in qa_speakers
    assert len(sections.qa) >= 1

    # Roles should be populated from participant list
    patrick_seg = next(
        seg for seg in sections.prepared_remarks if seg.speaker == "Patrick Gelsinger"
    )
    assert patrick_seg.role == "CEO"
    assert patrick_seg.affiliation == "Intel"


# ---------------------------------------------------------------------------
# Test 2: Name variant — fuzzy match resolves "Pat Gelsinger" -> Patrick Gelsinger
# ---------------------------------------------------------------------------

def test_name_variant_fuzzy_match(participants):
    raw_text = (
        "Pat Gelsinger: We are investing heavily in advanced packaging.\n"
        "David Zinsner: Capital allocation remains disciplined.\n"
    )

    segments = _split_by_speakers(raw_text, participants)

    speakers = {seg.speaker for seg in segments}
    # "Pat Gelsinger" should fuzzy-match to "Patrick Gelsinger"
    assert "Patrick Gelsinger" in speakers, (
        f"Expected fuzzy match to 'Patrick Gelsinger', got speakers: {speakers}"
    )


# ---------------------------------------------------------------------------
# Test 3: Unknown fallback — unrecognised speaker gets speaker="Unknown"
# ---------------------------------------------------------------------------

def test_unknown_fallback(participants):
    raw_text = (
        "Patrick Gelsinger: Our roadmap is on track.\n"
        "Random Stranger: I have a random comment.\n"
    )

    segments = _split_by_speakers(raw_text, participants)

    speakers = {seg.speaker for seg in segments}
    assert "Unknown" in speakers, (
        f"Expected 'Unknown' for unrecognised speaker, got: {speakers}"
    )

    unknown_seg = next(seg for seg in segments if seg.speaker == "Unknown")
    assert unknown_seg.role is None
    assert unknown_seg.affiliation is None


# ---------------------------------------------------------------------------
# Test 4: No Q&A marker — entire text goes to prepared_remarks, qa is empty
# ---------------------------------------------------------------------------

def test_no_qa_marker(participants):
    raw_text = (
        "Patrick Gelsinger: We delivered solid results.\n"
        "David Zinsner: Free cash flow was positive.\n"
    )

    sections = parse_transcript(raw_text, participants)

    assert len(sections.prepared_remarks) >= 1
    assert sections.qa == []


# ---------------------------------------------------------------------------
# Test 5: Empty participants list — all speakers become Unknown
# ---------------------------------------------------------------------------

def test_empty_participants():
    raw_text = (
        "Alice Johnson: Good morning everyone.\n"
        "Bob Smith: Thank you for joining.\n"
    )

    segments = _split_by_speakers(raw_text, [])

    assert all(seg.speaker == "Unknown" for seg in segments)


# ---------------------------------------------------------------------------
# Test 6: Lastname collision — shared last name must NOT build a short alias
# ---------------------------------------------------------------------------

def test_lastname_collision_no_short_alias():
    """Two participants sharing a last name: lastname-only alias must be absent
    from the index, so a speaker line with only that last name is not silently
    mis-attributed to either participant."""
    participants = [
        Participant(name="John Smith", role="CEO", affiliation="Acme"),
        Participant(name="Jane Smith", role="CFO", affiliation="Acme"),
    ]
    index = _build_alias_index(participants)

    # Full names must still resolve correctly.
    assert index.get("john smith") is not None
    assert index.get("john smith").name == "John Smith"
    assert index.get("jane smith") is not None
    assert index.get("jane smith").name == "Jane Smith"

    # Shared last name must NOT be in the index.
    assert "smith" not in index, (
        "Conflicting lastname alias 'smith' should be removed, not kept pointing to one participant"
    )

    # A speaker line using only the shared last name becomes Unknown.
    raw_text = "Smith: Hello everyone.\n"
    segments = _split_by_speakers(raw_text, participants)
    assert segments[0].speaker == "Unknown", (
        f"Expected 'Unknown' for ambiguous last name, got '{segments[0].speaker}'"
    )


# ---------------------------------------------------------------------------
# Test 7: Firstname-only alias — unambiguous first name must resolve correctly
# ---------------------------------------------------------------------------

def test_firstname_only_alias_resolves():
    """A speaker identified only by first name should resolve when that first
    name is unambiguous among participants."""
    participants = [
        Participant(name="Patrick Gelsinger", role="CEO", affiliation="Intel"),
        Participant(name="David Zinsner", role="CFO", affiliation="Intel"),
    ]
    raw_text = "Patrick: Good morning, everyone.\n"
    segments = _split_by_speakers(raw_text, participants)

    assert segments[0].speaker == "Patrick Gelsinger", (
        f"Expected 'Patrick Gelsinger' from firstname alias, got '{segments[0].speaker}'"
    )


# ---------------------------------------------------------------------------
# Test 8: Q&A earliest position — short pattern earlier than long pattern wins
# ---------------------------------------------------------------------------

def test_qa_split_takes_earliest_position():
    """When the text contains a short Q&A marker earlier than a longer variant,
    the split must occur at the earliest marker, not the first pattern tried."""
    participants = [
        Participant(name="Patrick Gelsinger", role="CEO", affiliation="Intel"),
        Participant(name="Ross Seymore", role="Analyst", affiliation="Deutsche Bank"),
    ]
    # "Q&A" appears in the prepared remarks as a section heading (earlier),
    # "Questions and Answers Session" appears later as the real boundary.
    # The split should happen at the "Q&A" position (earlier idx).
    raw_text = (
        "Patrick Gelsinger: We will now move to Q&A.\n"
        "\n"
        "Questions and Answers Session\n"
        "\n"
        "Ross Seymore: What is the margin outlook?\n"
    )

    sections = parse_transcript(raw_text, participants)

    # Split occurs at "Q&A" (inside the Patrick line), so the Q&A section
    # starts from that point — Ross Seymore must appear in qa.
    qa_speakers = {seg.speaker for seg in sections.qa}
    assert "Ross Seymore" in qa_speakers

    # The prepared remarks portion (before "Q&A") should contain Patrick.
    prepared_speakers = {seg.speaker for seg in sections.prepared_remarks}
    assert "Patrick Gelsinger" in prepared_speakers

    # Crucially: the split index must be before "Questions and Answers Session",
    # i.e., the prepared_remarks text must NOT contain "Questions and Answers Session".
    full_prepared_text = " ".join(seg.text for seg in sections.prepared_remarks)
    assert "Questions and Answers Session" not in full_prepared_text, (
        "Split should have occurred at the earlier 'Q&A' marker, not the later one"
    )
