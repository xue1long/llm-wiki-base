"""Test VersionManager — snapshot, history, diff, retention, atomic write (Task 1.4)."""
import json
from pathlib import Path

import pytest

from src.knowledge.core.object import (
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
    KnowledgeObject,
)
from src.knowledge.core.version_manager import VersionManager


def _make_object(obj_id="ko-001", lifecycle=LifecycleState.CREATED, content="original content", title="Test Object"):
    """Minimal helper to create a KnowledgeObject for testing."""
    return KnowledgeObject(
        id=obj_id,
        type=KnowledgeType.ENTITY,
        title=title,
        content=content,
        lifecycle=lifecycle,
        confidence=0.9,
        provenance=Provenance(source_path="/test.md"),
    )


class TestVersionManagerSnapshot:
    """snapshot() creates a VersionRef and persists the object state."""

    def test_snapshot_returns_versionref_with_correct_fields(self, tmp_path):
        """snapshot() returns a VersionRef with version_id and timestamp."""
        vm = VersionManager(tmp_path)
        obj = _make_object()

        vref = vm.snapshot(obj)

        assert isinstance(vref, VersionRef)
        assert vref.version_id.startswith("v_")
        assert vref.timestamp > 0

    def test_snapshot_persists_object_to_disk_as_valid_json(self, tmp_path):
        """snapshot() writes a complete, valid JSON snapshot file."""
        vm = VersionManager(tmp_path)
        obj = _make_object()

        vref = vm.snapshot(obj)

        version_file = tmp_path / "versions" / obj.id / f"{vref.version_id}.json"
        assert version_file.exists(), f"Expected snapshot file at {version_file}"

        data = json.loads(version_file.read_text(encoding="utf-8"))
        assert data["id"] == obj.id
        assert data["title"] == "Test Object"
        assert data["content"] == "original content"
        assert data["lifecycle"] == "created"
        assert data["type"] == "entity"

    def test_snapshot_appends_versionref_to_object_versions_list(self, tmp_path):
        """After snapshot, the object's versions list includes the new VersionRef."""
        vm = VersionManager(tmp_path)
        obj = _make_object()
        assert len(obj.versions) == 0

        vref = vm.snapshot(obj)

        assert len(obj.versions) == 1
        assert obj.versions[0].version_id == vref.version_id
        assert obj.versions[0].timestamp == vref.timestamp


class TestVersionManagerGetHistory:
    """get_history() returns all version snapshots in chronological order."""

    def test_get_history_returns_all_snapshots_in_timestamp_order(self, tmp_path):
        """Snapshots are returned sorted by timestamp (oldest first)."""
        vm = VersionManager(tmp_path)
        obj = _make_object()

        v1 = vm.snapshot(obj)
        v2 = vm.snapshot(obj)
        v3 = vm.snapshot(obj)

        history = vm.get_history(obj.id)
        assert len(history) == 3
        assert history[0].version_id == v1.version_id
        assert history[1].version_id == v2.version_id
        assert history[2].version_id == v3.version_id

    def test_get_history_returns_empty_list_for_unknown_object(self, tmp_path):
        """get_history() returns an empty list for objects with no snapshots."""
        vm = VersionManager(tmp_path)
        history = vm.get_history("nonexistent")
        assert history == []


class TestVersionManagerDiff:
    """diff() compares two versions and returns changed fields."""

    def test_diff_detects_changed_content_and_title(self, tmp_path):
        """diff() returns old/new values for every changed field."""
        vm = VersionManager(tmp_path)
        obj = _make_object(content="version one", title="First")
        v1 = vm.snapshot(obj)

        obj.content = "version two"
        obj.title = "Second"
        v2 = vm.snapshot(obj)

        result = vm.diff(v1, v2)

        assert "content" in result
        assert result["content"] == {"old": "version one", "new": "version two"}
        assert "title" in result
        assert result["title"] == {"old": "First", "new": "Second"}

    def test_diff_identical_versions_returns_empty_dict(self, tmp_path):
        """diff() on the same version returns an empty changeset."""
        vm = VersionManager(tmp_path)
        obj = _make_object()
        v1 = vm.snapshot(obj)

        result = vm.diff(v1, v1)
        assert result == {}

    def test_diff_unchanged_object_returns_empty_dict(self, tmp_path):
        """diff() between two snapshots with no changes returns empty dict."""
        vm = VersionManager(tmp_path)
        obj = _make_object()
        v1 = vm.snapshot(obj)
        v2 = vm.snapshot(obj)

        result = vm.diff(v1, v2)
        assert result == {}

    def test_diff_raises_on_unknown_version(self, tmp_path):
        """diff() raises ValueError when a version_id is not found."""
        vm = VersionManager(tmp_path)
        obj = _make_object()
        v1 = vm.snapshot(obj)

        ghost = VersionRef(version_id="v_nonexistent", timestamp=0)
        with pytest.raises(ValueError, match="not found"):
            vm.diff(v1, ghost)

    def test_diff_raises_on_different_objects(self, tmp_path):
        """diff() raises ValueError when versions belong to different objects."""
        vm = VersionManager(tmp_path)
        obj_a = _make_object(obj_id="ko-a")
        obj_b = _make_object(obj_id="ko-b")
        v_a = vm.snapshot(obj_a)
        v_b = vm.snapshot(obj_b)

        with pytest.raises(ValueError, match="different objects"):
            vm.diff(v_a, v_b)

    def test_diff_skips_versions_metadata_field(self, tmp_path):
        """diff() excludes the 'versions' metadata field from comparison."""
        vm = VersionManager(tmp_path)
        obj = _make_object()
        v1 = vm.snapshot(obj)  # v1 has versions=[v1]
        v2 = vm.snapshot(obj)  # v2 has versions=[v1, v2]

        result = vm.diff(v1, v2)
        # 'versions' field differs (v1 has 1 ref, v2 has 2 refs) but is excluded
        assert "versions" not in result


class TestVersionManagerRetention:
    """Retention policy keeps last 50 versions + key lifecycle change points."""

    def test_retention_limits_to_50_when_exceeding_max(self, tmp_path):
        """After >50 snapshots with non-key lifecycle, only 50 are kept."""
        vm = VersionManager(tmp_path)
        obj = _make_object(lifecycle=LifecycleState.PROCESSING)

        for _ in range(55):
            vm.snapshot(obj)

        history = vm.get_history(obj.id)
        assert len(history) == 50

        archive_dir = tmp_path / "versions" / obj.id / "_archive"
        assert archive_dir.exists()
        archived = list(archive_dir.glob("*.json"))
        assert len(archived) == 5

    def test_retention_preserves_key_lifecycle_versions_in_overflow(self, tmp_path):
        """Key lifecycle versions (CREATED, ACTIVE, ARCHIVED) survive retention
        even when they fall outside the last-50 window."""
        vm = VersionManager(tmp_path)
        obj = _make_object(lifecycle=LifecycleState.CREATED)

        # First snapshot with CREATED — this will eventually fall outside last 50
        key_vref = vm.snapshot(obj)

        # Push it out of the last-50 window with 55 PROCESSING snapshots
        obj.lifecycle = LifecycleState.PROCESSING
        for _ in range(55):
            vm.snapshot(obj)

        history = vm.get_history(obj.id)
        history_ids = {v.version_id for v in history}
        assert key_vref.version_id in history_ids, (
            "CREATED lifecycle version should be retained even beyond 50-version window"
        )

    def test_archived_files_moved_to_archive_subdirectory(self, tmp_path):
        """Archived snapshots are moved to _archive/, not deleted."""
        vm = VersionManager(tmp_path)
        obj = _make_object(lifecycle=LifecycleState.PROCESSING)

        first_vref = vm.snapshot(obj)  # This will be the oldest, get archived
        for _ in range(54):
            vm.snapshot(obj)

        archive_dir = tmp_path / "versions" / obj.id / "_archive"
        archive_file = archive_dir / f"{first_vref.version_id}.json"
        assert archive_file.exists(), (
            f"Archived version {first_vref.version_id} should be in _archive/"
        )

        # The original location should no longer have it
        original = tmp_path / "versions" / obj.id / f"{first_vref.version_id}.json"
        assert not original.exists(), (
            "Archived version should be moved (not copied) out of versions dir"
        )


class TestVersionManagerAtomicWrite:
    """Snapshot writes are atomic — no .tmp leftovers, no corrupt data."""

    def test_no_temp_files_left_behind_after_snapshot(self, tmp_path):
        """After a successful snapshot, no .tmp files remain on disk."""
        vm = VersionManager(tmp_path)
        obj = _make_object()
        vm.snapshot(obj)

        versions_dir = tmp_path / "versions" / obj.id
        tmp_files = list(versions_dir.glob("*.tmp"))
        assert len(tmp_files) == 0, (
            f"Found .tmp files after snapshot: {tmp_files}"
        )

    def test_snapshot_file_is_complete_and_deserializable(self, tmp_path):
        """A written snapshot file contains all required fields and can be
        reconstructed into a KnowledgeObject."""
        vm = VersionManager(tmp_path)
        obj = _make_object()
        vref = vm.snapshot(obj)

        version_file = tmp_path / "versions" / obj.id / f"{vref.version_id}.json"
        content = version_file.read_text(encoding="utf-8")
        data = json.loads(content)

        # All core fields must be present
        for field in ("id", "type", "title", "content", "lifecycle",
                      "confidence", "grade", "heat", "provenance",
                      "relations", "versions", "created_at", "updated_at"):
            assert field in data, f"Missing field '{field}' in snapshot JSON"
