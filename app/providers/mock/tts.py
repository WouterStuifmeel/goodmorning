from __future__ import annotations

import asyncio
from pathlib import Path

from app.models.script import SectionName
from app.providers.base import TTSProvider

_WORDS_PER_MINUTE = 150
_MIN_DURATION_SECONDS = 1.0


class MockTTSProvider(TTSProvider):
    """Synthesizes silent placeholder audio sized to the text's expected
    reading time, via ffmpeg's lavfi silence source - no network, no
    external API, deterministic duration.
    """

    async def synthesize(
        self, text: str, section: SectionName, voice: str, out_path: Path
    ) -> Path:
        word_count = max(len(text.split()), 1)
        duration = max(word_count / _WORDS_PER_MINUTE * 60.0, _MIN_DURATION_SECONDS)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            f"{duration:.3f}",
            str(out_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"mock TTS synthesis failed for section {section!r}: "
                f"{stderr.decode(errors='replace')}"
            )
        return out_path
