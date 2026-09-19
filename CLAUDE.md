# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Milestone 1 (mock-first vertical slice) is implemented: FastAPI service, typed Pydantic models, mock providers, an FFmpeg-based audio renderer, SQLite job storage, and atomic manifest/MP3 output — all runnable with zero paid API calls. `AGENTS.md` is the authoritative spec for what to build; read it in full before implementing further.

Real providers now built for all three swappable stages: `RssNewsProvider` (`config/feeds.json`), `OpenAIScriptProvider` (structured-output script generation, grounding validated post-hoc against supplied news candidates), and `OpenAITTSProvider` (`gpt-4o-mini-tts`, streamed WAV - see `app/providers/openai/`). The audio renderer normalizes every section's sample rate/channels before concatenation, since OpenAI's TTS output (24kHz mono) differs from the mock's (44.1kHz mono) - see `FFmpegAudioRenderer._normalize` in `app/audio/renderer.py`. Not yet built: Home Assistant wiring (see MVP boundary below).

### Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                          # full suite, no network/paid calls
uvicorn app.main:app --reload   # serves on :8000; POST /episodes, GET /episodes/{id}, GET /health
```

Requires `ffmpeg`/`ffprobe` on PATH. Config is env-driven (see `app/config.py`), prefixed `GOODMORNING_` (e.g. `GOODMORNING_OUTPUT_DIR`, `GOODMORNING_DB_PATH`). Provider selection:
- `GOODMORNING_NEWS_PROVIDER`: `mock` (default) or `rss` (reads `config/feeds.json`, live network, no key needed)
- `GOODMORNING_SCRIPT_PROVIDER`: `mock` (default) or `openai` (needs `GOODMORNING_OPENAI_API_KEY`, real paid calls)
- `GOODMORNING_TTS_PROVIDER`: `mock` (default) or `openai` (needs `GOODMORNING_OPENAI_API_KEY`, real paid calls)

## What this is

A standalone Python HTTP API (packaged with Docker) that generates a fresh, personalized English "morning radio" podcast episode. Home Assistant owns scheduling, gathers trusted home/calendar/weather context, pushes it into this service, plays the finished episode, and handles fallback. The service does the generation.

## Generation pipeline

Home Assistant POSTs the episode context; the service does not hold a broad HA access token when the data can be supplied in the request. The pipeline:

1. Validate and persist structured source facts.
2. Retrieve news candidates from configured feeds, preserving source details.
3. Use OpenAI to select relevant stories and produce a structured English script **grounded only in the supplied facts**.
4. Generate separate `intro`, `weather`, `calendar`, `news`, `outro` narration files via OpenAI TTS (`gpt-4o-mini-tts`, configurable presenter voice).
5. Use FFmpeg to combine narration with reusable themes/music beds/stings — ducking, fades, consistent pauses, final loudness normalization.
6. Write a dated MP3 plus a machine-readable manifest into a Home Assistant-accessible media directory.

Generation is **asynchronous and idempotent**: retries must not duplicate paid work or output unless regeneration is explicitly forced. API surface starts with: start/retry generation, read job status and failures, get episode metadata + media path, report health.

## Hard constraints (easy to violate)

- **Never let the model invent** weather, appointments, reminders, or news details — the script is grounded strictly in supplied facts and retrieved source data.
- **No ElevenLabs dependency.** TTS is OpenAI.
- Keep script generation, speech generation, news retrieval, and audio rendering behind **small, swappable interfaces**.
- Use **typed, strictly-validated** request/response/script/manifest models.
- Preserve original facts, selected news sources, generated scripts, per-section status, and errors for debugging.
- **Tests must not make paid external calls by default** — use deterministic fixtures and fake providers.
- Make configurable: presenter voice, delivery instructions, episode length, interests, feeds, music assets, output directory. Disclose that the voice is AI-generated.
- Atomic output writes; timeouts, bounded retries, actionable logging. Credentials come from env/secrets, never the repo.

## Build order

Mock-first vertical slice that runs locally with **no paid API calls**: one end-to-end episode from fixture data with mock script + speech providers, assembled into a playable MP3 + manifest. Then wire in OpenAI script generation and TTS, then Home Assistant. Expand personalization and production audio only after that path is reliable. Do **not** start with a custom Home Assistant integration — use HA REST actions and its media directory first.
