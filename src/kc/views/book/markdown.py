"""Pure Markdown rendering for compiled Book chapters."""
from __future__ import annotations

import hashlib
from typing import Any

from .compiler import ChapterRender
from .contract import KnowledgeBlockType
from .template import BookTemplate, BookView, compute_book_rendered_hash


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _header(r):
    c = _get(r, "chapter")
    return f"# {_get(c, 'title', '')}\nstable_key: {_get(c, 'stable_key', '')}\npublication_version: {_get(r, 'publication_version', 0)}"


def _context(r):
    report = _get(r, "integrity_report")
    lines = [f"context_id: {_get(report, 'context_id', 'unknown')}" ]
    validity = _get(report, "validity_id")
    if validity is not None:
        lines.append(f"validity_id: {validity}")
    return "\n".join(lines)


def _temporal_status(r):
    return str(_get(_get(r, "integrity_report"), "temporal_status", "unknown"))


def _knowledge_blocks(r):
    blocks = _get(r, "blocks", ())
    if not blocks:
        return "(no knowledge blocks)"
    out = []
    for item in blocks:
        block = _get(item, "knowledge_block")
        refs = _get(item, "evidence_refs", ())
        out.append(f"## Block {_get(block, 'id', '')}\n- mode: {_get(block, 'knowledge_mode', '')}\n- block_type: {_get(_get(block, 'block_type'), 'value', _get(block, 'block_type', ''))}\n- evidence: {len(refs)} refs")
        out.extend(f"[evidence: {_get(ref, 'evidence_id', '')}]" for ref in refs)
    return "\n".join(out)


def _conflicts(r):
    items = [item for item in _get(r, "blocks", ()) if _get(_get(item, "knowledge_block"), "block_type") in (KnowledgeBlockType.CONFLICT, "conflict")]
    if items:
        return "\n\n".join(f"## Conflict {_get(_get(item, 'knowledge_block'), 'id', '')}\n- statements: {', '.join(_get(ref, 'object_id', '') for ref in _get(_get(item, 'knowledge_block'), 'statement_refs', ())) }\n- evidence: {', '.join(_get(ref, 'evidence_id', '') for ref in _get(item, 'evidence_refs', ())) }" for item in items)
    fallback = _get(r, "conflicts") or ()
    if fallback:
        return "\n\n".join(f"- perspective: {_get(item, 'perspective', '')}\n- actual: {_get(item, 'actual', '')}\n- conditional: {_get(item, 'conditional', '')}" for item in fallback)
    return "(no conflicts)"


def _evidence_chain(r):
    return "\n".join(f"- {_get(ref, 'evidence_id', '')}: [{_get(ref, 'evidence_type', '')}/{_get(ref, 'strength', '')}] doc={_get(ref, 'document_id', '')} block={_get(ref, 'block_id', '')}" for item in _get(r, "blocks", ()) for ref in _get(item, "evidence_refs", ())) or "(no evidence)"


def _footer(r, rendered_hash):
    return f"generated_at: {_get(r, 'rendered_at', 0)}\nrendered_hash: {rendered_hash}"


_BOOK_SECTION_RENDERERS = {
    "header": _header, "context": _context, "temporal_status": _temporal_status,
    "knowledge_blocks": _knowledge_blocks, "conflicts": _conflicts,
    "evidence_chain": _evidence_chain,
}


def render_chapter(render: ChapterRender, *, template: BookTemplate | None = None) -> BookView:
    template = template or BookTemplate()
    chapter = _get(render, "chapter")
    blocks = _get(render, "blocks", ())
    ku_ids = tuple(_get(_get(item, "knowledge_block"), "knowledge_unit_ids", [""])[0] for item in blocks)
    evidence_refs = tuple((_get(ref, "evidence_id", ""), _get(ref, "strength", "")) for item in blocks for ref in _get(item, "evidence_refs", ()))
    provisional = {section: (template.custom_renderers[section](render) if section in template.custom_renderers else _BOOK_SECTION_RENDERERS.get(section, lambda _: f"(unsupported section: {section})")(render)) for section in template.sections}
    publication_version = _get(render, "publication_version", 0)
    view_id = "book-view-" + hashlib.sha256(f"{_get(chapter, 'id', '')}:{publication_version}".encode()).hexdigest()[:16]
    rendered_hash = compute_book_rendered_hash(book_id=_get(chapter, "book_id", ""), chapter_id=_get(chapter, "id", ""), knowledge_unit_ids=ku_ids, sections=template.sections, sections_content=provisional, publication_version=publication_version, evidence_refs=evidence_refs)
    provisional["footer"] = _footer(render, rendered_hash) if "footer" in provisional and "footer" not in template.custom_renderers else provisional.get("footer", "")
    return BookView(view_id, _get(chapter, "id", ""), ku_ids, publication_version, rendered_hash, _get(render, "rendered_at", 0), template.sections, provisional)


def render_chapter_from_dict(render_dict: dict, *, template: BookTemplate | None = None) -> BookView:
    return render_chapter(ChapterRender(**render_dict), template=template)
