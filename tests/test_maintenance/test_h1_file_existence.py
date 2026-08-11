"""Tests for H1 file-existence check."""
from src.maintenance.checks.h1_file_existence import H1FileExistenceCheck
from src.maintenance.health_check import CheckSeverity


def test_h1_passes_when_all_sources_exist(tmp_path):
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "raw" / "sources" / "foo.pdf").write_bytes(b"x")
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "foo.md").write_text(
        "---\nid: foo\nsources: [raw/sources/foo.pdf]\n---\nbody\n",
        encoding="utf-8",
    )

    check = H1FileExistenceCheck(tmp_path)
    result = check.run()

    assert result.passed
    assert result.issue_count == 0
    assert result.stats["pages_checked"] == 1
    assert result.stats["sources_checked"] == 1


def test_h1_fails_on_missing_source(tmp_path):
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "foo.md").write_text(
        "---\nid: foo\nsources: [raw/sources/missing.pdf]\n---\nbody\n",
        encoding="utf-8",
    )

    check = H1FileExistenceCheck(tmp_path)
    result = check.run()

    assert not result.passed
    assert result.issue_count == 1
    issue = result.issues[0]
    assert issue.severity == CheckSeverity.ERROR
    assert issue.code == "H1-MISSING-FILE"
    assert "raw/sources/missing.pdf" in issue.message


def test_h1_absolute_paths_checked(tmp_path):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "abs.md").write_text(
        "---\nid: abs\nsources: [/nonexistent/path/file.pdf]\n---\nbody\n",
        encoding="utf-8",
    )

    check = H1FileExistenceCheck(tmp_path)
    result = check.run()

    assert not result.passed
    assert result.issue_count == 1
