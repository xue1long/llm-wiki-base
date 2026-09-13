from __future__ import annotations

from pathlib import Path

import pytest

from src.skill_manager.manager import (
    build_artifact,
    inspect_source,
    validate_package_path,
)
from src.skill_manager.types import (
    Artifact,
    Deployment,
    PackageLimits,
    PackageValidationError,
    SourceSpec,
)


def _source(path: Path) -> SourceSpec:
    return SourceSpec(path=path)


def test_inspection_produces_distinct_domain_types_and_stable_artifact_hash(tmp_path: Path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: demo\n---\n\nUse it.\n", encoding="utf-8")
    (root / "references").mkdir()
    (root / "references" / "guide.md").write_text("guide", encoding="utf-8")

    source = _source(root)
    inspection = inspect_source(source)
    artifact = build_artifact(source)
    deployment = Deployment(
        deployment_id="deployment-1",
        artifact_id=artifact.artifact_id,
        target_id="codex",
        target_path="C:/Users/test/.codex/skills/demo",
        content_hash=artifact.content_hash,
    )

    assert inspection.package_type == "skill"
    assert inspection.name == "demo"
    assert inspection.content_hash == inspect_source(source).content_hash
    assert artifact.source == source
    assert artifact.content_hash == inspection.content_hash
    assert deployment.artifact_id == artifact.artifact_id
    assert deployment.target_id == "codex"
    with pytest.raises(AttributeError):
        source.path = tmp_path / "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        artifact.name = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        deployment.target_id = "claude"  # type: ignore[misc]


def test_plugin_manifest_is_rejected_before_any_package_is_accepted(tmp_path: Path):
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "SKILL.md").write_text("# not a plugin", encoding="utf-8")
    (root / "plugin.json").write_text('{"entrypoint":"run.py"}', encoding="utf-8")

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(_source(root))

    assert exc_info.value.code == "UNSUPPORTED_PLUGIN_TYPE"


def test_nested_plugin_manifest_is_rejected(tmp_path: Path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("# demo", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "plugin.json").write_text("{}", encoding="utf-8")

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(_source(root))

    assert exc_info.value.code == "UNSUPPORTED_PLUGIN_TYPE"


def test_package_scripts_are_never_executed(tmp_path: Path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("# demo", encoding="utf-8")
    sentinel = tmp_path / "executed.txt"
    (root / "run.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    inspect_source(_source(root))

    assert not sentinel.exists()


def test_source_path_validation_rejects_parent_escape(tmp_path: Path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("# demo", encoding="utf-8")

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(_source(root), extra_paths=[root / ".." / "escape.txt"])

    assert exc_info.value.code == "PATH_TRAVERSAL"


def test_public_package_path_validator_rejects_traversal_members():
    assert validate_package_path("references/guide.md") == "references/guide.md"
    for candidate in ("../escape.md", "references/../escape.md", "/absolute.md"):
        with pytest.raises(PackageValidationError) as exc_info:
            validate_package_path(candidate)
        assert exc_info.value.code == "PATH_TRAVERSAL"


def test_symlink_is_rejected_before_reading_the_target(tmp_path: Path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("# demo", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(_source(root))

    assert exc_info.value.code == "SYMLINK_NOT_ALLOWED"


def test_file_size_and_count_limits_are_enforced(tmp_path: Path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("# demo", encoding="utf-8")
    with pytest.raises(PackageValidationError) as size_error:
        inspect_source(_source(root), limits=PackageLimits(max_file_bytes=4))
    assert size_error.value.code == "FILE_TOO_LARGE"

    (root / "SKILL.md").write_text("ok", encoding="utf-8")
    (root / "one.txt").write_text("1", encoding="utf-8")
    (root / "two.txt").write_text("2", encoding="utf-8")
    with pytest.raises(PackageValidationError) as count_error:
        inspect_source(_source(root), limits=PackageLimits(max_files=2))
    assert count_error.value.code == "TOO_MANY_FILES"


def test_total_size_limit_is_enforced(tmp_path: Path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("12345", encoding="utf-8")
    (root / "reference.md").write_text("67890", encoding="utf-8")

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(
            _source(root),
            limits=PackageLimits(max_file_bytes=100, max_total_bytes=9, max_files=10),
        )

    assert exc_info.value.code == "PACKAGE_TOO_LARGE"


def test_manager_marker_is_reserved(tmp_path: Path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("# demo", encoding="utf-8")
    (root / ".ruflo-skill-manager.json").write_text("{}", encoding="utf-8")

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(_source(root))

    assert exc_info.value.code == "MANAGER_MARKER_NOT_ALLOWED"


def test_source_overlapping_manager_root_is_rejected(tmp_path: Path):
    root = tmp_path / "manager" / "skill"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("# demo", encoding="utf-8")

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(_source(root), forbidden_roots=[tmp_path / "manager"])

    assert exc_info.value.code == "SOURCE_SELF_CONTAINED"


def test_default_manager_library_root_is_forbidden(monkeypatch, tmp_path: Path):
    config = tmp_path / "config"
    library_source = config / "skill-manager" / "artifacts" / "demo"
    library_source.mkdir(parents=True)
    (library_source / "SKILL.md").write_text("# demo", encoding="utf-8")
    monkeypatch.setattr("src.skill_manager.manager.config_dir", lambda: config)

    with pytest.raises(PackageValidationError) as exc_info:
        inspect_source(_source(library_source))

    assert exc_info.value.code == "SOURCE_SELF_CONTAINED"
