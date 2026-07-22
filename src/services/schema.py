"""Schema migration listing per project.

Extracted from src/server/routes/schema.py. Computes the reachable
migration edges for a project, filtered by the project's current
schema_version.
"""
from __future__ import annotations

from ..project.registry import GlobalRegistryStore
from ..schemas.migration import SchemaVersion
from ..schemas.registry import MigrationRegistry


def get_schema(project_id: str) -> dict:
    """Return reachable migrations for a project.

    Returns a dict matching the previous route response:
        {
            "project_id": str,
            "schema_version": str | None,
            "schemas": [{"schema": str, "from": str, "to": str}, ...],
        }

    If the project is unknown or has an invalid schema_version, the
    list is empty rather than leaking the full registry.
    """
    project_version: SchemaVersion | None = None
    try:
        entry = (
            GlobalRegistryStore.by_id(project_id)
            or GlobalRegistryStore.by_name(project_id)
        )
        if entry and entry.schema_version:
            try:
                project_version = SchemaVersion(entry.schema_version)
            except ValueError:
                project_version = None
    except Exception:
        project_version = None

    all_migrations = MigrationRegistry.list_migrations()
    if project_version is None:
        schemas: list[dict[str, str]] = []
    else:
        # Order versions so we can compare with <=
        version_order = {v.value: i for i, v in enumerate(SchemaVersion)}
        project_idx = version_order.get(project_version.value, -1)
        schemas = [
            {"schema": s, "from": f, "to": t}
            for s, f, t in all_migrations
            if version_order.get(f, -1) <= project_idx
        ]

    return {
        "project_id": project_id,
        "schema_version": project_version.value if project_version else None,
        "schemas": schemas,
    }
