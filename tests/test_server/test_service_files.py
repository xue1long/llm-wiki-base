"""Tests for src.services.files — file listing + content reading.

These services extract logic previously inlined in src/server/routes/files.py
(path traversal check, rglob walk, response shaping). Routes now become
thin wrappers that map service exceptions to HTTPException.
"""
import pytest

from src.services import files as files_service


def test_list_files_returns_markdown_files(monkeypatch, tmp_path):
    """list_files walks the wiki tree and returns file metadata."""
    # Set up a project with some markdown files
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)
    (wiki_dir / "sources" / "a.md").write_text("# A", encoding="utf-8")
    (wiki_dir / "sources" / "b.md").write_text("## B" * 100, encoding="utf-8")
    (wiki_dir / "entities").mkdir()
    (wiki_dir / "entities" / "c.md").write_text("# C", encoding="utf-8")
    (wiki_dir / "not_markdown.txt").write_text("ignored", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_files("u", root="wiki")
    paths = sorted(f["path"] for f in result["files"])
    # 3 .md files, 1 .txt excluded
    assert "wiki/sources/a.md" in paths
    assert "wiki/sources/b.md" in paths
    assert "wiki/entities/c.md" in paths
    assert not any("not_markdown" in p for p in paths)
    assert result["truncated"] is False
    assert result["totalCount"] == 3


def test_list_files_truncates_at_max(monkeypatch, tmp_path):
    """list_files respects max_files limit."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)
    for i in range(5):
        (wiki_dir / "sources" / f"f{i}.md").write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_files("u", root="wiki", max_files=3)
    assert result["truncated"] is True
    assert len(result["files"]) == 3
    assert result["totalCount"] == 5


def test_list_files_missing_dir_returns_empty(monkeypatch, tmp_path):
    """If the wiki dir doesn't exist, return empty list (not an error)."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_files("u", root="wiki")
    assert result == {"files": [], "truncated": False, "totalCount": 0}


def test_read_file_content_returns_text(monkeypatch, tmp_path):
    """read_file_content reads file contents for a path within the wiki root."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)
    (wiki_dir / "sources" / "a.md").write_text("# Hello", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.read_file_content("u", "sources/a.md")
    assert result["content"] == "# Hello"
    # path is relative to project root (which contains the wiki/ subtree)
    assert result["path"] == "wiki/sources/a.md"


def test_read_file_content_blocks_traversal(monkeypatch, tmp_path):
    """read_file_content must reject paths that escape the wiki root."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    with pytest.raises(files_service.PathTraversalError):
        files_service.read_file_content("u", "../../etc/passwd")


def test_read_file_content_raises_not_found(monkeypatch, tmp_path):
    """If the file doesn't exist within wiki, raise FileNotFoundError."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    (wiki_dir / "sources").mkdir(parents=True)

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    with pytest.raises(files_service.FileNotFoundError):
        files_service.read_file_content("u", "sources/nonexistent.md")


def _fake_resolve(project_dir):
    """Build a (ProjectContext, WikiPaths) pair pointing at project_dir."""
    from src.project.context import ProjectContext
    from src.wiki.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
