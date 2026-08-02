"""CollectorAgent — standalone Agent wrapping the Collector pipeline stage.

Gives the Collector pipeline stage Agent identity with permissions, events,
and state tracking.
"""

import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.events.event_bus import event_bus
from src.knowledge.kernel import KnowledgeKernel, RAW_CREATE
from src.permissions import AgentType
from src.types import SourceType

# Import existing pipeline collector — do NOT copy code.
from src.pipeline.collector import collect as _pipeline_collect


@dataclass
class CollectorResult:
    """Result of a collection operation by CollectorAgent."""

    source_path: str
    content_hash: str    # md5 hex
    byte_size: int
    format: str          # pdf, docx, md, txt, url, etc.
    collected_at: int    # unix ms
    raw_text: str        # extracted text content


class CollectorAgent:
    """Independent Agent — fetches source content + metadata extraction.

    Pipeline role: collector:start → CollectorAgent → collector:done
    Agent identity: AgentType.COLLECTOR
    Permissions: raw.create, raw.read
    Events: document.collected
    """

    def __init__(self, kernel: KnowledgeKernel) -> None:
        self.kernel = kernel

    async def collect(self, source: str | Path) -> CollectorResult:
        """Fetch source content, extract metadata, publish document.collected event.

        Raises:
            PermissionError: if the agent lacks raw:create permission.
        """
        # 1. Permission check
        if not self.kernel.permissions.check(AgentType.COLLECTOR, RAW_CREATE):
            raise PermissionError(
                f"CollectorAgent lacks raw:create permission for {source}"
            )

        # 2. Record collector:start timestamp
        _start_ms = int(time.time() * 1000)

        # 3. Determine source type and delegate to existing pipeline collector
        source_str = str(source)
        if source_str.startswith(("http://", "https://")):
            source_type = SourceType.URL
        else:
            source_type = SourceType.FILE

        task_id = f"agent-collect-{uuid.uuid4().hex[:12]}"
        payload = await _pipeline_collect(task_id, source_str, source_type)

        # 4. Record collector:done timestamp
        collected_at = int(time.time() * 1000)

        # 5. Compute metadata
        content_hash = hashlib.md5(payload.content.encode("utf-8")).hexdigest()
        byte_size = len(payload.content.encode("utf-8"))

        # Determine format from source path / type
        if source_type == SourceType.URL:
            fmt = "url"
        else:
            ext = Path(source_str).suffix.lower().lstrip(".")
            fmt = ext if ext else "unknown"

        # 6. Build result
        result = CollectorResult(
            source_path=str(payload.raw_path),
            content_hash=content_hash,
            byte_size=byte_size,
            format=fmt,
            collected_at=collected_at,
            raw_text=payload.content,
        )

        # 7. Emit events on both kernel bus and global event bus
        payload = {
            "event": "document.collected",
            "source_path": result.source_path,
            "content_hash": result.content_hash,
            "byte_size": result.byte_size,
            "format": result.format,
            "collected_at": result.collected_at,
        }
        self.kernel.events.emit("document.collected", payload)
        event_bus.emit("collector:done", payload)

        return result
