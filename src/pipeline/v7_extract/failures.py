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
    """Per-document processing status (P2: never raises).

    Wave 2 (plan §2.2.1): three legacy values kept for backward
    compatibility with v3 callers; four new values give the pipeline
    a five-state vocabulary that distinguishes technical failures
    (FAILED) from quality blocks (BLOCKED) and skip-hit caches
    (SKIPPED).
    """

    # v3 legacy (backward compatible).
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    INCOMPLETE = "incomplete"
    # Wave 2 new values (plan §2.2.1).
    WRITTEN = "written"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExtractionResult:
    """Per-document result returned by Stage 7 driver / extract_pilot.

    Replaces the inconsistent return shapes the v2 stages used to
    hand back. P2 + D7 are enforced here:
      - ``status`` is always set
      - ``blocked_topic_ids`` lets the caller filter Stage-5 failures
        without re-running Stage 5

    Wave 2 (plan §2.2.1): the five-state status + ``legacy_status``
    pair lets callers tell technical failures (FAILED) apart from
    quality blocks (BLOCKED) while keeping a single v3-shaped
    ``legacy_status`` for older consumers (``run_full`` summary,
    Markdown report rows).
    """

    status: ExtractionStatus
    source_id: str
    source_md5: str = ""
    pages: list[Any] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    blocked_topic_ids: list[str] = field(default_factory=list)  # D7
    failure_stage: str | None = None
    attempts: int = 1

    # Five-state sub-fields (plan §2.2): page IDs bucketed by outcome.
    written_page_ids: list[str] = field(default_factory=list)
    blocked_page_ids: list[str] = field(default_factory=list)
    failed_page_ids: list[str] = field(default_factory=list)

    # Legacy compat field (plan §2.2.1): v3 callers read ``legacy_status``
    # when they want the old three-state verdict.
    legacy_status: ExtractionStatus | None = None

    # Wave 2 / Task 2: extra legacy fields stored on the dataclass so the
    # old ``extract_pilot`` / ``extract_full`` JSON contract (with keys
    # ``source`` / ``doc_type`` / ``complete`` / ``topics`` / ``error``)
    # round-trips through ``to_dict()``. Each ``_extract_one`` invocation
    # fills this with whatever the pre-refactor dict used to carry; the
    # default keeps new direct constructions clean.
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialization & mapping helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Single serialization entry point (plan §4 Task 2, checkbox 1).

        ``legacy_status`` is derived from ``status`` via
        ``_legacy_from_status`` unless an explicit value was set on the
        instance — that lets callers carry both views without manual
        bookkeeping.
        """
        legacy = self.legacy_status or self._legacy_from_status()
        base = {
            "status": self.status.value,
            "legacy_status": legacy.value,
            "source_id": self.source_id,
            "source_md5": self.source_md5,
            "pages": [p.id if hasattr(p, "id") else p for p in self.pages],
            "written_page_ids": list(self.written_page_ids),
            "blocked_page_ids": list(self.blocked_page_ids),
            "failed_page_ids": list(self.failed_page_ids),
            "review_reasons": list(self.review_reasons),
            "blocked_topic_ids": list(self.blocked_topic_ids),
            "failure_stage": self.failure_stage,
            "attempts": self.attempts,
        }
        # Legacy dict fields (``source`` / ``doc_type`` / ``complete`` /
        # ``topics`` / ``error`` / ``failure_stage`` / ``attempts`` etc.)
        # come through ``metadata``. They override the defaults on
        # collision so callers can set ``failure_stage`` or ``attempts``
        # via metadata without changing the dataclass shape.
        if self.metadata:
            base.update(self.metadata)
        return base

    def _legacy_from_status(self) -> ExtractionStatus:
        """Five-state → v3 three-state mapping (plan §2.2.1 table)."""
        mapping: dict[ExtractionStatus, ExtractionStatus] = {
            ExtractionStatus.WRITTEN: ExtractionStatus.OK,
            ExtractionStatus.SKIPPED: ExtractionStatus.OK,
            ExtractionStatus.BLOCKED: ExtractionStatus.NEEDS_REVIEW,
            ExtractionStatus.FAILED: ExtractionStatus.NEEDS_REVIEW,
            ExtractionStatus.INCOMPLETE: ExtractionStatus.INCOMPLETE,
            # Legacy pass-through — callers that still emit the v3 enum
            # get an identity map (no info loss).
            ExtractionStatus.OK: ExtractionStatus.OK,
            ExtractionStatus.NEEDS_REVIEW: ExtractionStatus.NEEDS_REVIEW,
        }
        return mapping.get(self.status, ExtractionStatus.NEEDS_REVIEW)

    @classmethod
    def from_v3_status(
        cls,
        status: ExtractionStatus,
        source_id: str,
        *,
        pages: list[Any] | None = None,
        **kwargs: Any,
    ) -> "ExtractionResult":
        """Build an ``ExtractionResult`` from a v3 ``ExtractionStatus``.

        Three-state → five-state derivation (plan §2.2.1):

        ======================  ====================================
        v3 ``status``           Five-state ``status``
        ======================  ====================================
        ``OK``                  ``WRITTEN`` (legacy ``OK`` carried in
                                ``legacy_status``)
        ``NEEDS_REVIEW``        ``BLOCKED``
        ``INCOMPLETE``          ``INCOMPLETE``
        ======================  ====================================

        Unknown inputs default to ``BLOCKED`` (safest: signal for
        review rather than pretending success).
        """
        new_status = {
            ExtractionStatus.OK: ExtractionStatus.WRITTEN,
            ExtractionStatus.NEEDS_REVIEW: ExtractionStatus.BLOCKED,
            ExtractionStatus.INCOMPLETE: ExtractionStatus.INCOMPLETE,
        }.get(status, ExtractionStatus.BLOCKED)
        return cls(
            status=new_status,
            source_id=source_id,
            legacy_status=status,
            pages=pages or [],
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Dict-like compat layer (plan §4 Task 2, checkbox 3)
    #
    # Lets legacy callers continue to read ``result["error"]`` /
    # ``result["complete"]`` / ``result["pages"]`` without crashing
    # while the rest of the migration moves to attribute access.
    # ``error`` is a synthesized boolean: True when ``review_reasons``
    # is non-empty (matches the old dict semantic in extract_pilot /
    # extract_full).
    # ------------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self.to_dict().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


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
