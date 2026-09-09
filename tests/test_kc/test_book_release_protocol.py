from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.kc.views.book.wiki.compiler import (
    CandidateReleaseValidationError,
    load_candidate_lifecycle,
    validate_candidate_release,
    write_candidate_lifecycle,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(tmp_path: Path, *, state: str | None = None) -> tuple[Path, Path, str]:
    root = tmp_path / "project"
    (root / ".llm-wiki").mkdir(parents=True)
    (root / ".llm-wiki" / "project.json").write_text('{"id":"project-1"}\n', encoding="utf-8")
    release_id = "a" * 32
    release = root / ".index" / "book-wiki" / "versions" / release_id
    release.mkdir(parents=True)
    chapter = release / "chapter.md"
    chapter.write_text("# Chapter\n", encoding="utf-8")
    manifest = {
        "manifest_version": 1,
        "run_id": release_id,
        "project_id": "project-1",
        "snapshot_id": "snapshot-1",
        "release_status": "complete",
        "generation_mode": "llm",
        "files": {"chapter.md": _sha(chapter)},
    }
    manifest["release_manifest_hash"] = hashlib.sha256(_canonical(manifest)).hexdigest()
    (release / "manifest.json").write_bytes(_canonical(manifest) + b"\n")
    if state is not None:
        write_candidate_lifecycle(release, state=state, manifest=manifest)
    return root, release, release_id


def test_validate_candidate_returns_immutable_identity(tmp_path: Path):
    root, release, release_id = _candidate(tmp_path)

    candidate = validate_candidate_release(root, output_dir=root / "book-wiki", release_id=release_id)

    assert candidate.release_id == release_id
    assert candidate.source_dir == release
    assert candidate.manifest_sha256 == hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest()
    assert candidate.lifecycle_state == "candidate"
    assert candidate.files == (("chapter.md", _sha(release / "chapter.md")),)


@pytest.mark.parametrize("mutation", ["manifest", "file", "missing", "unsafe"])
def test_validate_candidate_rejects_tampering(tmp_path: Path, mutation: str):
    root, release, release_id = _candidate(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "manifest":
        manifest["snapshot_id"] = "changed"
        manifest_path.write_bytes(_canonical(manifest) + b"\n")
    elif mutation == "file":
        (release / "chapter.md").write_text("tampered\n", encoding="utf-8")
    elif mutation == "missing":
        (release / "chapter.md").unlink()
    else:
        manifest["files"] = {"../outside.md": "0" * 64}
        manifest["release_manifest_hash"] = hashlib.sha256(
            _canonical({key: value for key, value in manifest.items() if key != "release_manifest_hash"})
        ).hexdigest()
        manifest_path.write_bytes(_canonical(manifest) + b"\n")

    with pytest.raises(CandidateReleaseValidationError):
        validate_candidate_release(root, output_dir=root / "book-wiki", release_id=release_id)


def test_validate_candidate_rejects_cross_project_identity(tmp_path: Path):
    root, release, release_id = _candidate(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["project_id"] = "project-2"
    manifest["release_manifest_hash"] = hashlib.sha256(
        _canonical({key: value for key, value in manifest.items() if key != "release_manifest_hash"})
    ).hexdigest()
    manifest_path.write_bytes(_canonical(manifest) + b"\n")

    with pytest.raises(CandidateReleaseValidationError, match="project_identity"):
        validate_candidate_release(root, output_dir=root / "book-wiki", release_id=release_id)


@pytest.mark.parametrize("state", ["rejected", "expired", "superseded"])
def test_non_promotable_lifecycle_state_is_rejected(tmp_path: Path, state: str):
    root, release, release_id = _candidate(tmp_path, state=state)

    with pytest.raises(CandidateReleaseValidationError, match="lifecycle"):
        validate_candidate_release(root, output_dir=root / "book-wiki", release_id=release_id)


def test_lifecycle_sidecar_does_not_change_manifest_identity(tmp_path: Path):
    root, release, release_id = _candidate(tmp_path)
    before = (release / "manifest.json").read_bytes()
    manifest = json.loads(before)

    write_candidate_lifecycle(release, state="validated", manifest=manifest)

    assert (release / "manifest.json").read_bytes() == before
    assert load_candidate_lifecycle(release, manifest=manifest) == "validated"
    assert validate_candidate_release(root, output_dir=root / "book-wiki", release_id=release_id).lifecycle_state == "validated"
