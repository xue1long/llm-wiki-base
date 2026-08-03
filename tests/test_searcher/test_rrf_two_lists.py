"""rrf_fusion must take TWO separate lists and combine per-document
RRF contribution independently for each list.

Background: the prior bug concatenated the two lists into one and ran
RRF over a single stream, which silently re-ranks documents in the
wrong way. Per the brief:
- each list's contribution is ``sum(1 / (k + rank))`` for each doc
  that appears in that list
- then merge across lists by sum, sort desc
- if one side is empty, return the other side's results (not empty)
"""

from src.searcher.hybrid_search import rrf_fusion


def _score(path: str, score: float) -> dict:
    return {"path": path, "title": path, "content": "", "score": score, "source": "x"}


def test_rrf_accepts_two_lists_independently():
    """rrf_fusion signature is (semantic_results, keyword_results, k=60)."""
    sem = [_score("A", 0.9), _score("B", 0.8), _score("C", 0.7)]
    kw = [_score("D", 0.6), _score("A", 0.5), _score("E", 0.4)]
    # A appears in both lists at ranks (0, 1) — should be top
    out = rrf_fusion(sem, kw, k=60)
    assert out[0]["path"] == "A"


def test_rrf_doc_in_both_lists_outranks_doc_in_one():
    """A (sem[0], kw[1]) must beat B (sem[1], no-kw) and D (no-sem, kw[0])."""
    sem = [_score("A", 0.9), _score("B", 0.8), _score("C", 0.7)]
    kw = [_score("D", 0.6), _score("A", 0.5), _score("E", 0.4)]
    out = rrf_fusion(sem, kw, k=60)
    paths = [r["path"] for r in out]
    assert paths[0] == "A"
    assert "A" in paths and "B" in paths and "D" in paths
    # Confirm A's score > B's score and A's score > D's score
    by_path = {r["path"]: r["score"] for r in out}
    assert by_path["A"] > by_path["B"]
    assert by_path["A"] > by_path["D"]


def test_rrf_returns_descending_score_order():
    sem = [_score("A", 0.9), _score("B", 0.8), _score("C", 0.7)]
    kw = [_score("D", 0.6), _score("A", 0.5), _score("E", 0.4)]
    out = rrf_fusion(sem, kw, k=60)
    scores = [r["score"] for r in out]
    assert scores == sorted(scores, reverse=True)


def test_rrf_empty_semantic_returns_keyword_results():
    """If semantic list is empty, the keyword list's results must be returned
    (not an empty list)."""
    kw = [_score("A", 0.9), _score("B", 0.8)]
    out = rrf_fusion([], kw, k=60)
    paths = [r["path"] for r in out]
    assert paths == ["A", "B"]


def test_rrf_empty_keyword_returns_semantic_results():
    """If keyword list is empty, the semantic list's results must be returned."""
    sem = [_score("A", 0.9), _score("B", 0.8)]
    out = rrf_fusion(sem, [], k=60)
    paths = [r["path"] for r in out]
    assert paths == ["A", "B"]


def test_rrf_k_parameter_changes_scores():
    """Smaller k gives a stronger rank-1 boost (RRF semantics)."""
    sem = [_score("A", 0.9), _score("B", 0.8)]
    kw = [_score("A", 0.5), _score("B", 0.5)]
    out_k60 = rrf_fusion(sem, kw, k=60)
    out_k1 = rrf_fusion(sem, kw, k=1)
    by60 = {r["path"]: r["score"] for r in out_k60}
    by1 = {r["path"]: r["score"] for r in out_k1}
    # With k=1, the gap between rank-0 and rank-1 is larger than with k=60
    gap_60 = by60["A"] - by60["B"]
    gap_1 = by1["A"] - by1["B"]
    assert gap_1 > gap_60


def test_rrf_doc_only_in_one_list_still_ranked():
    """A doc appearing in only one list still gets a score from that list."""
    sem = [_score("A", 0.9)]
    kw = [_score("B", 0.8)]
    out = rrf_fusion(sem, kw, k=60)
    paths = {r["path"] for r in out}
    assert paths == {"A", "B"}
    by_path = {r["path"]: r["score"] for r in out}
    assert by_path["A"] > 0
    assert by_path["B"] > 0
