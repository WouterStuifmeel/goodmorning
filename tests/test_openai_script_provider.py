from __future__ import annotations

import httpx
import openai
import pytest

from app.providers.openai.script import (
    OpenAIScriptProvider,
    ScriptGenerationError,
    _LLMScriptOutput,
    _LLMScriptSection,
)


class _FakeMessage:
    def __init__(self, parsed=None, refusal=None):
        self.parsed = parsed
        self.refusal = refusal


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeCompletion:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class _FakeCompletions:
    def __init__(self, result_or_exc):
        self._result_or_exc = result_or_exc
        self.last_call_kwargs: dict | None = None
        self.call_count = 0

    async def parse(self, **kwargs):
        self.call_count += 1
        self.last_call_kwargs = kwargs
        if isinstance(self._result_or_exc, BaseException):
            raise self._result_or_exc
        return self._result_or_exc


class _SequenceFakeCompletions:
    """Returns a different result_or_exc on each successive call."""

    def __init__(self, results_or_excs: list) -> None:
        self._results_or_excs = results_or_excs
        self.call_count = 0

    async def parse(self, **kwargs):
        result = self._results_or_excs[self.call_count]
        self.call_count += 1
        if isinstance(result, BaseException):
            raise result
        return result


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


def _make_provider(result_or_exc) -> tuple[OpenAIScriptProvider, _FakeCompletions]:
    completions = _FakeCompletions(result_or_exc)
    client = _FakeClient(completions)
    return OpenAIScriptProvider(client), completions  # type: ignore[arg-type]


def _make_sequence_provider(
    results_or_excs: list,
) -> tuple[OpenAIScriptProvider, _SequenceFakeCompletions]:
    completions = _SequenceFakeCompletions(results_or_excs)
    client = _FakeClient(completions)
    return OpenAIScriptProvider(client), completions  # type: ignore[arg-type]


def _valid_llm_output(news_indices: list[int]) -> _LLMScriptOutput:
    return _LLMScriptOutput(
        sections=[
            _LLMScriptSection(section="intro", text="Good morning."),
            _LLMScriptSection(section="weather", text="Sunny today."),
            _LLMScriptSection(section="calendar", text="No events today."),
            _LLMScriptSection(
                section="news", text="Here's the news.", grounded_source_indices=news_indices
            ),
            _LLMScriptSection(section="outro", text="Have a great day."),
        ]
    )


async def test_valid_output_produces_grounded_script(source_facts) -> None:
    from app.models.news import NewsCandidate

    candidates = [
        NewsCandidate(
            title="Story one",
            summary="Summary one",
            source="Source A",
            url="https://example.com/one",
            feed="general",
        ),
        NewsCandidate(
            title="Story two",
            summary="Summary two",
            source="Source B",
            url="https://example.com/two",
            feed="general",
        ),
    ]
    message = _FakeMessage(parsed=_valid_llm_output([0, 1]))
    provider, completions = _make_provider(_FakeCompletion(message))

    script = await provider.generate_script(source_facts, candidates)

    news_section = next(s for s in script.sections if s.section == "news")
    assert {str(u) for u in news_section.grounded_sources} == {
        "https://example.com/one",
        "https://example.com/two",
    }
    assert completions.last_call_kwargs["model"] == "gpt-4o-mini"


async def test_missing_section_raises(source_facts) -> None:
    incomplete = _LLMScriptOutput(
        sections=[
            _LLMScriptSection(section="intro", text="Good morning."),
            _LLMScriptSection(section="weather", text="Sunny."),
            _LLMScriptSection(section="calendar", text="No events."),
            _LLMScriptSection(section="news", text="News."),
            # outro missing
        ]
    )
    message = _FakeMessage(parsed=incomplete)
    provider, _ = _make_provider(_FakeCompletion(message))

    with pytest.raises(ScriptGenerationError, match="expected exactly"):
        await provider.generate_script(source_facts, [])


async def test_invalid_news_index_raises(source_facts) -> None:
    output = _valid_llm_output(news_indices=[5])  # no candidates supplied at all
    message = _FakeMessage(parsed=output)
    provider, _ = _make_provider(_FakeCompletion(message))

    with pytest.raises(ScriptGenerationError, match="invalid news candidate index"):
        await provider.generate_script(source_facts, [])


async def test_refusal_raises(source_facts) -> None:
    message = _FakeMessage(parsed=None, refusal="cannot comply")
    provider, _ = _make_provider(_FakeCompletion(message))

    with pytest.raises(ScriptGenerationError, match="refusal"):
        await provider.generate_script(source_facts, [])


async def test_openai_error_is_wrapped(source_facts) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    provider, _ = _make_provider(openai.APIConnectionError(request=request))

    with pytest.raises(ScriptGenerationError, match="OpenAI request failed"):
        await provider.generate_script(source_facts, [])


async def test_retries_and_recovers_after_incomplete_first_response(source_facts) -> None:
    incomplete = _LLMScriptOutput(
        sections=[
            _LLMScriptSection(section="intro", text="Good morning."),
            _LLMScriptSection(section="weather", text="Sunny."),
            _LLMScriptSection(section="calendar", text="No events."),
            _LLMScriptSection(section="news", text="News."),
            # outro missing on the first attempt
        ]
    )
    complete = _valid_llm_output([])
    provider, completions = _make_sequence_provider(
        [_FakeCompletion(_FakeMessage(parsed=incomplete)), _FakeCompletion(_FakeMessage(parsed=complete))]
    )

    script = await provider.generate_script(source_facts, [])

    assert completions.call_count == 2
    assert {s.section for s in script.sections} == {
        "intro", "weather", "calendar", "news", "outro",
    }


async def test_gives_up_after_exhausting_retries(source_facts) -> None:
    incomplete = _LLMScriptOutput(
        sections=[_LLMScriptSection(section="intro", text="Good morning.")]
    )
    provider, completions = _make_provider(_FakeCompletion(_FakeMessage(parsed=incomplete)))

    with pytest.raises(ScriptGenerationError, match="expected exactly"):
        await provider.generate_script(source_facts, [])

    assert completions.call_count == 3  # 1 initial attempt + 2 retries


async def test_transport_error_does_not_retry(source_facts) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    provider, completions = _make_provider(openai.APIConnectionError(request=request))

    with pytest.raises(ScriptGenerationError, match="OpenAI request failed"):
        await provider.generate_script(source_facts, [])

    assert completions.call_count == 1


async def test_empty_news_candidates_allows_empty_grounding(source_facts) -> None:
    output = _valid_llm_output(news_indices=[])
    message = _FakeMessage(parsed=output)
    provider, _ = _make_provider(_FakeCompletion(message))

    script = await provider.generate_script(source_facts, [])

    news_section = next(s for s in script.sections if s.section == "news")
    assert news_section.grounded_sources == []
