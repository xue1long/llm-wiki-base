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
"""
from __future__ import annotations

import time
from typing import Any

from .wiki_template import WikiTemplate, WikiView, compute_rendered_hash


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


__all__ = ["WikiTemplateCompiler"]
