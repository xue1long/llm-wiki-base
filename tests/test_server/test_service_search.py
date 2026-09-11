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
    monkeypatch.setattr(
        search_service,
        "vector_readiness",
        lambda paths, embedding_model=None, actionable_only=False: {"ready": True, "reason": "ready"},
    )
    monkeypatch.setattr(search_service, "_filter_actionable", lambda paths, results: results)
    modes = []

    async def fake_hybrid_search(query, top_k=10, paths=None, mode="hybrid"):
        modes.append(mode)
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
    assert modes == ["hybrid"]


def test_search_blocks_semantic_until_ready_but_allows_keyword(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        search_service,
        "resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )
    monkeypatch.setattr(
        search_service,
        "vector_readiness",
        lambda paths, embedding_model=None, actionable_only=False: {"ready": False, "reason": "pending"},
    )
    modes = []

    async def fake_hybrid_search(query, top_k=10, paths=None, mode="hybrid"):
        modes.append(mode)
        return [{"path": "wiki/a.md", "title": "A", "content": "abc", "score": 1.0, "source": mode}]

    monkeypatch.setattr(search_service, "hybrid_search", fake_hybrid_search)

    blocked = asyncio.run(search_service.search("u", "query", mode="hybrid"))
    keyword = asyncio.run(search_service.search("u", "query", mode="keyword"))

    assert blocked["results"] == []
    assert blocked["ready"] is False
    assert blocked["diagnostics"]["reason"] == "pending"
    assert keyword["results"][0]["source"] == "keyword"
    assert modes == ["keyword"]


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

    async def fake_hybrid_search(query, top_k=10, paths=None):
        return []

    monkeypatch.setattr(search_service, "hybrid_search", fake_hybrid_search)

    result = asyncio.run(search_service.search("u", "no match"))
    assert result["results"] == []
    assert result["query"] == "no match"


def test_search_abstains_on_unsupported_writing_request(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(search_service, "resolve_project", lambda project_id, by_id_only=True: _fake_resolve(project_dir))
    monkeypatch.setattr(
        search_service,
        "vector_readiness",
        lambda paths, embedding_model=None, actionable_only=False: {"ready": True, "reason": "ready"},
    )

    async def unexpected_search(*_args, **_kwargs):
        raise AssertionError("unsupported request should abstain before retrieval")

    monkeypatch.setattr(search_service, "hybrid_search", unexpected_search)
    result = asyncio.run(search_service.search("u", "根据这套知识库判断我的新书一定能签约，并给出成功率。"))
    assert result["results"] == []
    assert result["diagnostics"]["reason"] == "unsupported_query"


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
