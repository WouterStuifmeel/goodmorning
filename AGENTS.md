# Good Morning Podcast

## What this project should become

Build a small, reliable service that creates a fresh, personalized English morning podcast for playback through Home Assistant. The show should feel like calm morning radio rather than a long smart-speaker announcement: gentle at the start, gradually brighter, natural, concise, and useful.

Each episode should contain:

- A short introduction and date.
- A practical local weather forecast.
- Calendar appointments and useful reminders.
- A small selection of relevant news stories based on configured interests.
- A brief recap and outro.

Home Assistant remains responsible for wake-up scheduling, collecting trusted home/calendar/weather context, starting generation, playing the finished episode, and falling back gracefully when generation fails.

## Target architecture

Implement a standalone Python HTTP API packaged with Docker. Home Assistant should push the context needed for an episode into this service; avoid giving the service a broad Home Assistant access token when data can be supplied in the request.

The generation pipeline should be:

1. Validate and persist the structured source facts.
2. Retrieve news candidates from configured feeds and preserve their source details.
3. Use OpenAI to select relevant stories and produce a structured English script grounded only in the supplied facts.
4. Generate separate `intro`, `weather`, `calendar`, `news`, and `outro` narration files with OpenAI text-to-speech, initially using `gpt-4o-mini-tts` and a configurable presenter voice. Do not introduce an ElevenLabs dependency.
5. Use FFmpeg to combine narration with reusable themes, music beds, and stings. Support ducking, fades, consistent pauses, and final loudness normalization.
6. Write a dated MP3 plus a machine-readable manifest into a Home Assistant-accessible media directory.

Start with API capabilities to start or retry generation, read job status and failures, retrieve episode metadata and its media path, and report service health. Generation should be asynchronous and idempotent so retries do not duplicate paid work or output unless regeneration is explicitly forced.

## Implementation approach

- Build a mock-first vertical slice that works locally without paid API calls.
- Keep script generation, speech generation, news retrieval, and audio rendering behind small interfaces.
- Use typed request, response, script, and manifest models with strict validation.
- Preserve original facts, selected news sources, generated scripts, section status, and errors for debugging.
- Never allow the model to invent weather, appointments, reminders, or news details.
- Make the presenter voice, delivery instructions, episode length, interests, feeds, music assets, and output directory configurable.
- Clearly disclose that the presenter voice is AI-generated.
- Ensure tests use deterministic fixtures and fake providers; tests must not make paid external calls by default.
- Add timeouts, bounded retries, actionable logging, and atomic output writes.
- Keep credentials out of the repository and load them from environment variables or deployment secrets.

## MVP boundary

The first milestone is one end-to-end episode generated from fixture data with mock script and speech providers, assembled into a playable MP3 with a manifest. Then connect OpenAI script generation and TTS, followed by Home Assistant. Expand personalization and production-style audio only after that path is reliable.

Do not begin with a custom Home Assistant integration. Use Home Assistant REST actions and its media directory first; package the service as a Home Assistant app later if that materially improves deployment.
