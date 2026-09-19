from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.facts import SourceFacts
from app.models.manifest import Manifest
from app.models.script import SECTION_ORDER, SectionName

__all__ = ["JobState", "SectionState", "SectionName", "Job"]


class JobState(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SectionState(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Job(BaseModel):
    """Tracks one generation attempt end to end for status polling and retries."""

    model_config = ConfigDict(extra="forbid")

    id: str
    state: JobState = JobState.pending
    section_states: dict[SectionName, SectionState] = Field(
        default_factory=lambda: {s: SectionState.pending for s in SECTION_ORDER}
    )
    source_facts: SourceFacts
    force_regenerate: bool = False
    error: str | None = None
    manifest: Manifest | None = None
    created_at: datetime
    updated_at: datetime
