"""Tests for H4 ID format check."""
from src.maintenance.checks.h4_id_format import H4IdFormatCheck


def test_h4_passes_for_valid_uuid_v7_ids(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_lin-feng\n---\nbody",
        encoding="utf-8",
    )

    check = H4IdFormatCheck(tmp_path)
    result = check.run()
    assert result.passed
    assert result.issue_count == 0


def test_h4_warns_on_old_slug_format(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "a.md").write_text(
        "---\nid: lin-feng\n---\nbody", encoding="utf-8",
    )

    check = H4IdFormatCheck(tmp_path)
    result = check.run()
    # Warning (not error) keeps check "passed"
    assert result.passed
    assert result.issue_count == 1
    assert result.issues[0].code == "H4-INVALID-ID-FORMAT"


def test_h4_errors_on_missing_id(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "a.md").write_text(
        "---\ntitle: no id\n---\nbody", encoding="utf-8",
    )

    check = H4IdFormatCheck(tmp_path)
    result = check.run()
    assert not result.passed
    assert result.issues[0].code == "H4-MISSING-ID"
