"""Tests for quality types and scoring math."""
from src.quality.types import (
    JudgmentScores, Judgment, QualitySettings,
    compute_total, verdict_for,
)


def test_score_validation_raises_for_out_of_range():
    s = JudgmentScores(2.0, 0.5, 0.5, 0.5, 0.5, 0.5)  # source_type out of range
    import pytest
    with pytest.raises(ValueError):
        compute_total(s, QualitySettings().weights)


def test_compute_total_weighted():
    s = JudgmentScores(1.0, 0.8, 0.6, 0.5, 0.4, 0.3)
    weights = {
        "source_type_appropriateness": 0.20,
        "factuality": 0.40,
        "completeness": 0.20,
        "clarity": 0.10,
        "readability": 0.05,
        "searchability": 0.05,
    }
    total = compute_total(s, weights)
    expected = round(
        1.0 * 0.20 + 0.8 * 0.40 + 0.6 * 0.20 + 0.5 * 0.10 + 0.4 * 0.05 + 0.3 * 0.05, 4
    )
    assert abs(total - expected) < 1e-6


def test_verdict_for_pass_above_threshold():
    settings = QualitySettings(threshold_pass=0.7)
    assert verdict_for(0.8, settings) == "pass"
    assert verdict_for(0.69, settings) == "reject"


def test_judgment_round_trip():
    s = JudgmentScores(0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
    j = Judgment(
        page_id="foo", page_type="entity", scores=s, total_score=0.75,
        verdict="pass", issues=[{"dimension": "clarity", "severity": "minor"}],
        improvement_suggestions="lead with TL;DR",
    )
    d = j.to_dict()
    assert d["page_id"] == "foo"
    assert d["scores"]["clarity"] == 0.8
    assert d["verdict"] == "pass"


def test_default_weights_sum_to_one():
    settings = QualitySettings()
    total = sum(settings.weights.values())
    assert abs(total - 1.0) < 1e-6


def test_judgment_scores_from_dict():
    d = {
        "source_type_appropriateness": 0.5, "factuality": 0.5,
        "completeness": 0.5, "clarity": 0.5,
        "readability": 0.5, "searchability": 0.5,
    }
    s = JudgmentScores.from_dict(d)
    assert s.source_type_appropriateness == 0.5
