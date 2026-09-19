# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Milestone 1 (mock-first vertical slice) is implemented: FastAPI service, typed Pydantic models, mock providers, an FFmpeg-based audio renderer, SQLite job storage, and atomic manifest/MP3 output — all runnable with zero paid API calls. `AGENTS.md` is the authoritative spec for what to build; read it in full before implementing further.

Real providers now built for all three swappable stages: `RssNewsProvider` (`config/feeds.json`, currently 4 Google News feeds - world/Dutch/Utrecht/technology), `OpenAIScriptProvider` (structured-output script generation, grounding validated post-hoc against supplied news candidates, bounded retry on incomplete output), and `OpenAITTSProvider` (`gpt-4o-mini-tts`, streamed WAV - see `app/providers/openai/`). The audio renderer normalizes every section's sample rate/channels before concatenation, since OpenAI's TTS output (24kHz mono) differs from the mock's (44.1kHz mono) - see `FFmpegAudioRenderer._normalize` in `app/audio/renderer.py`.

The news/script prompt has been tuned through live iteration (see `app/providers/openai/script.py`'s `_SYSTEM_PROMPT`): exactly 5 headlines, current-affairs-led with exactly one guaranteed technology story (via the feed name shown per candidate), no sports/celebrity filler, and the intro must never greet the listener's location as if it were a public audience (this is a single-listener podcast, not a city broadcast).

### Remaining work

Everything below is unbuilt or unverified as of this note - the generation pipeline itself (facts → news → script → TTS → assembled MP3 + manifest) is real and working end-to-end, verified against live feeds and the real OpenAI APIs.

1. **Home Assistant integration - the big remaining piece, nothing started.** No REST action/automation yet for HA to POST `source_facts` (weather + calendar + reminders) into this service on a schedule, and nothing built for HA to play the finished episode or handle generation-failure fallback. This was always meant to be the last phase (see Build order below) and is the natural next milestone.
2. **Real media directory wiring.** `docker-compose.yml` currently bind-mounts a local `./output` folder for testing - needs to point at wherever the target HA instance actually reads media from.
3. **Intro jingle implemented; still needs real-world listening verification.** `assets/music/intro.mp3` is a real wake-up jingle (generated manually via the ElevenLabs website - not a service dependency; contemporary piano/guitar/synth wake-up arc ending in a soft lo-fi beat lift, fading to silence). `FFmpegAudioRenderer` plays it once at full volume before narration; narration cuts in (no fade-in - the jingle's own build already leads into it) at a fixed cue point, `intro_jingle_narration_start_seconds` (default 29s, `GOODMORNING_INTRO_JINGLE_NARRATION_START_SECONDS`), timed specifically to where `intro.mp3`'s build resolves - not derived from the file's total length, so **a replacement jingle with a different structure needs this value re-tuned by ear**, via `GOODMORNING_INTRO_JINGLE_FILE` - see `FFmpegAudioRenderer._mix_and_encode` in `app/audio/renderer.py`. **Deliberately narration-only after the intro** - no bed, loop, or outro sting under weather/calendar/news/outro, since background music (especially anything upbeat) reads as tonally wrong under serious news. This has been exercised with a real jingle file and listened to end-to-end by the user. Still needed: an outro sting was considered and explicitly rejected in favor of narration-only, but that call could be revisited; no other stings/beds exist for other sections by design.

**Loudness normalization is two-pass, not single-pass.** `loudnorm`'s default single-pass mode applies an adaptive gain that hasn't converged yet at the start of a track, and was audibly over-boosting the jingle's quiet birdsong opening. Fixed by measuring the full mix first (`print_format=json`) then applying one fixed `linear=true` gain from those measured values - see `FFmpegAudioRenderer._render_two_pass_loudnorm`. Effectively-silent input (mock TTS placeholder audio, which the test suite uses) measures as `-inf` and skips normalization entirely rather than erroring.

**The end-of-episode fade-out needs a silent tail to fade into.** The narration concat previously ended exactly on the outro's last spoken word with no trailing silence, so the final `_FADE_SECONDS` fade-out was cutting into actual speech - audibly like the narrator getting cut off mid-sentence. Fixed by appending `_FADE_SECONDS` of silence after the last section in `FFmpegAudioRenderer._concat_narration`, so the fade lands entirely on that silent tail. Verified with a synthetic-tone render: full volume held right up to the outro's true end, fade only audible in the appended silence.
4. **No true ducking.** AGENTS.md calls for ducking specifically; what exists is a constant reduced bed volume for the whole track, not dynamic sidechain compression tied to when narration is actually speaking.
5. **Episode length isn't configurable.** Nothing passes a target duration to the script provider - it just generates whatever length comes out naturally (~60-80s observed so far).
6. **AI-voice disclosure isn't actually spoken to the listener.** It exists as a manifest field (`Manifest.voice_disclosure`) for record-keeping, but nothing currently surfaces it during playback (e.g. in the outro, or via an HA notification).
7. **No auth on the API.** Every `POST /episodes` triggers real OpenAI spend; there's no API key or access control yet. Fine behind Docker's internal network, worth locking down before it's reachable from anywhere less trusted.

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
