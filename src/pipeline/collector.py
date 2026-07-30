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
import os
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


def _resolve_project_file(source: str, project_id: str | None) -> Path | None:
    """Resolve a project-relative source path to an absolute filesystem path.

    Uses string-based path manipulation (os.path) to avoid Path.resolve()
    which can corrupt CJK characters on Windows via low-level API calls.

    Returns the absolute Path if the file exists, or None if the project
    root cannot be determined or the file does not exist.
    """
    if project_id is None:
        return None
    try:
        from ..project.registry import GlobalRegistryStore
        entry = GlobalRegistryStore.by_id(project_id)
    except Exception:
        logger.debug("[collector] GlobalRegistryStore lookup failed for %s", project_id)
        return None
    if entry is None:
        logger.debug("[collector] project %s not found in registry", project_id)
        return None

    project_root = str(entry.path)
    candidate = os.path.abspath(os.path.join(project_root, source))
    if os.path.exists(candidate):
        return Path(candidate)
    return None


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
                _check_url_allowlisted(location)
                current_url = location
                continue
            response.raise_for_status()
            break
        else:
            raise PermissionDenied(f"Too many redirects (>{MAX_REDIRECT_HOPS}) from {source}")
        content = response.text
        raw_path = source
    else:
        from urllib.parse import unquote
        source_decoded = unquote(source)

        # Detect encoding corruption: if the path contains 4+ consecutive
        # question marks or the Unicode replacement character (U+FFFD),
        # the CJK characters were corrupted somewhere upstream (e.g.
        # non-UTF-8 terminal encoding). Fail fast instead of attempting
        # a doomed file read and wasting retries.
        _corruption_markers = ("????", "�")
        for _marker in _corruption_markers:
            if _marker in source_decoded:
                raise ValueError(
                    f"Source path appears to have encoding corruption "
                    f"(found {_marker!r} in {source_decoded!r}). "
                    f"Re-submit the path using a UTF-8 capable client."
                )

        file_path = Path(source_decoded)
        if not file_path.is_absolute() and project_id is not None:
            resolved = _resolve_project_file(source_decoded, project_id)
            if resolved is not None:
                file_path = resolved
            else:
                logger.warning(
                    "[collector] cannot resolve %r for project %s — "
                    "file does not exist or project root unknown",
                    source_decoded, project_id,
                )

        ext = file_path.suffix.lower()

        enforce_permission(AgentType.COLLECTOR, source, Permission.READ)

        if ext == ".pdf":
            content = extract_pdf_text(str(file_path))
        elif ext in [".docx", ".doc", ".xlsx", ".xls"]:
            content = extract_office_text(str(file_path))
        elif ext in [".md", ".txt"]:
            content = file_path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported file type: {file_path}")

        raw_path = source_decoded

    payload = CollectorDonePayload(
        task_id=task_id,
        raw_path=raw_path,
        content=content,
        source=source,
    )

    event_bus.emit(EventName.COLLECTOR_DONE, payload)
    return payload
