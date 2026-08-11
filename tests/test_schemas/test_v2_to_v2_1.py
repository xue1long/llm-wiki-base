# tests/test_schemas/test_v2_to_v2_1.py

from src.schemas.migration import MigrationContext
from src.schemas.migrations.v2_to_v2_1 import V2ToV2_1WikiPageMigration


def test_v2_to_v2_1_adds_relations_field(tmp_path):
    """Migration adds 'relations: []' to wiki pages that don't have it."""
    f = tmp_path / "wiki" / "sources" / "abc.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nschema_version: v2.0\nid: abc\n---\nbody\n", encoding="utf-8")

    ctx = MigrationContext(
        project_id="p", project_path=tmp_path, backup_dir=tmp_path / ".backup"
    )
    m = V2ToV2_1WikiPageMigration()
    m.up(ctx)

    text = f.read_text(encoding="utf-8")
    assert "schema_version: v2.1" in text
    assert "relations: []" in text


def test_v2_to_v2_1_idempotent(tmp_path):
    """Re-running on already-migrated files is a no-op."""
    f = tmp_path / "wiki" / "sources" / "abc.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nschema_version: v2.1\nid: abc\nrelations: []\n---\nbody\n", encoding="utf-8")

    ctx = MigrationContext(
        project_id="p", project_path=tmp_path, backup_dir=tmp_path / ".backup"
    )
    m = V2ToV2_1WikiPageMigration()
    result = m.up(ctx)
    assert result.files_changed == 0


def test_v2_to_v2_1_down_removes_relations(tmp_path):
    """down() removes relations field, downgrades schema_version."""
    f = tmp_path / "wiki" / "sources" / "abc.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nschema_version: v2.1\nid: abc\nrelations: []\n---\nbody\n", encoding="utf-8")

    ctx = MigrationContext(
        project_id="p", project_path=tmp_path, backup_dir=tmp_path / ".backup"
    )
    m = V2ToV2_1WikiPageMigration()
    m.down(ctx)

    text = f.read_text(encoding="utf-8")
    assert "schema_version: v2.0" in text
    assert "relations:" not in text
