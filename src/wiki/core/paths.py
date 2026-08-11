"""Wiki paths — typed accessors for the project root layout.

Directory purpose guide
------------------------
``wiki/``
    Primary content: Markdown pages organized by type (sources, entities,
    concepts, synthesis, _stubs).  Also holds index.md (page catalog),
    log.md (audit trail), and media/ (extracted images + captions).

``raw/sources/``
    Original user-supplied source files for ingestion (PDFs, docs, etc.).

``.llm-wiki/``
    Per-project metadata — identity, settings, alias registry.  NOT a cache.
    Contents survive export.  Includes:
    - project.json     — project identity (UUID, name, schema version)
    - slug_aliases.json — CJK slug ↔ canonical alias registry
    - .backup/         — schema-migration safety backups

``.index/``
    Project-local operational data — vector store, caches, queues, state.
    Contents are NOT exported (except lancedb/, which is rebuilt from wiki
    pages).  Distinguish:
    - Production data:  lancedb/ (vector embeddings — not disposable)
    - Caches:           lint_cache/ (LLM lint results, TTL 24h)
    - Operational logs: heat_events.log, reviews*.json
    - Staging / temp:   staging/, quarantine/, dedup_history/
    - Config:           quality_settings.json, batch_build_state.json

    All cache/log/staging directories under .index/ can be cleaned by
    ``src.maintenance.cache_cleanup.cleanup_all()`` at any time without
    data loss — the wiki pages are the source of truth.
"""
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
    def wiki_claims(self) -> Path:
        return self.root / "wiki" / "claims"

    @property
    def wiki_decisions(self) -> Path:
        return self.root / "wiki" / "decisions"

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

    @property
    def knowledge_dir(self) -> Path:
        """Librarian's archive directory — canonical location for archived notes.

        v2 layout: notes live under ``wiki/sources`` and similar typed
        subdirectories. ``knowledge_dir`` is kept as an alias for ``wiki``
        so that legacy code and tests that reference the old ``Knowledge/``
        directory still resolve within the project root.
        """
        return self.root / "wiki"
