"""VersionManager — snapshot, history, diff, and retention for KnowledgeObjects."""
import dataclasses
import json
import time
import uuid
from pathlib import Path

from src.knowledge.core.object import (
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
    KnowledgeObject,
)
from src.lib.write_hooks import safe_write

# Lifecycle states that are always preserved during retention
KEY_LIFECYCLE_STATES = frozenset({
    LifecycleState.CREATED.value,
    LifecycleState.ACTIVE.value,
    LifecycleState.ARCHIVED.value,
})

MAX_VERSIONS = 50


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_object(obj: KnowledgeObject) -> dict:
    """Convert a KnowledgeObject to a JSON-serializable dict."""
    return {
        "id": obj.id,
        "type": obj.type.value,
        "title": obj.title,
        "content": obj.content,
        "lifecycle": obj.lifecycle.value,
        "confidence": obj.confidence,
        "provenance": dataclasses.asdict(obj.provenance),
        "grade": obj.grade,
        "heat": obj.heat,
        "relations": obj.relations,
        "versions": [dataclasses.asdict(v) for v in obj.versions],
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }


def _deserialize_object(data: dict) -> KnowledgeObject:
    """Reconstruct a KnowledgeObject from a dict (snapshot file)."""
    return KnowledgeObject(
        id=data["id"],
        type=KnowledgeType(data["type"]),
        title=data["title"],
        content=data["content"],
        lifecycle=LifecycleState(data["lifecycle"]),
        confidence=data["confidence"],
        provenance=Provenance(**data["provenance"]),
        grade=data.get("grade", "B"),
        heat=data.get("heat", 50),
        relations=data.get("relations", []),
        versions=[VersionRef(**v) for v in data.get("versions", [])],
        created_at=data.get("created_at", 0),
        updated_at=data.get("updated_at", 0),
    )


# ---------------------------------------------------------------------------
# VersionManager
# ---------------------------------------------------------------------------

class VersionManager:
    """Manages version snapshots for KnowledgeObjects.

    Stores snapshots as JSON files under ``.index/versions/{object_id}/``.
    Each file is named ``{version_id}.json`` and contains the full serialized
    KnowledgeObject state.  A ``_history.json`` manifest tracks the version
    list per object, and a global ``_version_index.json`` maps version_id to
    object_id so that ``diff()`` can locate snapshots without an explicit
    object_id parameter.

    Retention policy: keep the last 50 versions plus any snapshots whose
    lifecycle state is CREATED, ACTIVE, or ARCHIVED.  Excess snapshots are
    moved to ``_archive/``.
    """

    def __init__(self, base_path: Path | str) -> None:
        self.base_path = Path(base_path)

    # ---- path helpers ------------------------------------------------------

    def _versions_root(self) -> Path:
        """Return the top-level versions directory."""
        return self.base_path / "versions"

    def _versions_dir(self, object_id: str) -> Path:
        """Return the per-object versions directory."""
        return self._versions_root() / object_id

    def _archive_dir(self, object_id: str) -> Path:
        """Return the archive directory for excess versions of *object_id*."""
        return self._versions_dir(object_id) / "_archive"

    def _manifest_path(self, object_id: str) -> Path:
        """Return the path to the per-object history manifest."""
        return self._versions_dir(object_id) / "_history.json"

    def _version_file_path(self, object_id: str, version_id: str) -> Path:
        """Return the path to a specific version snapshot file."""
        return self._versions_dir(object_id) / f"{version_id}.json"

    def _global_index_path(self) -> Path:
        """Return the path to the global version_id → object_id index."""
        return self._versions_root() / "_version_index.json"

    # ---- manifest I/O ------------------------------------------------------

    def _load_manifest(self, object_id: str) -> list[dict]:
        """Load the history manifest for *object_id*, or return empty list."""
        mp = self._manifest_path(object_id)
        if not mp.exists():
            return []
        return json.loads(mp.read_text(encoding="utf-8"))

    def _save_manifest(self, object_id: str, manifest: list[dict]) -> None:
        """Persist the history manifest atomically."""
        content = json.dumps(manifest, ensure_ascii=False, indent=2)
        safe_write(self._manifest_path(object_id), content)

    # ---- global index I/O --------------------------------------------------

    def _load_global_index(self) -> dict[str, str]:
        """Load the version_id → object_id mapping, or return empty dict."""
        ip = self._global_index_path()
        if not ip.exists():
            return {}
        return json.loads(ip.read_text(encoding="utf-8"))

    def _save_global_index(self, index: dict[str, str]) -> None:
        """Persist the global index atomically."""
        content = json.dumps(index, ensure_ascii=False, indent=2)
        safe_write(self._global_index_path(), content)

    # ---- snapshot ----------------------------------------------------------

    def snapshot(self, obj: KnowledgeObject) -> VersionRef:
        """Snapshot *obj* before mutation and persist it.

        Returns a ``VersionRef`` referencing the new snapshot.
        Side-effects: appends the ``VersionRef`` to ``obj.versions``,
        writes the snapshot JSON, updates the manifest, updates the global
        index, and applies retention.
        """
        timestamp = int(time.time() * 1000)
        version_id = f"v_{timestamp}_{uuid.uuid4().hex[:8]}"
        vref = VersionRef(version_id=version_id, timestamp=timestamp)

        # Link the ref into the object
        obj.versions.append(vref)

        # Serialize and write the snapshot
        data = _serialize_object(obj)
        version_path = self._version_file_path(obj.id, version_id)
        safe_write(version_path, json.dumps(data, ensure_ascii=False, indent=2))

        # Update the per-object manifest
        manifest = self._load_manifest(obj.id)
        manifest.append({
            "version_id": version_id,
            "timestamp": timestamp,
            "change_description": "",
            "lifecycle": obj.lifecycle.value,
        })

        # Apply retention before saving manifest
        manifest = self._apply_retention(obj.id, manifest)
        self._save_manifest(obj.id, manifest)

        # Update the global version_id → object_id index
        index = self._load_global_index()
        index[version_id] = obj.id
        self._save_global_index(index)

        return vref

    # ---- retention ---------------------------------------------------------

    def _apply_retention(self, object_id: str, manifest: list[dict]) -> list[dict]:
        """Enforce the retention policy on *manifest*.

        Keeps the 50 most-recent versions plus any versions whose lifecycle
        is in ``KEY_LIFECYCLE_STATES``.  Moves excess snapshot files to the
        ``_archive/`` subdirectory.  Returns the pruned manifest (sorted
        chronologically).
        """
        if len(manifest) <= MAX_VERSIONS:
            return manifest

        # Sort by timestamp descending (newest first)
        sorted_entries = sorted(manifest, key=lambda e: e["timestamp"], reverse=True)

        kept: list[dict] = []
        to_archive: list[dict] = []

        for i, entry in enumerate(sorted_entries):
            if i < MAX_VERSIONS:
                kept.append(entry)
            elif entry.get("lifecycle") in KEY_LIFECYCLE_STATES:
                kept.append(entry)
            else:
                to_archive.append(entry)

        # Move archived snapshot files to _archive/
        if to_archive:
            archive_dir = self._archive_dir(object_id)
            archive_dir.mkdir(parents=True, exist_ok=True)
            for entry in to_archive:
                version_file = self._version_file_path(object_id, entry["version_id"])
                archive_file = archive_dir / f"{entry['version_id']}.json"
                if version_file.exists():
                    version_file.rename(archive_file)

        # Return kept entries sorted chronologically
        kept.sort(key=lambda e: e["timestamp"])
        return kept

    # ---- history -----------------------------------------------------------

    def get_history(self, object_id: str) -> list[VersionRef]:
        """Return all version snapshots for *object_id* in timestamp order."""
        manifest = self._load_manifest(object_id)
        return [
            VersionRef(
                version_id=e["version_id"],
                timestamp=e["timestamp"],
                change_description=e.get("change_description", ""),
            )
            for e in manifest
        ]

    # ---- diff --------------------------------------------------------------

    def diff(self, v1: VersionRef, v2: VersionRef) -> dict:
        """Compare two version snapshots.

        Returns a dict mapping each changed field name to
        ``{"old": <v1 value>, "new": <v2 value>}``.  The ``versions``
        metadata field is excluded from the comparison.

        Raises ``ValueError`` if either version is unknown or if the two
        versions belong to different objects.
        """
        index = self._load_global_index()

        obj_id = index.get(v1.version_id)
        if obj_id is None:
            raise ValueError(f"Version {v1.version_id} not found in index")

        v2_obj_id = index.get(v2.version_id)
        if v2_obj_id is None:
            raise ValueError(f"Version {v2.version_id} not found in index")

        if v2_obj_id != obj_id:
            raise ValueError(
                f"Versions belong to different objects: "
                f"{v1.version_id} -> {obj_id}, {v2.version_id} -> {v2_obj_id}"
            )

        data1 = self._load_version_data(obj_id, v1.version_id)
        data2 = self._load_version_data(obj_id, v2.version_id)

        changes: dict = {}
        all_keys = set(data1.keys()) | set(data2.keys())

        for key in sorted(all_keys):
            if key == "versions":
                continue  # Metadata field — excluded from diff
            val1 = data1.get(key)
            val2 = data2.get(key)
            if val1 != val2:
                changes[key] = {"old": val1, "new": val2}

        return changes

    def _load_version_data(self, object_id: str, version_id: str) -> dict:
        """Load the raw snapshot data for a specific version.

        Checks both the primary location and the archive directory.
        Raises ``FileNotFoundError`` if the version snapshot cannot be found.
        """
        version_path = self._version_file_path(object_id, version_id)
        if not version_path.exists():
            archive_path = self._archive_dir(object_id) / f"{version_id}.json"
            if archive_path.exists():
                version_path = archive_path
            else:
                raise FileNotFoundError(
                    f"Version {version_id} snapshot not found for object {object_id}"
                )
        return json.loads(version_path.read_text(encoding="utf-8"))
