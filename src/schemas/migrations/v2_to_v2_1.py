# src/schemas/migrations/v2_to_v2_1.py
"""v2.0 → v2.1: Add `relations: []` field to wiki pages (Wiki Relations spec)."""
import logging

from ..migration import Migration, MigrationContext, MigrationPlan, MigrationResult, SchemaVersion
from ..registry import MigrationRegistry


_logger = logging.getLogger(__name__)


class V2ToV2_1WikiPageMigration(Migration):
    schema_name = "wiki_page"
    from_version = SchemaVersion.V2_0
    to_version = SchemaVersion.V2_1

    def preview(self, ctx: MigrationContext) -> MigrationPlan:
        files = list(ctx.project_path.glob("wiki/**/*.md"))
        return MigrationPlan(
            from_version=self.from_version,
            to_version=self.to_version,
            steps=[f"Add 'relations: []' to {len(files)} wiki pages"],
            affected_files=files,
            reversible=True,
        )

    def up(self, ctx: MigrationContext) -> MigrationResult:
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        for f in ctx.project_path.glob("wiki/**/*.md"):
            text = f.read_text(encoding="utf-8")
            if "schema_version: v2.1" in text:
                continue
            if text.startswith("---\n") and "relations:" not in text:
                text = text.replace(
                    "schema_version: v2.0",
                    "schema_version: v2.1\nrelations: []",
                    1,
                )
                f.write_text(text, encoding="utf-8")
                result.files_changed += 1

        # Update project.json
        pj = ctx.project_path / ".llm-wiki" / "project.json"
        if pj.exists():
            import json
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["schema_version"] = "v2.1"
            pj.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return result

    def down(self, ctx: MigrationContext) -> MigrationResult:
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        for f in ctx.project_path.glob("wiki/**/*.md"):
            text = f.read_text(encoding="utf-8")
            if "schema_version: v2.1" in text:
                # Remove relations: [] line
                lines = text.split("\n")
                lines = [l for l in lines if l.strip() != "relations: []"]
                text = "\n".join(lines).replace("schema_version: v2.1", "schema_version: v2.0")
                f.write_text(text, encoding="utf-8")
                result.files_changed += 1
        return result


MigrationRegistry.register(
    "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, V2ToV2_1WikiPageMigration()
)