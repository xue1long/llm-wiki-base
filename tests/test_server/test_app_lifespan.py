import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def lifespan_env(tmp_path, monkeypatch):
    from src.llm import embedding_runtime
    from src.llm.registry import ProviderRegistry
    from src.project import discovery, paths as project_paths

    root = tmp_path / "kb"
    (root / ".llm-wiki").mkdir(parents=True)
    project_id = "11111111-1111-4111-8111-111111111111"
    (root / ".llm-wiki" / "project.json").write_text(
        json.dumps({
            "id": project_id,
            "name": "lifespan-kb",
            "created_at": 0,
            "schema_version": "v2.0",
        }),
        encoding="utf-8",
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUFLO_PROJECT_ROOT", str(root))
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", config_dir)
    monkeypatch.setattr(discovery, "DEFAULT_SEARCH_PATHS", [tmp_path])

    class FakeEmbedding:
        def __init__(self):
            self.embed_calls = 0

        async def embed(self, texts):
            self.embed_calls += 1
            return [SimpleNamespace(embedding=[0.0]) for _ in texts]

    fake_embedding = FakeEmbedding()
    old_embedding = getattr(embedding_runtime, "_impl")
    old_loaded = set(ProviderRegistry._loaded_providers)
    old_default = ProviderRegistry.get_default
    old_load = ProviderRegistry.load

    config = SimpleNamespace(
        name="offline-test",
        type="ollama",
        api_key="",
        base_url="http://127.0.0.1:9",
        default_embedding_model="test-embedding",
    )
    monkeypatch.setattr(ProviderRegistry, "get_default", staticmethod(lambda: config))
    monkeypatch.setattr(ProviderRegistry, "load", staticmethod(lambda: {}))
    monkeypatch.setattr(
        "src.llm.provider_factory.create_embedding_provider",
        lambda **_: fake_embedding,
    )
    monkeypatch.setattr(
        "src.llm.provider_factory.resolve_embedding_provider_type",
        lambda name, provider_type: provider_type,
    )
    monkeypatch.setattr("src.vector.store.init_vector_store_for_paths", lambda _: None)
    monkeypatch.setattr("src.server.app.check_config_permissions", lambda: None, raising=False)

    class QueueStub:
        def get_status(self):
            return {"paused": True, "pending_count": 0, "running_count": 0}

    monkeypatch.setattr("src.queue.service.get_default_queue_service", lambda: QueueStub())
    monkeypatch.setattr("src.kc.mainline.recover_staged_bundles", lambda _: _empty_async())

    yield root, project_id, fake_embedding, config_dir

    if old_embedding is None:
        embedding_runtime.__reset_for_testing()
    else:
        embedding_runtime.set_embedding_provider(old_embedding)
    ProviderRegistry._loaded_providers.clear()
    ProviderRegistry._loaded_providers.update(old_loaded)
    ProviderRegistry.get_default = old_default
    ProviderRegistry.load = old_load


async def _empty_async():
    return []


def test_lifespan_starts_health_without_network(lifespan_env):
    _root, _project_id, fake_embedding, _config_dir = lifespan_env
    from src.server.app import create_app
    from src.llm.registry import ProviderRegistry

    close_calls = []
    original_close = ProviderRegistry.aclose_all
    ProviderRegistry.aclose_all = staticmethod(lambda: _record_close(close_calls))
    try:
        with TestClient(create_app()) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["ok"] is True
            assert fake_embedding.embed_calls == 1
    finally:
        ProviderRegistry.aclose_all = original_close
    assert close_calls == [True]


def _record_close(calls):
    async def close():
        calls.append(True)

    return close()


def test_lifespan_discovers_real_project_marker(lifespan_env):
    _root, project_id, _fake_embedding, config_dir = lifespan_env
    from src.server.app import create_app

    with TestClient(create_app()):
        registry = json.loads((config_dir / "registry.json").read_text(encoding="utf-8"))
    assert project_id in registry["projects"]


def test_lifespan_restores_embedding_singleton_on_shutdown(lifespan_env):
    _root, _project_id, _fake_embedding, _config_dir = lifespan_env
    from src.llm import embedding_runtime
    from src.server.app import create_app

    previous = object()
    embedding_runtime.set_embedding_provider(previous)
    with TestClient(create_app()):
        assert embedding_runtime.get_embedding_provider() is not previous
    assert embedding_runtime.get_embedding_provider() is previous
