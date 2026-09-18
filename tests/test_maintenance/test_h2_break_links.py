"""Tests for H2 break-links check."""
from src.maintenance.checks.h2_break_links import H2BreakLinksCheck


def test_h2_passes_when_all_wikilinks_resolve(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "foo.md").write_text(
        "---\nid: foo\n---\nbody", encoding="utf-8",
    )
    (tmp_path / "wiki" / "entities" / "bar.md").write_text(
        "---\nid: bar\n---\nsee [[foo]]\n", encoding="utf-8",
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert result.passed
    assert result.issue_count == 0


def test_h2_flags_broken_wikilink(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "foo.md").write_text(
        "---\nid: foo\n---\nsee [[missing-page]]\n", encoding="utf-8",
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.code == "H2-BROKEN-WIKILINK"
    assert issue.target == "missing-page"


def test_h2_flags_broken_relation(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "foo.md").write_text(
        "---\nid: foo\nrelations:\n  - target: ghost\n    type: references\n---\nbody",
        encoding="utf-8",
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.code == "H2-BROKEN-RELATION"


def test_h2_intentional_stub_not_broken(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "_stubs").mkdir(parents=True)
    (tmp_path / "wiki" / "_stubs" / "pending.md").write_text(
        "---\nid: pending\ntype: stub\n---\nstub", encoding="utf-8",
    )
    (tmp_path / "wiki" / "entities" / "foo.md").write_text(
        "---\nid: foo\n---\nsee [[pending]]", encoding="utf-8",
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert result.passed  # stub exempts wikilink
    assert result.issue_count == 0


def test_h2_treats_declared_taxonomy_as_virtual_target(tmp_path):
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    (tmp_path / "taxonomy.md").write_text(
        "# Taxonomy\n\n## Writing\n- Technique\n", encoding="utf-8",
    )
    (tmp_path / "wiki" / "concepts" / "foo.md").write_text(
        "---\nid: foo\ntype: concept\n---\nsee [[taxonomy/Technique]]",
        encoding="utf-8",
    )

    result = H2BreakLinksCheck(tmp_path).run()

    assert result.passed


def test_h2_rejects_undeclared_taxonomy_target(tmp_path):
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    (tmp_path / "taxonomy.md").write_text(
        "# Taxonomy\n\n## Writing\n- Technique\n", encoding="utf-8",
    )
    (tmp_path / "wiki" / "concepts" / "foo.md").write_text(
        "---\nid: foo\ntype: concept\n---\nsee [[taxonomy/Unknown]]",
        encoding="utf-8",
    )

    result = H2BreakLinksCheck(tmp_path).run()

    assert not result.passed
    assert result.issues[0].target == "taxonomy/Unknown"
