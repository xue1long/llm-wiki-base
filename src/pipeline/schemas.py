"""Shared pipeline dataclasses (AnalysisResult + Generator output)."""
from dataclasses import dataclass, field, asdict

from ..utils.slugify import slugify as _slugify


def _normalize_slug(slug: str) -> str:
    """Run the LLM-supplied slug through the deterministic slugify helper.

    The LLM is inconsistent with Chinese transliteration (创酷中文网 →
    ``chuangku-zhongwenwang`` vs ``chuang-kuo-zhong-wen-wang``). Re-derive
    from the slug string via pypinyin so every equivalent input lands on
    the same canonical form. Falls back to the original if slugify
    returns empty (e.g. all-symbol input).
    """
    if not slug:
        return slug
    normalized = _slugify(slug)
    return normalized or slug


@dataclass
class EntityMention:
    name: str
    slug: str
    type: str                       # "person" | "org" | "concept" | "place" | ...
    context: str
    confidence: float

    def __post_init__(self) -> None:
        self.slug = _normalize_slug(self.slug)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConceptMention:
    name: str = ""
    slug: str = ""
    context: str = ""
    confidence: float = 0.0
    # LLM may return "concept" instead of "name" — accept it as an alias.
    concept: str = ""

    def __post_init__(self) -> None:
        if self.concept and not self.name:
            self.name = self.concept
        self.slug = _normalize_slug(self.slug)


@dataclass
class PageSpec:
    type: str                       # "source" | "entity" | "concept" | "synthesis"
    slug: str
    title: str
    reasoning: str = ""
    # v2.2 fields — defaults match WikiPage so existing fixtures keep working.
    grade: str = "B"                # "A" | "B" | "C"
    processing_depth: str = "concept"  # "concept" | "memory"
    is_immutable: bool = False
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.slug = _normalize_slug(self.slug)


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
