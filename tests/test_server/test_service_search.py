"""Tests for src.services.search — search dispatch."""
import asyncio
from dataclasses import replace

from src.services import search as search_service
from src.integrations.gbrain.api import ensure_search_config, save_search_config, save_search_state
from src.integrations.gbrain.state import save_runtime_state
from src.integrations.gbrain.types import SearchState, SearchStatus


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


def test_search_uses_ready_gbrain_before_local_vector(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000}', encoding="utf-8"
    )
    (project_dir / "wiki" / "sources").mkdir(parents=True)
    ensure_search_config(project_dir)
    config = ensure_search_config(project_dir)
    save_search_config(project_dir, replace(config, enabled=True))
    save_search_state(
        project_dir,
        replace(
            SearchState(),
            status=SearchStatus.READY,
            embedding_coverage=1.0,
            path_mapping_coverage=1.0,
        ),
    )
    save_runtime_state(project_dir, {"status": "ready", "path": str(tmp_path / "gbrain")})
    (tmp_path / "gbrain").mkdir()
    (project_dir / ".index" / "gbrain" / "manifest.json").write_text(
        '{"wiki/sources/a": {"path": "wiki/sources/a.md"}}', encoding="utf-8"
    )

    monkeypatch.setattr(search_service, "resolve_project", lambda project_id, by_id_only=True: _fake_resolve(project_dir))
    monkeypatch.setattr(search_service, "vector_readiness", lambda *args, **kwargs: {"ready": False, "reason": "local_pending"})
    monkeypatch.setattr(search_service, "_filter_actionable", lambda paths, results: results)
    monkeypatch.setattr(
        search_service,
        "run_mcp_search",
        lambda *args, **kwargs: [{"slug": "wiki/sources/a", "page_id": "1", "title": "A", "type": "source", "chunk_text": "remote", "score": 0.9, "source_id": config.source_id}],
    )

    result = asyncio.run(search_service.search("u", "query", mode="hybrid"))

    assert result["results"][0]["source"] == "gbrain"
    assert result["diagnostics"]["backend"] == "gbrain"
    assert result["ready"] is True


def test_search_rejects_stale_missing_runtime_path(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000}', encoding="utf-8"
    )
    config = ensure_search_config(project_dir)
    save_search_config(project_dir, replace(config, enabled=True))
    save_search_state(
        project_dir,
        replace(SearchState(), status=SearchStatus.READY, embedding_coverage=1.0, path_mapping_coverage=1.0),
    )
    save_runtime_state(project_dir, {"status": "ready", "path": str(tmp_path / "deleted-gbrain")})

    monkeypatch.setattr(search_service, "resolve_project", lambda *args, **kwargs: _fake_resolve(project_dir))
    monkeypatch.setattr(search_service, "vector_readiness", lambda *args, **kwargs: {"ready": False, "reason": "local_pending"})
    monkeypatch.setattr(search_service, "hybrid_search", lambda *args, **kwargs: [])

    result = asyncio.run(search_service.search("u", "query", mode="hybrid"))

    assert result["ready"] is False
    assert result["results"] == []


def test_search_honors_global_local_kill_switch(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000}', encoding="utf-8"
    )
    config = ensure_search_config(project_dir)
    save_search_config(project_dir, replace(config, enabled=True))
    save_search_state(
        project_dir,
        replace(SearchState(), status=SearchStatus.READY, embedding_coverage=1.0, path_mapping_coverage=1.0),
    )
    runtime = tmp_path / "gbrain"
    runtime.mkdir()
    save_runtime_state(project_dir, {"status": "ready", "path": str(runtime)})

    monkeypatch.setenv("RUFLO_SEARCH_BACKEND", "local")
    monkeypatch.setattr(search_service, "resolve_project", lambda *args, **kwargs: _fake_resolve(project_dir))
    monkeypatch.setattr(search_service, "vector_readiness", lambda *args, **kwargs: {"ready": False, "reason": "local_pending"})
    monkeypatch.setattr(search_service, "run_mcp_search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("kill switch bypassed")))

    result = asyncio.run(search_service.search("u", "query", mode="hybrid"))

    assert result["results"] == []
    assert result["diagnostics"]["reason"] == "local_pending"


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
