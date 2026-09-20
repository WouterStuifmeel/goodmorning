from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import openai
from fastapi import FastAPI

from app.api.routes import router
from app.audio.renderer import FFmpegAudioRenderer
from app.config import Settings, get_settings
from app.pipeline.orchestrator import Pipeline
from app.providers.base import (
    AudioRenderer,
    NewsProvider,
    ScriptProvider,
    TTSProvider,
    WeatherProvider,
)
from app.providers.feeds import RssNewsProvider, load_feeds_config
from app.providers.knmi import KnmiWeatherProvider
from app.providers.mock import (
    MockNewsProvider,
    MockScriptProvider,
    MockTTSProvider,
    MockWeatherProvider,
)
from app.providers.openai import OpenAIScriptProvider, OpenAITTSProvider
from app.storage.db import JobStore


def _openai_client(settings: Settings) -> openai.AsyncOpenAI:
    if not settings.openai_api_key:
        raise ValueError(
            "GOODMORNING_OPENAI_API_KEY is required when an openai provider is selected"
        )
    return openai.AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_request_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def _build_news_provider(settings: Settings) -> NewsProvider:
    if settings.news_provider == "mock":
        return MockNewsProvider()
    if settings.news_provider == "rss":
        feeds_config = load_feeds_config(settings.feeds_config_path)
        return RssNewsProvider(feeds_config)
    raise ValueError(
        f"unknown or not-yet-implemented news provider: {settings.news_provider!r}"
    )


def _build_weather_provider(settings: Settings) -> WeatherProvider:
    if settings.weather_provider == "mock":
        return MockWeatherProvider()
    if settings.weather_provider == "knmi":
        if not settings.knmi_api_key:
            raise ValueError(
                "GOODMORNING_KNMI_API_KEY is required when the knmi weather "
                "provider is selected"
            )
        return KnmiWeatherProvider(
            settings.knmi_api_key,
            dataset_name=settings.knmi_dataset_name,
            dataset_version=settings.knmi_dataset_version,
        )
    raise ValueError(
        f"unknown or not-yet-implemented weather provider: {settings.weather_provider!r}"
    )


def _build_script_provider(
    settings: Settings, openai_client: openai.AsyncOpenAI | None
) -> ScriptProvider:
    if settings.script_provider == "mock":
        return MockScriptProvider()
    if settings.script_provider == "openai":
        assert openai_client is not None
        return OpenAIScriptProvider(
            openai_client,
            model=settings.openai_script_model,
            delivery_instructions=settings.delivery_instructions,
        )
    raise ValueError(
        f"unknown or not-yet-implemented script provider: {settings.script_provider!r}"
    )


def _build_tts_provider(
    settings: Settings, openai_client: openai.AsyncOpenAI | None
) -> TTSProvider:
    if settings.tts_provider == "mock":
        return MockTTSProvider()
    if settings.tts_provider == "openai":
        assert openai_client is not None
        return OpenAITTSProvider(
            openai_client,
            model=settings.openai_tts_model,
            delivery_instructions=settings.delivery_instructions,
        )
    raise ValueError(
        f"unknown or not-yet-implemented TTS provider: {settings.tts_provider!r}"
    )


def _build_audio_renderer(settings: Settings) -> AudioRenderer:
    return FFmpegAudioRenderer(
        intro_jingle_file=settings.intro_jingle_file,
        narration_start_seconds=settings.intro_jingle_narration_start_seconds,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    job_store = JobStore(settings.db_path)
    news_provider = _build_news_provider(settings)
    weather_provider = _build_weather_provider(settings)

    needs_openai = "openai" in (settings.script_provider, settings.tts_provider)
    openai_client = _openai_client(settings) if needs_openai else None

    pipeline = Pipeline(
        news_provider=news_provider,
        weather_provider=weather_provider,
        script_provider=_build_script_provider(settings, openai_client),
        tts_provider=_build_tts_provider(settings, openai_client),
        audio_renderer=_build_audio_renderer(settings),
        job_store=job_store,
        output_dir=settings.output_dir,
        voice=settings.presenter_voice,
    )

    app.state.settings = settings
    app.state.job_store = job_store
    app.state.pipeline = pipeline
    yield

    if isinstance(news_provider, RssNewsProvider):
        await news_provider.aclose()
    if isinstance(weather_provider, KnmiWeatherProvider):
        await weather_provider.aclose()
    if openai_client is not None:
        await openai_client.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Good Morning Podcast", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
