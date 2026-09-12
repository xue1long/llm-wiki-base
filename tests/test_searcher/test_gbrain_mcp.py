from __future__ import annotations

import pytest

from src.searcher.gbrain_mcp import (
    GBrainSearchError,
    adapt_results,
    build_search_request,
    search_with_fallback,
)


def _manifest():
    return {
        "wiki/sources/a": {
            "path": "wiki/sources/a.md",
            "page_type": "source",
        },
        "wiki/concepts/b": {
            "path": "wiki/concepts/b.md",
            "page_type": "concept",
        },
    }


def test_adapter_validates_source_deduplicates_chunks_and_maps_paths():
    remote = [
        {"slug": "wiki/sources/a", "page_id": "1", "title": "A", "type": "source", "chunk_text": "low", "score": 0.4, "source_id": "ruflo-demo"},
        {"slug": "wiki/sources/a", "page_id": "1", "title": "A", "type": "source", "chunk_text": "high", "score": 0.9, "source_id": "ruflo-demo"},
        {"slug": "wiki/concepts/b", "page_id": "2", "title": "B", "type": "concept", "chunk_text": "b", "score": 0.8, "source_id": "ruflo-demo"},
    ]

    result = adapt_results(remote, source_id="ruflo-demo", manifest=_manifest(), top_k=10)

    assert [item["path"] for item in result] == ["wiki/sources/a.md", "wiki/concepts/b.md"]
    assert result[0]["content"] == "high"
    assert result[0]["source"] == "gbrain"


def test_adapter_fails_closed_on_wrong_source_or_unmapped_slug():
    base = {"slug": "wiki/sources/a", "page_id": "1", "title": "A", "type": "source", "chunk_text": "a", "score": 0.9, "source_id": "wrong"}
    with pytest.raises(GBrainSearchError, match="source_scope_mismatch"):
        adapt_results([base], source_id="ruflo-demo", manifest=_manifest(), top_k=3)

    base["source_id"] = "ruflo-demo"
    base["slug"] = "wiki/missing"
    with pytest.raises(GBrainSearchError, match="path_mapping_failed"):
        adapt_results([base], source_id="ruflo-demo", manifest=_manifest(), top_k=3)


def test_search_falls_back_to_local_on_remote_error():
    local = [{"path": "wiki/sources/a.md", "title": "A", "score": 0.5, "source": "local"}]

    result = search_with_fallback(
        lambda: [{"slug": "wiki/missing", "page_id": "1", "title": "A", "type": "source", "chunk_text": "a", "score": 0.9, "source_id": "ruflo-demo"}],
        lambda: local,
        source_id="ruflo-demo",
        manifest=_manifest(),
        top_k=3,
    )

    assert result.results == local
    assert result.fallback_reason == "path_mapping_failed"


def test_search_request_never_carries_source_in_user_arguments():
    request = build_search_request("how to deploy", 5)

    assert request["method"] == "tools/call"
    assert request["params"] == {
        "name": "search",
        "arguments": {"query": "how to deploy", "limit": 5},
    }
