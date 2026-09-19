from __future__ import annotations

from datetime import UTC, datetime

from app.models.news import NewsCandidate
from app.providers.base import NewsProvider

_FIXTURE_CANDIDATES = [
    NewsCandidate(
        title="Local council approves new bike lane network",
        summary="The city council voted to expand protected bike lanes across "
        "three districts starting next spring.",
        source="Local Gazette",
        url="https://example.com/news/bike-lanes",
        feed="local",
        published_at=datetime(2026, 9, 19, 6, 0, tzinfo=UTC),
    ),
    NewsCandidate(
        title="Researchers report steady progress on battery recycling",
        summary="A new pilot plant says it can recover over 90% of lithium "
        "from used EV batteries.",
        source="Tech Digest",
        url="https://example.com/news/battery-recycling",
        feed="technology",
        published_at=datetime(2026, 9, 19, 5, 30, tzinfo=UTC),
    ),
    NewsCandidate(
        title="National team wins opening match of the tournament",
        summary="A late goal secured a 2-1 win in last night's opening fixture.",
        source="Sports Wire",
        url="https://example.com/news/opening-match",
        feed="sports",
        published_at=datetime(2026, 9, 19, 7, 0, tzinfo=UTC),
    ),
]


class MockNewsProvider(NewsProvider):
    """Returns fixture candidates, filtered by interest when possible.

    Deterministic and offline - used for the mock-first vertical slice and tests.
    """

    async def fetch_candidates(self, interests: list[str]) -> list[NewsCandidate]:
        if not interests:
            return list(_FIXTURE_CANDIDATES)
        wanted = {i.lower() for i in interests}
        matched = [c for c in _FIXTURE_CANDIDATES if c.feed.lower() in wanted]
        return matched or list(_FIXTURE_CANDIDATES)
