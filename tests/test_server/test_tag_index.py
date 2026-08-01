"""Tests for tag index endpoint (1.2.1) and include_tags extension (1.2.2)."""
import pytest

from src.services import tags as tags_service
from src.services import files as files_service


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)


def _make_project(tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    wiki_dir = project_dir / "wiki"
    for sub in ["sources", "concepts", "entities", "synthesis"]:
        (wiki_dir / sub).mkdir(parents=True)
    return project_dir, wiki_dir


class TestBuildTagIndex:
    """1.2.1 GET /api/v1/projects/{id}/tag-index"""

    def test_empty_wiki_returns_empty_namespaces(self, monkeypatch, tmp_path):
        project_dir, wiki_dir = _make_project(tmp_path)
        monkeypatch.setattr(
            "src.services.tags.resolve_project",
            lambda project_id, by_id_only=True: _fake_resolve(project_dir),
        )
        result = tags_service.build_tag_index("u")
        assert result == {"namespaces": {}}

    def test_aggregates_tags_by_namespace(self, monkeypatch, tmp_path):
        project_dir, wiki_dir = _make_project(tmp_path)
        (wiki_dir / "concepts" / "a.md").write_text(
            "---\ntags:\n  - 题材/玄幻\n  - 情绪/爽文\n---\n# A\n",
            encoding="utf-8",
        )
        (wiki_dir / "concepts" / "b.md").write_text(
            "---\ntags:\n  - 题材/玄幻\n  - 功能/写作技巧\n---\n# B\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "src.services.tags.resolve_project",
            lambda project_id, by_id_only=True: _fake_resolve(project_dir),
        )
        result = tags_service.build_tag_index("u")
        ns = result["namespaces"]
        assert "题材" in ns
        assert ns["题材"]["label"] == "题材类型"
        genre_tags = {t["name"]: t["count"] for t in ns["题材"]["tags"]}
        assert genre_tags["玄幻"] == 2

        assert "情绪" in ns
        mood_tags = {t["name"]: t["count"] for t in ns["情绪"]["tags"]}
        assert mood_tags["爽文"] == 1

        assert "功能" in ns
        func_tags = {t["name"]: t["count"] for t in ns["功能"]["tags"]}
        assert func_tags["写作技巧"] == 1

    def test_skips_invalid_tags(self, monkeypatch, tmp_path):
        project_dir, wiki_dir = _make_project(tmp_path)
        (wiki_dir / "concepts" / "a.md").write_text(
            "---\ntags:\n  - 题材/玄幻\n  - bareword\n  - invalid/foo\n---\n# A\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "src.services.tags.resolve_project",
            lambda project_id, by_id_only=True: _fake_resolve(project_dir),
        )
        result = tags_service.build_tag_index("u")
        ns = result["namespaces"]
        # Only 题材 should appear; bareword and invalid/foo are skipped
        assert "题材" in ns
        # invalid/foo: "invalid" is not a known prefix
        assert "invalid" not in ns


class TestListFilesIncludeTags:
    """1.2.2 GET /files?include_tags=true"""

    def test_include_tags_false_by_default(self, monkeypatch, tmp_path):
        project_dir, wiki_dir = _make_project(tmp_path)
        (wiki_dir / "concepts" / "a.md").write_text(
            "---\ntags:\n  - 题材/玄幻\n---\n# A\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "src.services.files.resolve_project",
            lambda project_id, by_id_only=True: _fake_resolve(project_dir),
        )
        result = files_service.list_files("u")
        for f in result["files"]:
            assert "tags" not in f

    def test_include_tags_true_returns_tags(self, monkeypatch, tmp_path):
        project_dir, wiki_dir = _make_project(tmp_path)
        (wiki_dir / "concepts" / "a.md").write_text(
            "---\ntags:\n  - 题材/玄幻\n  - 情绪/爽文\n---\n# A\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "src.services.files.resolve_project",
            lambda project_id, by_id_only=True: _fake_resolve(project_dir),
        )
        result = files_service.list_files("u", include_tags=True)
        files = result["files"]
        assert len(files) == 1
        assert set(files[0]["tags"]) == {"题材/玄幻", "情绪/爽文"}

    def test_include_tags_no_frontmatter_returns_empty(self, monkeypatch, tmp_path):
        project_dir, wiki_dir = _make_project(tmp_path)
        (wiki_dir / "concepts" / "a.md").write_text("# No frontmatter\n", encoding="utf-8")
        monkeypatch.setattr(
            "src.services.files.resolve_project",
            lambda project_id, by_id_only=True: _fake_resolve(project_dir),
        )
        result = files_service.list_files("u", include_tags=True)
        assert result["files"][0]["tags"] == []
