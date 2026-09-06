from dataclasses import replace

import pytest

from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.outline_validate import (
    build_page_index,
    validate_outline,
    validate_outline_schema,
)


def snapshot(*ids: str, unclassified: set[str] | None = None) -> WikiSnapshot:
    unclassified = unclassified or set()
    pages = tuple(
        PageRecord(i, f"Title {i}", "concept", f"concepts/{i}.md", None if i in unclassified else "x", "summary", (), (), "hash", 7, None)
        for i in ids
    )
    return WikiSnapshot("snap-1", "/wiki", "wiki-v3", pages, ())


def outline(ids: list[str], *, fallback: bool = False) -> dict:
    return {
        "schema_version": "outline-v1",
        "snapshot_id": "snap-1",
        "volumes": [{
            "volume_id": "v1",
            "title": "Volume",
            "is_fallback": fallback,
            "chapters": [{
                "chapter_id": "c1",
                "title": "Chapter",
                "page_ids": ids,
                "overview_refs": ids[:1],
            }],
        }],
    }


def codes(report):
    return {error.code for error in report.errors}


def test_valid_dynamic_sizes_and_repeated_titles() -> None:
    for ids in (("a",), ("a", "b", "c"), tuple(f"p{i}" for i in range(20))):
        report = validate_outline(snapshot(*ids), [outline(list(ids))])
        assert report.ok, report.errors
    payload = outline(["a"])
    payload["volumes"][0]["title"] = "same"
    assert validate_outline(snapshot("a"), [payload]).ok


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        (["a"], "missing-id"),
        (["a", "unknown"], "unknown-id"),
        (["a", "a"], "duplicate-id"),
    ],
)
def test_exact_id_coverage_is_fail_closed(ids: list[str], expected: str) -> None:
    report = validate_outline(snapshot("a", "b"), [outline(ids)])
    assert not report.ok
    assert expected in codes(report)


def test_duplicate_volume_and_chapter_ids_are_rejected() -> None:
    payload = outline(["a"])
    payload["volumes"].append(payload["volumes"][0].copy())
    report = validate_outline(snapshot("a"), [payload])
    assert "duplicate-volume-id" in codes(report)
    payload = outline(["a"])
    payload["volumes"][0]["chapters"].append(payload["volumes"][0]["chapters"][0].copy())
    report = validate_outline(snapshot("a"), [payload])
    assert "duplicate-chapter-id" in codes(report)


def test_fallback_volume_only_allowed_when_it_covers_pages() -> None:
    assert validate_outline(snapshot("a", unclassified={"a"}), [outline(["a"], fallback=True)]).ok
    report = validate_outline(snapshot("a"), [outline(["a"])])
    assert report.ok
    report = validate_outline(snapshot("a", unclassified={"a"}), [outline([], fallback=True)])
    assert not report.ok
    assert "empty-fallback" in codes(report)


def test_invalid_confidence_and_overview_refs() -> None:
    payload = outline(["a"])
    payload["volumes"][0]["chapters"][0]["confidence"] = float("nan")
    payload["volumes"][0]["chapters"][0]["overview_refs"] = ["unknown"]
    report = validate_outline(snapshot("a"), [payload])
    assert {"invalid-confidence", "invalid-overview-refs"} <= codes(report)


def test_schema_is_versioned_and_index_never_overwrites() -> None:
    errors = validate_outline_schema({"schema_version": "outline-v99"})
    assert any(error.code == "schema-version" for error in errors)
    with pytest.raises(ValueError, match="duplicate page id"):
        build_page_index([outline(["a"]), outline(["a"])])
