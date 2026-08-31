"""Tests for resolver.py include expansion + security (Phase 2).

Bug 1 fix: include paths must be bare filenames (no /, \\, ..).
Bug 15 fix: visited set prevents cycles.
"""
from pathlib import Path

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


# ---------------------------------------------------------------------------
# O-4: resolve() LRU cache (mtime-keyed; auto-invalidate on edit)
# ---------------------------------------------------------------------------

def test_resolve_caches_within_same_mtime(tmp_path):
    """Same project_root + unchanged file mtime → cached Template returned.

    Distinct from the no-override case where the bundled path is used;
    here we have a real project override so we can observe the
    file-read path being skipped the second time.
    """
    from src.wiki.templates import resolver as r

    project = tmp_path / ".wiki-templates"
    project.mkdir()
    p = _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    r.clear_cache()
    t1 = resolve(PageType.CONCEPT, tmp_path)
    # Get the on-disk mtime, then read it back to confirm the cache key
    # is built off the same value.
    mtime = p.stat().st_mtime_ns
    # Second call within the same mtime — must return the cached Template
    t2 = resolve(PageType.CONCEPT, tmp_path)
    assert t1 is t2, "expected cache hit (identity)"
    # Cleanup: clear cache so other tests start clean
    r.clear_cache()


def test_resolve_invalidates_when_mtime_changes(tmp_path):
    """Edit the override file → cache must invalidate, fresh content returned."""
    import time
    from src.wiki.templates import resolver as r

    project = tmp_path / ".wiki-templates"
    project.mkdir()
    p = _write(
        project,
        "concept.md",
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n<!-- slot:definition -->\n",
    )
    r.clear_cache()
    t1 = resolve(PageType.CONCEPT, tmp_path)
    # Wait long enough that the mtime ns will differ, then rewrite the file.
    time.sleep(0.05)
    p.write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## 重定义\n\n<!-- slot:definition -->\n",
        encoding="utf-8",
    )
    t2 = resolve(PageType.CONCEPT, tmp_path)
    assert t1 is not t2, "cache must invalidate on mtime change"
    # New template reflects the new content
    assert "重定义" in t2.body_markdown
    r.clear_cache()


def test_resolve_caches_per_project_root(tmp_path):
    """Two different project roots → two separate cache entries."""
    from src.wiki.templates import resolver as r

    a = tmp_path / "a" / ".wiki-templates"
    b = tmp_path / "b" / ".wiki-templates"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    _write(a, "concept.md",
           "<!-- wiki-template-version: 1.0.0 -->\n"
           "<!-- wiki-template-type: concept -->\n\n"
           "## 定义_A\n\n<!-- slot:definition -->\n")
    _write(b, "concept.md",
           "<!-- wiki-template-version: 1.0.0 -->\n"
           "<!-- wiki-template-type: concept -->\n\n"
           "## 定义_B\n\n<!-- slot:definition -->\n")
    r.clear_cache()
    t_a = resolve(PageType.CONCEPT, tmp_path / "a")
    t_b = resolve(PageType.CONCEPT, tmp_path / "b")
    assert t_a is not t_b
    assert "定义_A" in t_a.body_markdown
    assert "定义_B" in t_b.body_markdown
    r.clear_cache()


def test_resolve_cache_does_not_break_missing_file_error(tmp_path):
    """Cache must not mask FileNotFoundError when bundled file is absent.

    This guards against caching the exception path. We simulate by
    patching BUNDLED_DIR to a non-existent path.
    """
    from src.wiki.templates import resolver as r
    from src.wiki.templates.types import BUNDLED_DIR

    project = tmp_path / "no-templates"
    project.mkdir()
    r.clear_cache()
    original = BUNDLED_DIR
    try:
        # Temporarily point BUNDLED_DIR to a guaranteed-missing dir
        object.__setattr__(r, "BUNDLED_DIR", Path("/nonexistent-bundled-dir-xyz"))
        with pytest.raises(FileNotFoundError):
            resolve(PageType.CONCEPT, project)
        # Second call must STILL raise (no exception caching)
        with pytest.raises(FileNotFoundError):
            resolve(PageType.CONCEPT, project)
    finally:
        object.__setattr__(r, "BUNDLED_DIR", original)
        r.clear_cache()


def test_resolve_falls_back_when_user_template_is_inaccessible(tmp_path, monkeypatch):
    from src.wiki.templates import resolver as r

    r.clear_cache()
    inaccessible = Path("C:/inaccessible/wiki-templates/concept.md")
    bundled = r.BUNDLED_DIR / "concept.md"
    original_is_file = Path.is_file

    def denied_is_file(path):
        if path == inaccessible:
            raise PermissionError("denied")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", denied_is_file)
    monkeypatch.setattr(
        r,
        "_iter_candidates",
        lambda page_type, project_root: [(inaccessible, "user"), (bundled, "bundled")],
    )

    assert resolve(PageType.CONCEPT, tmp_path).source == "bundled"
    r.clear_cache()


# ---------------------------------------------------------------------------
# Phase 2.2 — project-level v3.0.0 templates hit for novel-wiki
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NOVEL_WIKI = REPO_ROOT / "knowledge" / "novel-wiki"

# 写作域 v3.0.0 模板的零采纳可选槽（spec §4.5 删除；plan 2.2 确认已清理）
_OLD_OPTIONAL_SLOTS = ("limitations?", "conflicts?", "source_meta?")


def test_project_level_priority_hits_novel_wiki():
    """novel-wiki 的 4 个页面模板必须命中项目级 v3.0.0（优先于 bundled 2.0.0）。"""
    from src.wiki.core.types import PageType
    from src.wiki.templates import resolver as r

    r.clear_cache()
    try:
        for ptype in (PageType.SOURCE, PageType.ENTITY, PageType.CONCEPT, PageType.SYNTHESIS):
            t = r.resolve(ptype, NOVEL_WIKI)
            assert t.source == "project", (
                f"{ptype.value} 模板应来自项目级，实际 {t.source}"
            )
            assert t.version == "3.0.0", (
                f"{ptype.value} 模板版本应为 3.0.0，实际 {t.version}"
            )
            assert t.path.parent == NOVEL_WIKI / ".wiki-templates"
    finally:
        r.clear_cache()


def test_novel_wiki_templates_no_zero_adoption_optional_slots():
    """spec §4.5 废弃的零采纳可选槽（limitations?/conflicts?/source_meta?）
    必须从项目级模板中清除（plan 2.2）。"""
    for name in ("concept.md", "source.md", "entity.md", "synthesis.md"):
        text = (NOVEL_WIKI / ".wiki-templates" / name).read_text(encoding="utf-8")
        for slot in _OLD_OPTIONAL_SLOTS:
            assert f"slot:{slot}" not in text, (
                f"{name} 仍含废弃可选槽 {slot!r}"
            )
