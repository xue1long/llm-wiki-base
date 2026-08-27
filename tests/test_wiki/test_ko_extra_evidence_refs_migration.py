"""C-0 Commit 4: migrate ``_ko_extra.evidence`` → ``WikiPage.evidence_refs``.

Plan ref: docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md §C-0 Commit 4.

Behavior under test:
- ``_ko_extra.evidence`` (a list of dicts with ``doc_id`` / ``block_id`` /
  ``quote``) is migrated into ``WikiPage.evidence_refs`` (a list of strings
  of the form ``"<doc_id>:<block_id>"``; ``"<doc_id>"`` if ``block_id``
  is missing).
- New writes go to ``evidence_refs`` directly. ``to_frontmatter_dict`` does
  NOT write ``_ko_extra.evidence``; ``from_dict`` reads it only as a
  migration fallback when ``evidence_refs`` is absent.
- ``_ko_extra`` itself still round-trips for non-evidence keys (no
  regression for ``memory.decision`` / ``provenance`` / ``capture_context``).
"""

from src.wiki.core.types import PageType, WikiPage


# ---------------------------------------------------------------------------
# Test 1: _ko_extra.evidence with full {doc_id, block_id, quote} → list[str]
# ---------------------------------------------------------------------------
def test_ko_extra_evidence_with_block_id_migrates_to_evidence_refs():
    """Legacy frontmatter ``_ko_extra.evidence`` (list of dicts) is migrated
    to ``evidence_refs`` as ``"<doc_id>:<block_id>"`` strings."""
    legacy = {
        "id": "card_legacy_evidence",
        "title": "Legacy Evidence",
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
        "grade": "B",
        "processing_depth": "concept",
        "is_immutable": False,
        "heat": 50,
        "last_used_at": 0,
        "zombie_since": None,
        "tags": [],
        "category": "",
        "taxonomy_sub": "",
        "related_entities": [],
        "custom_type": "",
        "workflow_state": "draft",
        "verified_at": 0,
        "_ko_extra": {
            "evidence": [
                {"doc_id": "d1", "block_id": "b1", "quote": "x"},
            ],
        },
    }
    page = WikiPage.from_dict(legacy, body="")
    assert page.evidence_refs == ["d1:b1"]


# ---------------------------------------------------------------------------
# Test 2: _ko_extra.evidence with doc_id only → "<doc_id>"
# ---------------------------------------------------------------------------
def test_ko_extra_evidence_without_block_id_yields_doc_id_only():
    """Entries without ``block_id`` format as bare ``"<doc_id>"``."""
    legacy = {
        "id": "card_legacy_evidence_no_block",
        "title": "Legacy Evidence No Block",
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
        "grade": "B",
        "processing_depth": "concept",
        "is_immutable": False,
        "heat": 50,
        "last_used_at": 0,
        "zombie_since": None,
        "tags": [],
        "category": "",
        "taxonomy_sub": "",
        "related_entities": [],
        "custom_type": "",
        "workflow_state": "draft",
        "verified_at": 0,
        "_ko_extra": {
            "evidence": [
                {"doc_id": "d1"},
                {"doc_id": "d2"},
            ],
        },
    }
    page = WikiPage.from_dict(legacy, body="")
    assert page.evidence_refs == ["d1", "d2"]


# ---------------------------------------------------------------------------
# Test 3: explicit evidence_refs does NOT serialize _ko_extra.evidence
# ---------------------------------------------------------------------------
def test_to_frontmatter_dict_writes_evidence_refs_top_level_only():
    """When ``evidence_refs`` is set, it appears at top level. The serialized
    ``_ko_extra`` (if present) must NOT reintroduce ``evidence``."""
    page = WikiPage(
        id="card_evidence_refs",
        title="Evidence Refs",
        type=PageType.CONCEPT,
        evidence_refs=["d1:b1", "d2"],
    )
    fm = page.to_frontmatter_dict()
    assert fm["evidence_refs"] == ["d1:b1", "d2"]
    ko_extra = fm.get("_ko_extra")
    if isinstance(ko_extra, dict):
        assert "evidence" not in ko_extra, (
            "After migration, _ko_extra.evidence should not be reintroduced"
        )


# ---------------------------------------------------------------------------
# Test 4: explicit evidence_refs wins over legacy _ko_extra.evidence
# ---------------------------------------------------------------------------
def test_explicit_evidence_refs_wins_over_legacy_ko_extra():
    """When both ``evidence_refs`` and ``_ko_extra.evidence`` are present,
    the explicit top-level field wins (it's the canonical home)."""
    legacy = {
        "id": "card_both_evidence",
        "title": "Both Evidence",
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
        "grade": "B",
        "processing_depth": "concept",
        "is_immutable": False,
        "heat": 50,
        "last_used_at": 0,
        "zombie_since": None,
        "tags": [],
        "category": "",
        "taxonomy_sub": "",
        "related_entities": [],
        "custom_type": "",
        "workflow_state": "draft",
        "verified_at": 0,
        "evidence_refs": ["explicit:only"],
        "_ko_extra": {
            "evidence": [{"doc_id": "legacy_doc", "block_id": "legacy_block"}],
        },
    }
    page = WikiPage.from_dict(legacy, body="")
    assert page.evidence_refs == ["explicit:only"]


# ---------------------------------------------------------------------------
# Test 5: empty _ko_extra → evidence_refs defaults to []
# ---------------------------------------------------------------------------
def test_empty_ko_extra_yields_empty_evidence_refs():
    """An empty ``_ko_extra`` (no evidence key) → ``evidence_refs == []``."""
    legacy = {
        "id": "card_empty_ko_extra",
        "title": "Empty Ko Extra",
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
        "grade": "B",
        "processing_depth": "concept",
        "is_immutable": False,
        "heat": 50,
        "last_used_at": 0,
        "zombie_since": None,
        "tags": [],
        "category": "",
        "taxonomy_sub": "",
        "related_entities": [],
        "custom_type": "",
        "workflow_state": "draft",
        "verified_at": 0,
        "_ko_extra": {},
    }
    page = WikiPage.from_dict(legacy, body="")
    assert page.evidence_refs == []


# ---------------------------------------------------------------------------
# Test 6: empty _ko_extra.evidence list → evidence_refs == []
# ---------------------------------------------------------------------------
def test_empty_evidence_list_yields_empty_evidence_refs():
    """``_ko_extra.evidence = []`` (explicit empty list) → ``evidence_refs = []``."""
    legacy = {
        "id": "card_empty_evidence",
        "title": "Empty Evidence",
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
        "grade": "B",
        "processing_depth": "concept",
        "is_immutable": False,
        "heat": 50,
        "last_used_at": 0,
        "zombie_since": None,
        "tags": [],
        "category": "",
        "taxonomy_sub": "",
        "related_entities": [],
        "custom_type": "",
        "workflow_state": "draft",
        "verified_at": 0,
        "_ko_extra": {"evidence": []},
    }
    page = WikiPage.from_dict(legacy, body="")
    assert page.evidence_refs == []


# ---------------------------------------------------------------------------
# Bonus: default WikiPage.evidence_refs is []
# ---------------------------------------------------------------------------
def test_default_evidence_refs_is_empty_list():
    """``WikiPage.evidence_refs`` defaults to ``[]`` (not None)."""
    page = WikiPage(id="w", title="W", type=PageType.CONCEPT)
    assert page.evidence_refs == []
    # And: empty list is not serialized to frontmatter.
    fm = page.to_frontmatter_dict()
    assert "evidence_refs" not in fm