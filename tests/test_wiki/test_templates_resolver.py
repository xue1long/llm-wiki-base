"""Tests for resolver.py include expansion + security (Phase 2).

Bug 1 fix: include paths must be bare filenames (no /, \\, ..).
Bug 15 fix: visited set prevents cycles.
"""
import pytest

from src.wiki.core.types import PageType
from src.wiki.templates.resolver import resolve, list_resolved


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_resolve_expands_include(tmp_path):
    """`<!-- include:_base.md -->` resolves the file and substitutes."""
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    _write(project, "_base.md", "<!-- shared boilerplate -->\n")
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:_base.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    t = resolve(PageType.CONCEPT, tmp_path)
    assert "<!-- shared boilerplate -->" in t.body_markdown
    assert "## 定义" in t.body_markdown


def test_resolve_include_path_traversal_blocked(tmp_path, monkeypatch):
    """Bug 1 fix: `<!-- include:../../etc/passwd -->` is rejected.

    Cannot test the actual filesystem path since this is inside tmp_path.
    Just verify the resolver raises ValueError for unsafe paths.
    """
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:../../etc/passwd -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    with pytest.raises(ValueError, match="bare filename"):
        resolve(PageType.CONCEPT, tmp_path)


def test_resolve_include_subdirectory_blocked(tmp_path):
    """`<!-- include:../other.md -->` is rejected (no parent traversal)."""
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:subdir/other.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    with pytest.raises(ValueError, match="bare filename"):
        resolve(PageType.CONCEPT, tmp_path)


def test_resolve_include_cycle_detected(tmp_path):
    """Bug 15 fix: concept → _base → concept cycle raises RecursionError.

    The cycle uses concept.md (the actual template name) and a
    fragment _base.md to simulate a realistic cyclic include.
    """
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:_base.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    _write(
        project,
        "_base.md",
        "<!-- include:concept.md -->\n",
    )
    with pytest.raises(RecursionError, match="circular"):
        resolve(PageType.CONCEPT, tmp_path)


def test_resolve_missing_include_keeps_marker(tmp_path):
    """Missing include: marker kept in body + no crash."""
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:_nonexistent.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    t = resolve(PageType.CONCEPT, tmp_path)
    # The missing include is left in place (warning, not silent drop)
    assert "<!-- include:_nonexistent.md -->" in t.body_markdown


def test_resolve_include_depth_limit(tmp_path):
    """Depth > 3 raises RecursionError (defence-in-depth).

    Chain: concept.md -> _l1.md -> _l2.md -> _l3.md -> _l4.md
    (4 levels of include recursion; MAX_INCLUDE_DEPTH = 3).
    """
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:_l1.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    _write(project, "_l1.md", "<!-- include:_l2.md -->\n")
    _write(project, "_l2.md", "<!-- include:_l3.md -->\n")
    _write(project, "_l3.md", "<!-- include:_l4.md -->\n")
    _write(project, "_l4.md", "<!-- should never reach -->\n")
    with pytest.raises(RecursionError):
        resolve(PageType.CONCEPT, tmp_path)


# ---------------------------------------------------------------------------
# O-1: list_resolved() INVALID-template fallback (TemplateParseError only)
# ---------------------------------------------------------------------------

def test_list_resolved_falls_back_for_invalid_type_header(tmp_path, monkeypatch):
    """A project override with mismatched type header surfaces as Template.

    list_resolved() catches TemplateParseError from resolve() and returns
    the invalid override's raw content so the CLI can mark it INVALID.
    """
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    # concept.md claims to be 'entity' (type mismatch) → TemplateParseError
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"
        "## bogus\n",
    )
    # Redirect USER_TEMPLATE_DIR to empty dir to avoid reading real user file
    empty_user = tmp_path / "empty-user-templates"
    empty_user.mkdir()
    monkeypatch.setattr("src.wiki.templates.types.USER_TEMPLATE_DIR", empty_user)

    templates = list_resolved(tmp_path)
    # Find the concept entry — should be the raw invalid content from project
    concept_entries = [t for t in templates if t.type == PageType.CONCEPT]
    assert len(concept_entries) == 1
    concept = concept_entries[0]
    assert concept.source == "project"
    assert concept.path == project / "concept.md"
    # Body keeps the raw content (no include expansion in the fallback)
    assert "<!-- wiki-template-type: entity -->" in concept.body_markdown


def test_resolve_propagates_unsafe_include_path_not_type_error(tmp_path):
    """Unsafe include path raises ValueError (not TemplateParseError).

    This guards the fix in list_resolved() that narrowed its except
    clause to TemplateParseError — we don't want a bad include path to
    be silently surfaced as an INVALID Template.
    """
    project = tmp_path / ".wiki-templates"
    project.mkdir()
    _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "<!-- include:../escape.md -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    with pytest.raises(ValueError, match="bare filename"):
        resolve(PageType.CONCEPT, tmp_path)
    # Confirm it's a plain ValueError (not TemplateParseError) so the
    # list_resolved() catch-narrowing is exercised by this test.
    try:
        resolve(PageType.CONCEPT, tmp_path)
    except ValueError as e:
        from src.wiki.templates.parser import TemplateParseError
        assert not isinstance(e, TemplateParseError), (
            f"include-path errors must remain plain ValueError, got {type(e).__name__}"
        )