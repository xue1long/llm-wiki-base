"""Tests for src.services.search — search dispatch."""
import asyncio

from src.services import search as search_service


def test_search_returns_results(monkeypatch, tmp_path):
    """search() delegates to hybrid_search and wraps the response."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.search.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    async def fake_hybrid_search(query, top_k=10):
        return [
            {"path": "wiki/a.md", "title": "A", "content": "abc", "score": 0.9, "source": "hybrid"},
        ]

    monkeypatch.setattr(search_service, "hybrid_search", fake_hybrid_search)

    result = asyncio.run(search_service.search("u", "my query", top_k=5, mode="hybrid"))
    assert result["mode"] == "hybrid"
    assert result["topK"] == 5
    assert result["query"] == "my query"
    assert len(result["results"]) == 1
    assert result["results"][0]["path"] == "wiki/a.md"


def test_search_empty_results(monkeypatch, tmp_path):
    """search returns an empty result list when hybrid_search returns nothing."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.search.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    async def fake_hybrid_search(query, top_k=10):
        return []

    monkeypatch.setattr(search_service, "hybrid_search", fake_hybrid_search)

    result = asyncio.run(search_service.search("u", "no match"))
    assert result["results"] == []
    assert result["query"] == "no match"


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
