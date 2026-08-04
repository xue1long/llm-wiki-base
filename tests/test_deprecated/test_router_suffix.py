# ruflo-kb/tests/test_deprecated/test_router_suffix.py
"""Verify route_task uses suffix-based extension detection, drops UNKNOWN,
and raises ValueError on empty input.

Before the fix: the router did substring matching (".md" in lower) which
mis-classified natural-language questions containing the literal token ".md"
as INGEST. It also silently returned INGEST for any unrecognized input,
obscuring routing failures.
"""
import pytest

pytest.importorskip("src._deprecated.orchestrator")
from src._deprecated.orchestrator.router import route_task, TaskIntent


def test_search_question_with_md_word_is_search():
    # "what is the .md format?" — natural language question containing ".md"
    # must still be classified as SEARCH, not INGEST.
    assert route_task("what is the .md format?") == TaskIntent.SEARCH


def test_url_with_extension_is_ingest():
    assert route_task("https://example.com/foo.pdf") == TaskIntent.INGEST
    assert route_task("https://example.com/foo.docx") == TaskIntent.INGEST
    assert route_task("https://example.com/foo.md") == TaskIntent.INGEST


def test_empty_input_raises():
    with pytest.raises(ValueError):
        route_task("")


def test_whitespace_only_raises():
    with pytest.raises(ValueError):
        route_task("   \t\n")


def test_unknown_intent_dropped():
    """TaskIntent.UNKNOWN must no longer exist — the brief requires dropping it."""
    assert not hasattr(TaskIntent, "UNKNOWN")
