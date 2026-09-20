from __future__ import annotations

import asyncio
import logging

import httpx

from app.providers.base import WeatherProvider

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 1.0


class KnmiWeatherProvider(WeatherProvider):
    """Fetches the latest KNMI "short term weather forecast" bulletin - a
    free-text (Dutch) forecast for the Netherlands, published a few times a
    day - via the KNMI Data Platform Open Data API.

    This is retrieved source data, not a replacement for the structured,
    HA-supplied `SourceFacts.weather` - it exists purely to give the script
    provider real prose to ground the weather section in, instead of a bare
    `conditions` code that can be empty/generic (e.g. "mixed conditions").

    Best-effort: any failure (auth, network, empty dataset, unexpected
    response shape) is logged and surfaced as `None` rather than raised -
    one flaky upstream call should never block episode generation.
    """

    def __init__(
        self,
        api_key: str,
        dataset_name: str = "short_term_weather_forecast",
        dataset_version: str = "1.0",
        base_url: str = "https://api.dataplatform.knmi.nl/open-data/v1",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.dataset_name = dataset_name
        self.dataset_version = dataset_version
        self.base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        # No default Authorization header on the client itself: the KNMI API
        # key is only ever attached explicitly, per request, to the two
        # api.dataplatform.knmi.nl calls below - never to the pre-signed
        # temporary download URL, which is a different host and needs none.
        self.http_client = http_client or httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS
        )

    async def fetch_forecast_text(self) -> str | None:
        try:
            filename = await self._latest_filename()
            if filename is None:
                logger.warning(
                    "KNMI dataset %r has no files available", self.dataset_name
                )
                return None
            download_url = await self._download_url(filename)
            content = await self._download(download_url)
        except Exception:
            logger.exception("failed to fetch KNMI forecast bulletin")
            return None

        return self._decode(content).strip() or None

    async def _latest_filename(self) -> str | None:
        url = (
            f"{self.base_url}/datasets/{self.dataset_name}"
            f"/versions/{self.dataset_version}/files"
        )
        params = {"maxKeys": 1, "orderBy": "created", "sorting": "desc"}
        response = await self._get_with_retries(url, params=params, authenticated=True)
        payload = response.json()
        files = payload.get("files") or []
        if not files:
            return None
        return files[0].get("filename")

    async def _download_url(self, filename: str) -> str:
        url = (
            f"{self.base_url}/datasets/{self.dataset_name}"
            f"/versions/{self.dataset_version}/files/{filename}/url"
        )
        response = await self._get_with_retries(url, authenticated=True)
        return response.json()["temporaryDownloadUrl"]

    async def _download(self, download_url: str) -> bytes:
        # Pre-signed URL on a different host - deliberately not authenticated,
        # so our KNMI API key is never sent to it.
        response = await self._get_with_retries(download_url, authenticated=False)
        return response.content

    async def _get_with_retries(
        self, url: str, params: dict | None = None, authenticated: bool = False
    ) -> httpx.Response:
        headers = {"Authorization": self.api_key} if authenticated else None
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self.http_client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    logger.info(
                        "retrying KNMI request to %r after error (attempt %d/%d): %s",
                        url, attempt + 1, _MAX_RETRIES, exc,
                    )
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _decode(self, content: bytes) -> str:
        # KNMI's text bulletins are published as classic ISO-8859-1, not
        # UTF-8 - fall back rather than raising on Dutch diacritics.
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("iso-8859-1")

    async def aclose(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()
