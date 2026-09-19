from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.facts import SourceFacts
from app.models.news import NewsCandidate
from app.models.script import Script, SectionName


class SectionAudio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: SectionName
    file: str
    duration_seconds: float


class Manifest(BaseModel):
    """Machine-readable record of a completed episode.

    Written alongside the MP3 into the Home Assistant media directory, and
    kept in job storage for debugging - it captures the facts, the script,
    the selected news, and the resulting audio layout.
    """

    model_config = ConfigDict(extra="forbid")

    episode_id: str
    episode_date: date
    audio_file: str
    voice: str
    voice_disclosure: str = (
        "This episode is narrated by an AI-generated voice."
    )
    sections: list[SectionAudio]
    script: Script
    source_facts: SourceFacts
    selected_news: list[NewsCandidate]
    created_at: datetime
