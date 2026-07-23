# src/schemas/migrations/v2_to_v2_2.py
"""v2.0 → v2.2: Add grade/processing_depth/is_immutable + convert slug IDs to UUID v7."""
import json
import logging
import re

from ..migration import (
    Migration, MigrationContext, MigrationPlan, MigrationResult, SchemaVersion,
)
from ..registry import MigrationRegistry
from ...wiki.core.id_generator import generate_page_id, ID_PATTERN


_logger = logging.getLogger(__name__)


class V2ToV2_2WikiPageMigration(Migration):
    schema_name = "wiki_page"
    from_version = SchemaVersion.V2_0
    to_version = SchemaVersion.V2_2

    def preview(self, ctx: MigrationContext) -> MigrationPlan:
        files = list(ctx.project_path.glob("wiki/**/*.md"))
        return MigrationPlan(
            from_version=self.from_version,
            to_version=self.to_version,
            steps=[
                f"Convert {len(files)} slug IDs to UUID v7",
                f"Add grade/processing_depth/is_immutable to {len(files)} pages",
            ],
            affected_files=files,
            reversible=True,
        )

    def up(self, ctx: MigrationContext) -> MigrationResult:
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        for f in ctx.project_path.glob("wiki/**/*.md"):
            text = f.read_text(encoding="utf-8")
            if "schema_version: v2.2" in text:
                continue
            new_text = self._add_v22_fields(text)
            new_text = self._convert_id_to_uuid_v7(new_text)
            if new_text != text:
                f.write_text(new_text, encoding="utf-8")
                result.files_changed += 1

        # Update project.json
        pj = ctx.project_path / ".llm-wiki" / "project.json"
        if pj.exists():
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["schema_version"] = "v2.2"
            pj.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return result

    def down(self, ctx: MigrationContext) -> MigrationResult:
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        for f in ctx.project_path.glob("wiki/**/*.md"):
            text = f.read_text(encoding="utf-8")
            new_text = re.sub(r"\n?grade: [ABC]\n", "\n", text)
            new_text = re.sub(r"\n?processing_depth: (concept|memory)\n", "\n", new_text)
            new_text = re.sub(r"\n?is_immutable: (true|false)\n", "\n", new_text)
            if new_text != text:
                f.write_text(new_text, encoding="utf-8")
                result.files_changed += 1
        return result

    def _add_v22_fields(self, text: str) -> str:
        """Add grade/processing_depth/is_immutable if missing."""
        if "grade:" not in text:
            text = text.replace(
                "schema_version: v2.0", "schema_version: v2.0\ngrade: B", 1
            )
        if "processing_depth:" not in text:
            text = text.replace(
                "schema_version: v2.0",
                "schema_version: v2.0\nprocessing_depth: concept",
                1,
            )
        if "is_immutable:" not in text:
            text = text.replace(
                "schema_version: v2.0",
                "schema_version: v2.0\nis_immutable: false",
                1,
            )
        return text

    def _convert_id_to_uuid_v7(self, text: str) -> str:
        """Convert 'id: <slug>' to 'id: card_<millis>_<rand>_<slug>'."""
        m = re.search(r"^id: ([a-z0-9-]+)$", text, re.MULTILINE)
        if m and not ID_PATTERN.match(m.group(1)):
            slug = m.group(1)
            new_id = generate_page_id(slug)
            text = text.replace(f"id: {slug}", f"id: {new_id}", 1)
        return text


MigrationRegistry.register(
    "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_2, V2ToV2_2WikiPageMigration()
)