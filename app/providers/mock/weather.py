from __future__ import annotations

from app.providers.base import WeatherProvider

_FIXTURE_FORECAST_TEXT = (
    "Vandaag overwegend bewolkt met kans op enkele buien in de middag. "
    "Middagtemperatuur rond 14 graden, matige westenwind."
)


class MockWeatherProvider(WeatherProvider):
    """Returns a fixture forecast bulletin. Deterministic and offline - used
    for the mock-first vertical slice and tests.
    """

    async def fetch_forecast_text(self) -> str | None:
        return _FIXTURE_FORECAST_TEXT
