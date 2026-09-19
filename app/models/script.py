from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, HttpUrl

SectionName = Literal["intro", "weather", "calendar", "news", "outro"]
SECTION_ORDER: tuple[SectionName, ...] = ("intro", "weather", "calendar", "news", "outro")


class ScriptSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: SectionName
    text: str
    # For the news section: which retrieved candidates this text is grounded in.
    grounded_sources: list[HttpUrl] = []


class Script(BaseModel):
    """The full narration script, one section per pipeline stage.

    Produced strictly from SourceFacts and retrieved NewsCandidates -
    never invented.
    """

    model_config = ConfigDict(extra="forbid")

    sections: list[ScriptSection]

    def section_text(self, name: SectionName) -> str:
        for s in self.sections:
            if s.section == name:
                return s.text
        raise KeyError(f"no section named {name!r} in script")
