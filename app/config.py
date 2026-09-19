from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOODMORNING_", env_file=".env")

    # Where the dated MP3 + manifest are written - point this at the Home
    # Assistant media directory in deployment.
    output_dir: Path = Path("./output")
    db_path: Path = Path("./data/jobs.sqlite3")

    presenter_voice: str = "alloy"
    delivery_instructions: str = (
        "Warm, calm morning-radio delivery: gentle at the start, gradually "
        "brighter, natural pacing, concise."
    )
    music_bed_file: Path | None = None
    feeds_config_path: Path = Path("./config/feeds.json")

    # Provider selection: "mock" (default, no paid calls) or "openai".
    script_provider: str = "mock"
    tts_provider: str = "mock"
    # News provider: "mock" (default, no network) or "rss" (live feeds,
    # configured via feeds_config_path - free, but not deterministic).
    news_provider: str = "mock"

    openai_api_key: str | None = None
    openai_script_model: str = "gpt-4o-mini"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_request_timeout_seconds: float = 30.0
    openai_max_retries: int = 2


def get_settings() -> Settings:
    return Settings()
