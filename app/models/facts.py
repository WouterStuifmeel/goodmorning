from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class WeatherForecast(BaseModel):
    """A trusted weather forecast as supplied by Home Assistant. Never generated."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    high_c: float
    low_c: float
    conditions: str
    precipitation_chance: float | None = Field(default=None, ge=0, le=100)
    rain_timing: str | None = Field(
        default=None,
        description=(
            "Free-text description of when rain is expected and of what kind, "
            "e.g. 'showers in the morning, thunderstorms in the evening'. "
            "May name multiple, non-contiguous parts of the day."
        ),
    )
    wind_kph: float | None = None
    wind_direction: str | None = None


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    start: datetime
    end: datetime | None = None
    location: str | None = None
    all_day: bool = False


class Reminder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    due: datetime | None = None


class SourceFacts(BaseModel):
    """The full set of trusted facts Home Assistant supplies for one episode.

    Grounds the entire script: nothing outside this model (plus retrieved
    news candidates) may be narrated.
    """

    model_config = ConfigDict(extra="forbid")

    episode_date: date
    location: str
    weather: WeatherForecast
    calendar_events: list[CalendarEvent] = Field(default_factory=list)
    reminders: list[Reminder] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
