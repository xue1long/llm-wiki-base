"""Background worker that materializes stub pages when new content references them."""
import asyncio
import logging

# Lightweight imports (no heavy side effects). The pipeline imports below are
# deferred to the call site to avoid pulling in src/pipeline/__init__.py
# (which requires pypdf, lancedb, docx, openpyxl, mcp, pyarrow at import time).
from ..storage.page_writer import read_page, write_page
from ..core.paths import WikiPaths
from ...lib.write_hooks import safe_write, DELETE_SENTINEL
from .schema_routing import validate_schema_routing  # noqa: F401  (re-exported per plan)
from ..core.types import PageType, WikiPage
from .wikilink import extract_wikilinks


_logger = logging.getLogger(__name__)


class StubMaterializerWorker:
    """Periodically scan wiki for content referencing stubs; materialize them."""

    def __init__(self, paths: WikiPaths, provider):
        self.paths = paths
        self.provider = provider

    async def run_once(self) -> list[str]:
        """Scan and materialize all referenced stubs. Returns list of materialized IDs."""
        referenced_stubs = self._find_referenced_stubs()
        materialized = []
        for stub_id in referenced_stubs:
            if await self._materialize_one(stub_id):
                materialized.append(stub_id)
        return materialized

    def _find_referenced_stubs(self) -> set[str]:
        """Find all stubs referenced by other wiki pages."""
        stub_ids: set[str] = set()
        for sub in [self.paths.wiki_sources, self.paths.wiki_entities,
                    self.paths.wiki_concepts, self.paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                page = read_page(f)
                links = extract_wikilinks(page.body)
                for link in links:
                    stub_path = self.paths.wiki_stubs / f"{link}.md"
                    if stub_path.exists():
                        stub_ids.add(link)
        return stub_ids

    async def _materialize_one(self, stub_id: str) -> bool:
        """Materialize one stub: call Generator to produce a real page from referring context."""
        # Deferred imports — keep src/pipeline/__init__.py out of the import graph
        # until we actually need generator/analyzer/schemas (which require pypdf,
        # lancedb, etc. at package init).
        from src.pipeline.generator import generate
        from src.pipeline.schemas import AnalysisResult, EntityMention

        stub_path = self.paths.wiki_stubs / f"{stub_id}.md"
        if not stub_path.exists():
            return False
        # Collect context from referring pages
        context_pages = []
        for sub in [self.paths.wiki_sources, self.paths.wiki_entities,
                    self.paths.wiki_concepts, self.paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                page = read_page(f)
                if stub_id in extract_wikilinks(page.body):
                    context_pages.append((page.id, page.body[:500]))
        if not context_pages:
            return False
        # Run LLM to generate real page (simple version: ask LLM to fill)
        analysis = AnalysisResult(
            task_id="stub", source_path=str(stub_path),
            summary=f"Materialized from {len(context_pages)} referring pages",
            entities=[EntityMention(name=stub_id, slug=stub_id, type="concept",
                                    context=context_pages[0][1], confidence=0.7)],
            suggested_pages=[],
        )
        # Generate
        pages = await generate(self.paths, analysis, existing_wiki_index="", provider=self.provider)
        if pages:
            new_page = pages[0]
            new_page.id = stub_id
            write_page(self.paths, new_page)
            # Remove stub via safe_write (atomic; deferred when in AtomicContext)
            safe_write(stub_path, DELETE_SENTINEL)
            _logger.info(f"[stubs] materialized {stub_id}")
            return True
        return False
