"""ConceptPage ↔ WikiPage adapter + source stub builder.

V7 Replace Plan Stage 0 Task 3.

This module produces the ``WikiPage`` objects the V7 ingest bridge
returns to ``commit_ingest`` for disk persistence. ``commit_ingest``
already does everything else: line 1744 ``write_page`` for disk I/O,
line 1698 ``mark_intent`` for vector pending, line 1742 ``_prepare_lineage``
for lineage tracking, line 1749 ``append_to_index`` for wiki index,
and line 1703 ``rewrite_wikilinks`` for gbrain compatibility.

Bypassing ``commit_ingest`` would mean duplicating that pipeline
(we did not in this change set — that's the bridge's whole point).
"""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.lib.errors import InvalidInputError
from src.wiki.core.id_generator import normalize_id_chars
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage

from .slot_filler import ConceptPage
from .topic_clusterer import OTHER_TOPIC_ID


# Inject this at the top of the body so lint (LINT-MISSING-SECTION)
# recognises the page as concept-shaped. Same pattern used by V7's
# own WikiWriter (line 573 of wiki_writer.py).
CONCEPT_BODY_PREFIX = "<!-- wiki-template-version: 3.0.0 -->\n"

# 8-slot body section headings — must match the 8 sections in
# ``knowledge/<project>/.wiki-templates/concept.md`` so the body
# renders correctly under the existing wiki template.
CONCEPT_SECTION_HEADINGS: dict[str, str] = {
    "definition": "定义",
    "characteristics": "主要特点",
    "context": "适用场景",
    "anti_patterns": "反模式与常见错误",
    "evidence": "证据强度",
    "examples": "例子",
    "related_concepts": "相关概念",
    "references": "参考来源",
}

# Source-template body section headings — match ``.wiki-templates/source.md``.
SOURCE_SECTION_HEADINGS: dict[str, str] = {
    "source_meta": "来源元数据",
    "transcription_quality": "转录质量",
    "summary": "摘要",
    "key_points": "关键观点",
    "credibility": "可信度声明",
}


def _strip_section_suffix(source: str) -> str:
    """Strip ``#section-N`` / ``#author-N`` / ``#item-N`` suffix from a source path.

    V7's deterministic splitter appends an item ordinal suffix to each
    item id (e.g. ``raw/sources/foo.md#author-1``). These item ids
    become ``ConceptPage.sources`` via ``topic.item_ids``. But the wiki
    H1 file-existence check treats each ``source`` as a literal file
    path — the suffix makes every source "not found".

    H1 expects the raw project-relative file path. We strip the
    fragment so the page survives the lint check.
    """
    idx = source.find("#")
    if idx == -1:
        return source
    return source[:idx]


def adapt_concept_page(page: ConceptPage) -> WikiPage:
    """Adapt V7's ``ConceptPage`` to the standard ``WikiPage`` for write.

    Body format: 8 ``## {zh_heading}\\n{slot_body}`` sections, prefixed
    with the wiki-template-version comment. Sections appear in the
    canonical order (definition first, references last) regardless of
    which slots the LLM filled in. Empty slots render an empty body —
    the section heading stays so the lint rule recognises the shape.

    Frontmatter: standard V6 fields populated. ``_ko_extra.slot_evidence``
    preserves the V7 evidence trail (item_id / source_text_excerpt /
    has_evidence / needs_review per slot) so downstream readers can
    audit the LLM's citations.

    Rejects ``OTHER_TOPIC_ID`` sentinel — the bridge must filter those
    upstream, but this is a defence-in-depth check so callers can't
    accidentally write a ``__other__`` placeholder page.
    """
    if page.topic_id == OTHER_TOPIC_ID or page.id.startswith("__other__"):
        raise InvalidInputError(
            f"refusing to adapt ConceptPage with sentinel topic id: "
            f"id={page.id!r} topic_id={page.topic_id!r}"
        )

    # Build body in canonical slot order so the 8 sections always
    # appear in the same order regardless of dict insertion order.
    body_sections: list[str] = []
    for slot_name, zh_heading in CONCEPT_SECTION_HEADINGS.items():
        body_sections.append(f"## {zh_heading}\n\n{page.slots.get(slot_name, '')}")
    body = CONCEPT_BODY_PREFIX + "\n\n".join(body_sections)

    # Move slot_evidence into _ko_extra for downstream readers.
    ko_extra: dict = {}
    if page.slot_evidence:
        ko_extra["slot_evidence"] = {
            slot_name: slot.to_dict()
            for slot_name, slot in page.slot_evidence.items()
        }

    # Strip item-ordinal suffixes (e.g. "#author-1", "#section-2")
    # from sources so the H1 file-existence check resolves the actual
    # file path. The original item ids stay in
    # _ko_extra.slot_evidence for audit.
    cleaned_sources = [_strip_section_suffix(s) for s in page.sources]

    # Set created_at/updated_at so the frontmatter has real timestamps
    # (WikiPage.to_frontmatter_dict → _to_iso_dt maps int 0 to None,
    # which YAML writes as empty string — cosmetically ugly).
    now = datetime.now(timezone.utc)

    return WikiPage(
        id=page.id,
        title=page.title,
        type=PageType.CONCEPT,
        sources=cleaned_sources,
        body=body,
        processing_depth="concept",
        # V7-written pages inherit V7 metadata; commit_ingest writes
        # them with to_frontmatter_dict (V6 schema) but the V7 origin
        # is preserved in _ko_extra for audit.
        _ko_extra=ko_extra,
    )


def build_source_stub_page(
    source_path: Path,
    source_text: str,
    task_id: str,
    *,
    paths: WikiPaths,
    concept_page_ids: Iterable[str] | None = None,
) -> WikiPage:
    """Build the source-page WikiPage stub for commit_ingest.

    Body format: 5 ``## {zh_heading}`` sections matching
    ``.wiki-templates/source.md`` (来源元数据 / 转录质量 / 摘要 /
    关键观点 / 可信度声明). The 5 sections are emitted regardless
    of V7 stage output — most fields are stub values; the 关键观点
    section lists links to ``concept_page_ids`` if provided.

    Frontmatter: standard V6 fields. ``id`` follows the existing
    ingest convention: ``<stem>-<8-char-path-hash>``. The path inside
    ``sources`` is project-relative (relative to ``paths.root``).

    This is a stub — V7's pipeline does not run a Stage 5 / Stage 6
    for the source document itself (only for the topic it produces).
    The operator can later edit the 摘要 / 转录质量 fields
    manually, or run a future Stage 7/8 source-summary pipeline.
    """
    concept_ids: list[str] = list(concept_page_ids or [])

    # ID + path hash — same convention as the candidate path
    # (ingest.py:485-488 ``_write_rejected_source_page``).
    src_str = str(source_path)
    raw_stem = Path(src_str).stem if Path(src_str).stem else src_str
    norm_stem = normalize_id_chars(unicodedata.normalize("NFC", raw_stem))
    path_hash = hashlib.md5(src_str.encode("utf-8")).hexdigest()[:8]
    page_id = f"{norm_stem}-{path_hash}" if norm_stem else f"kb-{task_id}"

    # Project-relative path for the sources[] field.
    try:
        rel_source = str(source_path.relative_to(paths.root)).replace("\\", "/")
    except ValueError:
        # source_path is outside the project root — fall back to absolute
        rel_source = src_str

    # Build the 5-section body. Stub values for most fields; the
    # 关键观点 section lists the produced concept pages (so the source
    # page is reachable from each concept via wikilink + back-relation).
    metadata_lines = [
        f"- 路径: `{rel_source}`",
    ]
    if task_id:
        metadata_lines.append(f"- 摄取时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        metadata_lines.append(f"- 任务 ID: `{task_id}`")

    key_points_lines = (
        "\n".join(f"- → [[concepts/{cid}]]" for cid in concept_ids)
        if concept_ids
        else ""
    )

    body_parts: list[str] = [CONCEPT_BODY_PREFIX.rstrip("\n")]
    body_parts.append(f"## {SOURCE_SECTION_HEADINGS['source_meta']}\n\n" + "\n".join(metadata_lines))
    body_parts.append(f"## {SOURCE_SECTION_HEADINGS['transcription_quality']}\n\n人工整理")
    body_parts.append(f"## {SOURCE_SECTION_HEADINGS['summary']}\n\n(无摘要)")
    if key_points_lines:
        body_parts.append(f"## {SOURCE_SECTION_HEADINGS['key_points']}\n\n{key_points_lines}")
    else:
        body_parts.append(f"## {SOURCE_SECTION_HEADINGS['key_points']}")
    body_parts.append(f"## {SOURCE_SECTION_HEADINGS['credibility']}\n\n未标注来源类型（默认按普通素材）")
    body = "\n\n".join(body_parts)

    # Build relations — every concept page gets a `references` edge
    # back to the source.
    from src.wiki.features.relations import Relation
    relations: list[Relation] = []
    for cid in concept_ids:
        relations.append(Relation(
            target_id=cid,
            type="references",
            weight=1.0,
            context="引用原始教程来源",
        ))

    # Set created_at/updated_at so the frontmatter has real timestamps
    # (WikiPage.to_frontmatter_dict → _to_iso_dt maps int 0 to None,
    # which YAML writes as empty string — cosmetically ugly and breaks
    # ordering by recency in the wiki index).
    now = datetime.now(timezone.utc)

    return WikiPage(
        id=page_id,
        title=raw_stem or page_id,
        type=PageType.SOURCE,
        sources=[rel_source],
        body=body,
        created_at=now,
        updated_at=now,
        processing_depth="source",
        relations=relations,
    )


__all__ = [
    "CONCEPT_BODY_PREFIX",
    "CONCEPT_SECTION_HEADINGS",
    "SOURCE_SECTION_HEADINGS",
    "_strip_section_suffix",
    "adapt_concept_page",
    "build_source_stub_page",
]
