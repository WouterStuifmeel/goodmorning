from __future__ import annotations

import httpx
import pytest

from app.providers.knmi.forecast import KnmiWeatherProvider

BASE_URL = "https://api.dataplatform.knmi.nl/open-data/v1"
FILES_URL = (
    f"{BASE_URL}/datasets/short_term_weather_forecast/versions/1.0/files"
)
FILE_URL_URL = (
    f"{BASE_URL}/datasets/short_term_weather_forecast/versions/1.0"
    "/files/latest.txt/url"
)
DOWNLOAD_URL = "https://cdn.example.com/temporary/latest.txt?sig=abc"

BULLETIN_TEXT = "Vandaag wisselend bewolkt met kans op een bui, middagtemperatuur 15 graden."


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.providers.knmi.forecast._RETRY_BACKOFF_SECONDS", 0.0)


def _provider(handler) -> KnmiWeatherProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return KnmiWeatherProvider("test-api-key", http_client=client)


async def test_fetches_latest_bulletin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == FILE_URL_URL:
            assert request.headers["authorization"] == "test-api-key"
            return httpx.Response(200, json={"temporaryDownloadUrl": DOWNLOAD_URL})
        if str(request.url).startswith(FILES_URL):
            assert request.headers["authorization"] == "test-api-key"
            assert request.url.params["maxKeys"] == "1"
            assert request.url.params["orderBy"] == "created"
            assert request.url.params["sorting"] == "desc"
            return httpx.Response(200, json={"files": [{"filename": "latest.txt"}]})
        if str(request.url) == DOWNLOAD_URL:
            # Pre-signed download URL - must not carry our API key.
            assert "authorization" not in request.headers
            return httpx.Response(200, content=BULLETIN_TEXT.encode("utf-8"))
        raise AssertionError(f"unexpected request to {request.url}")

    provider = _provider(handler)

    text = await provider.fetch_forecast_text()

    assert text == BULLETIN_TEXT


async def test_decodes_latin1_fallback() -> None:
    latin1_text = "Zwaar bewolkt met kans op mist, weinig verandering."

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == FILE_URL_URL:
            return httpx.Response(200, json={"temporaryDownloadUrl": DOWNLOAD_URL})
        if str(request.url).startswith(FILES_URL):
            return httpx.Response(200, json={"files": [{"filename": "latest.txt"}]})
        if str(request.url) == DOWNLOAD_URL:
            return httpx.Response(200, content=latin1_text.encode("iso-8859-1"))
        raise AssertionError(f"unexpected request to {request.url}")

    provider = _provider(handler)

    text = await provider.fetch_forecast_text()

    assert text == latin1_text


async def test_returns_none_when_dataset_has_no_files() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(FILES_URL):
            return httpx.Response(200, json={"files": []})
        raise AssertionError(f"unexpected request to {request.url}")

    provider = _provider(handler)

    assert await provider.fetch_forecast_text() is None


async def test_returns_none_on_upstream_error_instead_of_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    provider = _provider(handler)

    assert await provider.fetch_forecast_text() is None
