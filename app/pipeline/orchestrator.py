from __future__ import annotations

import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.models.facts import SourceFacts
from app.models.job import Job, JobState, SectionState
from app.models.manifest import Manifest, SectionAudio
from app.models.news import NewsCandidate
from app.models.script import SECTION_ORDER, Script, SectionName
from app.providers.base import AudioRenderer, NewsProvider, ScriptProvider, TTSProvider
from app.storage.db import JobStore
from app.storage.files import atomic_write_bytes, atomic_write_text


class PipelineError(Exception):
    """Raised when a pipeline stage fails; wraps the section, if any."""

    def __init__(self, message: str, section: SectionName | None = None) -> None:
        super().__init__(message)
        self.section = section


class Pipeline:
    """Orchestrates the six-stage episode generation pipeline, updating job
    state as it goes so status is visible to callers mid-run.
    """

    def __init__(
        self,
        news_provider: NewsProvider,
        script_provider: ScriptProvider,
        tts_provider: TTSProvider,
        audio_renderer: AudioRenderer,
        job_store: JobStore,
        output_dir: Path,
        voice: str,
    ) -> None:
        self.news_provider = news_provider
        self.script_provider = script_provider
        self.tts_provider = tts_provider
        self.audio_renderer = audio_renderer
        self.job_store = job_store
        self.output_dir = output_dir
        self.voice = voice

    async def run(self, job: Job) -> Job:
        job.state = JobState.running
        self._save(job)

        try:
            try:
                news_candidates = await self.news_provider.fetch_candidates(
                    job.source_facts.interests
                )
            except Exception as exc:
                raise PipelineError(f"news retrieval failed: {exc}") from exc

            try:
                script = await self.script_provider.generate_script(
                    job.source_facts, news_candidates
                )
            except Exception as exc:
                raise PipelineError(f"script generation failed: {exc}") from exc

            with tempfile.TemporaryDirectory(prefix=f"goodmorning-job-{job.id}-") as tmp_str:
                tmp = Path(tmp_str)
                section_files: dict[SectionName, Path] = {}
                section_audio: list[SectionAudio] = []

                for section in SECTION_ORDER:
                    job.section_states[section] = SectionState.running
                    self._save(job)
                    try:
                        text = script.section_text(section)
                        out_path = tmp / f"{section}.wav"
                        await self.tts_provider.synthesize(
                            text, section, self.voice, out_path
                        )
                    except Exception as exc:
                        job.section_states[section] = SectionState.failed
                        raise PipelineError(
                            f"synthesis failed for section {section!r}: {exc}",
                            section=section,
                        ) from exc

                    section_files[section] = out_path
                    job.section_states[section] = SectionState.completed
                    self._save(job)

                episode_id = f"{job.source_facts.episode_date.isoformat()}-{job.id[:8]}"
                final_tmp = tmp / f"{episode_id}.mp3"
                duration = self.audio_renderer.render(section_files, final_tmp)

                for section, path in section_files.items():
                    section_audio.append(
                        SectionAudio(
                            section=section,
                            file=path.name,
                            duration_seconds=self._file_duration(path),
                        )
                    )

                manifest = Manifest(
                    episode_id=episode_id,
                    episode_date=job.source_facts.episode_date,
                    audio_file=f"{episode_id}.mp3",
                    voice=self.voice,
                    sections=section_audio,
                    script=script,
                    source_facts=job.source_facts,
                    selected_news=self._selected_news(script, news_candidates),
                    created_at=datetime.now(UTC),
                )
                self._write_output(final_tmp, manifest, duration)

            job.manifest = manifest
            job.state = JobState.completed
            job.error = None
            self._save(job)

        except PipelineError as exc:
            job.state = JobState.failed
            job.error = str(exc)
            self._save(job)
        except Exception as exc:  # unexpected failures still surface on the job
            job.state = JobState.failed
            job.error = f"unexpected pipeline failure: {exc}"
            self._save(job)

        return job

    def _selected_news(
        self, script: Script, news_candidates: list[NewsCandidate]
    ) -> list[NewsCandidate]:
        """The candidates actually cited by the news section's grounded
        sources, in that order - not just however many sections exist.
        """
        news_section = next((s for s in script.sections if s.section == "news"), None)
        if news_section is None or not news_section.grounded_sources:
            return []
        by_url = {str(c.url): c for c in news_candidates}
        return [
            by_url[str(url)] for url in news_section.grounded_sources if str(url) in by_url
        ]

    def _write_output(self, rendered_mp3: Path, manifest: Manifest, duration: float) -> None:
        mp3_dest = self.output_dir / manifest.audio_file
        manifest_dest = self.output_dir / f"{manifest.episode_id}.manifest.json"
        atomic_write_bytes(mp3_dest, rendered_mp3.read_bytes())
        atomic_write_text(manifest_dest, manifest.model_dump_json(indent=2))

    def _file_duration(self, path: Path) -> float:
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

    def _save(self, job: Job) -> None:
        job.updated_at = datetime.now(UTC)
        self.job_store.save(job)


def new_job(source_facts: SourceFacts, force_regenerate: bool = False) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=str(uuid.uuid4()),
        source_facts=source_facts,
        force_regenerate=force_regenerate,
        created_at=now,
        updated_at=now,
    )
