from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class NewsCandidate(BaseModel):
    """A single story retrieved from a configured feed, before selection."""

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    source: str
    url: HttpUrl
    feed: str
    published_at: datetime | None = None
