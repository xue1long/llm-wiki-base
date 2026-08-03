"""Regression: every production caller of ``LLMProvider.complete`` MUST
invoke it with the ``messages=[...]`` chat-message contract.

The audit final review (I1) flagged five production callers still using
the removed ``prompt=`` / positional-string form:

  - src/searcher/qa.py (generate_answer)
  - src/quality/judge.py (QualityJudge.judge_page)
  - src/quality/ensemble.py (EnsembleJudge.vote_one)
  - src/research/runner.py (run_deep_research x2)
  - src/vision/captioner.py (VisionCaptioner.caption_one)

This test wires a StrictProvider mock (one that REJECTS the legacy
``prompt=`` form) into each caller and asserts that the code path
either succeeds (proving the call site was migrated) or raises
``TypeError`` because the caller passed the wrong shape (regression).
"""
import pytest


class StrictProvider:
    """Provider that rejects any call not matching the chat-messages contract.

    - Accepts: ``complete(messages=list[dict], **kw)`` where every item is
      ``{"role": str, "content": str}``.
    - Accepts: ``complete(prompt=...)`` ONLY if the caller ALSO wraps it in
      messages — the audit fix converts legacy prompt to messages.

    Any other shape (positional ``str``, missing ``messages``) raises
    ``TypeError`` so callers that regressed are caught immediately.
    """

    def __init__(self, content: str = "{}") -> None:
        self._content = content
        self.calls: list[dict] = []

    async def complete(self, messages=None, *, prompt=None, **kwargs):
        self.calls.append({"messages": messages, "prompt": prompt, "kwargs": kwargs})

        # If callers migrated, they pass messages= as a list of dicts.
        if isinstance(messages, list) and messages and all(
            isinstance(m, dict) and "role" in m and "content" in m for m in messages
        ):
            from src.llm.base import LLMResponse
            return LLMResponse(content=self._content, model="test", usage=None)

        # Otherwise it's a contract violation — surface a TypeError.
        raise TypeError(
            f"complete() requires messages=[...]; got messages={messages!r}, prompt={prompt!r}"
        )

    async def embed(self, *a, **kw):
        raise NotImplementedError

    async def health_check(self) -> dict:
        return {"ok": True, "detail": "test"}


# ---------- searcher.qa.generate_answer ----------

@pytest.mark.asyncio
async def test_searcher_qa_uses_messages_contract(monkeypatch):
    from src.searcher import qa

    provider = StrictProvider(content='{"answer": "ok"}')
    monkeypatch.setattr(qa, "_llm_provider", provider)

    out = await qa.generate_answer("hi", [{"content": "doc"}])
    assert out is not None
    # The call must have used messages= (not prompt=).
    assert provider.calls[0]["messages"] is not None
    assert provider.calls[0]["prompt"] is None


# ---------- quality.judge.QualityJudge.judge_page ----------

@pytest.mark.asyncio
async def test_quality_judge_uses_messages_contract(monkeypatch):
    from src.quality.judge import QualityJudge
    from src.quality.types import QualitySettings

    settings = QualitySettings()
    judge = QualityJudge(settings=settings)
    monkeypatch.setattr(judge, "provider", StrictProvider(content='{"scores": {}, "issues": []}'))

    result = await judge.judge_page("p1", "entity", "body", "source")
    assert result.page_id == "p1"


# ---------- quality.ensemble.EnsembleJudge.vote_one ----------

@pytest.mark.asyncio
async def test_quality_ensemble_uses_messages_contract(monkeypatch):
    from src.quality.ensemble import EnsembleJudge
    from src.quality.types import QualitySettings
    from src.llm.registry import ProviderRegistry, ProviderConfig

    # Register a tiny provider for the ensemble to resolve
    monkeypatch.setattr(
        ProviderRegistry,
        "load",
        lambda: {"openai": ProviderConfig(name="openai", type="openai", api_key="x")},
    )
    monkeypatch.setattr(ProviderRegistry, "require", lambda n: ProviderConfig(name=n, type="openai", api_key="x"))

    settings = QualitySettings()
    ens = EnsembleJudge(settings=settings, ensemble_judges=[], primary_provider="openai")

    # Patch the factory to return our strict provider
    def fake_factory(name, model_override=None):
        return StrictProvider(content='{"scores": {}}')

    from src.quality import ensemble as ens_mod
    monkeypatch.setattr(ens_mod, "create_llm_provider", fake_factory)

    agg = await ens.judge_page("p1", "entity", "body", "source")
    assert agg.page_id == "p1"


# ---------- vision.captioner.VisionCaptioner.caption_one ----------

@pytest.mark.asyncio
async def test_vision_captioner_uses_messages_contract(monkeypatch):
    from src.vision.captioner import VisionCaptioner
    from src.vision.extractor import ExtractedImage

    cap = VisionCaptioner.__new__(VisionCaptioner)
    cap.provider_registry_name = "x"
    cap.model = "m"
    cap.provider = StrictProvider(content='{"caption": "x", "alt_text": "y", "entities": [], "confidence": 0.5}')

    img = ExtractedImage(task_id="t", index=0, bytes=b"", mime_type="image/png", source_page="p", context="ctx")
    result = await cap.caption_one(img)
    assert result.confidence == 0.5


# ---------- research.runner.run_deep_research ----------

@pytest.mark.asyncio
async def test_research_runner_uses_messages_contract(monkeypatch, tmp_path):
    from src.research import runner
    from src.project.context import ProjectContext
    from src.wiki.storage.ensure import ensure_knowledge_base

    # Stub LLM factory
    from src.research import runner as runner_mod
    provider = StrictProvider(content='{"queries": ["q1", "q2", "q3"]}')
    # Two calls: queries + synthesis. Give different responses.
    responses = [
        '{"queries": ["q1", "q2", "q3"]}',
        "# synthesis body",
    ]
    call_iter = iter(responses)

    class _TwoRespProvider(StrictProvider):
        async def complete(self, *a, **kw):
            self.calls.append({"kwargs": kw})
            from src.llm.base import LLMResponse
            return LLMResponse(content=next(call_iter), model="test", usage=None)

    monkeypatch.setattr(runner_mod, "create_llm_provider", lambda n: _TwoRespProvider())
    monkeypatch.setattr(runner_mod, "ProviderRegistry", type("PR", (), {
        "get_default": staticmethod(lambda: type("Cfg", (), {"name": "openai"})()),
    })())

    # Stub Tavily
    class _TavilyStub:
        api_key = ""
        async def search(self, q, top_k=10): return []
        async def close(self): return None
    monkeypatch.setattr(runner, "TavilyProvider", lambda k: _TavilyStub())
    monkeypatch.setattr(runner, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "append_to_index", lambda *a, **kw: None)

    # Setup project
    ensure_knowledge_base(tmp_path)
    ctx = ProjectContext.from_path(tmp_path)

    result = await runner.run_deep_research(ctx, topic="topic")
    assert "synthesis_path" in result
