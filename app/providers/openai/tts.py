from __future__ import annotations

from pathlib import Path

import openai

from app.models.script import SectionName
from app.providers.base import TTSProvider


class TTSGenerationError(Exception):
    """Raised when OpenAI speech synthesis fails for a section."""


class OpenAITTSProvider(TTSProvider):
    """Synthesizes narration audio via OpenAI TTS (gpt-4o-mini-tts by default).

    Requests uncompressed WAV so the audio renderer can safely concatenate
    sections without a lossy re-encode round trip.
    """

    def __init__(
        self,
        client: openai.AsyncOpenAI,
        model: str = "gpt-4o-mini-tts",
        delivery_instructions: str = "",
    ) -> None:
        self.client = client
        self.model = model
        self.delivery_instructions = delivery_instructions

    async def synthesize(
        self, text: str, section: SectionName, voice: str, out_path: Path
    ) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with self.client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=voice,
                input=text,
                instructions=self.delivery_instructions or openai.omit,
                response_format="wav",
            ) as response:
                await response.stream_to_file(out_path)
        except openai.OpenAIError as exc:
            raise TTSGenerationError(
                f"TTS synthesis failed for section {section!r}: {exc}"
            ) from exc
        return out_path
