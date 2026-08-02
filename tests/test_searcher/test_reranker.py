# ruflo-kb/tests/test_searcher/test_reranker.py
"""Tests for the Reranker module — post-retrieval ranking with config toggle."""

import pytest

from src.searcher.reranker import (
    MAX_OVERLAP_BOOST,
    RankedResult,
    Reranker,
    RerankerConfig,
    SOURCE_DIVERSITY_BONUS,
    SOURCE_WEIGHTS,
)


def _make(
    object_id: str = "a",
    title: str = "A",
    content: str = "",
    score: float = 0.5,
    source: str = "vector",
    metadata: dict | None = None,
) -> RankedResult:
    """Helper to create a RankedResult with minimal boilerplate."""
    return RankedResult(
        object_id=object_id,
        title=title,
        content=content,
        score=score,
        source=source,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Test disabled pass-through (critical path)
# ---------------------------------------------------------------------------

def test_disabled_passes_through():
    """Reranker with enabled=False returns results unchanged."""
    reranker = Reranker(RerankerConfig(enabled=False))
    results = [_make(object_id="1"), _make(object_id="2")]
    out = reranker.rerank(results, "test query")
    assert out is results  # same list object


def test_disabled_is_default():
    """Reranker() with no config defaults to enabled=False."""
    reranker = Reranker()
    assert reranker.config.enabled is False
    results = [_make(object_id="1")]
    out = reranker.rerank(results, "any query")
    assert out is results


# ---------------------------------------------------------------------------
# Test enabled score_fusion
# ---------------------------------------------------------------------------

def test_enabled_score_fusion_reorders():
    """Enabled score_fusion re-ranks results — a result with higher
    relevance gets promoted."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    results = [
        _make(object_id="1", score=0.3, source="keyword"),
        _make(object_id="2", score=0.9, source="vector"),
    ]
    out = reranker.rerank(results, "test")
    # Higher-scored result should come first after fusion
    assert out[0].object_id == "2"
    assert out[1].object_id == "1"


def test_score_fusion_sorts_by_score_desc():
    """Final results are sorted by score descending."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    results = [
        _make(object_id="1", score=0.2, source="vector"),
        _make(object_id="2", score=0.9, source="vector"),
        _make(object_id="3", score=0.5, source="vector"),
    ]
    out = reranker.rerank(results, "test")
    scores = [r.score for r in out]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Test deduplication
# ---------------------------------------------------------------------------

def test_deduplication():
    """Two results with same object_id are merged into one."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    results = [
        _make(object_id="dup", score=0.6, source="vector"),
        _make(object_id="dup", score=0.4, source="keyword"),
    ]
    out = reranker.rerank(results, "test")
    ids = [r.object_id for r in out]
    assert ids == ["dup"]
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Test empty / single result edge cases
# ---------------------------------------------------------------------------

def test_empty_results():
    """Empty list returns empty list (no crash)."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    out = reranker.rerank([], "test")
    assert out == []


def test_single_result():
    """Single result is returned as-is."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    result = _make(object_id="only")
    out = reranker.rerank([result], "test")
    assert len(out) == 1
    assert out[0].object_id == "only"


# ---------------------------------------------------------------------------
# Test source diversity bonus
# ---------------------------------------------------------------------------

def test_source_bonus():
    """Result appearing in multiple sources gets score boosted."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    # Same object, two different sources
    results = [
        _make(object_id="x", score=0.8, source="vector"),
        _make(object_id="x", score=0.8, source="keyword"),
    ]
    out = reranker.rerank(results, "test")
    # Base weighted score = 0.8*0.5 + 0.8*0.3 = 0.4 + 0.24 = 0.64
    # Diversity bonus = 0.1 * (2-1) = 0.1
    # Expected composite = 0.74 (before query boost)
    # Query "test" doesn't match title "X", so no boost
    assert out[0].score > 0.7


def test_no_bonus_for_single_source():
    """Result from only one source gets no diversity bonus."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    results = [_make(object_id="x", score=0.8, source="vector")]
    out = reranker.rerank(results, "test")
    # Score = 0.8 * 0.5 = 0.4 (no diversity bonus, no query overlap)
    assert out[0].score == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Test query overlap boost
# ---------------------------------------------------------------------------

def test_query_overlap_boost():
    """Result with more query term matches gets a higher score."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    results = [
        _make(
            object_id="1", title="Python Guide",
            content="learn python programming", score=0.5, source="vector",
        ),
        _make(
            object_id="2", title="Java Guide",
            content="java is unrelated", score=0.5, source="vector",
        ),
    ]
    out = reranker.rerank(results, "python programming")
    # "1" matches both "python" and "programming" → 2/2 = 1.0 * 0.1 = 0.1 boost
    # "2" matches 0 terms → no boost
    by_id = {r.object_id: r.score for r in out}
    assert by_id["1"] > by_id["2"]


def test_query_overlap_partial():
    """Partial query term matching gives proportional boost."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    result = _make(
        object_id="1", title="Python",
        content="python language", score=0.5, source="vector",
    )
    out = reranker.rerank([result], "python java rust go")
    # Matches 1 out of 4 terms = 0.25 * 0.1 = 0.025 boost
    # Base score after fusion: 0.5 * 0.5 = 0.25
    assert out[0].score == pytest.approx(0.275)


# ---------------------------------------------------------------------------
# Test LLM fallback
# ---------------------------------------------------------------------------

def test_fallback_llm_to_score_fusion():
    """method='llm' but no LLM configured — falls back to score_fusion."""
    reranker = Reranker(RerankerConfig(enabled=True, method="llm"))
    results = [
        _make(object_id="1", score=0.9, source="vector"),
        _make(object_id="2", score=0.3, source="keyword"),
    ]
    out = reranker.rerank(results, "test")
    # Should still reorder (score_fusion applied), not pass through
    assert out[0].object_id == "1"
    assert len(out) == 2


# ---------------------------------------------------------------------------
# Test score range
# ---------------------------------------------------------------------------

def test_score_range_0_1():
    """All output scores are within [0.0, 1.0]."""
    reranker = Reranker(RerankerConfig(enabled=True, method="score_fusion"))
    results = [
        _make(object_id="1", score=0.99, source="vector"),
        _make(object_id="2", score=0.01, source="keyword"),
        _make(object_id="3", score=0.5, source="graph"),
        # Same id in multiple sources for diversity bonus
        _make(object_id="1", score=0.99, source="keyword"),
    ]
    out = reranker.rerank(results, "test")
    for r in out:
        assert 0.0 <= r.score <= 1.0, f"Score {r.score} out of range for {r.object_id}"


# ---------------------------------------------------------------------------
# Test config dataclass
# ---------------------------------------------------------------------------

def test_config_defaults():
    """RerankerConfig has correct default values."""
    cfg = RerankerConfig()
    assert cfg.enabled is False
    assert cfg.method == "score_fusion"


def test_config_custom():
    """RerankerConfig accepts custom values."""
    cfg = RerankerConfig(enabled=True, method="llm")
    assert cfg.enabled is True
    assert cfg.method == "llm"
