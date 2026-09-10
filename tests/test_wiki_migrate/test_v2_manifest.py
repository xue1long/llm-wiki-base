from __future__ import annotations

import hashlib
import json

import pytest

from src.wiki.migrate.v2_manifest import (
    ALLOWED_DISPOSITIONS,
    ManifestError,
    MigrationManifest,
    build_manifest,
    load_manifest,
    save_manifest,
)


def _write(root, relative: str, content: bytes = b"content"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_build_manifest_covers_raw_wiki_and_support_with_one_disposition(tmp_path):
    v2 = tmp_path / "v2"
    target = tmp_path / "target"
    _write(v2, "10_raw/01_B站视频转录/video.txt", b"raw")
    _write(v2, "10_raw/_archive/old.md")
    _write(v2, "10_raw/_skip/ignored.md")
    _write(v2, "10_raw/_seed/seed.md")
    _write(v2, "10_raw/metadata.batch", b"{}")
    _write(v2, "20_wiki/concepts/concept.md")
    _write(v2, "20_wiki/concepts/_to_recompile/draft.md")
    _write(v2, "20_wiki/entities/entity.md")
    _write(v2, "20_wiki/invalid_bad.md")
    _write(v2, "20_wiki/links.md")
    _write(v2, "20_wiki/overview.md")

    manifest = build_manifest(v2, target, "run-001")

    assert isinstance(manifest, MigrationManifest)
    assert manifest.run_id == "run-001"
    assert len(manifest.items) == 11
    assert len({item.source_path for item in manifest.items}) == 11
    assert all(item.disposition in ALLOWED_DISPOSITIONS for item in manifest.items)
    assert manifest.counts["total"] == 11
    assert manifest.counts["raw"] == 5
    assert manifest.counts["wiki"] == 6

    by_source = {item.source_path: item for item in manifest.items}
    assert by_source["10_raw/01_B站视频转录/video.txt"].target_path == (
        "raw/sources/01_B站视频转录/video.txt"
    )
    assert by_source["10_raw/_archive/old.md"].disposition == "archived"
    assert by_source["10_raw/_skip/ignored.md"].disposition == "skipped"
    assert by_source["10_raw/_seed/seed.md"].kind == "seed"
    assert by_source["10_raw/metadata.batch"].disposition == "metadata-only"
    assert by_source["20_wiki/concepts/_to_recompile/draft.md"].target_path == (
        "wiki/_pending/draft.md"
    )
    assert by_source["20_wiki/invalid_bad.md"].disposition == "quarantined"
    assert by_source["20_wiki/links.md"].disposition == "support-artifact"


def test_manifest_records_sha256_size_and_has_stable_digest(tmp_path):
    v2 = tmp_path / "v2"
    target = tmp_path / "target"
    source = _write(v2, "10_raw/a.txt", b"hello")

    manifest = build_manifest(v2, target, "run-001")
    item = manifest.items[0]
    assert item.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert item.size == 5
    assert manifest.manifest_hash == manifest.digest()
    assert manifest.manifest_hash == build_manifest(v2, target, "run-001").manifest_hash

    path = save_manifest(target, manifest)
    loaded = load_manifest(path)
    assert loaded.to_dict() == manifest.to_dict()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["manifest_hash"] == manifest.manifest_hash


def test_manifest_rejects_invalid_disposition_and_duplicate_source():
    with pytest.raises(ManifestError, match="disposition"):
        MigrationManifest(
            run_id="run-001",
            source_root="v2",
            project_root="target",
            items=[
                {
                    "source_path": "a",
                    "sha256": "0" * 64,
                    "size": 0,
                    "kind": "raw",
                    "disposition": "unknown",
                    "target_path": "raw/sources/a",
                    "reason": "test",
                }
            ],
        )

    with pytest.raises(ManifestError, match="duplicate"):
        MigrationManifest(
            run_id="run-001",
            source_root="v2",
            project_root="target",
            items=[
                {
                    "source_path": "a",
                    "sha256": "0" * 64,
                    "size": 0,
                    "kind": "raw",
                    "disposition": "skipped",
                    "target_path": "raw/_skip/a",
                    "reason": "test",
                },
                {
                    "source_path": "a",
                    "sha256": "0" * 64,
                    "size": 0,
                    "kind": "raw",
                    "disposition": "skipped",
                    "target_path": "raw/_skip/a",
                    "reason": "test",
                },
            ],
        )


def test_manifest_refuses_target_escape(tmp_path):
    v2 = tmp_path / "v2"
    _write(v2, "10_raw/a.txt")
    with pytest.raises(ManifestError, match="outside project root"):
        MigrationManifest(
            run_id="run-001",
            source_root=str(v2),
            project_root=str(tmp_path / "target"),
            items=[
                {
                    "source_path": "10_raw/a.txt",
                    "sha256": "0" * 64,
                    "size": 7,
                    "kind": "raw",
                    "disposition": "migrated",
                    "target_path": "../escape.txt",
                    "reason": "test",
                }
            ],
        )
