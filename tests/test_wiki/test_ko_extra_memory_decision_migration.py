"""C-0 Commit 2: migrate ``_ko_extra.memory.decision`` → ``WikiPage.decision_record``.

Back-compat: legacy pages with ``_ko_extra.memory.decision`` still load into
``page.decision_record``. V4 (ADR-002, 2026-08-31) further restricts this:
the migration is read-only on the in-memory WikiPage; ``decision_record``
is never written to disk by ``to_frontmatter_dict`` (V4 8-key whitelist
excludes it). New callers that need decision data should read it from
the in-memory attribute directly.
"""
from src.wiki.core.types import PageType, WikiPage


def test_from_dict_lifts_ko_extra_memory_decision_to_decision_record():
    """Legacy frontmatter key ``_ko_extra.memory.decision`` is migrated
    to the in-memory WikiPage.decision_record (read-only path)."""
    legacy = {
        "id": "card_legacy",
        "title": "Legacy",
        # V4 keeps concept as the canonical home for "decision" content.
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
        "tags": [],
        "_ko_extra": {
            "memory": {
                "decision": {"outcome": "approved", "ts": 123},
            },
        },
    }
    page = WikiPage.from_dict(legacy, body="")
    assert page.decision_record == {"outcome": "approved", "ts": 123}


def test_decision_record_not_in_frontmatter_v4():
    """V4: decision_record is in-memory only — never in to_frontmatter_dict.

    The 8-key V4 whitelist excludes decision_record (along with all other
    KO-mirror fields). The in-memory attribute is still populated from
    legacy pages, but new writes drop it.
    """
    page = WikiPage(
        id="card_x",
        title="X",
        type=PageType.CONCEPT,
        decision_record={"outcome": "rejected", "ts": 456},
    )
    fm = page.to_frontmatter_dict()
    assert "decision_record" not in fm
    assert "_ko_extra" not in fm


def test_explicit_decision_record_kept_in_memory():
    """When both decision_record and legacy _ko_extra.memory.decision are
    present, the explicit top-level field wins on the in-memory WikiPage
    (it's the canonical home in the legacy model)."""
    payload = {"from": "explicit"}
    legacy_payload = {"from": "legacy"}
    page = WikiPage(
        id="card_y",
        title="Y",
        type=PageType.CONCEPT,
        decision_record=payload,
    )
    page._ko_extra = {"memory": {"decision": legacy_payload}}
    # In-memory: explicit wins.
    assert page.decision_record == payload


def test_empty_ko_extra_yields_none_decision_record():
    """An empty ``_ko_extra`` (no memory.decision) → ``decision_record is None``."""
    data = {
        "id": "card_z",
        "title": "Z",
        "type": "concept",
        "sources": [],
        "created_at": 0,
        "updated_at": 0,
        "relations": [],
        "tags": [],
        "_ko_extra": {},
    }
    page = WikiPage.from_dict(data, body="")
    assert page.decision_record is None


def test_default_decision_record_is_none():
    """``WikiPage.decision_record`` defaults to ``None`` (no legacy data)."""
    page = WikiPage(id="w", title="W", type=PageType.CONCEPT)
    assert page.decision_record is None
    # V4: decision_record is in-memory only — never serialized.
    fm = page.to_frontmatter_dict()
    assert "decision_record" not in fm
