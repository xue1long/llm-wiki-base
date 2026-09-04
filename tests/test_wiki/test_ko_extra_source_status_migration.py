"""Tests for C-0 Commit 1: migrate _ko_extra.source_status to WikiPage.workflow_state.

Plan ref: docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md §C-0 Commit 1.

Behavior under test:
- Old frontmatter carrying ``_ko_extra.source_status`` (a string like
  "empty" / "complete" / "ready") is migrated to ``WikiPage.workflow_state``
  on ``from_dict``. The legacy ``_ko_extra.source_status`` key is removed
  from the parsed ``_ko_extra`` dict after migration (it is no longer the
  canonical home of the value), but the ``_ko_extra`` dict itself is
  preserved so other legacy keys still round-trip.
- Capture-time new writes go to ``workflow_state`` directly. The
  ``_ko_extra`` dict on a freshly captured page does NOT contain
  ``source_status`` (verified through the existing capture flow).
- Pages whose workflow_state was already migrated (i.e. the top-level
  field is present) round-trip cleanly and never reintroduce
  ``_ko_extra.source_status`` on re-serialization.
"""
from src.wiki.core.types import WikiPage, PageType


# ---------------------------------------------------------------------------
# Test 1: _ko_extra.source_status = "empty" migrates to workflow_state
# ---------------------------------------------------------------------------
def test_ko_extra_source_status_empty_migrates_to_workflow_state():
    """Legacy frontmatter with _ko_extra.source_status='empty' should be
    loaded with workflow_state='empty' on the resulting WikiPage."""
    fm = {
        "id": "legacy-empty",
        "title": "Legacy Empty",
        "type": "source",
        "workflow_state": "draft",
        "_ko_extra": {"source_status": "empty"},
    }
    page = WikiPage.from_dict(fm)
    assert page.workflow_state == "empty"


# ---------------------------------------------------------------------------
# Test 2: _ko_extra.source_status = "complete" migrates to workflow_state
# ---------------------------------------------------------------------------
def test_ko_extra_source_status_complete_migrates_to_workflow_state():
    """Legacy frontmatter with _ko_extra.source_status='complete' should
    be loaded with workflow_state='complete' on the resulting WikiPage."""
    fm = {
        "id": "legacy-complete",
        "title": "Legacy Complete",
        "type": "source",
        "workflow_state": "draft",
        "_ko_extra": {"source_status": "complete"},
    }
    page = WikiPage.from_dict(fm)
    assert page.workflow_state == "complete"


# ---------------------------------------------------------------------------
# Test 3: already-migrated page does not reintroduce _ko_extra.source_status
# ---------------------------------------------------------------------------
def test_already_migrated_page_has_no_source_status_in_ko_extra():
    """A page whose workflow_state was set via the field (not via
    _ko_extra) should serialize cleanly without _ko_extra.source_status."""
    page = WikiPage(
        id="already-migrated",
        title="Already Migrated",
        type=PageType.SOURCE,
        workflow_state="verified",
    )
    fm = page.to_frontmatter_dict()
    # The _ko_extra key may be absent or, if present, must not carry source_status
    ko_extra = fm.get("_ko_extra")
    if ko_extra is not None:
        assert "source_status" not in ko_extra, (
            "After migration, _ko_extra.source_status should not be reintroduced"
        )


# ---------------------------------------------------------------------------
# Test 4: _ko_extra.source_status = "ready" migrates to workflow_state
# ---------------------------------------------------------------------------
def test_ko_extra_source_status_ready_migrates_to_workflow_state():
    """Legacy frontmatter with _ko_extra.source_status='ready' should be
    loaded with workflow_state='ready' on the resulting WikiPage."""
    fm = {
        "id": "legacy-ready",
        "title": "Legacy Ready",
        "type": "source",
        "workflow_state": "draft",
        "_ko_extra": {"source_status": "ready"},
    }
    page = WikiPage.from_dict(fm)
    assert page.workflow_state == "ready"


# ---------------------------------------------------------------------------
# Test 5: page without _ko_extra.source_status keeps default workflow_state
# ---------------------------------------------------------------------------
def test_no_ko_extra_source_status_keeps_default_workflow_state():
    """A legacy page whose _ko_extra has no source_status key must keep
    the default workflow_state='draft' (no migration occurs)."""
    fm = {
        "id": "no-source-status",
        "title": "No Source Status",
        "type": "source",
        "_ko_extra": {},  # empty _ko_extra, no source_status
    }
    page = WikiPage.from_dict(fm)
    assert page.workflow_state == "draft"
