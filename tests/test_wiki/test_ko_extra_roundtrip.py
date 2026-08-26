"""Tests for WikiPage._ko_extra round-trip through from_dict/to_frontmatter_dict.

Plan Task 2: S1 加固 — from_dict 读回 _ko_extra。

Note (C-0 Commit 1): ``source_status`` is no longer the canonical home of
the capture-completeness signal — it has been migrated to
``WikiPage.workflow_state``. ``_ko_extra`` still round-trips for any other
legacy keys, but ``source_status`` is lifted to the top-level field on
``from_dict`` and removed from the ``_ko_extra`` dict (see
``test_ko_extra_source_status_migration.py``).
"""
import yaml
from src.wiki.core.types import WikiPage, PageType


def test_ko_extra_roundtrip():
    """_ko_extra (without source_status) survives to_frontmatter_dict → YAML → from_dict."""
    page = WikiPage(
        id="test-roundtrip", title="Test", type=PageType.SOURCE,
        body="hello",
    )
    page._ko_extra = {"capture_context": "shower thought"}

    # Serialize
    fm = page.to_frontmatter_dict()
    assert "_ko_extra" in fm
    assert fm["_ko_extra"]["capture_context"] == "shower thought"
    # source_status must NOT be present after C-0 Commit 1
    assert "source_status" not in fm["_ko_extra"]

    # Simulate YAML round-trip (as read_page does)
    fm_text = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    fm_back = yaml.safe_load(fm_text) or {}

    # Deserialize
    page2 = WikiPage.from_dict(fm_back, body="hello")
    assert hasattr(page2, "_ko_extra"), "from_dict should restore _ko_extra"
    assert page2._ko_extra == {"capture_context": "shower thought"}


def test_ko_extra_none_default():
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


def test_ko_extra_backward_compat():
    """Old pages without _ko_extra in frontmatter don't break from_dict."""
    old_fm = {
        "id": "old-page",
        "title": "Old Page",
        "type": "source",
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
    }
    # No _ko_extra key — should not raise
    page = WikiPage.from_dict(old_fm, body="old content")
    assert page.id == "old-page"
    assert page.title == "Old Page"
    assert getattr(page, "_ko_extra", None) is None


def test_ko_extra_multiple_fields():
    """_ko_extra with multiple non-source_status fields round-trips correctly."""
    page = WikiPage(
        id="test-multi", title="Multi", type=PageType.CONCEPT,
    )
    page._ko_extra = {"capture_context": "shower thought", "extra_tag": "tag-1"}

    fm = page.to_frontmatter_dict()
    fm_text = yaml.dump(fm, allow_unicode=True)
    fm_back = yaml.safe_load(fm_text) or {}

    page2 = WikiPage.from_dict(fm_back)
    assert page2._ko_extra["capture_context"] == "shower thought"
    assert page2._ko_extra["extra_tag"] == "tag-1"
    # source_status must NOT have been re-introduced
    assert "source_status" not in page2._ko_extra
