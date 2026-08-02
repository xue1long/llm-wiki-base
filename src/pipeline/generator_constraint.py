"""Generator role constraint — enforce render-only separation.

The Generator's job is to render the Markdown body via LLM.  Frontmatter
fields (id, title, type, grade, confidence-derived grade, provenance,
etc.) MUST be copied from the input KnowledgeObject — NOT invented,
modified, or embellished by the Generator.

``GeneratorOutputValidator`` compares the input KnowledgeObject against
the output WikiPage and returns a list of violation messages.  An empty
list means the output is consistent with the input.
"""
from __future__ import annotations

from dataclasses import fields as dc_fields

from ..wiki.core.types import PageType, WikiPage
from ..knowledge.core.object import KnowledgeObject, KnowledgeType


# ---------------------------------------------------------------------------
# KnowledgeType → PageType mapping
# ---------------------------------------------------------------------------

KO_TYPE_TO_PAGE_TYPE: dict[KnowledgeType, PageType] = {
    KnowledgeType.DOCUMENT:    PageType.SOURCE,
    KnowledgeType.ENTITY:      PageType.ENTITY,
    KnowledgeType.CONCEPT:     PageType.CONCEPT,
    KnowledgeType.CLAIM:       PageType.CLAIM,
    KnowledgeType.DECISION:    PageType.DECISION,
    KnowledgeType.PROCEDURE:   PageType.PROCEDURE,
    KnowledgeType.EVENT:       PageType.EVENT,
    KnowledgeType.SYNTHESIS:   PageType.SYNTHESIS,
}


class GeneratorOutputValidator:
    """Validate that Generator output (WikiPage) frontmatter matches input
    KnowledgeObject.

    The Generator's role is **render-only**: it renders the body via LLM,
    but frontmatter fields MUST come from the KnowledgeObject.
    This validator catches LLM hallucination in frontmatter.

    Usage::

        errors = GeneratorOutputValidator.validate(knowledge_object, wiki_page)
        if errors:
            raise ValueError(f"Generator output validation failed: {errors}")
    """

    # ------------------------------------------------------------------
    # Field checks: each entry is (wp_field_name, comparison_fn, label)
    # comparison_fn(ko, wp) -> str | None  (error message)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_id(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        if ko.id != wp.id:
            return (
                f"id mismatch: KnowledgeObject.id={ko.id!r}, "
                f"WikiPage.id={wp.id!r}"
            )
        return None

    @staticmethod
    def _check_title(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        if ko.title != wp.title:
            return (
                f"title mismatch: KnowledgeObject.title={ko.title!r}, "
                f"WikiPage.title={wp.title!r}"
            )
        return None

    @staticmethod
    def _check_type(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        expected_pt = KO_TYPE_TO_PAGE_TYPE.get(ko.type)
        if expected_pt is None:
            return f"unknown KnowledgeType: {ko.type!r}"
        if wp.type != expected_pt:
            return (
                f"type mismatch: expected PageType.{expected_pt.value} "
                f"(from KnowledgeType.{ko.type.value}), "
                f"got PageType.{wp.type.value}"
            )
        return None

    @staticmethod
    def _check_grade(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        if ko.grade != wp.grade:
            return (
                f"grade modified: KnowledgeObject.grade={ko.grade!r}, "
                f"WikiPage.grade={wp.grade!r}"
            )
        return None

    @staticmethod
    def _check_heat(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        if ko.heat != wp.heat:
            return (
                f"heat modified: KnowledgeObject.heat={ko.heat}, "
                f"WikiPage.heat={wp.heat}"
            )
        return None

    @staticmethod
    def _check_sources(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        prov_path = ko.provenance.source_path
        if prov_path not in wp.sources:
            return (
                f"sources missing provenance.source_path: "
                f"expected {prov_path!r} in sources, "
                f"got {wp.sources!r}"
            )
        return None

    @staticmethod
    def _check_timestamps(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        errors: list[str] = []
        if ko.created_at != wp.created_at:
            errors.append(
                f"created_at mismatch: KO={ko.created_at}, WP={wp.created_at}"
            )
        if ko.updated_at != wp.updated_at:
            errors.append(
                f"updated_at mismatch: KO={ko.updated_at}, WP={wp.updated_at}"
            )
        if errors:
            return "; ".join(errors)
        return None

    @staticmethod
    def _check_immutable(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        """is_immutable should be False by default — Generator must not set it."""
        if wp.is_immutable:
            return (
                f"is_immutable should be False (default), got True — "
                f"Generator must not set the immutable flag"
            )
        return None

    @staticmethod
    def _check_relations(ko: KnowledgeObject, wp: WikiPage) -> str | None:
        """Relations target_ids should match (non-strict: count check only).

        A full structural comparison would require deserializing KnowledgeObject
        relations (which are stored as plain dicts).  We check cardinality for
        now — if the counts differ, something was added or dropped.
        """
        ko_rel_count = len(ko.relations) if ko.relations else 0
        wp_rel_count = len(wp.relations) if wp.relations else 0
        if ko_rel_count != wp_rel_count:
            return (
                f"relation count mismatch: KO has {ko_rel_count} relations, "
                f"WP has {wp_rel_count}. Generator may have added or dropped "
                f"relations."
            )
        return None

    # ------------------------------------------------------------------
    # Field check registry
    # ------------------------------------------------------------------

    _CHECKS: list[tuple[str, "staticmethod"]] = [
        ("id", _check_id),
        ("title", _check_title),
        ("type", _check_type),
        ("grade", _check_grade),
        ("heat", _check_heat),
        ("sources", _check_sources),
        ("timestamps", _check_timestamps),
        ("is_immutable", _check_immutable),
        ("relations", _check_relations),
    ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def validate(cls, ko: KnowledgeObject, wp: WikiPage) -> list[str]:
        """Validate *wp* frontmatter against *ko*.

        Returns a list of error messages (str).  An empty list means the
        output is consistent with the input KnowledgeObject — the
        Generator did not invent, modify, or embellish frontmatter.
        """
        errors: list[str] = []
        for check_name, check_fn in cls._CHECKS:
            msg = check_fn(ko, wp)
            if msg is not None:
                errors.append(f"[{check_name}] {msg}")
        return errors
