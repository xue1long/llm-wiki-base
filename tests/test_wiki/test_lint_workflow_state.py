"""Test: lint workflow_state + processing_depth validation."""
from src.wiki.core.types import WikiPage, PageType
from src.wiki.features.lint import (
    VALID_WORKFLOW_STATES,
    VALID_PROCESSING_DEPTHS,
)


def test_valid_workflow_state():
    assert "draft" in VALID_WORKFLOW_STATES
    assert "ready" in VALID_WORKFLOW_STATES
    assert "verified" in VALID_WORKFLOW_STATES
    assert "outdated" in VALID_WORKFLOW_STATES
    assert len(VALID_WORKFLOW_STATES) == 4


def test_valid_processing_depth():
    assert "concept" in VALID_PROCESSING_DEPTHS
    assert "memory" in VALID_PROCESSING_DEPTHS
    assert "operation" in VALID_PROCESSING_DEPTHS
    assert len(VALID_PROCESSING_DEPTHS) == 3


def test_legacy_page_no_fields():
    """旧卡无 workflow_state → 不报."""
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT)
    ws = p.workflow_state or "draft"
    assert ws in VALID_WORKFLOW_STATES


def test_empty_string_workflow_state():
    """空字符串视为 draft."""
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, workflow_state="")
    ws = p.workflow_state or "draft"
    assert ws == "draft"


def test_empty_string_processing_depth():
    """空字符串视为 concept."""
    p = WikiPage(id="x", title="X", type=PageType.CONCEPT, processing_depth="")
    pd = p.processing_depth or "concept"
    assert pd == "concept"
