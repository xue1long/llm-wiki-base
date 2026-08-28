"""Keep the test suite independent from host-specific RUFLO settings."""
import pytest


@pytest.fixture(autouse=True)
def _clear_host_llm_provider(monkeypatch):
    monkeypatch.delenv("RUFLO_LLM_PROVIDER", raising=False)
