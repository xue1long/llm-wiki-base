"""Wiki paths — typed accessors for the project root layout."""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WikiPaths:
    root: Path

    @property
    def wiki(self) -> Path:
        return self.root / "wiki"

    @property
    def wiki_sources(self) -> Path:
        return self.root / "wiki" / "sources"

    @property
    def wiki_entities(self) -> Path:
        return self.root / "wiki" / "entities"

    @property
    def wiki_concepts(self) -> Path:
        return self.root / "wiki" / "concepts"

    @property
    def wiki_synthesis(self) -> Path:
        return self.root / "wiki" / "synthesis"

    @property
    def wiki_stubs(self) -> Path:
        return self.root / "wiki" / "_stubs"

    @property
    def raw_sources(self) -> Path:
        return self.root / "raw" / "sources"

    @property
    def index(self) -> Path:
        return self.root / ".index"

    @property
    def llm_wiki(self) -> Path:
        return self.root / ".llm-wiki"

    @property
    def llm_wiki_log(self) -> Path:
        return self.root / "wiki" / "log.md"

    @property
    def llm_wiki_index(self) -> Path:
        return self.root / "wiki" / "index.md"
