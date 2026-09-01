from src.maintenance.content_health import build_content_health
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def test_build_content_health_summarizes_pages_and_triage(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(
        id="operation-1", title="Operation", type=PageType.CONCEPT,
        grade="A", processing_depth="operation", body="steps",
    ))
    write_page(paths, WikiPage(
        id="linked", title="Linked", type=PageType.CONCEPT,
        body="See [[operation-1]] and [[missing-page]].",
    ))
    paths.index.joinpath("triage.log").write_text(
        '{"action":"skip"}\n{"action":"process"}\n', encoding="utf-8"
    )

    report = build_content_health(paths)

    assert report["page_count"] == 2
    assert report["grades"] == {"B": 2}
    assert report["processing_depths"] == {"concept": 2}
    assert report["dangling_link_count"] == 1
    assert report["orphan_count"] == 1
    assert report["triage_non_process_count"] == 1


def test_build_content_health_reports_unreadable_pages(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    broken = paths.wiki_concepts / "broken.md"
    broken.write_text("---\nnot: [valid\n---\nbody", encoding="utf-8")

    report = build_content_health(paths)

    assert report["page_count"] == 0
    assert report["check_errors"] == [{"path": str(broken), "error": "invalid page"}]
