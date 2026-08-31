"""Tests for WikiPage._ko_extra round-trip through from_dict/to_frontmatter_dict.

V4 (ADR-002, 2026-08-31): _ko_extra is NOT written to disk by
``to_frontmatter_dict``. Legacy pages that have it in their frontmatter
still get it loaded into the in-memory WikiPage via ``from_dict`` for
backward compatibility with code that needs the KO mirror, but new writes
never include it.
"""
import yaml
from src.wiki.core.types import WikiPage, PageType


def test_ko_extra_not_written_to_disk_v4():
    """V4 contract: to_frontmatter_dict() never emits _ko_extra.

    The V4 schema is an 8-key strict whitelist. _ko_extra (which carried
    KO mirror fields like capture_context/provenance/evidence) is dropped
    on write. Anything that needed _ko_extra must move to a V4 key.
    """
    page = WikiPage(
        id="test-roundtrip", title="Test", type=PageType.SOURCE,
        body="hello",
    )
    page._ko_extra = {"capture_context": "shower thought"}

    fm = page.to_frontmatter_dict()
    assert "_ko_extra" not in fm, (
        "V4: to_frontmatter_dict() must not emit _ko_extra"
    )


def test_ko_extra_default_absent():
    """Normal WikiPage without _ko_extra round-trips cleanly."""
    page = WikiPage(
        id="test-none", title="Test", type=PageType.CONCEPT, body="",
    )
    fm = page.to_frontmatter_dict()
    assert "_ko_extra" not in fm

    fm_text = yaml.dump(fm, allow_unicode=True)
    fm_back = yaml.safe_load(fm_text) or {}
    page2 = WikiPage.from_dict(fm_back, body="")
    # _ko_extra should not exist or be None
    assert getattr(page2, "_ko_extra", None) is None


def test_ko_extra_legacy_read_back():
    """Legacy pages WITH _ko_extra in frontmatter are read back into memory.

    V4 read-side tolerance: pages written before the V4 cut-over still
    carry _ko_extra in disk; we restore it on the in-memory WikiPage so
    any code that still reads it (lint, audit, KO mirror) works. The
    contract is read-only on the read side.
    """
    old_fm = {
        "id": "old-page",
        "title": "Old Page",
        "type": "source",
        "sources": [],
        "created_at": 1700000000000,
        "updated_at": 1700000000000,
        "relations": [],
        "tags": [],
        "_ko_extra": {"capture_context": "shower thought"},
    }
    page = WikiPage.from_dict(old_fm, body="hello")
    assert hasattr(page, "_ko_extra")
    assert page._ko_extra == {"capture_context": "shower thought"}

    # V4: writing this page drops _ko_extra (no longer in frontmatter).
    fm = page.to_frontmatter_dict()
    assert "_ko_extra" not in fm


def test_ko_extra_multiple_fields_dropped_on_write():
    """All legacy _ko_extra fields are dropped on V4 write.

    V4 only writes the 8-key whitelist. Even if multiple _ko_extra subkeys
    are set on the in-memory page, none of them reach disk.
    """
    page = WikiPage(
        id="test-multi", title="Multi", type=PageType.CONCEPT,
        body="",
    )
    page._ko_extra = {
        "knowledge_object_id": "ko_123",
        "document_id": "doc_456",
        "evidence": [{"document_id": "doc_456", "block_id": "block_1"}],
        "projection_version": "kc-wiki-v1",
    }
    fm = page.to_frontmatter_dict()
    assert "_ko_extra" not in fm