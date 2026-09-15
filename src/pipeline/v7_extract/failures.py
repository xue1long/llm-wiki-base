"""Unified failure semantics — D4 + D10 + D11.

D4 (architecture decision):  v7 failures reuse the same JSON file as
    the existing Generator-pipeline reviews_queue.json (one queue, one
    CLI), but we DO NOT call the existing ``ReviewQueue.enqueue`` because
    its fixed schema (``source_id`` / ``title`` / ``matches``) doesn't
    fit v7's needs (``failure_stage`` / ``source`` / ``payload``).

    Instead we read+write the same file via lower-level access, adding
    v7-only fields. The CLI in T3.3 filters by ``source="v7_extract"``
    to keep the two pipelines' items separate at display time.

D10: every v7 failure item carries ``source="v7_extract"`` so the
    shared CLI can distinguish them from Generator items.

D11: payloads are passed through ``sanitize_payload`` to redact
    sensitive fields and truncate long strings before they hit disk.

P2: callers do NOT raise. Any stage failure is recorded via
``enqueue_failure`` + audit_logger, and processing continues with the
next source.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


V7_SOURCE_TAG = "v7_extract"
"""D10: tag every v7-emitted review item with this source."""


class ExtractionStatus(str, Enum):
    """Per-document processing status (P2: never raises)."""

    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    INCOMPLETE = "incomplete"


@dataclass
class ExtractionResult:
    """Per-document result returned by Stage 7 driver / extract_pilot.

    Replaces the inconsistent return shapes the v2 stages used to
    hand back. P2 + D7 are enforced here:
      - ``status`` is always set
      - ``blocked_topic_ids`` lets the caller filter Stage-5 failures
        without re-running Stage 5
    """

    status: ExtractionStatus
    source_id: str
    pages: list[Any] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    blocked_topic_ids: list[str] = field(default_factory=list)  # D7
    failure_stage: str | None = None


# D11: sensitive-field whitelist + payload size cap
SENSITIVE_FIELDS: frozenset[str] = frozenset({
    "api_key", "email", "phone", "id_card", "password", "secret",
    "token", "auth", "authorization",
})
_MAX_STRING_LEN: int = 500


def sanitize_payload(payload: Any) -> Any:
    """D11: redact sensitive fields and cap string length, recursively.

    The pipeline emits LLM payloads to disk for audit. Those payloads
    may contain user input (raw document text), LLM debug info, or
    accidental API key dumps. We:
      - Replace values for sensitive keys with ``[REDACTED]``
      - Truncate any string longer than ``_MAX_STRING_LEN`` chars
    We DO NOT delete the payload — operators need the structural
    info to debug v7 failures.
    """
    if isinstance(payload, dict):
        return {
            k: ("[REDACTED]" if k.lower() in SENSITIVE_FIELDS else sanitize_payload(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [sanitize_payload(v) for v in payload]
    if isinstance(payload, str) and len(payload) > _MAX_STRING_LEN:
        return payload[:_MAX_STRING_LEN] + "..."
    return payload


# ---------------------------------------------------------------------------
# Review-queue I/O — share the file with the Generator pipeline
# (D4) but emit v7-shaped items
# ---------------------------------------------------------------------------

_DEFAULT_QUEUE_PATH = Path(".index") / "reviews_queue.json"


def _read_queue(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    return [dict(it) for it in items if isinstance(it, dict)] if isinstance(items, list) else []


def _write_queue(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


_REASON_MAX_LEN: int = 500


def _truncate_reason(reason: str) -> str:
    """Cap ``reason`` to ``_REASON_MAX_LEN`` chars (avoid sensitive payload
    leaks on disk; consistent with D11 string truncation).
    """
    if len(reason) > _REASON_MAX_LEN:
        return reason[:_REASON_MAX_LEN] + "..."
    return reason


def _stable_review_id(
    source_id: str,
    stage: str,
    page_id: str,
    topic_id: str,
    reason: str,
    content_hash: str,
) -> str:
    """plan §4 Task 3: stable review ID derived from identity fields.

    sha1(source + \0 + stage + \0 + page_id + \0 + topic_id + \0 +
         reason + \0 + content_hash)[:12], prefixed with ``v7fail-``.
    """
    identity = (
        f"{source_id}\0{stage}\0{page_id}\0{topic_id}\0"
        f"{reason}\0{content_hash}"
    )
    suffix = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"v7fail-{suffix}"


def _format_reason(
    reason: str,
    prompt_kind: str = "",
    provider: str = "",
) -> str:
    """P12: append ``prompt=<kind> provider=<name>`` tags when present.

    Returns ``reason`` truncated to ``_REASON_MAX_LEN``.
    """
    base = _truncate_reason(reason)
    tags: list[str] = []
    if prompt_kind:
        tags.append(f"prompt={prompt_kind}")
    if provider:
        tags.append(f"provider={provider}")
    if not tags:
        return base
    suffix = " ".join(tags)
    combined = f"{base} {suffix}"
    # Re-apply cap after tag append so total stays <= _REASON_MAX_LEN
    if len(combined) > _REASON_MAX_LEN:
        return combined[:_REASON_MAX_LEN] + "..."
    return combined


def enqueue_failure(
    source_id: str,
    stage: str,
    *,
    page_id: str = "",
    topic_id: str = "",
    reason: str,
    content_hash: str = "",
    prompt_kind: str = "",
    provider: str = "",
    payload: dict | None = None,
    queue_path: Path | str = _DEFAULT_QUEUE_PATH,
) -> str:
    """Record a v7 failure to the shared reviews queue.

    Stable review ID derived from ``(source_id, stage, page_id, topic_id,
    reason, content_hash)``; the same identity dedupes (attempts += 1,
    ``last_seen_at`` updated, ``last_prompt_kind`` / ``last_provider``
    refreshed). Different identity fields produce different review IDs.

    Args:
        source_id: Logical source identifier (relative path or stable slug).
        stage: Pipeline stage name (e.g. ``stage5``).
        page_id: Stable page ID (from ``_page_id._stable_page_id``) when
            the failure is page-scoped; empty for source-scoped failures.
        topic_id: Topic cluster ID (when applicable).
        reason: Human-readable failure reason (keyword-only, required).
        content_hash: Content hash of the source artifact (when available);
            differentiates re-extracts of the same source.
        prompt_kind: Optional P12 label — which prompt produced the failure.
        provider: Optional P12 label — which LLM provider was active.
        payload: Optional context dict; sanitized via D11 before write.
        queue_path: Override the default ``.index/reviews_queue.json``.

    Returns:
        The generated (or matched) review_id (stable sha1 prefix).
    """
    path = Path(queue_path)
    items = _read_queue(path)
    sanitized = sanitize_payload(payload or {})

    review_id = _stable_review_id(
        str(source_id), stage, page_id, topic_id, reason, content_hash,
    )
    formatted_reason = _format_reason(reason, prompt_kind, provider)

    now = _now_ms()
    for existing in items:
        if existing.get("id") == review_id:
            existing["attempts"] = int(existing.get("attempts", 0)) + 1
            existing["last_seen_at"] = now
            existing["reason"] = formatted_reason
            existing["last_prompt_kind"] = prompt_kind or existing.get("last_prompt_kind", "")
            existing["last_provider"] = provider or existing.get("last_provider", "")
            existing["status"] = existing.get("status", "open")
            _write_queue(path, items)
            return review_id

    items.append({
        "id": review_id,
        "source": V7_SOURCE_TAG,            # D10
        "failure_stage": stage,
        "reason": formatted_reason,
        "source_id": str(source_id),
        "page_id": page_id,
        "topic_id": topic_id,
        "content_hash": content_hash,
        "payload": sanitized,                 # D11
        "created_at": now,
        "last_seen_at": now,
        "last_prompt_kind": prompt_kind,
        "last_provider": provider,
        "attempts": 1,
        "status": "open",
    })
    _write_queue(path, items)
    return review_id


def filter_failed_topics(
    pages: list[Any],
    failed_topic_ids: list[str],
) -> list[Any]:
    """D7: drop Stage-5-failed topics before handing pages to WikiWriter.

    The writer treats pages as opaque; only the ``topic_id`` attribute is
    inspected. Topics whose id appears in ``failed_topic_ids`` are
    removed.
    """
    failed = set(failed_topic_ids)
    return [p for p in pages if getattr(p, "topic_id", None) not in failed]


def _now_ms() -> int:
    return int(time.time() * 1000)
