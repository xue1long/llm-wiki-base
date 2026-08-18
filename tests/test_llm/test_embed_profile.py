"""R11 — dependency reproducibility + local-embedding profile.

Coverage:
- pyproject declares the optional `embedding` extra (sentence-transformers)
  so local fallback is an explicit, documented install profile.
- The embedding availability helper reports whether local
  sentence-transformers is importable (keyword-only vs semantic mode).
- /ready reflects embedding capability: when neither remote nor local
  embedding is usable, the vector/provider entries note keyword-only.
"""
import pytest


# ---------------------------------------------------------------------------
# 1. optional extra declared
# ---------------------------------------------------------------------------

def test_pyproject_declares_embedding_extra():
    """pyproject.toml has an `embedding` optional dependency group."""
    from pathlib import Path
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "embedding" in text
    assert "sentence-transformers" in text


def test_embedding_extra_is_optional():
    """sentence-transformers is NOT in the hard dependency list."""
    from pathlib import Path
    import tomllib
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert not any("sentence-transformers" in d for d in deps)
    extras = data["project"]["optional-dependencies"]
    assert any("sentence-transformers" in d for d in extras["embedding"])


def test_lockfile_exists_and_covers_core():
    """requirements.lock exists and pins every pyproject hard dependency."""
    from pathlib import Path
    import tomllib

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock_text = Path("requirements.lock").read_text(encoding="utf-8")
    for dep in data["project"]["dependencies"]:
        name = dep.split(">=")[0].split("==")[0].strip().lower()
        # lancedb is pinned in the lock under its PyPI name.
        assert name in lock_text.lower(), f"{name} missing from requirements.lock"


# ---------------------------------------------------------------------------
# 2. embedding availability helper
# ---------------------------------------------------------------------------

def test_local_embedding_available_when_installed(monkeypatch):
    """local_embedding_available() True when sentence-transformers imports."""
    import sys
    from src.llm import embed_profile as profile

    class _FakeST:
        pass

    real_import = __import__
    def _fake_import(name, *a, **k):
        if name == "sentence_transformers":
            sys.modules["sentence_transformers"] = _FakeST
            return _FakeST
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert profile.local_embedding_available() is True


def test_local_embedding_unavailable_when_missing(monkeypatch):
    """local_embedding_available() False when sentence-transformers is absent."""
    from src.llm import embed_profile as profile

    real_import = __import__
    def _fake_import(name, *a, **k):
        if name == "sentence_transformers":
            raise ImportError("no module named 'sentence_transformers'")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert profile.local_embedding_available() is False


def test_embedding_mode_reports_keyword_only(monkeypatch):
    """embedding_mode() returns 'keyword-only' with no usable provider."""
    from src.llm import embed_profile as profile

    monkeypatch.setattr(profile, "local_embedding_available", lambda: False)
    # No remote provider either (registry empty / no default).
    from src.llm.registry import ProviderRegistry
    import src.llm.embed_profile as ep
    monkeypatch.setattr(
        ProviderRegistry, "get_default",
        lambda: (_ for _ in ()).throw(RuntimeError("none")),
    )
    assert ep.embedding_mode() == "keyword-only"


def test_embedding_mode_reports_remote(monkeypatch):
    """embedding_mode() returns 'remote' when a remote provider is usable."""
    from src.llm import embed_profile as profile
    from src.llm.registry import ProviderRegistry
    from src.llm.types import ProviderConfig

    monkeypatch.setattr(
        ProviderRegistry, "get_default",
        lambda: ProviderConfig(name="openai", type="openai", base_url="https://x"),
    )
    assert profile.embedding_mode() == "remote"


def test_embedding_mode_reports_local(monkeypatch):
    """embedding_mode() returns 'local' when only local is available."""
    from src.llm import embed_profile as profile
    from src.llm.registry import ProviderRegistry

    monkeypatch.setattr(profile, "local_embedding_available", lambda: True)
    monkeypatch.setattr(
        ProviderRegistry, "get_default",
        lambda: (_ for _ in ()).throw(RuntimeError("none")),
    )
    assert profile.embedding_mode() == "local"


# ---------------------------------------------------------------------------
# 3. readiness reflects keyword-only
# ---------------------------------------------------------------------------

def test_ready_vector_entry_reflects_keyword_only(monkeypatch):
    """check_vector reports keyword-only when embedding_mode says so."""
    from src.server import ready as ready_mod
    from src.llm import embed_profile as profile

    monkeypatch.setattr(profile, "embedding_mode", lambda: "keyword-only")
    status, detail = ready_mod.check_vector()
    assert status == "degraded"
    assert "keyword-only" in detail
