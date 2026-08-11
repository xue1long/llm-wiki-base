# src/schemas/migrations/v1_to_v2.py
"""v1.0 → v2.0: Refactored as Migration class (was function-based)."""
import json
import logging

from ..migration import Migration, MigrationContext, MigrationPlan, MigrationResult, SchemaVersion


_logger = logging.getLogger(__name__)


class V1ToV2WikiPageMigration(Migration):
    """Move notes/ → wiki/ and upgrade frontmatter schema to v2.0.

    Pre-v2 KB layout had:
        <root>/Notes/<task_id>.md

    v2.0 KB layout:
        <root>/wiki/sources/<task_id>.md
    """

    schema_name = "wiki_page"
    from_version = SchemaVersion.V1_0
    to_version = SchemaVersion.V2_0

    def preview(self, ctx: MigrationContext) -> MigrationPlan:
        notes_dir = ctx.project_path / "Notes"
        files = list(notes_dir.glob("*.md")) if notes_dir.exists() else []
        return MigrationPlan(
            from_version=self.from_version,
            to_version=self.to_version,
            steps=[
                f"Move {len(files)} files from Notes/ to wiki/sources/",
                "Add 'id', 'type', 'sources', 'created_at', 'updated_at' fields",
                "Update .llm-wiki/project.json schema_version to v2.0",
            ],
            affected_files=files,
            reversible=True,
        )

    def up(self, ctx: MigrationContext) -> MigrationResult:
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        notes_dir = ctx.project_path / "Notes"
        wiki_sources = ctx.project_path / "wiki" / "sources"
        if notes_dir.exists() and not wiki_sources.exists():
            wiki_sources.mkdir(parents=True, exist_ok=True)
            for f in notes_dir.glob("*.md"):
                target = wiki_sources / f.name
                target.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                result.files_changed += 1
        # Update project.json
        pj = ctx.project_path / ".llm-wiki" / "project.json"
        if pj.exists():
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["schema_version"] = "v2.0"
            pj.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return result

    def down(self, ctx: MigrationContext) -> MigrationResult:
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        notes_dir = ctx.project_path / "Notes"
        wiki_sources = ctx.project_path / "wiki" / "sources"
        if wiki_sources.exists() and not notes_dir.exists():
            notes_dir.mkdir(parents=True, exist_ok=True)
            for f in wiki_sources.glob("*.md"):
                target = notes_dir / f.name
                target.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                result.files_changed += 1
        pj = ctx.project_path / ".llm-wiki" / "project.json"
        if pj.exists():
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["schema_version"] = "v1.0"
            pj.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return result


# Auto-register on import
from ..registry import MigrationRegistry
MigrationRegistry.register(
    "wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, V1ToV2WikiPageMigration()
)
