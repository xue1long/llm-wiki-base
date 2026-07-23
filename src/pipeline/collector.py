# ruflo-kb/src/pipeline/collector.py
import ipaddress
import logging
import socket
from urllib.parse import urlparse
import httpx
from pathlib import Path

from ..events.event_bus import event_bus
from ..events.events import EventName, CollectorDonePayload
from ..inbox.manager import get_inbox_manager
from ..utils.extract.pdf import extract_pdf_text
from ..utils.extract.office import extract_office_text
from ..utils.text import html_to_text
from ..types import SourceType
from ..permissions import AgentType, enforce_permission, Permission, PermissionDenied

logger = logging.getLogger(__name__)


def _check_url_allowlisted(url: str) -> None:
    """Reject URLs whose hostname resolves to a non-public address."""
    host = urlparse(url).hostname or ""
    try:
        address = ipaddress.ip_address(socket.gethostbyname(host))
    except socket.gaierror as exc:
        raise PermissionDenied(f"DNS resolution failed for {host}") from exc

    if address.is_private or address.is_loopback or address.is_link_local:
        raise PermissionDenied(
            f"URL {url} resolves to private/loopback/link-local {address}"
        )


async def collect(task_id: str, source: str, source_type: SourceType) -> CollectorDonePayload:
    """采集内容"""
    inbox = get_inbox_manager()
    content = ""

    if source_type == SourceType.URL:
        enforce_permission(AgentType.COLLECTOR, source, Permission.READ)
        _check_url_allowlisted(source)
        response = httpx.get(source, timeout=30, follow_redirects=True)
        response.raise_for_status()
        content = html_to_text(response.text)
        ext = ".html.txt"
        raw_path = inbox.processing_path / f"{task_id}{ext}"
    else:
        file_path = Path(source)
        ext = file_path.suffix.lower()

        # 权限检查: Collector 只允许读本地文件
        enforce_permission(AgentType.COLLECTOR, source, Permission.READ)

        if ext == ".pdf":
            content = extract_pdf_text(source)
        elif ext in [".docx", ".doc", ".xlsx", ".xls"]:
            content = extract_office_text(source)
        elif ext in [".md", ".txt"]:
            content = file_path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported file type: {source}")

        inbox.move_to_processing(source)
        raw_path = inbox.processing_path / f"{task_id}{ext}"

    # 权限检查: Collector 只允许写 Inbox/Processing
    enforce_permission(AgentType.COLLECTOR, str(raw_path), Permission.WRITE)

    raw_path.write_text(content, encoding="utf-8")

    payload = CollectorDonePayload(
        task_id=task_id,
        raw_path=str(raw_path),
        content=content,
    )

    event_bus.emit(EventName.COLLECTOR_DONE, payload)
    return payload
