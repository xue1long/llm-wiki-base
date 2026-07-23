"""Regression tests for the F1 dead-code cleanup.

These assertions deliberately check the public implementation surface rather
than exercising compatibility behavior that the provider contract no longer
supports.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

from src.agent.runtime import AgentRuntime
from src.llm.openai_provider import OpenAIProvider
from src.llm.ollama_provider import OllamaProvider
from src.llm.types import ProviderConfig


def test_agent_runtime_only_extracts_llm_response_content() -> None:
    """The runtime must not retain the removed dict-response compatibility path."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(AgentRuntime.run)))

    dict_isinstance_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
        and len(node.args) == 2
        and isinstance(node.args[1], ast.Name)
        and node.args[1].id == "dict"
    ]
    assert not dict_isinstance_calls


def test_openai_provider_keeps_sdk_client_only_in_private_storage() -> None:
    """OpenAIProvider should use ``_sdk`` rather than expose ``client``."""
    sdk_client = object()
    config = ProviderConfig(
        name="openai",
        type="openai",
        api_key="test-key",
        default_chat_model="test-model",
    )

    provider = OpenAIProvider(config, client=sdk_client)

    assert provider._sdk is sdk_client
    assert not hasattr(provider, "client")


def test_ollama_embedding_interface_is_embed_only() -> None:
    """The provider contract exposes ``embed`` and no legacy ``embedding`` alias."""
    assert hasattr(OllamaProvider, "embed")
    assert not hasattr(OllamaProvider, "embedding")
