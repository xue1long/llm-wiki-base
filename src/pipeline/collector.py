# ruflo-kb/src/pipeline/collector.py
import logging
import httpx
from pathlib import Path

from ..events.event_bus import event_bus
from ..events.events import EventName, CollectorDonePayload
from ..inbox.manager import get_inbox_manager
from ..utils.extract.pdf import extract_pdf_text
from ..utils.extract.office import extract_office_text
from ..utils.text import html_to_text
from ..types import SourceType

logger = logging.getLogger(__name__)

async def collect(task_id: str, source: str, source_type: SourceType) -> CollectorDonePayload:
    """采集内容"""
    inbox = get_inbox_manager()
    content = ""

    if source_type == SourceType.URL:
        response = httpx.get(source, timeout=30)
        response.raise_for_status()
        content = html_to_text(response.text)
        ext = ".html.txt"
    else:
        file_path = Path(source)
        ext = file_path.suffix.lower()

        if ext == ".pdf":
            content = extract_pdf_text(source)
        elif ext in [".docx", ".doc", ".xlsx", ".xls"]:
            content = extract_office_text(source)
        elif ext in [".md", ".txt"]:
            content = file_path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported file type: {source}")

    # 保存原始内容
    inbox.move_to_processing(source)
    raw_path = inbox.processing_path / f"{task_id}{ext}"
    raw_path.write_text(content, encoding="utf-8")

    payload = CollectorDonePayload(
        task_id=task_id,
        raw_path=str(raw_path),
        content=content,
    )

    event_bus.emit(EventName.COLLECTOR_DONE, payload)
    return payload
