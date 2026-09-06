from pathlib import Path

from src.kc.views.book.wiki.scanner import scan_wiki_snapshot
from src.pipeline.ingest import _normalize_generated_pages
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.page_writer import write_page


def test_ingest_taxonomy_and_provenance_reach_book_scanner(tmp_path: Path):
    paths = WikiPaths(tmp_path)
    for directory in (paths.wiki_sources, paths.wiki_entities, paths.wiki_concepts,
                      paths.wiki_synthesis, paths.wiki_stubs, paths.llm_wiki):
        directory.mkdir(parents=True, exist_ok=True)
    page = WikiPage(id="c1", title="Concept", type=PageType.CONCEPT,
                    body="## Definition\n\nBody", sources=["raw/sources/a.md"])
    page.category = "写作技法"
    page.taxonomy_sub = "冲突"

    _normalize_generated_pages([page], paths)
    write_page(paths, page)

    record = scan_wiki_snapshot(paths.wiki).pages[0]
    assert record.primary_taxonomy == "写作技法"
    assert record.sources == ("raw/sources/a.md",)
    assert ("taxonomy_of", "taxonomy-写作技法") in record.relation_targets
