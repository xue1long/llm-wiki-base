"""Test: Anthropic default base_url ends with /v1.

Background: The default registry entry had base_url 'https://api.anthropic.com'
without the /v1 path, which would build requests like
https://api.anthropic.com/messages instead of https://api.anthropic.com/v1/messages.
"""
from src.llm.registry import _default_providers


def test_anthropic_default_base_url_ends_with_v1():
    """The registry's default Anthropic provider must use base_url .../v1."""
    defaults = _default_providers()
    assert "anthropic" in defaults
    anthropic = defaults["anthropic"]
    assert anthropic.base_url.endswith("/v1"), (
        f"Anthropic base_url must end with /v1, got {anthropic.base_url!r}"
    )
    assert anthropic.base_url == "https://api.anthropic.com/v1"
