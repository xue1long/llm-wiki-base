from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.wiki.migrate.v2_raw import (
    RawCollisionError,
    RawHashError,
    RawPathError,
    classify_raw,
    collect_raw_files,
    copy_raw_file,
    detect_collisions,
    map_raw_path,
    sha256_file,
)


def test_map_raw_paths_for_platforms_and_special_directories(tmp_path: Path):
    assert map_raw_path(Path("10_raw/01_B站视频转录/X.txt"), tmp_path).name == "X.txt"
    assert map_raw_path(Path("10_raw/02_抖音视频笔记/X.md"), tmp_path).name == "X.md"
    assert map_raw_path(Path("10_raw/03_小红书收藏夹/X.md"), tmp_path).name == "X.md"
    assert map_raw_path(Path("10_raw/_archive/old.txt"), tmp_path) == (
        tmp_path / "raw" / "_archive" / "old.txt"
    )


def test_collect_raw_files_excludes_skip_by_default(tmp_path: Path):
    (tmp_path / "01_B站视频转录").mkdir()
    (tmp_path / "01_B站视频转录" / "keep.txt").write_text("x", encoding="utf-8")
    (tmp_path / "_skip").mkdir()
    (tmp_path / "_skip" / "skip.txt").write_text("x", encoding="utf-8")

    assert [p.name for p in collect_raw_files(tmp_path)] == ["keep.txt"]
    assert {p.name for p in collect_raw_files(tmp_path, include_skip=True)} == {
        "keep.txt",
        "skip.txt",
    }


def test_detect_collisions_and_optional_platform_prefix(tmp_path: Path):
    files = [
        Path("10_raw/01_B站视频转录/123.txt"),
        Path("10_raw/02_抖音视频笔记/123.txt"),
    ]
    assert len(detect_collisions(files, tmp_path)) == 1
    assert map_raw_path(files[0], tmp_path, add_platform_prefix=True).name == (
        "01_B站视频转录__123.txt"
    )


def test_sha256_and_safe_staging_copy(tmp_path: Path):
    source = tmp_path / "source.bin"
    source.write_bytes(bytes(range(32)))
    staging = tmp_path / "staging"
    target = staging / "raw" / "sources" / "source.bin"

    copied = copy_raw_file(
        source,
        target,
        staging_root=staging,
        expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    assert copied == target
    assert target.read_bytes() == source.read_bytes()
    assert sha256_file(target) == sha256_file(source)


def test_raw_copy_rejects_traversal_collision_and_hash_failure(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("content", encoding="utf-8")
    staging = tmp_path / "staging"

    with pytest.raises(RawPathError):
        copy_raw_file(source, staging / ".." / "escape.txt", staging_root=staging)
    with pytest.raises(RawHashError):
        copy_raw_file(source, staging / "raw" / "source.txt", staging_root=staging, expected_sha256="0" * 64)

    target = staging / "raw" / "source.txt"
    target.parent.mkdir(parents=True)
    target.write_text("other", encoding="utf-8")
    with pytest.raises(RawCollisionError):
        copy_raw_file(source, target, staging_root=staging)


def test_classify_raw_dispositions():
    assert classify_raw(Path("10_raw/a.txt"))["disposition"] == "migrated"
    assert classify_raw(Path("10_raw/_archive/a.txt"))["disposition"] == "archived"
    assert classify_raw(Path("10_raw/_skip/a.txt"))["disposition"] == "skipped"
    assert classify_raw(Path("10_raw/_seed/a.txt"))["kind"] == "seed"
    assert classify_raw(Path("10_raw/meta.batch"))["disposition"] == "metadata-only"
