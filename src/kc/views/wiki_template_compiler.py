"""WikiTemplateCompiler (路线 v2.2 §A-7 / Z-7, spec §12.4 R-7).

Compiles a ``WikiView`` from Core inputs (KnowledgeObject list, Conflict
list, Evidence lookup, topic_scope, publication_version) by walking the
template's sections in order and rendering each one from the inputs.

Spec gates enforced here:

* §A7 Gate — 不同观点不被静默合并: each Conflict surfaces its own
  perspective / actual / conditional row.
* §A7 Gate — 每个事实都有 Evidence 入口: every KU gets an evidence_refs
  row in the rendered knowledge_units section; KU without evidence is
  flagged as missing (not silently dropped).
* §12.4 R-7 — Wiki 通过 Query + Template 编译: the compiler is the only
  Wiki render path here; legacy per-source projection is preserved in
  ``src/wiki/projection.py`` unchanged.

Inputs are duck-typed (dict or dataclass — anything with the expected
attributes). This decouples the compiler from the C-1 / C-4 dataclass
shape evolution: if those schemas grow, the compiler only needs the
attribute readers updated, not the call sites.

Task 6（plan 2026-08-29-kc-integrity-idempotency-layered.md）扩展：
- ``rebuild_wiki_view(paths, view_inputs) -> RebuildReport`` 先生成
  内存/staging；全部编译成功后逐个调既有 writer；任何编译或写入失败
  → ``reason_codes`` 含失败原因，未完成页面保持原状。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .wiki_template import WikiTemplate, WikiView, compute_rendered_hash

_logger = logging.getLogger(__name__)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read attribute or dict key from ``obj`` (duck-typed)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _render_summary(knowledge_units, topic_scope, conflicts, evidence_lookup) -> str:
    """Top-3 KU summary (knowledge_mode-agnostic).

    Each line: "<ku_id>: <claim>" — kept short; longer narrative is the
    knowledge_units section's job.
    """
    top = knowledge_units[:3]
    lines = [f"- {_get(ku, 'id', '?')}: {_get(ku, 'claim', '')}" for ku in top]
    if not lines:
        return "(no knowledge units)"
    return "\n".join(lines)


def _render_context_filters(knowledge_units, topic_scope, conflicts, evidence_lookup) -> str:
    """Surface the topic_scope's context_filters (domain/platform/audience)."""
    cf = topic_scope.get("context_filters", {}) if isinstance(topic_scope, dict) else {}
    if not cf:
        return "(no context filters)"
    return ", ".join(f"{k}={v}" for k, v in sorted(cf.items()))


def _render_temporal_status(knowledge_units, topic_scope, conflicts, evidence_lookup) -> str:
    """Surface each KU's temporal_status (current/historical/scheduled/unknown).

    Statuses are deduplicated by value but the order follows the KU order
    so a reader can trace back to the source position.
    """
    if not knowledge_units:
        return "(no knowledge units)"
    seen: list[str] = []
    out: list[str] = []
    for ku in knowledge_units:
        status = str(_get(ku, "temporal_status", "unknown"))
        if status not in seen:
            seen.append(status)
            out.append(status)
    return " / ".join(out)


def _render_knowledge_units(knowledge_units, topic_scope, conflicts, evidence_lookup) -> str:
    """Render KU list with per-row evidence refs (document_id + block_id).

    spec §A7 Gate — 每个事实都有 Evidence 入口. KU without an evidence_lookup
    entry is rendered with a "missing-evidence" flag (NOT silently dropped).
    """
    if not knowledge_units:
        return "(no knowledge units)"
    lines: list[str] = []
    for ku in knowledge_units:
        ku_id = str(_get(ku, "id", "?"))
        title = _get(ku, "title", "")
        mode = _get(ku, "knowledge_mode", "unknown")
        ev = evidence_lookup.get(ku_id)
        if ev is None:
            # spec §A7 Gate: not silently dropped — flag the missing entry.
            lines.append(
                f"- {ku_id} ({mode}): {title} — [evidence: missing-evidence]"
            )
            continue
        doc_id = _get(ev, "document_id", "?")
        blk_id = _get(ev, "block_id", "?")
        lines.append(
            f"- {ku_id} ({mode}): {title} — [evidence: doc={doc_id} block={blk_id}]"
        )
    return "\n".join(lines)


def _render_conflicts(knowledge_units, topic_scope, conflicts, evidence_lookup) -> str:
    """Render each Conflict as its own row (no silent merge).

    spec §A7 Gate — 不同观点不被静默合并. Three lines per Conflict:
    perspective / actual / conditional.
    """
    if not conflicts:
        return "(no conflicts)"
    blocks: list[str] = []
    for cf in conflicts:
        cf_id = _get(cf, "id", "?")
        perspective = _get(cf, "perspective", "")
        actual = _get(cf, "actual", "")
        conditional = _get(cf, "conditional", "")
        blocks.append(
            f"## Conflict {cf_id}\n"
            f"- perspective: {perspective}\n"
            f"- actual: {actual}\n"
            f"- conditional: {conditional}"
        )
    return "\n\n".join(blocks)


def _render_evidence_refs(knowledge_units, topic_scope, conflicts, evidence_lookup) -> str:
    """Flat evidence entry list (document_id + block_id per KU)."""
    if not knowledge_units:
        return "(no knowledge units)"
    lines: list[str] = []
    for ku in knowledge_units:
        ku_id = str(_get(ku, "id", "?"))
        ev = evidence_lookup.get(ku_id)
        if ev is None:
            lines.append(f"- {ku_id}: (no evidence)")
            continue
        doc_id = _get(ev, "document_id", "?")
        blk_id = _get(ev, "block_id", "?")
        eid = _get(ev, "evidence_id", "?")
        lines.append(f"- {ku_id}: evidence_id={eid} doc={doc_id} block={blk_id}")
    return "\n".join(lines)


_SECTION_RENDERERS = {
    "summary": _render_summary,
    "context_filters": _render_context_filters,
    "temporal_status": _render_temporal_status,
    "knowledge_units": _render_knowledge_units,
    "conflicts": _render_conflicts,
    "evidence_refs": _render_evidence_refs,
}


class WikiTemplateCompiler:
    """Compile a ``WikiView`` by walking the template's sections in order.

    Same topic_scope + same publication_version + same KU/Conflict/Evidence
    inputs always produce the same ``rendered_hash`` (B-3.5 rebuild
    idempotent contract).
    """

    def __init__(self, template: WikiTemplate | None = None) -> None:
        self.template: WikiTemplate = template or WikiTemplate()

    def compile(
        self,
        topic_scope: dict,
        knowledge_units: list,
        conflicts: list,
        evidence_lookup: dict,
        publication_version: int,
        query_time: int | None = None,
    ) -> WikiView:
        """Render the WikiView by walking ``self.template.sections``.

        Args:
            topic_scope: {"concept_ids": [...], "context_filters": {...}}.
            knowledge_units: list of KnowledgeObject-shaped items (duck-typed).
            conflicts: list of Conflict-shaped items (duck-typed).
            evidence_lookup: dict mapping KU id → Evidence-shaped item.
            publication_version: B-4 watermark — must equal Core.
            query_time: unix-ms. ``None`` means "now".

        Returns:
            WikiView with sections_content + rendered_hash populated.
        """
        # 1. compute generated_at
        if query_time is None:
            query_time = int(time.time() * 1000)

        # 2. build per-section content in template order
        sections_content: dict[str, str] = {}
        for section in self.template.sections:
            renderer = _SECTION_RENDERERS.get(section)
            if renderer is None:
                # Unknown section — render a placeholder rather than crash.
                sections_content[section] = f"(unsupported section: {section})"
                continue
            sections_content[section] = renderer(
                knowledge_units, topic_scope, conflicts, evidence_lookup,
            )

        # 3. knowledge_unit_ids in input order (deterministic)
        ku_ids = tuple(str(_get(ku, "id", "")) for ku in knowledge_units)

        # 4. rendered_hash: deterministic over inputs + content
        rendered_hash = compute_rendered_hash(
            knowledge_unit_ids=ku_ids,
            sections=self.template.sections,
            sections_content=sections_content,
            publication_version=publication_version,
        )

        # 5. view id: deterministic from topic_scope + publication_version
        view_id = self._make_view_id(topic_scope, publication_version)

        return WikiView(
            id=view_id,
            topic_scope=dict(topic_scope) if isinstance(topic_scope, dict) else {},
            publication_version=publication_version,
            knowledge_unit_ids=ku_ids,
            rendered_hash=rendered_hash,
            generated_at=int(query_time),
            sections_content=sections_content,
        )

    @staticmethod
    def _make_view_id(topic_scope: dict, publication_version: int) -> str:
        """Deterministic view id from topic_scope + publication_version."""
        import hashlib
        import json

        payload = {
            "topic_scope": topic_scope,
            "publication_version": publication_version,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return f"wiki-view-{digest}"


@dataclass
class RebuildReport:
    """Result of ``rebuild_wiki_view`` — staging-first rebuild report.

    Task 6 frozen interface. The staging-first contract means:

    *   All views are compiled in memory first.
    *   Only after every view compiles successfully do we start writing
        to disk via the existing ``write_page``.
    *   On any compile failure: no pages are written.
    *   On any write failure: subsequent writes are skipped (already
        written pages remain — Wiki is the source of truth; the caller
        decides whether to roll back / clean up). The failing page id
        appears in ``failed_ids`` and pages after it appear in
        ``skipped_ids``.

    Attributes:
        passed:            True iff every input view compiled AND every
                           page was written successfully.
        page_ids:          Pages successfully written (in input order).
        failed_ids:        Page ids that failed to compile OR write.
        skipped_ids:       Page ids skipped because an earlier input
                           failed (write order halted).
        reason_codes:      Empty tuple on success; otherwise contains one
                           of ``compile_failed``, ``write_failed``.
    """

    passed: bool
    page_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def _compile_one(
    compiler: "WikiTemplateCompiler",
    view_input: dict,
) -> tuple[Any, Any, str | None]:
    """Compile one view input. Returns (page, view, failure_code).

    A view_input is a dict carrying:
        page:               WikiPage-shaped object (must expose .id, .title, .body)
        topic_scope:        {"concept_ids": [...], "context_filters": {...}}
        publication_version: int
        knowledge_units:    list of duck-typed KU items
        conflicts:          list of duck-typed Conflict items
        evidence_lookup:    dict[ku_id] -> Evidence-shaped

    Failure conditions (compile-only, no I/O):
        * missing/empty knowledge_units → ("compile_failed", "empty_top_k")
        * missing/empty evidence_lookup → ("compile_failed", "empty_evidence")
    """
    page = view_input.get("page")
    knowledge_units = view_input.get("knowledge_units", [])
    evidence_lookup = view_input.get("evidence_lookup", {})
    if not knowledge_units:
        return page, None, "empty_top_k"
    if not evidence_lookup:
        return page, None, "empty_evidence"
    try:
        view = compiler.compile(
            topic_scope=view_input.get("topic_scope", {}),
            knowledge_units=knowledge_units,
            conflicts=view_input.get("conflicts", []),
            evidence_lookup=evidence_lookup,
            publication_version=view_input.get("publication_version", 1),
            query_time=view_input.get("query_time"),
        )
    except Exception as e:  # noqa: BLE001 — compiler may raise on bad input
        _logger.warning("rebuild_wiki_view: compile failed for %s: %s",
                        getattr(page, "id", None), e)
        return page, None, f"compile_exception:{type(e).__name__}"
    return page, view, None


def rebuild_wiki_view(
    paths: Any,
    view_inputs: list[dict],
    *,
    template: WikiTemplate | None = None,
) -> RebuildReport:
    """Staging-first rebuild of Wiki pages from compiled views.

    Task 6 §Step 3: compile every input view in memory first; if any
    compile fails, abort with ``compile_failed`` in ``reason_codes``
    and do NOT call ``write_page`` (so existing wiki content is left
    untouched). If every compile succeeds, write pages in input order
    via the existing ``src.wiki.storage.page_writer.write_page``;
    a mid-batch write failure stops subsequent writes (those pages
    appear in ``skipped_ids``).

    Reuses the existing wiki writer (``write_page``) — no second
    writer / no global publication waterline. Wiki stays the source
    of truth; the rebuild path only publishes compiled views that
    have already passed the compile-time evidence gate.
    """
    from src.wiki.storage.page_writer import write_page

    compiler = WikiTemplateCompiler(template=template)

    # Stage 1: compile every input in memory.
    compiled: list[tuple[Any, Any, str | None]] = []
    for vi in view_inputs:
        compiled.append(_compile_one(compiler, vi))

    page_ids: list[str] = []
    failed_ids: list[str] = []
    reason_codes: list[str] = []
    if any(failure is not None for _, _, failure in compiled):
        reason_codes.append("compile_failed")
        for page, _view, failure in compiled:
            if failure is not None:
                failed_ids.append(getattr(page, "id", "<missing_id>") or "<missing_id>")
        return RebuildReport(
            passed=False,
            page_ids=[],
            failed_ids=failed_ids,
            skipped_ids=[],
            reason_codes=tuple(reason_codes),
        )

    # Stage 2: write each page in order. A failure halts subsequent writes.
    skipped: list[str] = []
    halted = False
    for page, view, _failure in compiled:
        if halted:
            skipped.append(getattr(page, "id", "<missing_id>") or "<missing_id>")
            continue
        try:
            write_page(paths, page)
        except Exception as e:  # noqa: BLE001 — surface writer failures
            _logger.warning(
                "rebuild_wiki_view: write_page failed for %s: %s",
                getattr(page, "id", None), e,
            )
            failed_ids.append(getattr(page, "id", "<missing_id>") or "<missing_id>")
            halted = True
            continue
        page_ids.append(getattr(page, "id", "<missing_id>") or "<missing_id>")

    if halted:
        reason_codes.append("write_failed")

    return RebuildReport(
        passed=not halted,
        page_ids=page_ids,
        failed_ids=failed_ids,
        skipped_ids=skipped,
        reason_codes=tuple(reason_codes),
    )


__all__ = ["WikiTemplateCompiler", "RebuildReport", "rebuild_wiki_view"]
