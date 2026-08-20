"""Test: WikiPage workflow_state + verified_at round-trip."""
import pytest
from src.wiki.core.types import WikiPage, PageType


def test_default_workflow_state():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    assert p.workflow_state == "draft"


def test_default_verified_at():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    assert p.verified_at == 0


def test_workflow_state_roundtrip():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="verified")
    d = p.to_frontmatter_dict()
    p2 = WikiPage.from_dict(d)
    assert p2.workflow_state == "verified"


def test_verified_at_roundtrip():
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, verified_at=1234567890)
    d = p.to_frontmatter_dict()
    p2 = WikiPage.from_dict(d)
    assert p2.verified_at == 1234567890


def test_legacy_page_no_workflow_state():
    """存量卡无 workflow_state 字段 → 默认 draft."""
    d = {"id": "x", "title": "X", "type": "concept"}
    p = WikiPage.from_dict(d)
    assert p.workflow_state == "draft"


def test_legacy_page_no_verified_at():
    """存量卡无 verified_at 字段 → 默认 0."""
    d = {"id": "x", "title": "X", "type": "concept"}
    p = WikiPage.from_dict(d)
    assert p.verified_at == 0


def test_processing_depth_still_defaults():
    """确认 processing_depth 默认值不受影响."""
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    assert p.processing_depth == "concept"


def test_invalid_workflow_state_legacy_default():
    """非法 workflow_state 值保持原样（lint 负责检查，from_dict 不报错）."""
    d = {"id": "x", "title": "X", "type": "concept", "workflow_state": "bogus"}
    p = WikiPage.from_dict(d)
    assert p.workflow_state == "bogus"