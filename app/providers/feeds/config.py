from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, HttpUrl


class FeedSource(BaseModel):
    """One configured RSS/Atom feed.

    `interests` tags which requested interests this feed satisfies; an empty
    list means the feed is general-purpose and always included.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    url: HttpUrl
    interests: list[str] = []


class FeedsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feeds: list[FeedSource]


def load_feeds_config(path: Path) -> FeedsConfig:
    data = json.loads(path.read_text())
    return FeedsConfig.model_validate(data)
