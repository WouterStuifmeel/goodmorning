from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.audio.renderer import FFmpegAudioRenderer
from app.models.job import JobState, SectionState
from app.pipeline.orchestrator import Pipeline, new_job
from app.providers.mock import (
    MockNewsProvider,
    MockScriptProvider,
    MockTTSProvider,
    MockWeatherProvider,
)
from app.storage.db import JobStore


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    job_store = JobStore(tmp_path / "jobs.sqlite3")
    return Pipeline(
        news_provider=MockNewsProvider(),
        weather_provider=MockWeatherProvider(),
        script_provider=MockScriptProvider(),
        tts_provider=MockTTSProvider(),
        audio_renderer=FFmpegAudioRenderer(intro_jingle_file=None),
        job_store=job_store,
        output_dir=tmp_path / "output",
        voice="alloy",
    )


async def test_full_pipeline_produces_playable_episode(pipeline, source_facts, tmp_path):
    job = new_job(source_facts)

    result = await pipeline.run(job)

    assert result.state == JobState.completed
    assert result.error is None
    assert all(s == SectionState.completed for s in result.section_states.values())

    manifest = result.manifest
    assert manifest is not None
    assert manifest.episode_date == source_facts.episode_date
    assert manifest.source_facts == source_facts
    assert len(manifest.sections) == 5
    assert manifest.weather_forecast_text

    mp3_path = tmp_path / "output" / manifest.audio_file
    assert mp3_path.exists()
    assert mp3_path.stat().st_size > 0

    manifest_path = tmp_path / "output" / f"{manifest.episode_id}.manifest.json"
    assert manifest_path.exists()
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk["episode_id"] == manifest.episode_id


async def test_pipeline_grounds_news_section_in_selected_sources(pipeline, source_facts):
    job = new_job(source_facts)

    result = await pipeline.run(job)

    news_section = next(s for s in result.manifest.script.sections if s.section == "news")
    assert news_section.grounded_sources
    selected_urls = {str(c.url) for c in result.manifest.selected_news}
    assert all(str(u) in selected_urls for u in news_section.grounded_sources)


async def test_pipeline_never_invents_calendar_events(pipeline, source_facts):
    job = new_job(source_facts)

    result = await pipeline.run(job)

    calendar_section = next(
        s for s in result.manifest.script.sections if s.section == "calendar"
    )
    for event in source_facts.calendar_events:
        assert event.title in calendar_section.text
    for reminder in source_facts.reminders:
        assert reminder.text in calendar_section.text


async def test_pipeline_survives_weather_provider_failure(tmp_path, source_facts):
    class _FailingWeatherProvider(MockWeatherProvider):
        async def fetch_forecast_text(self) -> str | None:
            raise RuntimeError("KNMI is down")

    job_store = JobStore(tmp_path / "jobs.sqlite3")
    pipeline = Pipeline(
        news_provider=MockNewsProvider(),
        weather_provider=_FailingWeatherProvider(),
        script_provider=MockScriptProvider(),
        tts_provider=MockTTSProvider(),
        audio_renderer=FFmpegAudioRenderer(intro_jingle_file=None),
        job_store=job_store,
        output_dir=tmp_path / "output",
        voice="alloy",
    )
    job = new_job(source_facts)

    result = await pipeline.run(job)

    assert result.state == JobState.completed
    assert result.manifest.weather_forecast_text is None
