"""Tests for QualityJudge (with a fake LLM provider)."""
import asyncio
import json

from src.quality.judge import QualityJudge
from src.quality.types import QualitySettings


class FakeProvider:
    """Stub LLM provider that returns a predetermined JSON verdict."""
    name = "fake"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[str] = []

    async def complete(self, prompt: str, **kwargs):
        self.calls.append(prompt)
        # Return content as a plain JSON string — judge parses either LLMResponse.content or dict.
        from src.llm.base import LLMResponse
        return LLMResponse(
            content=json.dumps(self.payload),
            model="fake",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
        )

    async def close(self):
        pass


def _pass_payload(score=0.9):
    return {
        "scores": {k: score for k in [
            "source_type_appropriateness", "factuality", "completeness",
            "clarity", "readability", "searchability",
        ]},
        "issues": [],
        "improvement_suggestions": "looks good",
    }


def _fail_payload(score=0.3):
    return _pass_payload(score=score)


def test_judge_page_returns_pass(monkeypatch):
    settings = QualitySettings()
    provider = FakeProvider(_pass_payload(score=0.9))
    monkeypatch.setattr("src.quality.judge.create_llm_provider", lambda name: provider)

    judge = QualityJudge(settings, "openai")
    j = asyncio.run(judge.judge_page("p1", "entity", "some body"))
    assert j.verdict == "pass"
    assert j.total_score >= 0.7
    assert len(provider.calls) == 1


def test_judge_batch_pass(monkeypatch):
    settings = QualitySettings(threshold_pass=0.7)
    provider = FakeProvider(_pass_payload(score=0.9))
    monkeypatch.setattr("src.quality.judge.create_llm_provider", lambda name: provider)

    judge = QualityJudge(settings, "openai")
    pages = [{"id": "a", "type": "entity", "body": "x"}, {"id": "b", "type": "entity", "body": "y"}]
    result = asyncio.run(judge.judge_batch(pages))
    assert set(result.pages_passed) == {"a", "b"}
    assert result.pages_quarantined == []


def test_judge_batch_reject_after_retry(monkeypatch):
    settings = QualitySettings(threshold_pass=0.7)
    provider = FakeProvider(_fail_payload(score=0.3))
    monkeypatch.setattr("src.quality.judge.create_llm_provider", lambda name: provider)

    judge = QualityJudge(settings, "openai")
    pages = [{"id": "x", "type": "entity", "body": "bad"}]
    result = asyncio.run(judge.judge_batch(pages))
    assert "x" in result.pages_quarantined
    assert "x" in result.pages_rejected
    # Two calls: initial + 1 retry
    assert result.pages["x"].llm_call_count == 2


def test_score_validation_caps_out_of_range(monkeypatch):
    """LLM hallucinates 1.5 for some dim → judge clamps to 0 (passed via _safe_scores)."""
    settings = QualitySettings()
    bad_payload = {
        "scores": {k: 0.5 for k in [
            "source_type_appropriateness", "factuality", "completeness",
            "clarity", "readability", "searchability",
        ]},
        "issues": [],
        "improvement_suggestions": "",
    }
    # Overwrite one score to verify graceful handling
    bad_payload["scores"]["clarity"] = 1.7  # out of range
    provider = FakeProvider(bad_payload)
    monkeypatch.setattr("src.quality.judge.create_llm_provider", lambda name: provider)

    judge = QualityJudge(settings, "openai")
    j = asyncio.run(judge.judge_page("p", "entity", "x"))
    # clarity clamped to 0.0
    assert j.scores.clarity == 0.0


def test_judge_batch_uses_ensemble_when_configured(monkeypatch):
    """When ensemble_judges is set, judge_batch delegates to EnsembleJudge."""
    settings = QualitySettings(threshold_pass=0.7)

    provider_calls: list[str] = []

    def fake_create(name, model_override=None):
        provider_calls.append(name)
        return FakeProvider(_pass_payload(score=0.9))

    # EnsembleJudge imports create_llm_provider from src.llm.provider_factory.
    # Patch both the judge module and the ensemble module's reference.
    monkeypatch.setattr("src.quality.judge.create_llm_provider", fake_create)
    monkeypatch.setattr("src.quality.ensemble.create_llm_provider", fake_create)

    judge = QualityJudge(settings, "openai", ensemble_judges=["anthropic"])
    pages = [{"id": "a", "type": "entity", "body": "x"}]
    result = asyncio.run(judge.judge_batch(pages))
    # Both providers called (ensemble path)
    assert "openai" in provider_calls
    assert "anthropic" in provider_calls
    assert "a" in result.pages_passed
    # 2 judges × 1 call each → llm_call_count=2
    assert result.pages["a"].llm_call_count == 2
