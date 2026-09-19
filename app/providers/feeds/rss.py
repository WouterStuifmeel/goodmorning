from __future__ import annotations

import asyncio
import logging
import re
from calendar import timegm
from datetime import UTC, datetime

import feedparser
import httpx

from app.models.news import NewsCandidate
from app.providers.base import NewsProvider
from app.providers.feeds.config import FeedSource, FeedsConfig

logger = logging.getLogger(__name__)

_MAX_ITEMS_PER_FEED = 8
_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 1.0
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_EPOCH = datetime.min.replace(tzinfo=UTC)


class RssNewsProvider(NewsProvider):
    """Fetches candidate stories from configured RSS/Atom feeds.

    Feeds relevant to the requested interests (plus any general feed with no
    interest tags) are fetched concurrently. A feed that fails after retries
    is logged and skipped rather than failing the whole retrieval - one dead
    feed should never block episode generation.
    """

    def __init__(
        self,
        feeds_config: FeedsConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.feeds_config = feeds_config
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "goodmorning-podcast/0.1 (+news retrieval)"},
            follow_redirects=True,
        )

    async def fetch_candidates(self, interests: list[str]) -> list[NewsCandidate]:
        feeds = self._select_feeds(interests)
        if not feeds:
            logger.warning("no configured feeds matched interests=%r", interests)
            return []

        results = await asyncio.gather(
            *(self._fetch_feed(f) for f in feeds), return_exceptions=True
        )

        candidates: list[NewsCandidate] = []
        for feed, result in zip(feeds, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("skipping feed %r after failure: %s", feed.name, result)
                continue
            candidates.extend(result)

        # No importance ranking here beyond recency - which stories are
        # actually worth including is left entirely to the script provider's
        # own judgment, given the listener's stated interests.
        candidates.sort(key=lambda c: c.published_at or _EPOCH, reverse=True)
        return candidates

    def _select_feeds(self, interests: list[str]) -> list[FeedSource]:
        wanted = {i.lower() for i in interests}
        return [
            f
            for f in self.feeds_config.feeds
            if not f.interests or wanted & {i.lower() for i in f.interests}
        ]

    async def _fetch_feed(self, feed: FeedSource) -> list[NewsCandidate]:
        content = await self._fetch_with_retries(feed)
        parsed = feedparser.parse(content)
        candidates = []
        for entry in parsed.entries[:_MAX_ITEMS_PER_FEED]:
            link = entry.get("link")
            if not link:
                continue

            title = self._clean_html(entry.get("title", ""))
            aggregator_source = entry.get("source")
            if aggregator_source and aggregator_source.get("title"):
                # Google News-style aggregator entry: the real publisher name
                # is in entry.source, and the title is suffixed with it
                # (e.g. "Headline - NOS") - strip the redundant suffix. The
                # entry's own "summary" is not an article excerpt here, just
                # an HTML list of other outlets' headlines for the same
                # story, so it's dropped rather than fed to the model as if
                # it were real content.
                publisher = aggregator_source["title"]
                title = self._strip_source_suffix(title, publisher)
                summary = ""
            else:
                publisher = feed.name
                summary = self._clean_html(entry.get("summary", ""))

            candidates.append(
                NewsCandidate(
                    title=title,
                    summary=summary,
                    source=publisher,
                    url=link,
                    feed=feed.name,
                    published_at=self._parse_published(entry),
                )
            )
        return candidates

    async def _fetch_with_retries(self, feed: FeedSource) -> bytes:
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self.http_client.get(str(feed.url))
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    logger.info(
                        "retrying feed %r after error (attempt %d/%d): %s",
                        feed.name, attempt + 1, _MAX_RETRIES, exc,
                    )
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _clean_html(self, text: str) -> str:
        return _HTML_TAG_RE.sub("", text).strip()

    def _strip_source_suffix(self, title: str, publisher: str) -> str:
        suffix = f" - {publisher}"
        if title.endswith(suffix):
            return title[: -len(suffix)]
        return title

    def _parse_published(self, entry: dict) -> datetime | None:
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if struct is None:
            return None
        return datetime.fromtimestamp(timegm(struct), tz=UTC)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()
