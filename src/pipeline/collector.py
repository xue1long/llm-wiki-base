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

# Encodings for double-encoding detection and fallback decode.
# GBK/Big5 cover all Chinese content (Simplified + Traditional).
_DOUBLE_ENCODE_CANDIDATES = ("gbk", "big5")
_FALLBACK_ENCODINGS = ("gbk", "gb2312", "big5")


def _repair_double_encoding(text: str) -> str | None:
    """If text looks double-encoded, try to repair it. Returns repaired text or None.

    Detects CJK text where original GBK/Big5 bytes were misinterpreted as
    Latin-1 and then encoded as UTF-8.  Tries both GBK and Big5 round-trips,
    picks the one with the highest CJK character yield.

    Three preconditions (avoid false positives on French/German/normal CJK):
    1. High Latin-1 Supplement density (U+0080–U+00FF ≥ 35%)
    2. Low ASCII density (< 20%) — rules out European languages
    3. Low existing CJK density (< 2%) — already-valid CJK shouldn't be "repaired"
    """
    total = len(text)
    if total < 15:
        return None

    # Precondition 1: Latin-1 Supplement density
    latin1_supp = sum(1 for c in text if '\x80' <= c <= '\xff')
    if latin1_supp / total < 0.35:
        return None

    # Precondition 2: ASCII density must be LOW (rules out French/German/etc.)
    if sum(1 for c in text if ' ' <= c <= '~') / total > 0.20:
        return None

    # Precondition 3: Existing CJK density must be LOW
    if sum(1 for c in text if '一' <= c <= '鿿') / total > 0.02:
        return None

    # Try candidate encodings — pick highest CJK yield.
    best_score = 0.0
    best_text = None

    for enc in _DOUBLE_ENCODE_CANDIDATES:
        try:
            roundtripped = text.encode("latin-1").decode(enc)
        except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
            continue
        rt_cjk = sum(1 for c in roundtripped if '一' <= c <= '鿿')
        if rt_cjk == 0:
            continue
        score = rt_cjk / max(len(roundtripped), 1)
        if score > best_score:
            best_score = score
            best_text = roundtripped

    if best_score > 0.12 and best_text:
        return best_text
    return None


def _cjk_ideograph_density(text: str) -> float:
    """Fraction of characters in the CJK Unified Ideographs block (U+4E00–U+9FFF)."""
    total = len(text)
    if total == 0:
        return 0.0
    return sum(1 for c in text if '一' <= c <= '鿿') / total


def _decode_text_file(raw_bytes: bytes, source_path: str) -> str:
    """Try UTF-8, fall back to CJK encodings, then check for double-encoding.

    Returns the decoded text str (always valid Unicode).
    Raises ValueError if all decoding attempts fail.
    """
    utf8_text: str | None = None
    utf8_density: float = 0.0
    cjk_candidates: list[tuple[str, float]] = []  # (text, cjk_density)

    # 1. UTF-8
    try:
        text = raw_bytes.decode("utf-8")
        repaired = _repair_double_encoding(text)
        if repaired is not None:
            return repaired.replace("\r\n", "\n").replace("\r", "\n")
        utf8_text = text
        utf8_density = _cjk_ideograph_density(text)
    except UnicodeDecodeError:
        pass

    # 2. charset-normalizer (optional dependency)
    try:
        from charset_normalizer import from_bytes
        result = from_bytes(raw_bytes).best()
        if result:
            cjk_candidates.append((str(result), _cjk_ideograph_density(str(result))))
    except ImportError:
        pass

    # 3. Manual CJK encoding trial
    for enc in _FALLBACK_ENCODINGS:
        try:
            alt = raw_bytes.decode(enc)
            cjk_candidates.append((alt, _cjk_ideograph_density(alt)))
        except (UnicodeDecodeError, LookupError):
            continue

    # --- Selection ---
    # When UTF-8 succeeded with low CJK (< 0.1), the source is likely a
    # Western language.  Only override with a CJK fallback when it has a
    # very strong CJK signal (> 0.4) — rules out accidental CJK byte
    # pairs in French/German UTF-8 text.
    if utf8_text is not None and utf8_density < 0.1:
        for text, d in cjk_candidates:
            if d > 0.4:
                return text.replace("\r\n", "\n").replace("\r", "\n")
        return utf8_text.replace("\r\n", "\n").replace("\r", "\n")

    # UTF-8 succeeded with CJK content or failed entirely.
    # Collect all successful candidates and pick the one with the
    # highest CJK ideograph density (handles mojibake where GBK/Big5
    # bytes are accidentally valid UTF-8 or charset-normalizer guesses
    # the wrong encoding).
    all_candidates: list[tuple[str, float]] = []
    if utf8_text is not None:
        all_candidates.append((utf8_text, utf8_density))
    all_candidates.extend(cjk_candidates)

    if not all_candidates:
        raise ValueError(f"Cannot decode {source_path}: not UTF-8 or common CJK encoding")

    best = max(all_candidates, key=lambda x: x[1])
    # Normalise Windows line endings (read_bytes preserves \r\n).
    return best[0].replace("\r\n", "\n").replace("\r", "\n")


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
        elif ext in [".epub", ".mobi"]:
            from ..utils.extract.ebook import extract_ebook
            content = extract_ebook(file_path)
        elif ext in [".html", ".htm"]:
            raw_bytes = file_path.read_bytes()
            html_str = _decode_text_file(raw_bytes, str(file_path))
            from ..utils.text import html_to_text as _html_to_text
            content = _html_to_text(html_str)
        elif ext in [".md", ".txt"]:
            raw_bytes = file_path.read_bytes()
            content = _decode_text_file(raw_bytes, str(file_path))
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
