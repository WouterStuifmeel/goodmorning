from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.providers.feeds import FeedSource, FeedsConfig
from app.providers.feeds.rss import RssNewsProvider

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "feeds"

FEED_A_URL = "https://feeds.example.com/a.xml"
FEED_B_URL = "https://feeds.example.com/b.xml"
FEED_BROKEN_URL = "https://feeds.example.com/broken.xml"
FEED_AGGREGATOR_URL = "https://feeds.example.com/aggregator.xml"


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.feeds.rss._RETRY_BACKOFF_SECONDS", 0.0)


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == FEED_A_URL:
            return httpx.Response(200, content=(FIXTURES_DIR / "sample_feed_a.xml").read_bytes())
        if request.url == FEED_B_URL:
            return httpx.Response(200, content=(FIXTURES_DIR / "sample_feed_b.xml").read_bytes())
        if request.url == FEED_BROKEN_URL:
            return httpx.Response(500, content=b"server error")
        if request.url == FEED_AGGREGATOR_URL:
            return httpx.Response(
                200, content=(FIXTURES_DIR / "google_news_style.xml").read_bytes()
            )
        raise AssertionError(f"unexpected request to {request.url}")

    return httpx.MockTransport(handler)


def _provider(feeds: list[FeedSource]) -> RssNewsProvider:
    client = httpx.AsyncClient(transport=_mock_transport())
    return RssNewsProvider(FeedsConfig(feeds=feeds), http_client=client)


async def test_fetches_and_parses_general_feed() -> None:
    provider = _provider([FeedSource(name="Feed A", url=FEED_A_URL, interests=[])])

    candidates = await provider.fetch_candidates(interests=[])

    assert len(candidates) == 2
    first = candidates[0]
    assert first.title == "First story from feed A"
    assert "markup" in first.summary
    assert "<b>" not in first.summary
    assert str(first.url) == "https://example.com/feed-a/first-story"
    assert first.source == "Feed A"
    assert first.published_at is not None


async def test_selects_feeds_by_interest() -> None:
    provider = _provider(
        [
            FeedSource(name="Feed A", url=FEED_A_URL, interests=["technology"]),
            FeedSource(name="Feed B", url=FEED_B_URL, interests=["sports"]),
        ]
    )

    candidates = await provider.fetch_candidates(interests=["sports"])

    assert len(candidates) == 1
    assert candidates[0].source == "Feed B"


async def test_general_feed_included_regardless_of_interests() -> None:
    provider = _provider(
        [
            FeedSource(name="Feed A", url=FEED_A_URL, interests=[]),
            FeedSource(name="Feed B", url=FEED_B_URL, interests=["sports"]),
        ]
    )

    candidates = await provider.fetch_candidates(interests=["technology"])

    sources = {c.source for c in candidates}
    assert sources == {"Feed A"}


async def test_broken_feed_is_skipped_not_fatal() -> None:
    provider = _provider(
        [
            FeedSource(name="Feed A", url=FEED_A_URL, interests=[]),
            FeedSource(name="Broken Feed", url=FEED_BROKEN_URL, interests=[]),
        ]
    )

    candidates = await provider.fetch_candidates(interests=[])

    assert len(candidates) == 2
    assert all(c.source == "Feed A" for c in candidates)


async def test_no_matching_feeds_returns_empty() -> None:
    provider = _provider([FeedSource(name="Feed B", url=FEED_B_URL, interests=["sports"])])

    candidates = await provider.fetch_candidates(interests=["technology"])

    assert candidates == []


async def test_aggregator_style_entries_use_real_publisher_and_strip_title_suffix() -> None:
    provider = _provider(
        [FeedSource(name="Google News World", url=FEED_AGGREGATOR_URL, interests=[])]
    )

    candidates = await provider.fetch_candidates(interests=[])

    assert len(candidates) == 2
    first = next(c for c in candidates if "bike lane" in c.title)
    assert first.title == "City approves new bike lane network"
    assert first.source == "Local Gazette"
    # the feed name (our config label) is kept separately from the real publisher
    assert first.feed == "Google News World"


async def test_aggregator_style_entries_drop_fake_summary() -> None:
    provider = _provider(
        [FeedSource(name="Google News World", url=FEED_AGGREGATOR_URL, interests=[])]
    )

    candidates = await provider.fetch_candidates(interests=[])

    # the raw <description> is an HTML list of unrelated other-outlet
    # headlines, not a real excerpt - it must not leak through as if it were
    assert all(c.summary == "" for c in candidates)
    assert all("Other Outlet" not in c.summary for c in candidates)
