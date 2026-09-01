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
from hashlib import sha256
from urllib.parse import urlparse
import httpx
from pathlib import Path

from ..events.event_bus import event_bus
from ..events.events import EventName, CollectorDonePayload
from ..utils.extract.pdf import extract_pdf_text
from ..utils.extract.office import extract_office_text
from .extraction_types import artifact_from_text, collect_artifact
from ..types import SourceType
from ..permissions import AgentType, enforce_permission, Permission, PermissionDenied

logger = logging.getLogger(__name__)

MAX_REDIRECT_HOPS = 5


class SourceTooLargeError(ValueError):
    """Raised when a source (URL body or local file) exceeds the cap.

    R2: the cap is enforced here, in the unified source-read layer, so
    every ingestion entry (HTTP upload, URL ingest, CLI, folder ingest)
    is subject to the same resource limit.
    """


def _enforce_source_size(size_bytes: int, source: str) -> None:
    """Raise SourceTooLargeError when ``size_bytes`` exceeds the cap."""
    from ..config import settings
    max_bytes = settings().max_upload_bytes
    if size_bytes > max_bytes:
        raise SourceTooLargeError(
            f"source {source!r} is {size_bytes} bytes, exceeding the "
            f"{max_bytes}-byte limit (RUFLO_MAX_UPLOAD_BYTES)"
        )

# Encodings for double-encoding detection and fallback decode.
# GBK/Big5 cover all Chinese content (Simplified + Traditional).
# _DOUBLE_ENCODE_SOURCE_CODECS: single-byte codecs that original GBK/Big5
# bytes may have been misinterpreted through before being re-saved as UTF-8.
# latin-1 is the classic case; koi8-r/u cover the batch-50 586KB mojibake
# (GBK bytes misread as KOI8-U → UTF-8). cp437/cp1251 cover other pipelines.
_DOUBLE_ENCODE_SOURCE_CODECS = ("latin-1", "koi8-u", "koi8-r", "cp437", "cp1251")
_DOUBLE_ENCODE_TARGET_ENCODINGS = ("gbk", "big5")
_FALLBACK_ENCODINGS = ("gbk", "gb2312", "big5")


def _repair_double_encoding(text: str) -> str | None:
    """If text looks double-encoded, try to repair it. Returns repaired text or None.

    Detects CJK text where original GBK/Big5 bytes were misinterpreted through
    a single-byte codec (latin-1, KOI8-U/KOI8-R, cp437, cp1251) and then
    encoded as UTF-8.  Tries every source-codec × target-encoding round-trip
    and picks the one with the highest CJK character yield at the lowest
    byte-loss.

    Preconditions (avoid false positives on Russian/French/valid CJK):
    1. Low ASCII density (< 20%) — rules out European languages
    2. Low existing CJK density (< 2%) — already-valid CJK shouldn't be "repaired"
    3. The winning round-trip must produce strong CJK yield (> 40%) with
       near-zero encoding loss — a garbled re-decode of Russian/French text
       fails one of these guards
    """
    total = len(text)
    if total < 15:
        return None

    # Precondition 1: ASCII density must be LOW (rules out French/German/etc.)
    if sum(1 for c in text if ' ' <= c <= '~') / total > 0.20:
        return None

    # Precondition 2: Existing CJK density must be LOW
    if sum(1 for c in text if '一' <= c <= '鿿') / total > 0.02:
        return None

    # Try candidate codec × encoding combos — pick the highest CJK yield at
    # the lowest byte-loss. `errors="replace"` tolerates chars outside the
    # source codec (a file may mix two mojibake pipelines); the loss ratio
    # penalises candidates that needed heavy replacement.
    best_score = 0.0
    best_text = None

    for codec in _DOUBLE_ENCODE_SOURCE_CODECS:
        try:
            encoded = text.encode(codec, errors="replace")
        except (UnicodeEncodeError, LookupError):
            continue
        loss = encoded.count(b"?") / max(len(encoded), 1)
        if loss > 0.10:
            continue  # too much of the source couldn't round-trip
        for enc in _DOUBLE_ENCODE_TARGET_ENCODINGS:
            try:
                roundtripped = encoded.decode(enc, errors="replace")
            except (UnicodeDecodeError, LookupError):
                continue
            # A genuine CJK round-trip decodes almost cleanly (the 586KB
            # batch-50 file had 0.02% U+FFFD across 265k chars). A high
            # U+FFFD ratio means the bytes weren't valid for *enc* (wrong
            # encoding guess, or Russian text misround-tripped via koi8-r
            # into GBK garbage) — reject it.
            if roundtripped.count("\ufffd") / max(len(roundtripped), 1) > 0.01:
                continue
            rt_cjk = sum(1 for c in roundtripped if '一' <= c <= '鿿')
            if rt_cjk == 0:
                continue
            score = rt_cjk / max(len(roundtripped), 1) - loss
            if score > best_score:
                best_score = score
                best_text = roundtripped

    # Require a strong CJK yield (≥40%) so a random garble of Russian/French
    # bytes is never "repaired" into pseudo-Chinese.
    if best_score >= 0.40 and best_text:
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


def _check_ip_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address,
                    url: str) -> None:
    """Reject private / loopback / link-local / multicast / unspecified IPs.

    Used by ``_PinnedDnsTransport`` after we've resolved the hostname.
    Defense-in-depth: even if the hostname looks benign, an attacker can
    point DNS at an internal IP — we want the check to apply to the
    IP we'll actually connect to, not the textual hostname.
    """
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise PermissionDenied(
            f"URL {url} resolves to disallowed address {address} "
            f"(private / loopback / link-local / multicast / reserved)"
        )


def _check_url_allowlisted(url: str) -> None:
    """Reject URLs whose hostname resolves to a non-public address.

    Pre-PR-3 helper retained so direct callers (e.g. unit tests) keep a
    public entrypoint; the redirect loop now uses
    ``_PinnedDnsTransport`` which performs the same check on the IP
    it will actually use for the socket, eliminating the
    DNS-resolve-then-reconnect TOCTOU window.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise PermissionDenied(f"URL {url!r} is missing a scheme or hostname")
    if parsed.scheme not in ("http", "https"):
        raise PermissionDenied(
            f"URL {url!r} uses disallowed scheme {parsed.scheme!r}"
        )
    host = parsed.hostname
    try:
        address = ipaddress.ip_address(socket.gethostbyname(host))
    except socket.gaierror as exc:
        raise PermissionDenied(f"DNS resolution failed for {host}") from exc

    _check_ip_public(address, url)


class _PinnedDnsTransport(httpx.BaseTransport):
    """DNS-pinning httpx transport — single IP per resolved hostname.

    Defense against the classic SSRF race: the prior code resolved the
    hostname twice (once in ``_check_url_allowlisted`` then again inside
    httpx), giving an attacker controlling DNS the window to return a
    public IP on the first resolve and a private IP on the second.

    The transport resolves the hostname exactly once, validates the IP
    is public, then issues the request against that single IP via the
    URL's netloc. The original hostname is preserved in the ``Host:``
    header for virtual-host routing.

    Caching: pin the IP for the lifetime of this transport so the
    redirect loop within a single fetch resolves the same hostname
    to the same IP throughout. The cache is per-transport instance —
    the collector creates a fresh transport per request, so the cache
    also guards against same-redirect-loop DNS rebinding attempts.

    Note: this protection is best-effort. The transport operates below
    httpx's hostname verification layer; HTTPS vhost validation still
    happens in httpx. For absolute guarantees, pair this with a
    deployed egress proxy that enforces IP policy on every request.
    """

    def __init__(self) -> None:
        self._pin_cache: dict[str, str] = {}

    def _resolve_and_pin(self, url: str) -> str:
        """Resolve + IP-validate the URL's hostname and rewrite the URL
        to address-anchored form. Returns the rewritten URL.

        Raises ``PermissionDenied`` if the host fails IP allowlist.
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            raise PermissionDenied(f"URL {url!r} is missing a scheme or hostname")
        if parsed.scheme not in ("http", "https"):
            raise PermissionDenied(
                f"URL {url!r} uses disallowed scheme {parsed.scheme!r}"
            )
        host = parsed.hostname
        # If the URL is already IP-anchored (an earlier redirect
        # constructed it), skip the resolve step.
        try:
            cached_ip = self._pin_cache[host]
        except KeyError:
            try:
                cached_ip = socket.gethostbyname(host)
            except socket.gaierror as exc:
                raise PermissionDenied(
                    f"DNS resolution failed for {host}"
                ) from exc
            try:
                address = ipaddress.ip_address(cached_ip)
            except ValueError as exc:
                raise PermissionDenied(
                    f"DNS result for {host} is not a parseable IP: {cached_ip}"
                ) from exc
            _check_ip_public(address, url)
            self._pin_cache[host] = cached_ip

        # Rewrite the URL with the IP in the netloc while preserving the
        # path / query / fragment from the original URL.
        netloc = cached_ip
        if parsed.port:
            netloc = f"{cached_ip}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            pinned_url = self._resolve_and_pin(str(request.url))
        except PermissionDenied:
            raise
        if pinned_url == str(request.url):
            return httpx.HTTPTransport().handle_request(request)
        # Reconstruct request with the IP-pinned URL but original
        # ``Host:`` header so the vhost resolves correctly on the
        # remote server.
        original_host = request.headers.get("host") or urlparse(
            str(request.url)
        ).hostname
        pinned_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers={**request.headers, "host": original_host},
            content=request.content,
            extensions=request.extensions,
        )
        return httpx.HTTPTransport().handle_request(pinned_request)

    def close(self) -> None:
        self._pin_cache.clear()


def _safe_redirect_join(base_url: str, location: str) -> str:
    """Resolve a possibly-relative ``Location`` header against ``base_url``.

    Returns the absolute URL that the client should follow next.
    Falls back to ``location`` unchanged for absolute URLs (we still
    have to validate them); pre-PR-3 the collector did
    ``current_url = location`` which silently dropped the base for
    relative redirects, breaking every common 302 case.
    """
    from urllib.parse import urljoin

    if not location:
        return base_url
    return urljoin(base_url, location)


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
    artifact = None

    if source_type == SourceType.URL:
        enforce_permission(AgentType.COLLECTOR, source, Permission.READ)
        # PR-3: redirect chain now flows through a DNS-pinned transport so
        # the same hostname resolves to the same IP for every hop, with
        # relative ``Location:`` headers correctly joined against the
        # current URL (the prior ``current_url = location`` form silently
        # dropped the base for relative redirects). The transport's
        # ``_check_ip_public`` covers every redirect target, eliminating
        # the SSRF TOCTOU window on the redirect chain.
        #
        # The entry URL is checked once via the cheaper path-first
        # ``_check_url_allowlisted`` so a private/loopback entry URL
        # short-circuits before any HTTP transport cost. The
        # transport-level check still applies for redirects — an
        # attacker cannot bypass the gate by chaining public → private
        # redirect targets.
        _check_url_allowlisted(source)
        transport = _PinnedDnsTransport()
        try:
            current_url = source
            response = None
            for _ in range(MAX_REDIRECT_HOPS):
                # Pin the URL on every iteration so each hop validates its
                # own hostname (an attacker redirecting to a different
                # host is caught at the transport's _resolve_and_pin).
                response = httpx.get(
                    current_url,
                    timeout=30,
                    follow_redirects=False,
                    transport=transport,
                )
                if response.is_redirect:
                    _loc = (
                        response.headers.get("Location")
                        or response.headers.get("location")
                        or ""
                    )
                    location = str(_loc) if _loc is not None else ""
                    if not location:
                        # Empty ``Location:`` is a protocol error;
                        # surface it rather than looping forever.
                        response.raise_for_status()
                    # urljoin absolute-wins, then resolves relative
                    # against the current URL's base; covers common 302
                    # patterns (/v2, //host/x, ../foo).
                    current_url = _safe_redirect_join(current_url, location)
                    continue
                response.raise_for_status()
                break
            else:
                raise PermissionDenied(
                    f"Too many redirects (>{MAX_REDIRECT_HOPS}) from {source}"
                )
        finally:
            transport.close()
        # R2: unified source cap — a URL body larger than the configured
        # limit is rejected before it can be parsed/embedded.
        content = response.text
        raw_content = response.content
        if not isinstance(raw_content, (bytes, bytearray)):
            raw_content = content.encode("utf-8")
        _enforce_source_size(len(raw_content), source)
        raw_path = source
        artifact = artifact_from_text(
            content,
            source_id=raw_path,
            format="html",
            extraction_method="html_text",
            source_bytes_sha256=sha256(raw_content).hexdigest(),
        )
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

        # R2: unified source cap — reject oversized local files before
        # reading them into memory (PDF/office extraction would otherwise
        # buffer the whole file).
        try:
            _enforce_source_size(file_path.stat().st_size, str(file_path))
        except OSError:
            # stat may fail for exotic paths; the read below will surface
            # the real error.
            pass

        if ext == ".pdf":
            content = extract_pdf_text(str(file_path))
        elif ext in [".docx", ".doc", ".xlsx"]:
            content = extract_office_text(str(file_path))
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
        artifact = collect_artifact(file_path, source_id=raw_path)

    payload = CollectorDonePayload(
        task_id=task_id,
        raw_path=raw_path,
        content=content,
        source=source,
        artifact=artifact,
    )

    event_bus.emit(EventName.COLLECTOR_DONE, payload)
    return payload
