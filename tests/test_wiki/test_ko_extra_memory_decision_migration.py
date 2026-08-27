"""C-0 Commit 2: migrate ``_ko_extra.memory.decision`` → ``WikiPage.decision_record``.

Back-compat: legacy pages with ``_ko_extra.memory.decision`` still load into
``page.decision_record``. New writes use the top-level field only.
"""
from src.wiki.core.types import PageType, WikiPage


def test_from_dict_lifts_ko_extra_memory_decision_to_decision_record():
    """Legacy frontmatter key ``_ko_extra.memory.decision`` is migrated."""
    legacy = {
        "id": "card_legacy",
        "title": "Legacy",
        "type": "decision",
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
            "memory": {
                "decision": {"outcome": "approved", "ts": 123},
            },
        },
    }
    page = WikiPage.from_dict(legacy, body="")
    assert page.decision_record == {"outcome": "approved", "ts": 123}


def test_to_frontmatter_dict_writes_decision_record_top_level_only():
    """When ``decision_record`` is set, it appears at top level, not under
    ``_ko_extra.memory.decision``."""
    page = WikiPage(
        id="card_x",
        title="X",
        type=PageType.DECISION,
        decision_record={"outcome": "rejected", "ts": 456},
    )
    fm = page.to_frontmatter_dict()
    assert fm["decision_record"] == {"outcome": "rejected", "ts": 456}
    # Not duplicated under _ko_extra.memory.decision
    ko_extra = fm.get("_ko_extra")
    if isinstance(ko_extra, dict):
        memory = ko_extra.get("memory")
        if isinstance(memory, dict):
            assert "decision" not in memory


def test_explicit_decision_record_wins_over_legacy_ko_extra():
    """When both are present, the explicit top-level field wins (it's the
    canonical home; legacy key is only a migration fallback)."""
    payload = {"from": "explicit"}
    legacy_payload = {"from": "legacy"}
    page = WikiPage(
        id="card_y",
        title="Y",
        type=PageType.DECISION,
        decision_record=payload,
        # Inject _ko_extra with the legacy key — note: this is an internal
        # attribute, but we set it via the dataclass directly.
    )
    page._ko_extra = {"memory": {"decision": legacy_payload}}
    fm = page.to_frontmatter_dict()
    # to_frontmatter_dict writes decision_record, not the legacy key
    assert fm["decision_record"] == payload


def test_empty_ko_extra_yields_none_decision_record():
    """An empty ``_ko_extra`` (no memory.decision) → ``decision_record is None``."""
    data = {
        "id": "card_z",
        "title": "Z",
        "type": "decision",
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
    page = WikiPage.from_dict(data, body="")
    assert page.decision_record is None


def test_default_decision_record_is_none():
    """``WikiPage.decision_record`` defaults to ``None`` (no legacy data)."""
    page = WikiPage(id="w", title="W", type=PageType.DECISION)
    assert page.decision_record is None
    # Also: the field does not appear as a top-level frontmatter key when None.
    fm = page.to_frontmatter_dict()
    assert "decision_record" not in fm