# tests/test_wiki/test_lint.py
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.lint import lint_wiki, LintSeverity
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.wiki.features.indexer import append_to_index


def test_lint_clean_wiki_no_issues(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="foo", title="Foo", type=PageType.ENTITY, body="Hello world"))
    write_page(p, WikiPage(id="bar", title="Bar", type=PageType.CONCEPT, body="Other content"))
    append_to_index(p, [("foo", PageType.ENTITY, "Foo"), ("bar", PageType.CONCEPT, "Bar")])

    report = lint_wiki(p)
    assert report.scanned_pages == 2
    assert report.issues == []


def test_lint_counts_files_with_duplicate_page_ids(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="shared", title="Entity", type=PageType.ENTITY, body="Entity body"))
    write_page(p, WikiPage(id="shared", title="Concept", type=PageType.CONCEPT, body="Concept body"))

    report = lint_wiki(p)

    assert report.scanned_pages == 2


def test_lint_detects_orphan(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Write page but don't add to index
    write_page(p, WikiPage(id="orphan", title="Orphan", type=PageType.ENTITY, body="..."))
    append_to_index(p, [])  # empty index

    report = lint_wiki(p)
    codes = [i.code for i in report.issues]
    assert "LINT-ORPHAN" in codes


def test_lint_detects_duplicate_content(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    body = "Identical content"
    write_page(p, WikiPage(id="dup1", title="Dup1", type=PageType.ENTITY, body=body))
    write_page(p, WikiPage(id="dup2", title="Dup2", type=PageType.ENTITY, body=body))
    append_to_index(p, [("dup1", PageType.ENTITY, "Dup1"), ("dup2", PageType.ENTITY, "Dup2")])

    report = lint_wiki(p)
    codes = [i.code for i in report.issues]
    assert "LINT-DUPLICATE" in codes


def test_lint_detects_empty_body(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="empty", title="Empty", type=PageType.ENTITY, body=""))
    append_to_index(p, [("empty", PageType.ENTITY, "Empty")])

    report = lint_wiki(p)
    empty_issues = [i for i in report.issues if i.code == "LINT-EMPTY-BODY"]
    assert len(empty_issues) == 1
    assert empty_issues[0].severity == LintSeverity.INFO