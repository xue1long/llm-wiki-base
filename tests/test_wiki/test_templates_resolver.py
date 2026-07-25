"""Tests for wiki page templates resolver (Plan 25 v1)."""
from pathlib import Path

import pytest

from src.wiki.core.types import PageType
from src.wiki.templates import Template, resolve, list_available


def test_resolve_bundled_concept(tmp_path: Path) -> None:
    """Bundled concept template resolves with correct type and version."""
    t = resolve(PageType.CONCEPT, tmp_path)
    assert t.type == PageType.CONCEPT
    assert t.source == "bundled"
    assert t.version == "1.0.0"
    assert "## 定义" in t.body_markdown
    assert "<!-- slot:definition -->" in t.body_markdown


def test_resolve_bundled_source(tmp_path: Path) -> None:
    """Bundled source template resolves."""
    t = resolve(PageType.SOURCE, tmp_path)
    assert t.type == PageType.SOURCE
    assert t.source == "bundled"
    assert "## 来源元数据" in t.body_markdown


def test_resolve_bundled_entity(tmp_path: Path) -> None:
    """Bundled entity template resolves."""
    t = resolve(PageType.ENTITY, tmp_path)
    assert t.type == PageType.ENTITY
    assert t.source == "bundled"
    assert "## 基本信息" in t.body_markdown


def test_resolve_bundled_synthesis(tmp_path: Path) -> None:
    """Bundled synthesis template resolves."""
    t = resolve(PageType.SYNTHESIS, tmp_path)
    assert t.type == PageType.SYNTHESIS
    assert t.source == "bundled"
    assert "## 对比维度" in t.body_markdown


def test_project_override_takes_priority(tmp_path: Path) -> None:
    """Project-level .wiki-templates/concept.md overrides bundled."""
    project_templates = tmp_path / ".wiki-templates"
    project_templates.mkdir()
    custom = project_templates / "concept.md"
    custom.write_text(
        "<!-- wiki-template-version: 2.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n"
        "## Project Custom Definition\n\n"
        "<!-- slot:definition -->\n",
        encoding="utf-8",
    )
    t = resolve(PageType.CONCEPT, tmp_path)
    assert t.source == "project"
    assert t.version == "2.0.0"
    assert "Project Custom Definition" in t.body_markdown


def test_template_type_mismatch_raises(tmp_path: Path) -> None:
    """A template file with the wrong type header is rejected (not silently used)."""
    bad = tmp_path / ".wiki-templates"
    bad.mkdir()
    (bad / "concept.md").write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: entity -->\n\n"  # wrong type!
        "body\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="type mismatch"):
        resolve(PageType.CONCEPT, tmp_path)


def test_list_available_returns_all_four_types(tmp_path: Path) -> None:
    """list_available surfaces one entry per PageType (bundled always provides 4)."""
    templates = list_available(tmp_path)
    types = {t.type for t in templates}
    assert types == set(PageType)


def test_resolve_missing_bundled_raises(tmp_path: Path, monkeypatch) -> None:
    """If bundled file is deleted, resolve raises FileNotFoundError."""
    # Simulate by removing the bundled dir from sys.path resolution
    from src.wiki.templates import resolver as r
    original = r.BUNDLED_DIR
    r.BUNDLED_DIR = tmp_path / "nonexistent"
    try:
        with pytest.raises(FileNotFoundError, match="No wiki template"):
            resolve(PageType.CONCEPT, tmp_path)
    finally:
        r.BUNDLED_DIR = original
