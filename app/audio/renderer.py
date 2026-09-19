from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from app.models.script import SECTION_ORDER, SectionName
from app.providers.base import AudioRenderer

_PAUSE_SECONDS = 0.8
_FADE_SECONDS = 1.5
_SAMPLE_RATE = 44100
_DEFAULT_NARRATION_START_SECONDS = 29.0
_LOUDNORM_TARGET = "I=-16:TP=-1.5:LRA=11"


class FFmpegAudioRenderer(AudioRenderer):
    """Concatenates per-section narration with pauses, optionally preceding it
    with a one-shot wake-up jingle. Narration starts at a fixed cue point
    within the jingle (`narration_start_seconds`, timed to that jingle's own
    build) rather than fading in, applies fade-out and loudness normalization
    at the end, and encodes the result to MP3.

    The jingle plays once, at full volume, and is not looped or mixed under
    the rest of the episode - the news/weather/calendar sections must never
    have music under them. It is optional: when `intro_jingle_file` is None
    or missing, the renderer falls back to narration-only output.
    """

    def __init__(
        self,
        intro_jingle_file: Path | None = None,
        narration_start_seconds: float = _DEFAULT_NARRATION_START_SECONDS,
    ) -> None:
        self.intro_jingle_file = (
            intro_jingle_file
            if intro_jingle_file and intro_jingle_file.exists()
            else None
        )
        self.narration_start_seconds = narration_start_seconds

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

        # Silence appended after the final section, so the end-of-episode
        # fade-out (_FADE_SECONDS) has silence to fade through instead of
        # cutting into the outro's actual last words.
        tail_file = tmp / "tail.wav"
        self._run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"anullsrc=r={_SAMPLE_RATE}:cl=mono", "-t", f"{_FADE_SECONDS}",
                str(tail_file),
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
        lines.append(f"file '{tail_file.resolve()}'")
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
        duration = self._probe_duration(narration)
        fade_out_start = max(duration - _FADE_SECONDS, 0)
        fade_out_filter = f"afade=t=out:st={fade_out_start}:d={_FADE_SECONDS}"

        if self.intro_jingle_file is None:
            inputs = ["-i", str(narration)]
            pre_filter = (
                f"[0:a]afade=t=in:st=0:d={_FADE_SECONDS},{fade_out_filter}[pre]"
            )
        else:
            # Narration starts at a fixed cue point within the jingle rather
            # than fading in - the jingle's own build already leads into it.
            delay_ms = max(round(self.narration_start_seconds * 1000), 0)
            inputs = ["-i", str(narration), "-i", str(self.intro_jingle_file)]
            pre_filter = (
                f"[0:a]{fade_out_filter},adelay={delay_ms}:all=1[voice];"
                f"[1:a][voice]amix=inputs=2:duration=longest:dropout_transition=0[pre]"
            )

        self._render_two_pass_loudnorm(inputs, pre_filter, out_path)

    def _render_two_pass_loudnorm(
        self, inputs: list[str], pre_filter: str, out_path: Path
    ) -> None:
        # Single-pass loudnorm applies an adaptive, still-converging gain as
        # it goes, which can noticeably over-boost a quiet opening (e.g. the
        # jingle's birdsong) before it has "seen" the rest of the track.
        # Two-pass measures the whole mix first, then applies one fixed
        # linear gain, so the source's intended relative dynamics survive.
        measure = subprocess.run(
            [
                "ffmpeg", "-y", *inputs, "-filter_complex",
                f"{pre_filter};[pre]loudnorm={_LOUDNORM_TARGET}:print_format=json[measured]",
                "-map", "[measured]", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
        )
        if measure.returncode != 0:
            raise RuntimeError(f"ffmpeg loudnorm measurement failed\n{measure.stderr}")
        stats = self._parse_loudnorm_stats(measure.stderr)

        # Effectively-silent input (e.g. mock TTS placeholder audio) measures
        # as -inf loudness, which loudnorm's measured_I option rejects -
        # there's nothing meaningful to normalize, so skip it.
        if float(stats["input_i"]) == float("-inf"):
            self._run(
                ["ffmpeg", "-y", *inputs, "-filter_complex", f"{pre_filter}", "-map", "[pre]", str(out_path)]
            )
            return

        apply_filter = (
            f"{pre_filter};[pre]loudnorm={_LOUDNORM_TARGET}:"
            f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
            f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:linear=true[out]"
        )
        self._run(
            ["ffmpeg", "-y", *inputs, "-filter_complex", apply_filter, "-map", "[out]", str(out_path)]
        )

    def _parse_loudnorm_stats(self, stderr: str) -> dict:
        start = stderr.rindex("{")
        end = stderr.rindex("}") + 1
        return json.loads(stderr[start:end])

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
