# tests/test_schemas/test_migration.py
from pathlib import Path

import pytest

from src.schemas.migration import Migration, MigrationContext, MigrationPlan, MigrationResult, SchemaVersion


class _AddFieldMigration(Migration):
    """Test migration that adds 'new_field: ""' to all wiki .md files."""
    schema_name = "wiki_page"
    from_version = SchemaVersion.V1_0
    to_version = SchemaVersion.V2_0

    def preview(self, ctx):
        files = list(ctx.project_path.glob("wiki/**/*.md"))
        return MigrationPlan(
            from_version=self.from_version,
            to_version=self.to_version,
            steps=[f"Add 'new_field: \"\"' to {len(files)} files"],
            affected_files=files,
            reversible=True,
        )

    def up(self, ctx):
        self._require_backup(ctx)
        changed = 0
        if not ctx.dry_run:
            for f in ctx.project_path.glob("wiki/**/*.md"):
                text = f.read_text(encoding="utf-8")
                if "new_field:" not in text and text.startswith("---\n"):
                    text = text.replace("---\n", "---\nnew_field: \"\"\n", 1)
                    f.write_text(text, encoding="utf-8")
                    changed += 1
        return MigrationResult(success=True, files_changed=changed)

    def down(self, ctx):
        self._require_backup(ctx)
        changed = 0
        if not ctx.dry_run:
            for f in ctx.project_path.glob("wiki/**/*.md"):
                text = f.read_text(encoding="utf-8")
                if "new_field:" in text:
                    lines = text.split("\n")
                    lines = [l for l in lines if not l.startswith("new_field:")]
                    f.write_text("\n".join(lines), encoding="utf-8")
                    changed += 1
        return MigrationResult(success=True, files_changed=changed)


def test_migration_metadata():
    """Migration subclass declares schema_name, from_version, to_version."""
    m = _AddFieldMigration()
    assert m.schema_name == "wiki_page"
    assert m.from_version.value == "v1.0"
    assert m.to_version.value == "v2.0"


def test_migration_preview_does_not_modify(tmp_path):
    """preview() shows plan without modifying files."""
    f = tmp_path / "wiki" / "a.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
    ctx = MigrationContext(project_id="p1", project_path=tmp_path, dry_run=True)
    m = _AddFieldMigration()

    plan = m.preview(ctx)
    assert "Add 'new_field" in plan.steps[0]
    assert plan.affected_files == [f]
    # File not modified
    assert "new_field:" not in f.read_text()


def test_migration_up_modifies_files(tmp_path):
    """up() applies changes; dry_run=False by default."""
    f = tmp_path / "wiki" / "a.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
    ctx = MigrationContext(project_id="p1", project_path=tmp_path, backup_dir=tmp_path / "backup")
    m = _AddFieldMigration()

    result = m.up(ctx)
    assert result.success
    assert result.files_changed == 1
    assert "new_field:" in f.read_text()


def test_migration_up_idempotent(tmp_path):
    """Re-running up() on already-migrated files is a no-op."""
    f = tmp_path / "wiki" / "a.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nnew_field: \"\"\nid: x\n---\nbody\n", encoding="utf-8")
    ctx = MigrationContext(project_id="p1", project_path=tmp_path, backup_dir=tmp_path / "backup")
    m = _AddFieldMigration()

    result = m.up(ctx)
    assert result.files_changed == 0  # already migrated


def test_migration_down_reverts(tmp_path):
    """down() reverses up()."""
    f = tmp_path / "wiki" / "a.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\nnew_field: \"\"\nid: x\n---\nbody\n", encoding="utf-8")
    ctx = MigrationContext(project_id="p1", project_path=tmp_path, backup_dir=tmp_path / "backup")
    m = _AddFieldMigration()

    m.down(ctx)
    assert "new_field:" not in f.read_text()
    assert "id: x" in f.read_text()


def test_migration_requires_backup_dir_for_up():
    """up() should fail if no backup_dir provided (safety)."""
    # This enforces safety contract: always backup before mutating
    from src.schemas.migration import MigrationSafetyError
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        f = tmp_path / "wiki" / "a.md"
        f.parent.mkdir(parents=True)
        f.write_text("---\nid: x\n---\nbody\n", encoding="utf-8")
        ctx = MigrationContext(project_id="p1", project_path=tmp_path, backup_dir=None)
        m = _AddFieldMigration()
        # The migration framework enforces this; specific migration may not.
        # If migration doesn't enforce, the test verifies behavior is safe (either pass or raise)
        try:
            result = m.up(ctx)
            # If migration allowed no backup, that's a contract violation
            # (test passes only if migration raises)
            pytest.fail("Migration should require backup_dir")
        except MigrationSafetyError:
            pass  # expected
