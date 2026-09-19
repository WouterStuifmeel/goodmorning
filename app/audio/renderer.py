from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.models.script import SECTION_ORDER, SectionName
from app.providers.base import AudioRenderer

_PAUSE_SECONDS = 0.8
_FADE_SECONDS = 1.5
_BED_VOLUME = 0.12
_SAMPLE_RATE = 44100


class FFmpegAudioRenderer(AudioRenderer):
    """Concatenates per-section narration with pauses, optionally mixes in a
    looped background music bed at reduced volume, applies fade in/out and
    loudness normalization, and encodes the result to MP3.

    Music bed is optional: when `bed_file` is None or missing, the renderer
    falls back to narration-only output.
    """

    def __init__(self, bed_file: Path | None = None) -> None:
        self.bed_file = bed_file if bed_file and bed_file.exists() else None

    def render(
        self, section_files: dict[SectionName, Path], out_path: Path
    ) -> float:
        missing = [s for s in SECTION_ORDER if s not in section_files]
        if missing:
            raise ValueError(f"missing section audio for: {missing}")

        out_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="goodmorning-render-") as tmp_str:
            tmp = Path(tmp_str)
            narration = self._concat_narration(section_files, tmp)
            self._mix_and_encode(narration, out_path)

        return self._probe_duration(out_path)

    def _concat_narration(
        self, section_files: dict[SectionName, Path], tmp: Path
    ) -> Path:
        pause_file = tmp / "pause.wav"
        self._run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"anullsrc=r={_SAMPLE_RATE}:cl=mono", "-t", f"{_PAUSE_SECONDS}",
                str(pause_file),
            ]
        )

        # Different TTS providers emit different sample rates/channel layouts
        # (the mock provider's silence is 44.1kHz mono, OpenAI's TTS output
        # may not be) - normalize everything to one PCM format before the
        # stream-copy concat below, which requires matching input formats.
        normalized = {
            section: self._normalize(path, tmp, f"{section}-norm.wav")
            for section, path in section_files.items()
        }

        list_file = tmp / "concat_list.txt"
        lines = []
        for i, section in enumerate(SECTION_ORDER):
            lines.append(f"file '{normalized[section].resolve()}'")
            if i < len(SECTION_ORDER) - 1:
                lines.append(f"file '{pause_file.resolve()}'")
        list_file.write_text("\n".join(lines) + "\n")

        narration = tmp / "narration.wav"
        self._run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file), "-c", "copy", str(narration),
            ]
        )
        return narration

    def _normalize(self, path: Path, tmp: Path, out_name: str) -> Path:
        out_path = tmp / out_name
        self._run(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-ar", str(_SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le",
                str(out_path),
            ]
        )
        return out_path

    def _mix_and_encode(self, narration: Path, out_path: Path) -> None:
        fade_filter = (
            f"afade=t=in:st=0:d={_FADE_SECONDS},"
            f"afade=t=out:st={{fade_out_start}}:d={_FADE_SECONDS}"
        )
        duration = self._probe_duration(narration)
        fade_out_start = max(duration - _FADE_SECONDS, 0)

        if self.bed_file is None:
            filter_chain = fade_filter.format(fade_out_start=fade_out_start)
            filter_chain += ",loudnorm"
            self._run(
                [
                    "ffmpeg", "-y", "-i", str(narration),
                    "-af", filter_chain, str(out_path),
                ]
            )
            return

        narration_filter = fade_filter.format(fade_out_start=fade_out_start)
        self._run(
            [
                "ffmpeg", "-y",
                "-i", str(narration),
                "-stream_loop", "-1", "-i", str(self.bed_file),
                "-filter_complex",
                f"[0:a]{narration_filter}[voice];"
                f"[1:a]volume={_BED_VOLUME}[bed];"
                f"[voice][bed]amix=inputs=2:duration=first:dropout_transition=0,"
                f"loudnorm[out]",
                "-map", "[out]",
                str(out_path),
            ]
        )

    def _probe_duration(self, path: Path) -> float:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())

    def _run(self, cmd: list[str]) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg command failed: {' '.join(cmd)}\n{result.stderr}")
