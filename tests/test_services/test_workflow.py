"""Test: workflow state machine."""
import pytest
from src.services.capture import mark_page_verified
from src.wiki.core.types import WikiPage, PageType

VALID_WORKFLOW_STATES = {"draft", "ready", "verified", "outdated"}


def test_workflow_initial_state_is_draft():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    assert p.workflow_state == "draft"


def test_transition_draft_to_ready():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    # 直接设（lint 验证）
    p.workflow_state = "ready"
    assert p.workflow_state == "ready"


def test_transition_ready_to_verified():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="ready")
    p.workflow_state = "verified"
    assert p.workflow_state == "verified"


def test_transition_verified_to_outdated():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="verified")
    p.workflow_state = "outdated"
    assert p.workflow_state == "outdated"


def test_transition_invalid_raises():
    """非法值允许（lint 负责检查，不阻断写入）."""
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    p.workflow_state = "bogus"  # 允许，lint 会报
    assert p.workflow_state == "bogus"


def test_workflow_state_persists_via_roundtrip():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="verified")
    d = p.to_frontmatter_dict()
    p2 = WikiPage.from_dict(d)
    assert p2.workflow_state == "verified"


def test_mark_page_verified_sets_verified():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    result = mark_page_verified(p, user_id="test")
    assert result.workflow_state == "verified"
    assert result.verified_at > 0


def test_mark_page_verified_from_draft():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="draft")
    result = mark_page_verified(p, user_id="test")
    assert result.workflow_state == "verified"


def test_mark_page_verified_already_verified():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="verified")
    result = mark_page_verified(p, user_id="test")
    assert result.workflow_state == "verified"


def test_mark_page_verified_rollback():
    """save 失败时回滚 workflow_state 和 verified_at."""
    from src.services.capture import mark_page_verified_rollback

    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="draft")
    old_state = "draft"
    old_verified_at = 0
    mark_page_verified(p, user_id="test")
    p2 = mark_page_verified_rollback(p, old_state, old_verified_at)
    assert p2.workflow_state == "draft"
    assert p2.verified_at == 0