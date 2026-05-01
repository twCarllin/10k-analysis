from pydantic import BaseModel
from typing import Optional


class TranscriptLink(BaseModel):
    """從 earnings-calls 列表頁抓到的連結資訊"""
    title: str
    quarter: str
    year: str
    url: str
    date: Optional[str] = None


class Participant(BaseModel):
    name: str
    role: Optional[str] = None
    affiliation: Optional[str] = None


class SpeakerSegment(BaseModel):
    """單一發言段落"""
    speaker: str
    role: Optional[str] = None
    affiliation: Optional[str] = None
    text: str


class TranscriptSections(BaseModel):
    prepared_remarks: list[SpeakerSegment]
    qa: list[SpeakerSegment]


class Transcript(BaseModel):
    """完整 transcript 輸出"""
    ticker: str
    quarter: str
    year: str
    date: str
    url: str
    participants: list[Participant]
    sections: TranscriptSections
    raw_text: str
    scraped_at: str
