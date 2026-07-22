"""Tests for EnsembleJudge."""
import asyncio
import json

from src.llm.base import LLMResponse
from src.quality.ensemble import EnsembleJudge, _safe_scores
from src.quality.types import QualitySettings, JudgmentScores


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[str] = []

    async def complete(self, prompt, **kwargs):
        self.calls.append(prompt)
        return LLMResponse(content=json.dumps(self.payload), model="fake", usage={})

    async def close(self):
        pass


GOOD_SCORES = {k: 0.9 for k in [
    "source_type_appropriateness", "factuality", "completeness",
    "clarity", "readability", "searchability",
]}


def test_ensemble_default_2_judges(monkeypatch):
    """Both providers exist in registry → 2 judges participate."""
    from src.llm import registry as reg
    providers_calls: list[str] = []

    def fake_create(name, model_override=None):
        providers_calls.append(name)
        # Both judges agree on high quality
        return FakeProvider({"scores": GOOD_SCORES, "issues": [], "improvement_suggestions": "ok"})

    monkeypatch.setattr("src.quality.ensemble.create_llm_provider", fake_create)
    settings = QualitySettings()

    ensemble = EnsembleJudge(settings, ensemble_judges=["anthropic"], primary_provider="openai")
    agg = asyncio.run(ensemble.judge_page("p1", "entity", "good body"))
    # Both judges voted
    assert len(agg.votes) == 2
    assert agg.verdict == "pass"
    assert providers_calls == ["openai", "anthropic"]


def test_ensemble_veto_on_low_factuality(monkeypatch):
    """One judge scores factuality=0.1 → verdict=reject (no second chance)."""
    from src.llm import registry as reg
    def fake_create(name, model_override=None):
        if name == "openai":
            bad = dict(GOOD_SCORES)
            bad["factuality"] = 0.1  # below veto threshold
            return FakeProvider({"scores": bad, "issues": [], "improvement_suggestions": ""})
        return FakeProvider({"scores": GOOD_SCORES, "issues": [], "improvement_suggestions": ""})

    monkeypatch.setattr("src.quality.ensemble.create_llm_provider", fake_create)
    settings = QualitySettings()
    ensemble = EnsembleJudge(settings, ensemble_judges=["anthropic"], primary_provider="openai")
    agg = asyncio.run(ensemble.judge_page("p1", "entity", "x"))
    assert agg.verdict == "reject"
    # Veto issue present
    assert any("Veto" in i.get("description", "") for i in agg.issues)


def test_ensemble_aggregation_mean(monkeypatch):
    """Mean of two votes per dimension."""
    scores_a = {k: 0.6 for k in [
        "source_type_appropriateness", "factuality", "completeness",
        "clarity", "readability", "searchability",
    ]}
    scores_b = {k: 0.8 for k in [
        "source_type_appropriateness", "factuality", "completeness",
        "clarity", "readability", "searchability",
    ]}

    def fake_create(name, model_override=None):
        if name == "openai":
            return FakeProvider({"scores": scores_a, "issues": [
                {"dimension": "clarity", "severity": "minor", "description": "A"},
            ], "improvement_suggestions": "from A"})
        return FakeProvider({"scores": scores_b, "issues": [
            {"dimension": "clarity", "severity": "minor", "description": "A"},  # duplicate by description
            {"dimension": "completeness", "severity": "major", "description": "B"},
        ], "improvement_suggestions": "from B"})

    monkeypatch.setattr("src.quality.ensemble.create_llm_provider", fake_create)
    settings = QualitySettings()
    ensemble = EnsembleJudge(settings, ensemble_judges=["anthropic"], primary_provider="openai")
    agg = asyncio.run(ensemble.judge_page("p1", "entity", "x"))

    # Mean should be 0.7 for every dim
    for dim in [
        "source_type_appropriateness", "factuality", "completeness",
        "clarity", "readability", "searchability",
    ]:
        assert abs(getattr(agg.aggregated_scores, dim) - 0.7) < 1e-6

    # Deduplicated issues by (dimension, description) — 2 distinct issues
    descriptions = [i.get("description") for i in agg.issues]
    assert descriptions.count("A") == 1
    assert descriptions.count("B") == 1


def test_safe_scores_clamps_out_of_range():
    bad = {"clarity": 1.5, "factuality": -0.3}
    s = _safe_scores(bad)
    assert s.clarity == 0.0  # clamped (out of range → 0)
    assert s.factuality == 0.0  # clamped
