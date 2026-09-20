from __future__ import annotations

from app.models.facts import SourceFacts
from app.models.news import NewsCandidate
from app.models.script import Script, ScriptSection
from app.providers.base import ScriptProvider

_MAX_NEWS_STORIES = 4


class MockScriptProvider(ScriptProvider):
    """Builds a script from simple templates, strictly grounded in the given
    facts and news candidates - no model call, fully deterministic.
    """

    async def generate_script(
        self, facts: SourceFacts, news_candidates: list[NewsCandidate]
    ) -> Script:
        selected_news = news_candidates[:_MAX_NEWS_STORIES]

        sections = [
            ScriptSection(
                section="intro",
                text=(
                    f"Good morning! Here's your update for "
                    f"{facts.episode_date.strftime('%A, %B %-d')} in {facts.location}."
                ),
            ),
            ScriptSection(section="weather", text=self._weather_text(facts)),
            ScriptSection(section="calendar", text=self._calendar_text(facts)),
            ScriptSection(
                section="news",
                text=self._news_text(selected_news),
                grounded_sources=[c.url for c in selected_news],
            ),
            ScriptSection(
                section="outro",
                text="That's your morning update. Have a great day.",
            ),
        ]
        return Script(sections=sections)

    def _weather_text(self, facts: SourceFacts) -> str:
        w = facts.weather
        parts = [
            f"Today's forecast: {w.summary}, with a high of {w.high_c:.0f} "
            f"and a low of {w.low_c:.0f} degrees. Conditions: {w.conditions}."
        ]
        if w.precipitation_chance is not None:
            parts.append(f"Chance of precipitation: {w.precipitation_chance:.0f} percent.")
            if w.rain_timing:
                parts.append(f"Expect {w.rain_timing}.")
        if w.wind_kph is not None:
            direction = f" from the {w.wind_direction}" if w.wind_direction else ""
            parts.append(f"Wind: {w.wind_kph:.0f} kph{direction}.")
        return " ".join(parts)

    def _calendar_text(self, facts: SourceFacts) -> str:
        if not facts.calendar_events and not facts.reminders:
            return "You have no appointments or reminders on the calendar today."
        lines = []
        for event in facts.calendar_events:
            when = "all day" if event.all_day else event.start.strftime("%-I:%M %p")
            lines.append(f"{event.title} at {when}.")
        for reminder in facts.reminders:
            lines.append(f"Reminder: {reminder.text}.")
        return " ".join(lines)

    def _news_text(self, selected_news: list[NewsCandidate]) -> str:
        if not selected_news:
            return "There are no news stories to share this morning."
        lines = [f"{c.title}. {c.summary} ({c.source})." for c in selected_news]
        return " ".join(lines)
