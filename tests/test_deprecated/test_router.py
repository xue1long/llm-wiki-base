# ruflo-kb/tests/test_deprecated/test_router.py
# Tests for deprecated orchestrator module
import pytest

pytest.importorskip("src._deprecated.orchestrator")
from src._deprecated.orchestrator.router import route_task, parse_source, TaskIntent

def test_route_task_search():
    assert route_task("?hello world") == TaskIntent.SEARCH
    assert route_task("search: hello") == TaskIntent.SEARCH
    assert route_task("find: something") == TaskIntent.SEARCH

def test_route_task_ingest():
    assert route_task("http://example.com") == TaskIntent.INGEST
    assert route_task("/path/to/file.md") == TaskIntent.INGEST
    assert route_task("/path/to/file.pdf") == TaskIntent.INGEST

def test_parse_source_url():
    source, source_type = parse_source("http://example.com")
    assert source == "http://example.com"
    assert source_type == "url"

def test_parse_source_file():
    source, source_type = parse_source("/path/to/file.md")
    assert source == "/path/to/file.md"
    assert source_type == "file"
