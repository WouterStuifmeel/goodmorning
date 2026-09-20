from __future__ import annotations

import logging

import openai
from pydantic import BaseModel, ConfigDict, Field

from app.models.facts import SourceFacts
from app.models.news import NewsCandidate
from app.models.script import SECTION_ORDER, Script, ScriptSection, SectionName
from app.providers.base import ScriptProvider

logger = logging.getLogger(__name__)

_MAX_NEWS_CANDIDATES_SHOWN = 25
# The model occasionally returns syntactically valid structured output that
# simply omits a required section (e.g. drops "outro") - the JSON schema
# constrains each section object's shape but can't force exactly five
# distinct section values to appear. Retrying is cheap and reliably recovers.
_MAX_VALIDATION_RETRIES = 2

_SYSTEM_PROMPT = """\
You are the presenter for a short, calm morning-radio podcast made for one \
specific listener - not a public broadcast for a city or region. Your tone \
is warm at the start, gradually brighter, natural, concise, and useful.

You must write exactly five narration sections: intro, weather, calendar, \
news, outro.

Hard rules:
- This is a personal podcast for one listener. Never greet or address the \
listener's location as if it were the audience (e.g. do not say "Good \
morning, Utrecht!" or otherwise speak to the city/region by name). The \
location is only context for the weather and local news - address the \
listener directly and generically instead (e.g. "Good morning!").
- Use ONLY the facts given to you below. Never invent weather details, \
appointments, reminders, or news stories that are not explicitly supplied.
- For the news section, select exactly 5 stories from the numbered \
candidate list given to you, and report their indices in \
grounded_source_indices. Give the listener a real headline roundup, not \
just the single most recent item. Only select fewer than 5 if there are \
genuinely fewer than 5 candidates in the whole list that are remotely \
interesting to this listener - never pad with irrelevant stories just to \
hit the count.
- Lead with current affairs: prioritize major world, national, and local \
news over other categories. Always include exactly one technology story - \
pick the most significant one available, even if none are standout - as \
long as at least one candidate tagged as technology appears in the list \
below. If there are genuinely no technology candidates in the list, five \
current-affairs stories is fine instead. Never include more than one \
technology story. This is a current-affairs briefing first, not a tech \
roundup.
- Use your own judgment of newsworthiness and, above all, relevance to this \
specific listener's stated interests below. The candidate list is pulled \
from general news feeds as well as interest-specific ones, so it will \
contain plenty of stories that don't belong in this listener's episode - \
routine sports results, celebrity gossip, and similar filler should be \
skipped unless one of the listener's stated interests actually covers that \
topic. When in doubt, favor genuine relevance to the listener over raw \
prominence in the news cycle.
- Do not reference or describe any news story that is not in the candidate \
list.
- If there are no calendar events or reminders, say so plainly - do not \
invent any.
- Keep each section brief and spoken-friendly (no bullet points, no markdown).
"""


class _LLMScriptSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: SectionName
    text: str
    grounded_source_indices: list[int] = Field(
        default_factory=list,
        description=(
            "Indices into the numbered news candidate list this section's "
            "text is grounded in. Leave empty for all sections except news."
        ),
    )


class _LLMScriptOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[_LLMScriptSection]


class ScriptGenerationError(Exception):
    """Raised when the model output can't be trusted as grounded."""


class OpenAIScriptProvider(ScriptProvider):
    """Uses OpenAI structured outputs to select relevant news and write a
    script strictly grounded in the supplied facts and candidates.

    Grounding is enforced two ways: the prompt instructs the model to use
    only the given facts, and the news section's sources are validated
    against the actual candidate list post-hoc - any reference to a
    candidate index that wasn't supplied is treated as a hard failure
    rather than silently trusted.
    """

    def __init__(
        self,
        client: openai.AsyncOpenAI,
        model: str = "gpt-4o-mini",
        delivery_instructions: str = "",
    ) -> None:
        self.client = client
        self.model = model
        self.delivery_instructions = delivery_instructions

    async def generate_script(
        self,
        facts: SourceFacts,
        news_candidates: list[NewsCandidate],
        weather_forecast_text: str | None = None,
    ) -> Script:
        shown_candidates = news_candidates[:_MAX_NEWS_CANDIDATES_SHOWN]
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": self._user_prompt(
                    facts, shown_candidates, weather_forecast_text
                ),
            },
        ]

        last_error: ScriptGenerationError | None = None
        for attempt in range(_MAX_VALIDATION_RETRIES + 1):
            try:
                completion = await self.client.chat.completions.parse(
                    model=self.model,
                    messages=messages,
                    response_format=_LLMScriptOutput,
                )
            except openai.OpenAIError as exc:
                raise ScriptGenerationError(f"OpenAI request failed: {exc}") from exc

            parsed = completion.choices[0].message.parsed
            if parsed is None:
                refusal = completion.choices[0].message.refusal
                last_error = ScriptGenerationError(
                    f"model did not return structured output (refusal: {refusal!r})"
                )
            else:
                try:
                    return self._to_script(parsed, shown_candidates)
                except ScriptGenerationError as exc:
                    last_error = exc

            if attempt < _MAX_VALIDATION_RETRIES:
                logger.warning(
                    "script generation attempt %d/%d invalid, retrying: %s",
                    attempt + 1, _MAX_VALIDATION_RETRIES + 1, last_error,
                )

        assert last_error is not None
        raise last_error

    def _system_prompt(self) -> str:
        if not self.delivery_instructions:
            return _SYSTEM_PROMPT
        return f"{_SYSTEM_PROMPT}\nDelivery instructions: {self.delivery_instructions}"

    def _user_prompt(
        self,
        facts: SourceFacts,
        candidates: list[NewsCandidate],
        weather_forecast_text: str | None,
    ) -> str:
        lines = [
            f"Date: {facts.episode_date.isoformat()}",
            f"Location: {facts.location}",
            "",
            "Weather:",
            f"  Summary: {facts.weather.summary}",
            f"  High: {facts.weather.high_c:.0f}C, Low: {facts.weather.low_c:.0f}C",
            f"  Conditions: {facts.weather.conditions}",
        ]
        if facts.weather.precipitation_chance is not None:
            lines.append(
                f"  Precipitation chance: {facts.weather.precipitation_chance:.0f}%"
            )
            if facts.weather.rain_timing:
                lines.append(f"  Rain timing: {facts.weather.rain_timing}")
        if facts.weather.wind_kph is not None:
            direction = (
                f" from the {facts.weather.wind_direction}"
                if facts.weather.wind_direction
                else ""
            )
            lines.append(f"  Wind: {facts.weather.wind_kph:.0f} kph{direction}")
        if weather_forecast_text:
            lines.append(
                "  Additional official forecast bulletin (KNMI, in Dutch - use "
                "this only to add real texture/context to the weather section "
                "in English, e.g. cloud development or how conditions change "
                "through the day; the numbers above remain authoritative if "
                "they conflict with anything below):"
            )
            lines.append(f"    {weather_forecast_text}")

        lines.append("")
        lines.append("Calendar events:")
        if facts.calendar_events:
            for event in facts.calendar_events:
                when = "all day" if event.all_day else event.start.isoformat()
                loc = f" at {event.location}" if event.location else ""
                lines.append(f"  - {event.title} ({when}){loc}")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("Reminders:")
        if facts.reminders:
            for reminder in facts.reminders:
                due = f" (due {reminder.due.isoformat()})" if reminder.due else ""
                lines.append(f"  - {reminder.text}{due}")
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append(f"Listener interests: {', '.join(facts.interests) or '(none specified)'}")

        lines.append("")
        lines.append(
            "Candidate news stories, most recent first (reference by index only). "
            "\"feed\" names the configured feed the story came from - a feed name "
            "containing \"Technology\" marks a technology story:"
        )
        if candidates:
            for i, c in enumerate(candidates):
                summary_part = f" - {c.summary}" if c.summary else ""
                lines.append(
                    f"  [{i}] {c.title}{summary_part} (source: {c.source}, feed: {c.feed})"
                )
        else:
            lines.append("  (none available)")

        return "\n".join(lines)

    def _to_script(
        self, parsed: _LLMScriptOutput, candidates: list[NewsCandidate]
    ) -> Script:
        by_name = {s.section: s for s in parsed.sections}
        missing = [s for s in SECTION_ORDER if s not in by_name]
        if missing or len(parsed.sections) != len(SECTION_ORDER):
            raise ScriptGenerationError(
                f"model returned sections {list(by_name)}, expected exactly {list(SECTION_ORDER)}"
            )

        sections: list[ScriptSection] = []
        for name in SECTION_ORDER:
            llm_section = by_name[name]
            grounded_sources = []
            if name == "news":
                for idx in llm_section.grounded_source_indices:
                    if idx < 0 or idx >= len(candidates):
                        raise ScriptGenerationError(
                            f"model referenced invalid news candidate index {idx} "
                            f"(only {len(candidates)} candidates were supplied)"
                        )
                    grounded_sources.append(candidates[idx].url)
            sections.append(
                ScriptSection(
                    section=name, text=llm_section.text, grounded_sources=grounded_sources
                )
            )

        return Script(sections=sections)
