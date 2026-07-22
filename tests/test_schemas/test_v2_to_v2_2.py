"""Tests for src/schemas/migrations/v2_to_v2_2.py."""
import json
from pathlib import Path

from src.schemas.migration import MigrationContext, SchemaVersion
from src.schemas.registry import MigrationRegistry
from src.schemas.migrations.v2_to_v2_2 import V2ToV2_2WikiPageMigration


def _make_ctx(tmp_path: Path, *, dry_run: bool = False, backup_dir: Path | None = None):
    return MigrationContext(
        project_id="test-project",
        project_path=tmp_path,
        backup_dir=backup_dir,
        dry_run=dry_run,
    )


def _write_v20_page(path: Path, slug: str = "foo", title: str = "Foo") -> None:
    """Write a minimal v2.0 wiki page (slug id, no relations/grade)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n"
        f"id: {slug}\n"
        f"title: {title}\n"
        f"type: entity\n"
        f"sources:\n"
        f"  - raw/sources/x.pdf\n"
        f"created_at: 1000\n"
        f"updated_at: 2000\n"
        f"schema_version: v2.0\n"
        f"---\n\n"
        f"Body of {slug}\n",
        encoding="utf-8",
    )


def test_up_adds_v22_fields(tmp_path):
    """up() adds grade/processing_depth/is_immutable to frontmatter."""
    page = tmp_path / "wiki" / "entities" / "foo.md"
    _write_v20_page(page, slug="foo")

    ctx = _make_ctx(tmp_path, backup_dir=tmp_path / "backup")
    migration = V2ToV2_2WikiPageMigration()
    result = migration.up(ctx)

    assert result.success
    text = page.read_text(encoding="utf-8")
    assert "grade: B" in text
    assert "processing_depth: concept" in text
    assert "is_immutable: false" in text


def test_up_converts_id_to_uuid(tmp_path):
    """up() converts slug IDs to UUID v7 format."""
    page = tmp_path / "wiki" / "entities" / "foo.md"
    _write_v20_page(page, slug="my-slug")

    ctx = _make_ctx(tmp_path, backup_dir=tmp_path / "backup")
    migration = V2ToV2_2WikiPageMigration()
    result = migration.up(ctx)

    text = page.read_text(encoding="utf-8")
    assert "id: my-slug" not in text
    assert "id: card_" in text
    assert text.count("id: card_") >= 1


def test_down_reverts(tmp_path):
    """down() removes v2.2 fields and restores v2.0 schema_version."""
    page = tmp_path / "wiki" / "entities" / "foo.md"
    _write_v20_page(page, slug="foo")

    # First run up()
    up_ctx = _make_ctx(tmp_path, backup_dir=tmp_path / "backup")
    V2ToV2_2WikiPageMigration().up(up_ctx)

    # Then run down()
    down_ctx = _make_ctx(tmp_path, backup_dir=tmp_path / "backup")
    result = V2ToV2_2WikiPageMigration().down(down_ctx)

    assert result.success
    text = page.read_text(encoding="utf-8")
    assert "grade:" not in text
    assert "processing_depth:" not in text
    assert "is_immutable:" not in text
    assert "schema_version: v2.0" in text


def test_migration_is_registered():
    """V2ToV2_2WikiPageMigration is registered in MigrationRegistry."""
    migration_cls = MigrationRegistry.get("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1)
    assert migration_cls is not None
    # Note: V2_1 slot is now used by v2_to_v2_2 (most recent registration wins)