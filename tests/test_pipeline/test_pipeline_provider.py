"""Audit I4 regression: pipeline's `_get_provider()` uses the registry default.

Previously hard-coded ``"openai"`` — ignored ``RUFLO_LLM_PROVIDER`` and
the registry's named-default. After the fix, ``_get_provider()`` reads
``ProviderRegistry.get_default()`` and falls back to OpenAI only when
the registry is empty.
"""
from src.pipeline import pipeline as pipeline_mod


def test_get_provider_uses_registry_default(monkeypatch):
    """When the registry has a configured default, _get_provider uses it."""
    from src.llm.registry import ProviderConfig
    from src.llm import registry as reg

    cfg = ProviderConfig(name="myprovider", type="openai", api_key="x",
                         default_chat_model="x")

    monkeypatch.setattr(reg, "ProviderRegistry", type(
        "PR",
        (),
        {
            "get_default": staticmethod(lambda: cfg),
        },
    ))

    captured = {}

    def fake_factory(name, model_override=None):
        captured["name"] = name
        return object()

    # The pipeline module does a local import of create_llm_provider.
    # Patch at the source instead.
    from src.llm import provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", fake_factory)

    provider = pipeline_mod._get_provider()
    assert provider is not None
    # Verify that "myprovider" was the name passed (not hard-coded "openai")
    assert captured.get("name") == "myprovider"


def test_get_provider_falls_back_to_openai_when_registry_empty(monkeypatch):
    """When the registry has no default, fall back to openai."""
    from src.llm.registry import ProviderNotFoundError
    from src.llm import registry as reg

    class FakeRegistry:
        @staticmethod
        def get_default():
            raise ProviderNotFoundError("none")

    monkeypatch.setattr(reg, "ProviderRegistry", FakeRegistry)

    captured = {}

    def fake_factory(name, model_override=None):
        captured["name"] = name
        return object()

    from src.llm import provider_factory as pf
    monkeypatch.setattr(pf, "create_llm_provider", fake_factory)

    pipeline_mod._get_provider()
    assert captured.get("name") == "openai"