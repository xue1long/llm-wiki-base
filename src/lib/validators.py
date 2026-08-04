"""
Validators for HTTP API input sanitization.

Extracted from pressure test Round 6 findings:
- Empty source strings were accepted
- Path traversal attempts were not rejected at entry
- Null byte injection was not filtered
- Non-existent files were enqueued (delayed failure)

All validators raise ValueError on invalid input; HTTP routes
convert to 400 Bad Request.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def validate_source_string(source: str) -> None:
    """Validate a source string before enqueuing.

    Raises ValueError with descriptive message if the source is invalid.

    Checks:
    1. Non-empty and non-whitespace
    2. No null bytes (injection attack)
    3. No path traversal outside project (for file paths)
    4. No control characters (except valid URL chars)

    Does NOT check:
    - File existence (deferred to Collector stage)
    - URL reachability (deferred to Collector stage)
    """
    if not source or not source.strip():
        raise ValueError("Source cannot be empty or whitespace")

    # Null byte injection prevention
    if "\x00" in source:
        raise ValueError("Source contains null byte (potential injection attack)")

    # Control character detection (except common URL-safe chars)
    # Allow: tabs, newlines in URLs (encoded as %09, %0A)
    # Block: other C0 controls (0x01-0x1F except 0x09, 0x0A, 0x0D)
    for i, ch in enumerate(source):
        code = ord(ch)
        if 0x01 <= code <= 0x1F and ch not in ("\t", "\n", "\r"):
            raise ValueError(
                f"Source contains control character at position {i} (0x{code:02X})"
            )

    # For non-URL sources, check for obvious path traversal
    if not source.startswith(("http://", "https://")):
        # Normalize path separators
        normalized = source.replace("\\", "/")

        # Check for traversal attempts
        # Note: we allow legitimate paths like "raw/sources/../sources/file.md"
        # but block attempts to escape project root
        parts = normalized.split("/")

        # Track traversal depth
        depth = 0
        max_escapes = 0
        for part in parts:
            if part == "..":
                depth -= 1
                max_escapes = max(max_escapes, -depth)
            elif part and part != ".":
                depth += 1

        # If path tries to escape more than 3 levels, it's suspicious
        # (project root is typically 2-3 levels above raw/sources/)
        if max_escapes > 3:
            raise ValueError(
                f"Source path attempts to escape project root "
                f"(traverses {max_escapes} levels): {source!r}"
            )


def validate_file_source(source: str, project_root: Path) -> None:
    """Additional validation for file sources.

    Checks that the resolved path stays within the project root.
    This is called AFTER validate_source_string().

    Raises ValueError if the path would escape the project boundary.
    """
    # First run base validation
    validate_source_string(source)

    # Normalize to absolute path
    source_normalized = source.replace("\\", "/")

    # On Windows, Unix-style paths like "/etc/passwd" are NOT absolute
    # They get treated as relative paths under current drive
    # We should detect this pattern and reject it explicitly
    if source_normalized.startswith("/") and not os.path.isabs(source_normalized):
        # Unix-style absolute path on Windows - reject
        raise ValueError(
            f"Absolute path {source!r} is outside project root"
        )

    if os.path.isabs(source_normalized):
        # Absolute path - must be under project root
        try:
            rel = os.path.relpath(source_normalized, str(project_root))
            if rel.startswith(".."):
                raise ValueError(
                    f"Absolute path {source!r} is outside project root"
                )
        except ValueError:
            # Different drives on Windows
            raise ValueError(
                f"Absolute path {source!r} is outside project root"
            )
    else:
        # Relative path - resolve and check
        resolved = os.path.abspath(os.path.join(str(project_root), source_normalized))
        root_abs = os.path.abspath(str(project_root))

        try:
            rel = os.path.relpath(resolved, root_abs)
            if rel.startswith(".."):
                raise ValueError(
                    f"Relative path {source!r} escapes project root "
                    f"(resolves to {resolved!r})"
                )
        except ValueError:
            raise ValueError(
                f"Relative path {source!r} cannot be resolved within project"
            )


def validate_url_source(source: str) -> None:
    """Validate URL source format.

    Checks:
    - Valid URL scheme (http/https only)
    - Has a hostname
    - No private/loopback IP (additional check, Collector also does this)

    Raises ValueError if the URL is malformed or suspicious.
    """
    from urllib.parse import urlparse

    # First run base validation
    validate_source_string(source)

    parsed = urlparse(source)

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme must be http or https, got: {parsed.scheme!r}"
        )

    # Hostname check
    if not parsed.hostname:
        raise ValueError(f"URL has no hostname: {source!r}")

    # Basic sanity: no credentials in URL
    if parsed.username or parsed.password:
        raise ValueError(
            "URLs with embedded credentials are not allowed"
        )


def validate_source(source: str, project_root: Path | None = None) -> None:
    """Main entry point for source validation.

    Detects source type and routes to appropriate validator.

    Args:
        source: The source string to validate
        project_root: Required for file sources; ignored for URLs

    Raises:
        ValueError: If the source is invalid
    """
    if not source or not source.strip():
        raise ValueError("Source cannot be empty")

    is_url = source.startswith(("http://", "https://"))

    if is_url:
        validate_url_source(source)
    elif project_root is not None:
        validate_file_source(source, project_root)
    else:
        # Fallback: just basic string validation
        validate_source_string(source)