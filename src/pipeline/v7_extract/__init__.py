"""V7.1.1 extract pipeline (RFC v6, plan 2026-09-13).

This subpackage implements the 7-stage extraction pipeline for raw source
files. It is intentionally separate from the existing
``src.pipeline.stages`` (Collector / Analyzer / Generator) so the legacy
pipeline keeps running unchanged while V7 extract evolves.

R10 (plan 2026-09-15-v3): feature-flag based rollout.

    - USE_V3_PIPELINE=true (default):  use the async + LLM-only v3 implementation
                                       (Phase 2 deliverables).
    - USE_V3_PIPELINE=false:           fall back to the legacy v2 implementation
                                       (sync, heuristic-or-LLM) kept in
                                       ``_legacy.py`` for emergency rollback.

Stages (v3 names):
  1. doc_classifier          → classify_doc(content) -> Classification
  2. structure_recognizer    → extract_structure(content, doc_type) -> Structure
  3. completeness_checker    → check_completeness(content, doc_type) -> (bool, str)
  4. topic_clusterer         → cluster_topics(items) -> list[Topic]
  5. slot_filler             → fill_slots(topic, template) -> ConceptPage
  6. relation_extractor      → extract_relations(pages) -> Relations
  7. wiki_writer             → commit_and_index(pages, relations)

All LLM calls go through LLMClient (this file) so the pipeline can be
unit-tested with a fake LLM (M9-V5 fix).
"""
from __future__ import annotations

import os


# R10: feature flag controlling v3 vs v2 implementation
USE_V3_PIPELINE: bool = os.environ.get("V7_USE_V3", "true").lower() == "true"


def __getattr__(name: str):
    """PEP 562 — lazy attribute access for the v3 / v2 toggle.

    Importing the heavy ``doc_classifier`` / ``completeness_checker`` /
    ``topic_clusterer`` / ``slot_filler`` modules at package import time
    breaks callers that only need, e.g., ``wiki_writer`` or the prompts
    sub-package. Defer the choice until first access.

    Mapping (R10):
        classify_doc         → doc_classifier.classify_doc
        check_completeness   → completeness_checker.check_completeness
        cluster_topics       → topic_clusterer.cluster_topics
        fill_slots           → slot_filler.fill_slots

    v2 fallback files live in ``_legacy_*.py`` (created at Phase 1
    T1.0 from the original v2 sources). When USE_V3_PIPELINE=false
    those legacy modules are imported instead.
    """
    name_to_module = {
        "classify_doc": "doc_classifier",
        "check_completeness": "completeness_checker",
        "cluster_topics": "topic_clusterer",
        "fill_slots": "slot_filler",
    }
    if name in name_to_module:
        module_name = name_to_module[name]
        if USE_V3_PIPELINE:
            try:
                module = __import__(f"src.pipeline.v7_extract.{module_name}", fromlist=[name])
                return getattr(module, name)
            except (ImportError, AttributeError) as e:
                raise RuntimeError(
                    f"v3 implementation of {name!r} is not yet available "
                    f"(Phase 2 not completed). Set V7_USE_V3=false to use v2. "
                    f"Underlying error: {e!r}"
                ) from e
        # v2 fallback
        legacy_module = __import__(
            f"src.pipeline.v7_extract._legacy_{module_name}", fromlist=[name]
        )
        return getattr(legacy_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "USE_V3_PIPELINE",
    "classify_doc",
    "check_completeness",
    "cluster_topics",
    "fill_slots",
]
