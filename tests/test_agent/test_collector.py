"""Tests for CollectorAgent — standalone Agent wrapping the Collector pipeline stage."""

import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.collector import CollectorAgent, CollectorResult
from src.knowledge.kernel import KnowledgeKernel


# ---------------------------------------------------------------------------
# CollectorResult dataclass tests
# ---------------------------------------------------------------------------

class TestCollectorResult:
    """CollectorResult dataclass field validation."""

    def test_contains_expected_fields(self):
        """All six fields are present and correctly stored."""
        result = CollectorResult(
            source_path="/test/file.md",
            content_hash="d41d8cd98f00b204e9800998ecf8427e",
            byte_size=1024,
            format="md",
            collected_at=1759430400000,
            raw_text="# Hello",
        )
        assert result.source_path == "/test/file.md"
        assert result.content_hash == "d41d8cd98f00b204e9800998ecf8427e"
        assert result.byte_size == 1024
        assert result.format == "md"
        assert result.collected_at == 1759430400000
        assert result.raw_text == "# Hello"

    def test_content_hash_is_valid_md5_hex(self):
        """content_hash must be a valid 32-character lowercase hex string."""
        result = CollectorResult(
            source_path="/t.md",
            content_hash=hashlib.md5(b"test").hexdigest(),
            byte_size=4,
            format="md",
            collected_at=0,
            raw_text="test",
        )
        assert len(result.content_hash) == 32
        assert all(c in "0123456789abcdef" for c in result.content_hash)

    def test_format_detected_from_extension(self):
        """format field should represent the detected source format."""
        # These test that the dataclass faithfully stores the format value.
        # Actual detection logic lives in CollectorAgent.collect().
        for ext in ("md", "txt", "pdf", "docx", "url"):
            result = CollectorResult("a." + ext, "abc", 100, ext, 1000, "")
            assert result.format == ext

    def test_collected_at_within_last_second(self):
        """collected_at should be a recent Unix ms timestamp."""
        now_ms = int(time.time() * 1000)
        result = CollectorResult("a.md", "abc", 100, "md", now_ms, "")
        assert abs(result.collected_at - now_ms) <= 1000


# ---------------------------------------------------------------------------
# CollectorAgent tests
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously (follows existing test_agent pattern)."""
    return asyncio.run(coro)


class TestCollectorAgent:
    """CollectorAgent lifecycle and behaviour tests."""

    def test_initializes_with_kernel(self, tmp_path):
        """CollectorAgent stores the kernel reference on init."""
        kernel = KnowledgeKernel(tmp_path)
        agent = CollectorAgent(kernel)
        assert agent.kernel is kernel

    def test_collect_permission_denied_raises_permission_error(self, tmp_path):
        """When COLLECTOR lacks raw:create, collect() raises PermissionError."""
        kernel = KnowledgeKernel(tmp_path)
        # Override the permission check to simulate denial
        kernel.permissions.check = MagicMock(return_value=False)
        agent = CollectorAgent(kernel)

        with pytest.raises(PermissionError, match="raw:create"):
            _run(agent.collect("test.md"))

    def test_collect_emits_document_collected_event(self, tmp_path):
        """collect() emits a document.collected event with the correct fields."""
        from src.events.events import CollectorDonePayload

        kernel = KnowledgeKernel(tmp_path)
        agent = CollectorAgent(kernel)

        # Capture emitted events
        captured_events: list = []
        kernel.events.on("document.collected", lambda p: captured_events.append(p))

        # Mock the pipeline collector so we don't actually read a file
        fake_payload = CollectorDonePayload(
            task_id="fake-task",
            raw_path=tmp_path / "test.md",
            content="# Test content",
            source="test.md",
        )

        with patch(
            "src.agent.collector._pipeline_collect",
            new=AsyncMock(return_value=fake_payload),
        ):
            result = _run(agent.collect("test.md"))

        # Verify result
        assert result.source_path == str(tmp_path / "test.md")
        assert result.raw_text == "# Test content"
        assert result.format == "md"

        # Verify event emitted
        assert len(captured_events) == 1
        event = captured_events[0]
        assert event["event"] == "document.collected"
        assert event["source_path"] == result.source_path
        assert event["content_hash"] == result.content_hash
        assert event["byte_size"] == len("# Test content".encode("utf-8"))
        assert event["format"] == "md"
        assert isinstance(event["collected_at"], int)
