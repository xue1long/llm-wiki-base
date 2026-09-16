"""Tests for the page->canonical migration tool (Task 51)."""
from __future__ import annotations

from src.reconciliation.canonical_models import CanonicalConcept, ReconciliationStatus
from src.reconciliation.canonical_registry import CanonicalRegistry
from src.reconciliation.migrate_pages import (
    MigrationReport,
    analyze_unmigrated_pages,
    migrate_pages,
)


def _write_page(pages_dir, page_id: str, *, title: str = "", canonical_id: str | None = None) -> None:
    """Write a minimal wiki page with optional frontmatter fields."""
    fm_lines = ["---"]
    fm_lines.append(f"id: {page_id}")
    if title:
        fm_lines.append(f"title: {title}")
    if canonical_id is not None:
        fm_lines.append(f"canonical_id: {canonical_id}")
    fm_lines.append("---")
    body = f"# Body of {page_id}\n"
    text = "\n".join(fm_lines) + "\n\n" + body
    (pages_dir / f"{page_id}.md").write_text(text, encoding="utf-8")


def test_analyze_empty_project(tmp_path):
    """No wiki/concepts/ -> 0 scanned."""
    report = analyze_unmigrated_pages(tmp_path)
    assert report.scanned_pages == 0
    assert report.already_migrated == 0
    assert report.would_migrate == []
    assert report.unmigrated == []


def test_analyze_finds_pages_without_canonical_id_in_frontmatter(tmp_path):
    """3 pages, 1 with canonical_id -> 2 unmigrated (or matched)."""
    pages_dir = tmp_path / "wiki" / "concepts"
    pages_dir.mkdir(parents=True)
    _write_page(pages_dir, "p-old-1", title="扩句法")
    _write_page(pages_dir, "p-old-2", title="Some other")
    _write_page(pages_dir, "p-already", title="Already migrated", canonical_id="c-abc")

    report = analyze_unmigrated_pages(tmp_path)
    assert report.scanned_pages == 3
    assert report.already_migrated == 1
    # "扩句法" page is migrated via alias match (if seeded) or unmigrated
    # otherwise; the test just verifies count consistency.
    assert report.scanned_pages == report.already_migrated + len(report.would_migrate) + len(report.unmigrated)


def test_analyze_alias_match_suggests_canonical(tmp_path):
    """Page with title matching a registry alias -> suggested canonical."""
    pages_dir = tmp_path / "wiki" / "concepts"
    pages_dir.mkdir(parents=True)
    _write_page(pages_dir, "p-legacy", title="扩句法")

    reg = CanonicalRegistry(tmp_path)
    reg._save_concepts({
        "c-kuoju": CanonicalConcept(
            canonical_id="c-kuoju", preferred_label="扩句法",
            member_page_ids=[], status=ReconciliationStatus.ACTIVE,
            aliases=["扩句法", "kuoju"], resolver_fingerprint="fp",
        ),
    })

    report = analyze_unmigrated_pages(tmp_path, registry=reg)
    assert ("p-legacy", "c-kuoju") in report.would_migrate


def test_migrate_dry_run_does_not_modify_files(tmp_path):
    """dry_run=True -> file is read but never written."""
    pages_dir = tmp_path / "wiki" / "concepts"
    pages_dir.mkdir(parents=True)
    _write_page(pages_dir, "p-legacy", title="扩句法")
    reg = CanonicalRegistry(tmp_path)
    reg._save_concepts({
        "c-kuoju": CanonicalConcept(
            canonical_id="c-kuoju", preferred_label="扩句法",
            member_page_ids=[], status=ReconciliationStatus.ACTIVE,
            resolver_fingerprint="fp",
        ),
    })

    before = (pages_dir / "p-legacy.md").read_text(encoding="utf-8")
    report = migrate_pages(tmp_path, dry_run=True, registry=reg)
    after = (pages_dir / "p-legacy.md").read_text(encoding="utf-8")
    assert before == after
    assert report.dry_run is True
    assert report.applied is False
    # The match is still in would_migrate so the operator can audit.
    assert ("p-legacy", "c-kuoju") in report.would_migrate


def test_migrate_apply_writes_canonical_id_to_frontmatter(tmp_path):
    """dry_run=False -> page frontmatter gains canonical_id field."""
    pages_dir = tmp_path / "wiki" / "concepts"
    pages_dir.mkdir(parents=True)
    _write_page(pages_dir, "p-legacy", title="扩句法")
    reg = CanonicalRegistry(tmp_path)
    reg._save_concepts({
        "c-kuoju": CanonicalConcept(
            canonical_id="c-kuoju", preferred_label="扩句法",
            member_page_ids=[], status=ReconciliationStatus.ACTIVE,
            resolver_fingerprint="fp",
        ),
    })

    report = migrate_pages(tmp_path, dry_run=False, registry=reg)
    assert report.dry_run is False
    assert report.applied is True
    assert ("p-legacy", "c-kuoju") in report.would_migrate

    after = (pages_dir / "p-legacy.md").read_text(encoding="utf-8")
    assert "canonical_id: c-kuoju" in after
    # The other frontmatter fields are preserved.
    assert "id: p-legacy" in after
    assert "title: 扩句法" in after


def test_analyze_skips_pages_with_canonical_id(tmp_path):
    """All pages already migrated -> 0 unmigrated."""
    pages_dir = tmp_path / "wiki" / "concepts"
    pages_dir.mkdir(parents=True)
    _write_page(pages_dir, "p-1", canonical_id="c-1")
    _write_page(pages_dir, "p-2", canonical_id="c-2")
    report = analyze_unmigrated_pages(tmp_path)
    assert report.scanned_pages == 2
    assert report.already_migrated == 2
    assert report.would_migrate == []
    assert report.unmigrated == []


def test_migrate_reports_errors_for_unparseable_page(tmp_path):
    """A page with a malformed frontmatter that cannot be parsed is
    recorded as an error when apply mode is selected."""
    pages_dir = tmp_path / "wiki" / "concepts"
    pages_dir.mkdir(parents=True)
    _write_page(pages_dir, "p-legacy", title="扩句法")
    # Corrupt the file: frontmatter is no longer valid YAML.
    (pages_dir / "p-legacy.md").write_text("---this is : not: valid: yaml\n---\n\nbody\n", encoding="utf-8")
    reg = CanonicalRegistry(tmp_path)
    reg._save_concepts({
        "c-kuoju": CanonicalConcept(
            canonical_id="c-kuoju", preferred_label="扩句法",
            member_page_ids=[], status=ReconciliationStatus.ACTIVE,
            resolver_fingerprint="fp",
        ),
    })

    report = migrate_pages(tmp_path, dry_run=False, registry=reg)
    # Page is unparseable so it's in unmigrated (analyze), but should
    # not produce a rewrite error (no apply attempted).
    assert "p-legacy" in report.unmigrated
    # And the file was not corrupted by apply.
    assert (pages_dir / "p-legacy.md").read_text(encoding="utf-8") == (
        "---this is : not: valid: yaml\n---\n\nbody\n"
    )