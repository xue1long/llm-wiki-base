"""Stage 7: atomic, retrying, checkpointed Wiki writer.

v3 (plan 2026-09-15) adds three guards on top of the v2 writer:

  A. P4 — pages whose ``topic_id`` is ``__other__`` (Stage 4's sentinel
     bucket for items the LLM forgot to assign) are routed to
     ``report.blocked``, never written.

  B. needs_review — pages with any slot flagged ``needs_review`` are
     blocked. The body is partial / unreliable; we don't auto-publish
     such pages.

  C. has_evidence — pages where no slot has evidence at all are
     blocked. Without evidence the page is just hallucination.

These three guards plus the existing content_filter are the v3 "four
gates" (P3 + P4). WriteReport.blocked records all four categories.

v4 (plan 2026-09-17, Task 19) appends a CommitManifest ledger without
touching the four gates: every ``commit_and_index`` call writes
``.index/commit_manifests/<commit_id>.json`` and updates it as each
page is published, the index is appended, and the checkpoint is
flushed. On restart, ``reconcile_unfinished_commits`` walks the
non-terminal manifests and recovers either as PREPARED (re-run) or
RECONCILED (commit + index done).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping

import yaml

from .audit_logger import AuditLogger
from .commit_manifest import (
    CommitManifest,
    CommitPhase,
    PageCommitRecord,
    manifest_dir,
    write_manifest,
)
from .failures import enqueue_failure
from .relation_extractor import PageRelation
from .slot_filler import ConceptPage
from .topic_clusterer import OTHER_TOPIC_ID


log = logging.getLogger(__name__)


PageWriter = Callable[[ConceptPage, Path], None]


# P4: pages whose id starts with this prefix are written into the
# review queue, NOT to disk. This is the v3 sentinel — it lets the
# writer refuse the Stage 4 "其他主题" bucket while still letting
# pages flow through the normal pipeline.
_BLOCKED_TOPIC_PREFIX = "__other__"


@dataclass
class WriteReport:
    """Per-batch write outcome for the WikiWriter.

    Wave 3 / Task 3 (plan 2026-09-15 control plane refactor) extends the
    v3 report with:
      - ``page_writes``: map of page_id → filesystem Path actually
        written. ``None`` for pages that were blocked/skipped/failed.
        Wave 4 Luna-F reads this to build the source-level checkpoint
        without re-implementing writer semantics.
      - ``dry_run``: True when V7_ALLOW_APPLY was not set; no pages
        were touched on disk (mirrors extract_full.py dry_run semantics).

    Compatibility note: existing consumers still read ``written /
    skipped / blocked / failed``. The new fields are additive.
    """

    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    page_writes: dict[str, Path | None] = field(default_factory=dict)
    dry_run: bool = False


class WikiWriter:
    """Write V7 concept pages without duplicating work after a restart."""

    def __init__(
        self,
        root: str | Path,
        *,
        page_writer: PageWriter | None = None,
        content_filter: Any = None,
        max_retries: int = 3,
        queue_path: str | Path | None = None,
        provider: str = "",
        prompt_kind: str = "",
        pipeline_fingerprint: str = "",
        commit_id_factory: Callable[[], str] | None = None,
        durable_failure_path: str | Path | None = None,
        queue_projection_pending_path: str | Path | None = None,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be positive")
        self.root = Path(root)
        self.pages_dir = self.root / "wiki" / "concepts"
        self.index_path = self.root / "wiki" / "index.md"
        self.checkpoint_path = self.root / ".index" / "v7_checkpoint.json"
        self.audit = AuditLogger(self.root / ".index" / "extract_report.json")
        self.page_writer = page_writer or self._write_page_atomically
        self.content_filter = content_filter
        self.max_retries = max_retries
        # Wave 3 / Task 3 (plan §4): every blocked / failed page is
        # recorded in the shared reviews_queue so human triage can
        # recover. queue_path is optional — when None, the writer skips
        # enqueueing (back-compat for tests that don't care about the
        # queue side-effect).
        self.queue_path = Path(queue_path) if queue_path is not None else None
        self.provider = provider
        self.prompt_kind = prompt_kind
        # Task 21 (plan §4 F11): durable failure fact is the source of
        # truth for every page outcome. ``durable_failure_path`` is
        # optional (defaults to None) so existing callers/tests see no
        # change. ``queue_projection_pending_path`` captures projection
        # failures from ``reviews_queue.json`` so a repair job can replay
        # them later — also opt-in.
        self.durable_failure_path = (
            Path(durable_failure_path) if durable_failure_path is not None else None
        )
        self.queue_projection_pending_path = (
            Path(queue_projection_pending_path)
            if queue_projection_pending_path is not None
            else None
        )
        # Task 19 (plan §4): commit manifest hooks. Both kwargs are
        # additive and default-safe — existing callers see no change.
        # ``pipeline_fingerprint`` is recorded on every manifest so
        # Task 22's source checkpoint can detect pipeline upgrades.
        # ``commit_id_factory`` defaults to uuid4 hex; tests inject a
        # deterministic factory to make commit ids predictable.
        self.pipeline_fingerprint = pipeline_fingerprint
        self.commit_id_factory: Callable[[], str] = (
            commit_id_factory if commit_id_factory is not None else (lambda: uuid.uuid4().hex)
        )

    def commit_and_index(
        self,
        pages: Iterable[ConceptPage],
        relations: Iterable[PageRelation] = (),
    ) -> WriteReport:
        pages = list(pages)
        relation_map = _relations_by_source(relations)
        self._last_relations = relation_map
        checkpoint = self._read_checkpoint()
        completed = checkpoint["completed"]
        report = WriteReport()
        # Task 19: open the manifest up-front so a crash before any
        # write still leaves a PREPARED ledger entry. ``source_id``
        # defaults to the first page's first source; a single-page
        # batch keeps this consistent with the per-page records.
        manifest = self._open_manifest(pages)
        manifest_failed = False

        for page in pages:
            # Guard A: P4 — __other__ topic is a sentinel, never write.
            # H1 (Wave 3 / plan-audit): use getattr to match the
            # ``failures.filter_failed_topics`` pattern. ConceptPage.topic_id
            # was promoted to a formal field by Luna-A but tests still
            # construct ConceptPage instances without setting it, so a
            # direct attribute access here would crash the whole batch.
            _topic_id = getattr(page, "topic_id", None)
            if _topic_id == OTHER_TOPIC_ID or page.id.startswith(_BLOCKED_TOPIC_PREFIX):
                report.page_writes[page.id] = None
                report.blocked.append(page.id)
                self._enqueue_failure(
                    page, "stage7_gate",
                    reason=f"__other__: topic={_topic_id}",
                )
                self._record_page_blocked(manifest, page)
                continue

            # Guard B: needs_review — any slot flagged for review blocks.
            if page.needs_review_slots:
                report.page_writes[page.id] = None
                report.blocked.append(page.id)
                self._enqueue_failure(
                    page, "stage7_gate",
                    reason=f"needs_review: slots={','.join(page.needs_review_slots)}",
                )
                self._record_page_blocked(manifest, page)
                manifest_failed = True
                continue

            # Guard C: has_evidence — no evidence at all means hallucination.
            if not page.has_evidence:
                report.page_writes[page.id] = None
                report.blocked.append(page.id)
                self._enqueue_failure(
                    page, "stage7_gate",
                    reason="no_evidence",
                )
                self._record_page_blocked(manifest, page)
                manifest_failed = True
                continue

            # Guard D: content_filter (existing v2).
            if self.content_filter is not None:
                filter_result = self.content_filter.check(
                    page.body,
                    source_id=page.sources[0] if page.sources else page.id,
                    title=page.title,
                )
                if getattr(filter_result.status, "value", filter_result.status) == "needs_review":
                    report.page_writes[page.id] = None
                    report.blocked.append(page.id)
                    self._enqueue_failure(
                        page, "stage7_content_filter",
                        reason=f"content_filter: {filter_result.status}",
                    )
                    self._record_page_blocked(manifest, page)
                    manifest_failed = True
                    continue

            try:
                path = self._page_path(page.id)
            except ValueError as exc:
                # Invalid page ID is a technical failure (T3 plan §4)
                # not a blocked outcome — record in failed so the
                # caller knows it should be retried (or fixed).
                report.page_writes[page.id] = None
                report.failed[page.id] = f"page_id_invalid: {exc}"
                self._enqueue_failure(
                    page, "stage7_path",
                    reason=f"page_id_invalid: {exc}",
                )
                self._record_page_failed(manifest, page, f"page_id_invalid: {exc}")
                manifest_failed = True
                continue
            # Task 19: idempotent re-run. If the manifest already has a
            # COMMITTED record for this page AND the on-disk sha1
            # matches, treat the page as skipped (no rewrite, no
            # append-to-index double-write).
            if self._manifest_page_already_committed(manifest, page, path):
                report.page_writes[page.id] = path
                report.skipped.append(page.id)
                self._audit_page(page)
                # Task 21: durable outcome fact for idempotent skips.
                self._record_durable_outcome(
                    page.id,
                    str(getattr(page, "topic_id", "") or ""),
                    source_paths=list(getattr(page, "sources", []) or []),
                    outcome="skipped",
                    reason="manifest_already_committed",
                    phase="stage7_commit",
                )
                continue
            if page.id in completed and path.exists():
                report.page_writes[page.id] = path
                report.skipped.append(page.id)
                self._audit_page(page)
                # Backfill the manifest so a future restart sees this
                # page as committed even though the writer skipped it.
                self._record_page_committed(manifest, page, path)
                # Task 21: durable outcome fact for idempotent skips.
                self._record_durable_outcome(
                    page.id,
                    str(getattr(page, "topic_id", "") or ""),
                    source_paths=list(getattr(page, "sources", []) or []),
                    outcome="skipped",
                    reason="checkpoint_already_completed",
                    phase="stage7_commit",
                )
                continue
            if page.id in completed:
                completed.remove(page.id)
                self._save_checkpoint(completed)

            last_error: Exception | None = None
            for _ in range(self.max_retries):
                try:
                    self.page_writer(page, path)
                    last_error = None
                    break
                except Exception as exc:  # retry boundary intentionally broad
                    last_error = exc
            if last_error is not None:
                report.page_writes[page.id] = None
                report.failed[page.id] = str(last_error)
                self._enqueue_failure(
                    page, "stage7_write",
                    reason=f"writer_retry_exhausted: {last_error}",
                    content_hash="",
                )
                self._record_page_failed(manifest, page, str(last_error))
                manifest_failed = True
                continue

            if page.id not in completed:
                completed.append(page.id)
            # Task 19: mark CHECKPOINTING just before the checkpoint
            # flush, then back to the per-page record on success.
            manifest.phase = CommitPhase.CHECKPOINTING
            manifest.updated_at_ms = int(time.time() * 1000)
            self._save_checkpoint(completed)
            report.page_writes[page.id] = path
            report.written.append(page.id)
            self._record_page_committed(manifest, page, path)
            self._audit_page(page)
            # Task 21: durable outcome fact for the committed page.
            self._record_durable_outcome(
                page.id,
                str(getattr(page, "topic_id", "") or ""),
                source_paths=list(getattr(page, "sources", []) or []),
                outcome="committed",
                reason="",
                phase="stage7_commit",
                committed_at_ms=int(time.time() * 1000),
            )

        manifest.phase = CommitPhase.INDEXING
        manifest.updated_at_ms = int(time.time() * 1000)
        self._append_index(pages, report)
        self._close_manifest(manifest, manifest_failed, report)
        return report

    def _enqueue_failure(
        self,
        page: ConceptPage,
        stage: str,
        *,
        reason: str,
        content_hash: str = "",
    ) -> None:
        """Record a page-level failure into the reviews queue (Task 3).

        Task 21 (plan §4 F11): this now orchestrates two independent
        writes:

          1. ``_record_durable_outcome`` — append the outcome fact to
             ``durable_failure.jsonl`` (100% coverage, never raises).
             Written FIRST so a queue projection failure never costs us
             the outcome.
          2. ``_project_failures_to_review_queue`` — project gated /
             failed pages into ``reviews_queue.json`` (idempotent via
             Luna-B's stable sha1 ``enqueue_failure``). On projection
             failure, the projection request is captured in
             ``queue_projection_pending.jsonl`` for a repair job.

        Both helpers swallow IO errors per Failure Contract §1 — the
        writer itself must never raise.
        """
        self._record_durable_outcome(
            page.id,
            str(getattr(page, "topic_id", "") or ""),
            source_paths=list(getattr(page, "sources", []) or []),
            outcome="blocked" if stage != "stage7_write" and stage != "stage7_path" else "failed",
            reason=reason,
            phase=stage,
        )
        self._project_failures_to_review_queue(
            page, stage, reason=reason, content_hash=content_hash,
        )

    def _record_durable_outcome(
        self,
        page_id: str,
        topic_id: str,
        *,
        source_paths: list[str],
        outcome: str,
        reason: str = "",
        phase: str = "",
        revision_hash: str = "",
        committed_at_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        """Append one JSONL line to ``durable_failure.jsonl``.

        Task 21 (plan §4 F11): ``durable_failure.jsonl`` is the source of
        truth for every page outcome (committed / blocked / failed /
        skipped / reconciled) — 100% coverage, no overlap with
        ``reviews_queue.json``.

        Never raises (Failure Contract §1): if disk write fails, the
        exception is swallowed + logged; the writer itself must not
        crash because the audit trail could not be flushed. A no-op when
        ``self.durable_failure_path`` is None so callers that haven't
        opted into the durable trail still work unchanged.
        """
        if self.durable_failure_path is None:
            return
        try:
            payload = {
                "timestamp_ms": int(time.time() * 1000),
                "page_id": page_id,
                "topic_id": topic_id,
                "source_paths": list(source_paths),
                "outcome": outcome,
                "reason": reason,
                "phase": phase,
                "revision_hash": revision_hash,
                "committed_at_ms": committed_at_ms,
                "error": error,
            }
            self.durable_failure_path.parent.mkdir(parents=True, exist_ok=True)
            with self.durable_failure_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — Failure Contract §1: never raises
            return

    def _project_failures_to_review_queue(
        self,
        page: ConceptPage,
        stage: str,
        *,
        reason: str,
        content_hash: str = "",
    ) -> None:
        """Project a blocked / failed page into ``reviews_queue.json``.

        No-op when ``self.queue_path`` is None (tests + dry-run callers).
        Wraps ``enqueue_failure`` in try/except: on projection failure,
        appends the request to ``queue_projection_pending.jsonl`` (when
        configured) so a repair job can replay it later. Never raises.
        """
        if self.queue_path is None:
            return
        try:
            enqueue_failure(
                source_id=str(page.sources[0] if page.sources else page.id),
                stage=stage,
                page_id=page.id,
                topic_id=str(getattr(page, "topic_id", "") or ""),
                reason=reason,
                content_hash=content_hash,
                prompt_kind=self.prompt_kind,
                provider=self.provider,
                queue_path=self.queue_path,
            )
        except Exception as exc:  # noqa: BLE001 — Failure Contract §1
            # queue projection failed → record to pending log so a repair
            # job can replay. Best-effort: pending log write is itself
            # wrapped in try/except (Failure Contract §1).
            self._record_queue_projection_pending(
                page=page,
                stage=stage,
                reason=reason,
                content_hash=content_hash,
                queue_path=self.queue_path,
                error=exc,
            )

    def _record_queue_projection_pending(
        self,
        *,
        page: ConceptPage,
        stage: str,
        reason: str,
        content_hash: str,
        queue_path: Path,
        error: Exception,
    ) -> None:
        """Append one JSONL line to ``queue_projection_pending.jsonl``.

        Best-effort: if the pending log itself cannot be written (disk
        full / permission denied), the error is swallowed per Failure
        Contract §1. A no-op when ``self.queue_projection_pending_path``
        is None so callers that haven't opted in still work.
        """
        if self.queue_projection_pending_path is None:
            return
        try:
            payload = {
                "timestamp_ms": int(time.time() * 1000),
                "page_id": page.id,
                "topic_id": str(getattr(page, "topic_id", "") or ""),
                "source_id": str(page.sources[0] if page.sources else page.id),
                "stage": stage,
                "reason": reason,
                "content_hash": content_hash,
                "prompt_kind": self.prompt_kind,
                "provider": self.provider,
                "queue_path": str(queue_path),
                "error": "queue io failed: " + repr(error),
            }
            self.queue_projection_pending_path.parent.mkdir(
                parents=True, exist_ok=True
            )
            with self.queue_projection_pending_path.open(
                "a", encoding="utf-8"
            ) as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — Failure Contract §1: never raises
            return

    def _write_page_atomically(self, page: ConceptPage, path: Path) -> None:
        relations = getattr(self, "_last_relations", {}).get(page.id, [])
        # Task 20: pull ``commit_id`` from the active manifest (set by
        # ``_open_manifest`` / cleared by ``_close_manifest``). When the
        # writer is invoked outside a ``commit_and_index`` call (e.g. a
        # test or a dry-run script that exercises ``_write_page_atomically``
        # directly) the attribute is missing → commit_id falls back to
        # ``""`` so back-compat callers keep working.
        manifest = getattr(self, "_current_manifest", None)
        commit_id = manifest.commit_id if manifest is not None else ""
        committed_at = int(time.time() * 1000)
        frontmatter = {
            "id": page.id,
            "title": page.title,
            "type": page.type,
            "sources": list(page.sources),
            "relations": [relation.to_dict() for relation in relations],
            "owner": "v7",
            "pipeline": "v7",
            "commit_id": commit_id,
            "pipeline_fingerprint": self.pipeline_fingerprint,
            # First pass writes ``revision_hash=""``; the real sha1 is
            # substituted into the same dict before the second dump so
            # ``_compute_revision_hash`` and the on-disk payload agree.
            "revision_hash": "",
            "committed_at": committed_at,
        }
        body = page.body
        frontmatter["revision_hash"] = self._compute_revision_hash(frontmatter, body)
        content = "---\n" + yaml.safe_dump(
            frontmatter, allow_unicode=True, sort_keys=False
        ) + "---\n\n" + body
        self._atomic_write(path, content)

    @staticmethod
    def _compute_revision_hash(frontmatter: dict[str, Any], body: str) -> str:
        """Sha1 of the rendered page with ``revision_hash`` set to ``""``.

        The two-pass dump (empty hash → sha1 → fill in hash → re-dump)
        relies on this method being byte-identical to the second dump
        in ``_write_page_atomically``. The dump settings are pinned here
        so any future change to the dump defaults would force a test
        failure rather than silently invalidating every on-disk hash.
        """
        payload = dict(frontmatter)
        payload["revision_hash"] = ""
        dumped = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        return hashlib.sha1((dumped + body).encode("utf-8")).hexdigest()

    def _append_index(self, pages: list[ConceptPage], report: WriteReport) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.index_path.read_text(encoding="utf-8") if self.index_path.exists() else "# Wiki Index\n\n"
        existing = set()
        for line in content.splitlines():
            if line.startswith("- **"):
                existing.add(line.split("**", 2)[1])
        for page in pages:
            if page.id not in report.written and page.id not in report.skipped:
                continue
            if page.id in existing:
                continue
            if not content.endswith("\n"):
                content += "\n"
            content += f"- **{page.id}** (concept) — {page.title}\n"
            existing.add(page.id)
        self._atomic_write(self.index_path, content)

    def rebuild_index(self) -> int:
        """Task 39: scan wiki/concepts/*.md, regenerate wiki/index.md.

        Useful when the index drifts from disk (manual edit, batch rollback,
        partial crash) and a clean rebuild is desired.

        Returns the count of pages indexed. Pages with no frontmatter /
        missing id/title are skipped with a warning. Output rows are sorted
        by page_id ascending for deterministic indexing.
        """
        import yaml as _yaml
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        rows: list[tuple[str, str]] = []   # (page_id, title)
        skipped = 0
        for md_path in sorted(self.pages_dir.glob("*.md")):
            try:
                text = md_path.read_text(encoding="utf-8")
            except OSError as e:
                log.warning("rebuild_index: cannot read %s: %s", md_path, e)
                skipped += 1
                continue
            # Frontmatter is the part between the first pair of --- fences.
            if not text.startswith("---"):
                log.warning("rebuild_index: %s missing frontmatter; skipped", md_path.name)
                skipped += 1
                continue
            try:
                _, fm_block, body = text.split("---", 2)
                frontmatter = _yaml.safe_load(fm_block) or {}
            except (ValueError, _yaml.YAMLError) as e:
                log.warning("rebuild_index: %s frontmatter parse failed: %s", md_path.name, e)
                skipped += 1
                continue
            page_id = str(frontmatter.get("id", "") or "").strip()
            title = str(frontmatter.get("title", "") or "").strip()
            page_type = str(frontmatter.get("type", "concept") or "concept")
            if not page_id or not title:
                log.warning("rebuild_index: %s missing id/title; skipped", md_path.name)
                skipped += 1
                continue
            rows.append((page_id, title, page_type))
        rows.sort(key=lambda r: r[0])
        lines = ["# Wiki Index", ""]
        for page_id, title, page_type in rows:
            lines.append(f"- **{page_id}** ({page_type}) — {title}")
        content = "\n".join(lines) + "\n"
        try:
            self._atomic_write(self.index_path, content)
        except OSError as e:
            log.error("rebuild_index: failed to write %s: %s", self.index_path, e)
        log.info("rebuild_index: %d pages indexed, %d skipped", len(rows), skipped)
        return len(rows)

    def _audit_page(self, page: ConceptPage) -> None:
        for source_id in page.sources:
            self.audit.record(source_id, [page.id])

    def _read_checkpoint(self) -> dict[str, list[str]]:
        if not self.checkpoint_path.exists():
            return {"completed": []}
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            completed = payload.get("completed", [])
            if isinstance(completed, list):
                return {"completed": list(dict.fromkeys(str(item) for item in completed))}
        except (OSError, ValueError, AttributeError):
            pass
        return {"completed": []}

    def _save_checkpoint(self, completed: list[str]) -> None:
        self._atomic_write(
            self.checkpoint_path,
            json.dumps({"completed": completed}, ensure_ascii=False, indent=2) + "\n",
        )

    def _page_path(self, page_id: str) -> Path:
        if not page_id or Path(page_id).is_absolute() or PureWindowsPath(page_id).is_absolute():
            raise ValueError("page id must be a relative filename")
        if any(char in page_id for char in "/\\") or ".." in page_id:
            raise ValueError("page id must be a single filename")
        path = self.pages_dir / f"{page_id}.md"
        try:
            path.resolve().relative_to(self.pages_dir.resolve())
        except ValueError as exc:
            raise ValueError("page id escapes concept directory") from exc
        return path

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    # ------------------------------------------------------------------
    # Task 19 (plan §4): CommitManifest hooks. These four helpers are
    # the only surface area added on top of the v3 writer. The four
    # gates (P4 / needs_review / has_evidence / content_filter) and the
    # retry / checkpoint flow above are untouched.
    # ------------------------------------------------------------------

    def _open_manifest(self, pages: list[ConceptPage]) -> CommitManifest:
        """Create + persist a PREPARED manifest for this batch.

        ``source_id`` falls back to ``"<unknown>"`` when the batch is
        empty so ``CommitManifest.source_id`` (a required str) never
        crashes the writer. Page-level sources fill in the per-page
        ``PageCommitRecord.source_paths`` instead.
        """
        now_ms = int(time.time() * 1000)
        source_id = "<unknown>"
        if pages:
            first_sources = getattr(pages[0], "sources", []) or []
            if first_sources:
                source_id = str(first_sources[0])
        manifest = CommitManifest(
            commit_id=self.commit_id_factory(),
            source_id=source_id,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            pipeline_fingerprint=self.pipeline_fingerprint,
            phase=CommitPhase.PREPARED,
        )
        # Ensure the per-project manifest directory exists.
        manifest_dir(self.root)
        write_manifest(self.root, manifest)
        # Task 20: stash the manifest so ``_write_page_atomically`` can
        # embed ``commit_id`` into each page frontmatter. Cleared by
        # ``_close_manifest`` so a stray reference after the batch
        # doesn't leak into the next one.
        self._current_manifest = manifest
        return manifest

    def _close_manifest(
        self,
        manifest: CommitManifest,
        manifest_failed: bool,
        report: WriteReport,
    ) -> None:
        """Final phase transition for the batch's manifest.

        * Any blocked / failed page → manifest.phase = FAILED.
        * Otherwise → manifest.phase = COMMITTED.
        * Any technical exception while writing the page (writer
          retry exhausted, page_id_invalid) is captured in
          ``manifest.error`` and surfaces in the on-disk ledger for
          ``reconcile_unfinished_commits`` to find.
        """
        now_ms = int(time.time() * 1000)
        if manifest_failed or report.blocked or report.failed:
            manifest.phase = CommitPhase.FAILED
            if report.failed:
                first_page_id, first_error = next(iter(report.failed.items()))
                manifest.error = f"{first_page_id}: {first_error}"
        else:
            manifest.phase = CommitPhase.COMMITTED
        manifest.updated_at_ms = now_ms
        write_manifest(self.root, manifest)
        # Task 20: drop the in-flight manifest reference. ``_write_page_atomically``
        # falls back to commit_id="" once this is cleared, so an out-of-band
        # call after ``commit_and_index`` returns won't accidentally
        # attribute its pages to the closed commit.
        self._current_manifest = None

    def _record_page_committed(
        self,
        manifest: CommitManifest,
        page: ConceptPage,
        path: Path,
    ) -> None:
        """Append / update a COMMITTED ``PageCommitRecord`` for ``page``.

        ``revision_hash`` is the sha1 of the rendered body (Task 19
        placeholder; Task 20 will extend this to cover frontmatter).
        The manifest is rewritten at every per-page transition so a
        mid-batch crash leaves a recoverable ledger.
        """
        record = PageCommitRecord(
            page_id=page.id,
            topic_id=str(getattr(page, "topic_id", "") or ""),
            source_paths=list(page.sources),
            phase=CommitPhase.COMMITTED,
            revision_hash=hashlib.sha1(page.body.encode("utf-8")).hexdigest(),
            written_path=str(path),
            committed_at_ms=int(time.time() * 1000),
        )
        manifest.pages[page.id] = record
        manifest.updated_at_ms = record.committed_at_ms
        write_manifest(self.root, manifest)

    def _record_page_blocked(
        self,
        manifest: CommitManifest,
        page: ConceptPage,
    ) -> None:
        """Append a FAILED record for a gate-rejected page."""
        record = PageCommitRecord(
            page_id=page.id,
            topic_id=str(getattr(page, "topic_id", "") or ""),
            source_paths=list(page.sources),
            phase=CommitPhase.FAILED,
            error="blocked_by_gate",
        )
        manifest.pages[page.id] = record
        manifest.updated_at_ms = int(time.time() * 1000)
        write_manifest(self.root, manifest)

    def _record_page_failed(
        self,
        manifest: CommitManifest,
        page: ConceptPage,
        error: str,
    ) -> None:
        """Append a FAILED record for a technical write failure."""
        record = PageCommitRecord(
            page_id=page.id,
            topic_id=str(getattr(page, "topic_id", "") or ""),
            source_paths=list(page.sources),
            phase=CommitPhase.FAILED,
            error=str(error),
        )
        manifest.pages[page.id] = record
        manifest.updated_at_ms = int(time.time() * 1000)
        write_manifest(self.root, manifest)

    def _manifest_page_already_committed(
        self,
        manifest: CommitManifest,
        page: ConceptPage,
        path: Path,
    ) -> bool:
        """True when this same batch's manifest already committed ``page``.

        On the second ``commit_and_index`` call with the same page,
        ``report.skipped`` should reflect idempotency without rewriting
        the file or re-appending to the wiki index.
        """
        existing = manifest.pages.get(page.id)
        if existing is None or existing.phase != CommitPhase.COMMITTED:
            return False
        if existing.revision_hash != hashlib.sha1(page.body.encode("utf-8")).hexdigest():
            return False
        # The page file must already exist on disk; if not, treat this
        # as not-yet-committed and let the normal write path handle it.
        return path.exists()


def _relations_by_source(relations: Iterable[PageRelation]) -> dict[str, list[PageRelation]]:
    result: dict[str, list[PageRelation]] = {}
    seen: set[tuple[str, str, str]] = set()
    for raw in relations:
        relation = _coerce_relation(raw)
        key = (relation.source_id, relation.target_id, relation.type)
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(relation.source_id, []).append(relation)
    return result


def _coerce_relation(raw: Any) -> PageRelation:
    if isinstance(raw, PageRelation):
        return raw
    if isinstance(raw, Mapping):
        return PageRelation(
            str(raw.get("source_id", raw.get("source", ""))),
            str(raw.get("target_id", raw.get("target", ""))),
            str(raw.get("type", "")),
            float(raw.get("weight", 1.0)),
            str(raw.get("context", "")),
        )
    return PageRelation(
        str(getattr(raw, "source_id", "")),
        str(getattr(raw, "target_id", "")),
        str(getattr(raw, "type", "")),
        float(getattr(raw, "weight", 1.0)),
        str(getattr(raw, "context", "")),
    )


# ---------------------------------------------------------------------------
# Task 40: queue projection repair job
# ---------------------------------------------------------------------------


def repair_queue_projections(root: Path | str) -> int:
    """Replay ``.index/queue_projection_pending.jsonl`` into reviews_queue.

    Task 21 + Task 40: wiki_writer writes a pending log line whenever the
    reviews_queue projection itself fails (disk full, permission denied).
    This function scans the pending log, replays each entry through
    ``enqueue_failure``, and removes successfully repaired entries from the
    pending log. Failed re-projection keeps the entry (preserves data).

    Best-effort, never raises (Failure Contract §1). Returns the count of
    successfully repaired entries. Missing pending file is a no-op (0).

    Atomic rewrite: successful entries are filtered out and the pending log
    is overwritten via tmp + rename.
    """
    root_path = Path(root)
    pending_path = root_path / ".index" / "queue_projection_pending.jsonl"
    if not pending_path.exists():
        return 0
    try:
        lines = pending_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        log.warning("repair_queue_projections: cannot read %s: %s", pending_path, e)
        return 0

    remaining: list[str] = []
    repaired = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        queue_path = Path(payload.get(
            "queue_path",
            str(root_path / ".index" / "reviews_queue.json"),
        ))
        try:
            from .failures import enqueue_failure
            enqueue_failure(
                source_id=str(payload.get("source_id", "")),
                stage=str(payload.get("stage", "stage7")),
                page_id=str(payload.get("page_id", "")),
                topic_id=str(payload.get("topic_id", "")),
                reason=str(payload.get("reason", "queue io failed: prior")),
                content_hash=str(payload.get("content_hash", "")),
                prompt_kind=str(payload.get("prompt_kind", "")),
                provider=str(payload.get("provider", "")),
                queue_path=queue_path,
            )
            repaired += 1
        except Exception as e:  # noqa: BLE001
            log.warning(
                "repair_queue_projections: replay failed for page_id=%s: %s",
                payload.get("page_id"), e,
            )
            remaining.append(line)

    # Atomic rewrite of pending log with only the still-failing entries.
    try:
        tmp = pending_path.with_suffix(".jsonl.tmp")
        if remaining:
            tmp.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            tmp.write_text("", encoding="utf-8")
        tmp.replace(pending_path)
    except OSError as e:
        log.error("repair_queue_projections: failed to rewrite %s: %s", pending_path, e)

    log.info("repair_queue_projections: %d repaired, %d still pending", repaired, len(remaining))
    return repaired
