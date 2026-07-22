"""Shared pipeline dataclasses (AnalysisResult + Generator output)."""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class EntityMention:
    name: str
    slug: str
    type: str                       # "person" | "org" | "concept" | "place" | ...
    context: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConceptMention:
    name: str
    slug: str
    context: str
    confidence: float


@dataclass
class PageSpec:
    type: str                       # "source" | "entity" | "concept" | "synthesis"
    slug: str
    title: str
    reasoning: str = ""


@dataclass
class AnalysisResult:
    """Output of Analyzer Step 1."""
    task_id: str
    source_path: str
    summary: str
    key_facts: list[str] = field(default_factory=list)
    entities: list[EntityMention] = field(default_factory=list)
    concepts: list[ConceptMention] = field(default_factory=list)
    suggested_pages: list[PageSpec] = field(default_factory=list)
    links_to_existing: list[str] = field(default_factory=list)
    folder_context: str = ""