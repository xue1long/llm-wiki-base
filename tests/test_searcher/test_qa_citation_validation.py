"""qa module must validate citations in the LLM output.

Per the brief: any ``[1-9]\\d*`` citation index not in
``range(1, len(context) + 1)`` must be discarded; remaining valid
citations must be preserved.

A citation outside the valid range (e.g. ``[99]`` when only 2 sources
exist) is a hallucinated reference and must not be passed through to
the caller.

We test the citation-parsing helper directly, plus a citation-stripping
helper, so the validation logic is verifiable without an LLM.
"""

from src.searcher.qa import (
    validate_citations,
    strip_invalid_citations,
    _parse_citation_indices,
)


def test_parse_citation_indices_simple():
    """Extract all [N] markers from text."""
    assert _parse_citation_indices("hello [1] world [2]") == [1, 2]


def test_parse_citation_indices_no_citations():
    assert _parse_citation_indices("no citations here") == []


def test_parse_citation_indices_multi_digit():
    assert _parse_citation_indices("ref [12] and [345]") == [12, 345]


def test_parse_citation_indices_ignores_zero():
    """[0] is not a valid citation (1-indexed)."""
    assert _parse_citation_indices("not a ref [0]") == []


def test_parse_citation_indices_dedup_preserves_order():
    """Repeated citation indices appear once in the result."""
    assert _parse_citation_indices("[1] again [1] and [2] [2]") == [1, 2]


def test_validate_citations_all_in_range():
    """All citations within range → all preserved, in document order, no dupes."""
    out = validate_citations("[1] and [2]", n_context=3)
    assert out == [1, 2]


def test_validate_citations_drops_out_of_range():
    """Citations beyond n_context are dropped."""
    out = validate_citations("[1] [2] [99]", n_context=2)
    assert out == [1, 2]


def test_validate_citations_drops_zero():
    """[0] is not a valid 1-indexed citation and is dropped."""
    out = validate_citations("[0] [1]", n_context=2)
    assert out == [1]


def test_validate_citations_empty_text():
    assert validate_citations("", n_context=5) == []


def test_validate_citations_n_context_zero():
    """When there are no context sources, no citation can be valid."""
    assert validate_citations("[1] [2]", n_context=0) == []


def test_strip_invalid_citations_keeps_valid():
    """Citations in range are preserved (with brackets)."""
    text = "Per [1] and [2] the answer is X."
    out = strip_invalid_citations(text, n_context=3)
    assert "[1]" in out
    assert "[2]" in out
    assert "[99]" not in out


def test_strip_invalid_citations_removes_invalid():
    """Citations out of range are stripped from the text."""
    text = "The claim [99] is unfounded."
    out = strip_invalid_citations(text, n_context=2)
    assert "[99]" not in out
    # Other text content remains
    assert "The claim" in out
    assert "is unfounded" in out


def test_strip_invalid_citations_preserves_phrase():
    text = "Per [1] (a) and [99] (b) the answer is X."
    out = strip_invalid_citations(text, n_context=2)
    assert "[1]" in out
    assert "[99]" not in out
