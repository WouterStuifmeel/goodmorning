from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.models.facts import SourceFacts
from app.models.news import NewsCandidate
from app.models.script import Script, SectionName


class NewsProvider(ABC):
    """Retrieves candidate stories from configured feeds for a set of interests."""

    @abstractmethod
    async def fetch_candidates(self, interests: list[str]) -> list[NewsCandidate]: ...


class ScriptProvider(ABC):
    """Turns source facts + retrieved news into a grounded narration script."""

    @abstractmethod
    async def generate_script(
        self, facts: SourceFacts, news_candidates: list[NewsCandidate]
    ) -> Script: ...


class TTSProvider(ABC):
    """Synthesizes narration audio for one script section."""

    @abstractmethod
    async def synthesize(
        self, text: str, section: SectionName, voice: str, out_path: Path
    ) -> Path:
        """Write synthesized audio to out_path and return it."""
        ...


class AudioRenderer(ABC):
    """Combines per-section narration with music beds into the final episode."""

    @abstractmethod
    def render(
        self, section_files: dict[SectionName, Path], out_path: Path
    ) -> float:
        """Write the assembled episode to out_path, return its duration in seconds."""
        ...
