"""ProvenanceTracker — records and queries source → claim → knowledge chains.

Stores provenance data in a JSON file at ``{wiki_paths.index}/provenance.json``
with two indices:

* ``_sources`` — forward index: source_path → {derived_objects, source_status}
* ``_objects`` — reverse index: object_id → {derived_from}
"""
import json
from pathlib import Path

from src.lib.write_hooks import safe_write


class ProvenanceTracker:
    """Records and queries source → claim → knowledge provenance chains."""

    def __init__(self, wiki_paths):
        """Initialise the tracker from a WikiPaths object.

        The backing store is ``{wiki_paths.index}/provenance.json``.  If the
        file does not exist an empty store is created.
        """
        self._wiki_paths = wiki_paths
        self._store_path = Path(wiki_paths.index) / "provenance.json"
        self._data = self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        """Load the provenance store from disk, or return an empty default."""
        if self._store_path.exists():
            try:
                raw = self._store_path.read_text(encoding="utf-8")
                return json.loads(raw)
            except (json.JSONDecodeError, OSError):
                pass
        return {"_sources": {}, "_objects": {}}

    def _save(self) -> None:
        """Persist the provenance store atomically via safe_write."""
        safe_write(self._store_path, json.dumps(self._data, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_derivation(self, source_path: str, derived_object_id: str) -> None:
        """Record that *derived_object_id* was derived from *source_path*.

        Idempotent: calling multiple times with the same pair has no
        additional effect.
        """
        # Forward index
        sources = self._data.setdefault("_sources", {})
        entry = sources.setdefault(source_path, {"derived_objects": [], "source_status": "active"})
        if derived_object_id not in entry["derived_objects"]:
            entry["derived_objects"].append(derived_object_id)

        # Reverse index
        objects = self._data.setdefault("_objects", {})
        if derived_object_id not in objects:
            objects[derived_object_id] = {"derived_from": source_path}

        self._save()

    def get_derived_objects(self, source_path: str) -> list[str]:
        """Return all object IDs derived from the given source.

        Returns an empty list for unknown sources.
        """
        sources = self._data.get("_sources", {})
        entry = sources.get(source_path)
        if entry is None:
            return []
        return list(entry.get("derived_objects", []))

    def mark_source_deleted(self, source_path: str) -> None:
        """Mark all objects derived from *source_path* with ``source_status: deleted``.

        Does NOT delete the derived objects — preserves the provenance chain.
        No-op for unknown sources.
        """
        sources = self._data.setdefault("_sources", {})
        entry = sources.get(source_path)
        if entry is not None:
            entry["source_status"] = "deleted"
            self._save()

    def get_provenance_chain(self, object_id: str) -> dict:
        """Return the full provenance chain for an object.

        Returns a dict with keys ``source_path``, ``derived_from``,
        ``derived_objects``, and ``source_status``.  Returns an empty dict
        for unknown objects.
        """
        objects = self._data.get("_objects", {})
        obj_entry = objects.get(object_id)
        if obj_entry is None:
            return {}

        source_path = obj_entry["derived_from"]

        sources = self._data.get("_sources", {})
        src_entry = sources.get(source_path, {})

        return {
            "source_path": source_path,
            "derived_from": source_path,
            "derived_objects": list(src_entry.get("derived_objects", [])),
            "source_status": src_entry.get("source_status", "active"),
        }
