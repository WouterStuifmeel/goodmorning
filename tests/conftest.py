from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.facts import SourceFacts

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def source_facts() -> SourceFacts:
    data = json.loads((FIXTURES_DIR / "source_facts.json").read_text())
    return SourceFacts.model_validate(data)
