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


def test_list_raw_files_detects_ingested_via_frontmatter(monkeypatch, tmp_path):
    """list_raw_files must detect ingestion by reading wiki page frontmatter
    'sources' field, NOT by filename stem matching.

    Regression: wiki pages use generated IDs as filenames (e.g. kb-2026...-.md),
    not the raw file name. The old stem-prefix match always failed, reporting
    every raw file as not-ingested.
    """
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    # Raw files
    raw_dir = project_dir / "raw" / "sources"
    raw_dir.mkdir(parents=True)
    (raw_dir / "doc1.pdf").write_text("pdf content", encoding="utf-8")
    (raw_dir / "doc2.docx").write_text("docx content", encoding="utf-8")
    (raw_dir / "doc3.xlsx").write_text("xlsx content", encoding="utf-8")
    (raw_dir / "no_wiki_page.pdf").write_text("orphan", encoding="utf-8")

    # Wiki source pages — filenames are generated IDs (not raw file names)
    wiki_sources = project_dir / "wiki" / "sources"
    wiki_sources.mkdir(parents=True)
    (wiki_sources / "kb-20260726154545-e84f1b2b.md").write_text(
        "---\n"
        "id: kb-20260726154545-e84f1b2b\n"
        "title: doc1.pdf\n"
        "type: source\n"
        "sources:\n"
        "- raw/sources/doc1.pdf\n"
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )
    (wiki_sources / "kb-20260726154727-87487434.md").write_text(
        "---\n"
        "id: kb-20260726154727-87487434\n"
        "title: doc2.docx\n"
        "type: source\n"
        "sources:\n"
        "- raw\\sources\\doc2.docx\n"  # Windows-style backslash
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )
    # doc3: source path written as absolute-style with forward slashes
    (wiki_sources / "kb-20260726154728-6537763a.md").write_text(
        "---\n"
        "id: kb-20260726154728-6537763a\n"
        "title: doc3.xlsx\n"
        "type: source\n"
        "sources:\n"
        "- raw/sources/doc3.xlsx\n"
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_raw_files("u")
    files_by_name = {f["name"]: f for f in result["files"]}

    # Files referenced by wiki page frontmatter → ingested
    assert files_by_name["doc1.pdf"]["ingested"] is True
    assert files_by_name["doc2.docx"]["ingested"] is True
    assert files_by_name["doc3.xlsx"]["ingested"] is True
    # No wiki page references this file → not ingested
    assert files_by_name["no_wiki_page.pdf"]["ingested"] is False


def test_list_raw_files_missing_dir_returns_empty(monkeypatch, tmp_path):
    """If raw/sources doesn't exist, return empty list (not an error)."""
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

    result = files_service.list_raw_files("u")
    assert result == {"files": []}


def test_list_raw_files_filters_non_raw_extensions(monkeypatch, tmp_path):
    """Only files with extensions in _RAW_EXTS should appear."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    raw_dir = project_dir / "raw" / "sources"
    raw_dir.mkdir(parents=True)
    (raw_dir / "a.pdf").write_text("pdf", encoding="utf-8")
    (raw_dir / "b.exe").write_text("exe", encoding="utf-8")
    (raw_dir / "c.py").write_text("py", encoding="utf-8")
    (raw_dir / "d.docx").write_text("docx", encoding="utf-8")
    (raw_dir / "subdir").mkdir()
    (raw_dir / "subdir" / "e.txt").write_text("txt", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = files_service.list_raw_files("u")
    names = {f["name"] for f in result["files"]}
    assert names == {"a.pdf", "d.docx", "e.txt"}
    assert "b.exe" not in names
    assert "c.py" not in names


def _fake_resolve(project_dir):
    """Build a (ProjectContext, WikiPaths) pair pointing at project_dir."""
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
