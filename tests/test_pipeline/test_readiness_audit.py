from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline import readiness_audit
from src.pipeline.readiness_audit import (
    compare_readiness_records,
    read_readiness_record,
    write_readiness_record,
)


def _record(**overrides) -> dict:
    value = {
        "assessment_version": "content-readiness-v1",
        "policy_version": "content-policy-v1",
        "source_id": "raw/sources/example.md",
        "decision": "skip_no_content",
        "reason_codes": ["metadata_only"],
        "input_text_sha256": "a" * 64,
        "source_bytes_sha256": "b" * 64,
        "evidence_capacity": {"blocks": 0, "chars": 0, "units": 0},
        "failure_reason": "metadata_only",
    }
    value.update(overrides)
    return value


def test_write_is_atomic_versioned_and_excludes_source_body(tmp_path: Path) -> None:
    record = _record(source_text="must not be persisted", body="also forbidden")

    path = write_readiness_record(tmp_path, record)

    assert path.is_file()
    assert path.parent == tmp_path / ".index" / "quarantine" / "readiness" / "content-policy-v1"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "source_text" not in stored
    assert "body" not in stored
    assert read_readiness_record(path) == stored


def test_policy_version_change_does_not_overwrite_prior_record(tmp_path: Path) -> None:
    first = write_readiness_record(tmp_path, _record())
    second = write_readiness_record(
        tmp_path,
        _record(policy_version="content-policy-v0", decision="ready"),
    )

    assert first != second
    assert first.read_text(encoding="utf-8")
    assert read_readiness_record(second)["policy_version"] == "content-policy-v0"


def test_conflicting_duplicate_record_is_rejected(tmp_path: Path) -> None:
    write_readiness_record(tmp_path, _record())

    with pytest.raises(FileExistsError):
        write_readiness_record(tmp_path, _record(reason_codes=["policy_violation"]))


def test_corrupt_record_is_audit_error(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt"):
        read_readiness_record(path)


def test_compare_reports_decision_reason_and_policy_changes() -> None:
    diff = compare_readiness_records(
        _record(),
        _record(policy_version="content-policy-v0", decision="ready", reason_codes=[]),
    )

    assert diff["policy_version"] == {"old": "content-policy-v1", "new": "content-policy-v0"}
    assert diff["decision"] == {"old": "skip_no_content", "new": "ready"}
    assert diff["reason_codes"] == {"old": ["metadata_only"], "new": []}


def test_legacy_record_is_read_only(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="read-only"):
        write_readiness_record(tmp_path, _record(policy_version="legacy-sanitizer-v0"))


def test_replace_permission_failure_is_not_silenced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_replace(*args, **kwargs):
        raise PermissionError("audit directory denied")

    monkeypatch.setattr(readiness_audit.os, "replace", deny_replace)

    with pytest.raises(PermissionError, match="audit directory denied"):
        write_readiness_record(tmp_path, _record())
