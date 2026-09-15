"""R10 (plan 2026-09-15-v3): v2 fallback — sync + heuristic implementation.

Created at Phase 1 Task 1.0 as a placeholder. The actual v2 source will
be copied in here at Phase 2 Task 2.1 (BEFORE the doc_classifier rewrite)
so that ``V7_USE_V3=false`` continues to work after the v3 rewrite of
each stage.

Why this exists:
- v3 makes destructive changes (delete heuristics, top-level async)
- If v3 misbehaves in production, ``V7_USE_V3=false`` flips back to v2
- git revert would lose all uncommitted work — feature flag is safer

Timeline:
- T1.0 (now): empty placeholder, no API surface
- T2.1 (Phase 2): copy original sync doc_classifier here, rename
  exported function to ``classify_doc_v2`` to avoid clashing with v3's
  public ``classify_doc`` (the lazy ``__getattr__`` in ``__init__.py``
  is what routes between the two)
- T2.2-T2.4: same pattern for completeness_checker / cluster_topics /
  fill_slots
"""
from __future__ import annotations
