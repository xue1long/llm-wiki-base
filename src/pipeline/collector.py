# ruflo-kb/src/pipeline/collector.py
"""Collect raw source content for downstream LLM stages.

Two source kinds:

- **URL**: HTTP fetch with SSRF / private-IP guard (T4 `_check_url_allowlisted`).
- **Local file**: read directly from the project's ``raw/sources/<file>``.
  The collector does NOT stage a copy in any staging directory; the
  original file path (project-relative, e.g. ``raw/sources/foo.md``) is
  passed through to the pipeline as ``source_path`` so wiki pages record
  a stable reference to the user-owned artefact.

The collector used to copy content to ``Inbox/Processing/<task_id>.<ext>``
and the pipeline moved the original file there after success — this
two-step dance was redundant with the idempotency cache (md5-of-source,
7-day TTL, see ``src/utils/idempotency.py``) and made the wiki page's
``sources:`` field point to an obscure internal path instead of the
user-visible file. The Inbox subdir is gone.
"""
import ipaddress
import logging
import socket
from urllib.parse import urlparse
import httpx
from pathlib import Path

from ..events.event_bus import event_bus
from ..events.events import EventName, CollectorDonePayload
from ..utils.extract.pdf import extract_pdf_text
from ..utils.extract.office import extract_office_text
from ..types import SourceType
from ..permissions import AgentType, enforce_permission, Permission, PermissionDenied

logger = logging.getLogger(__name__)

MAX_REDIRECT_HOPS = 5


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


async def collect(
    task_id: str,
    source: str,
    source_type: SourceType,
    project_id: str | None = None,
) -> CollectorDonePayload:
    """Read the source and return its content + the project-relative path.

    For URLs we use ``source`` as both the read target and the
    ``raw_path`` carried into the pipeline (the URL itself is recorded in
    the wiki page's ``sources:`` list).

    For local files we receive a project-relative path (e.g.
    ``raw/sources/foo.md``) from the ingest service. We resolve it
    against the project's ``WikiPaths.root`` so the reader sees the
    absolute filesystem path while permission checks and the recorded
    ``sources:`` stay project-relative.
    """
    content = ""

    if source_type == SourceType.URL:
        enforce_permission(AgentType.COLLECTOR, source, Permission.READ)
        _check_url_allowlisted(source)
        current_url = source
        for _ in range(MAX_REDIRECT_HOPS):
            response = httpx.get(current_url, timeout=30, follow_redirects=False)
            if response.is_redirect:
                location = response.headers.get("Location") or response.headers.get("location") or ""
                if not location:
                    response.raise_for_status()
                # Re-validate the redirect target against the same ACL
                _check_url_allowlisted(location)
                current_url = location
                continue
            response.raise_for_status()
            break
        else:
            raise PermissionDenied(f"Too many redirects (>{MAX_REDIRECT_HOPS}) from {source}")
        content = response.text
        raw_path = source  # URLs are recorded verbatim in sources:
    else:
        # Resolve project-relative paths against the project's WikiPaths.root
        # when we have a project_id. The ingest service normalises absolute
        # paths down to project-relative form (see
        # services.ingest._normalize_absolute_path), so by the time we get
        # here the path is e.g. ``raw/sources/foo.md`` — meaningless without
        # anchoring it to the project root.
        file_path = Path(source)
        if not file_path.is_absolute() and project_id is not None:
            try:
                from ..project.registry import GlobalRegistryStore
                entry = GlobalRegistryStore.by_id(project_id)
                if entry is not None:
                    project_root = Path(entry.path)
                    candidate = (project_root / source).resolve()
                    if candidate.exists():
                        file_path = candidate
            except Exception:
                pass
        ext = file_path.suffix.lower()

        # Permission check uses the project-relative form (``raw/sources/...``)
        # so ``_is_within(..., "raw/sources")`` matches the allowlist.
        enforce_permission(AgentType.COLLECTOR, source, Permission.READ)

        if ext == ".pdf":
            content = extract_pdf_text(str(file_path))
        elif ext in [".docx", ".doc", ".xlsx", ".xls"]:
            content = extract_office_text(str(file_path))
        elif ext in [".md", ".txt"]:
            content = file_path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported file type: {file_path}")

        # raw_path stays project-relative so the wiki page's ``sources:``
        # is a stable, user-visible reference (e.g. ``raw/sources/foo.md``)
        # rather than an internal staging path.
        raw_path = source

    payload = CollectorDonePayload(
        task_id=task_id,
        raw_path=raw_path,
        content=content,
        source=source,
    )

    event_bus.emit(EventName.COLLECTOR_DONE, payload)
    return payload