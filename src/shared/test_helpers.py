"""Shared test helpers (mock LLM providers, etc.)."""
import json

from src.llm.base import LLMResponse


class ScriptedLLMProvider:
    """Mock LLM provider that returns scripted_responses in order.

    Each scripted entry is wrapped as ``LLMResponse(content=json.dumps(entry))``
    so callers that depend on ``response.content`` (the post-Task-3 canonical
    payload) work transparently with the mock.
    """

    def __init__(self, scripted_responses: list):
        self.scripted = list(scripted_responses)
        self.calls: list = []

    async def complete(self, messages=None, *, response_format=None, system=None, **kwargs):
        # Preserve backwards-compat kwarg-style usage from legacy tests:
        # ScriptedLLMProvider used to accept prompt=str positionally — accept
        # both forms (messages= list OR prompt= str) so old and new tests
        # both work.
        if messages is None:
            prompt = kwargs.pop("prompt", None)
            if prompt is not None:
                self.calls.append({"prompt": prompt, "schema": response_format})
            else:
                self.calls.append({"messages": [], "schema": response_format})
        else:
            self.calls.append({"messages": messages, "schema": response_format})

        if not self.scripted:
            raise RuntimeError(f"Mock LLM exhausted (calls: {len(self.calls)})")
        entry = self.scripted.pop(0)
        # If the entry is already an LLMResponse, return as-is (covers callers
        # who want to test the parse path). Else wrap as content=json.dumps().
        if isinstance(entry, LLMResponse):
            return entry
        if isinstance(entry, str):
            return LLMResponse(content=entry, model="mock")
        return LLMResponse(content=json.dumps(entry), model="mock")
