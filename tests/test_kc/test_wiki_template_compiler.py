"""Tests for WikiTemplate + WikiTemplateCompiler (路线 v2.2 §A-7 / Z-7).

Spec §12.4 R-7: Wiki 必须展示主要结论、适用上下文、时间状态、不同观点、
冲突和证据入口。Wiki 不按单篇原文生成摘要，而通过 Query + Template 编译。

6 TDD tests covering:

1. ``WikiTemplateCompiler.compile(...)`` returns a ``WikiView`` dataclass
   with the spec §12.4 schema fields populated.
2. The template is configurable: a custom ``sections`` tuple changes the
   rendered content order / presence of KU list, Conflict list, Evidence
   list, Temporal status display.
3. Same ``topic_scope`` + same ``publication_version`` rebuilt → identical
   ``rendered_hash`` (rebuild equivalence for B-3.5 delete + rebuild).
4. Different perspectives are NOT silently merged (spec §A7 Gate): each
   Conflict appears as its own row in the rendered content.
5. Every fact has an Evidence entry point: rendered content includes a
   per-knowledge-unit evidence reference row (document_id + block_id).
6. Delete + rebuild integration seam: ``WikiView`` carries enough
   ``publication_version`` + ``knowledge_unit_ids`` + ``rendered_hash``
   to support the B-3.5 "delete Wiki then rebuild from Core" contract
   (smoke test on the dataclass surface, not the persistence path).

These tests are intentionally independent of the implementation files
(``src/kc.views.wiki_template`` and ``src.kc.views.wiki_template_compiler``):
until those modules ship, every test in this file must FAIL with
``ImportError`` or ``ModuleNotFoundError``. After the modules ship,
all 6 must pass.
"""
from __future__ import annotations

import time

import pytest

# NB: src.kc.views.wiki_template + src.kc.views.wiki_template_compiler are
# the modules under test — they do not exist yet at the time these tests
# are authored, so the imports below are the red signal that kicks off
# TDD step 2.
from src.kc.views.wiki_template import WikiTemplate, WikiView
from src.kc.views.wiki_template_compiler import WikiTemplateCompiler


# ── helpers ─────────────────────────────────────────────────────────────────


def _now_ms() -> int:
    """Return the current Unix time in milliseconds."""
    return int(time.time() * 1000)


def make_knowledge_unit(
    ku_id: str = "ku-001",
    *,
    title: str = "Foundational claim",
    claim: str = "All non-trivial knowledge units carry evidence.",
    knowledge_mode: str = "observed",
    context_filters: dict | None = None,
    temporal_status: str = "current",
    evidence_refs: tuple[dict, ...] = (),
) -> dict:
    """Build a minimal KnowledgeObject-shaped dict for compiler tests.

    We use a dict (not a real dataclass) to keep the test surface small
    and to decouple from C-1 / C-4 dataclass evolution. The compiler is
    expected to read ``.id`` / ``.title`` / ``.claim`` / ``.knowledge_mode``
    / ``.context_filters`` / ``.temporal_status`` / ``.evidence_refs`` —
    duck-typed, so dict works as well as a dataclass.
    """
    return {
        "id": ku_id,
        "title": title,
        "claim": claim,
        "knowledge_mode": knowledge_mode,
        "context_filters": context_filters or {"domain": "spec", "platform": "core"},
        "temporal_status": temporal_status,
        "evidence_refs": list(evidence_refs),
    }


def make_conflict(
    cid: str = "cf-001",
    *,
    perspective: str = "Implementation A says X.",
    actual: str = "Implementation B says Y.",
    conditional: str = "If context = real-time, choose B.",
    ku_ids: tuple[str, ...] = (),
) -> dict:
    """Build a minimal Conflict-shaped dict."""
    return {
        "id": cid,
        "perspective": perspective,
        "actual": actual,
        "conditional": conditional,
        "ku_ids": list(ku_ids),
    }


def make_evidence(
    eid: str = "ev-001",
    *,
    document_id: str = "doc-001",
    block_id: str = "blk-001",
) -> dict:
    """Build a minimal Evidence-shaped dict (matches src.kc.contracts.evidence.Evidence)."""
    return {
        "evidence_id": eid,
        "document_id": document_id,
        "block_id": block_id,
        "quote": "evidence quote",
        "quote_hash": "h-" + eid,
    }


# ── test 1: compile(...) returns a WikiView with spec §12.4 schema ─────────


def test_compile_returns_wiki_view_with_spec_schema() -> None:
    """``compile`` returns a ``WikiView`` with the 6 spec §12.4 fields.

    Validates id / topic_scope / publication_version / knowledge_unit_ids /
    rendered_hash / generated_at are all populated.
    """
    compiler = WikiTemplateCompiler()
    topic = {"concept_ids": ["concept-A"], "context_filters": {"domain": "spec"}}
    kus = [make_knowledge_unit("ku-001"), make_knowledge_unit("ku-002")]
    conflicts: list = []
    evidence = {"ku-001": make_evidence("ev-001")}

    view = compiler.compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=7,
        query_time=_now_ms(),
    )

    assert isinstance(view, WikiView)
    assert isinstance(view.id, str) and view.id
    assert view.topic_scope == topic
    assert view.publication_version == 7
    assert view.knowledge_unit_ids == ("ku-001", "ku-002")
    assert isinstance(view.rendered_hash, str) and len(view.rendered_hash) >= 16
    assert isinstance(view.generated_at, int) and view.generated_at > 0


# ── test 2: template configurable (sections / KU / Conflict / Evidence / Temporal)


def test_template_is_configurable() -> None:
    """Custom WikiTemplate.sections controls rendered content shape.

    A minimal template (``("summary", "knowledge_units")``) must still
    surface the KU list, and a richer template with all 6 sections must
    surface the temporal status display, the conflict list, and the
    evidence list. The rendered content is exposed via a ``sections_content``
    dict on the WikiView so tests can assert structural presence.
    """
    topic = {"concept_ids": ["c"], "context_filters": {}}
    kus = [make_knowledge_unit("ku-001", temporal_status="historical")]
    conflicts = [make_conflict("cf-001")]
    evidence = {"ku-001": make_evidence("ev-001")}

    # 2a. minimal template — only summary + knowledge_units
    minimal_view = WikiTemplateCompiler(
        template=WikiTemplate(template_id="minimal_v1", sections=("summary", "knowledge_units")),
    ).compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=1,
        query_time=_now_ms(),
    )
    minimal_sections = dict(minimal_view.sections_content)
    assert "summary" in minimal_sections
    assert "knowledge_units" in minimal_sections
    # Conflict + temporal_status + evidence_refs NOT in minimal template
    assert "conflicts" not in minimal_sections
    assert "temporal_status" not in minimal_sections
    assert "evidence_refs" not in minimal_sections

    # 2b. full default template — all 6 sections
    full_view = WikiTemplateCompiler().compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=1,
        query_time=_now_ms(),
    )
    full_sections = dict(full_view.sections_content)
    assert set(full_sections.keys()) >= {
        "summary",
        "context_filters",
        "temporal_status",
        "knowledge_units",
        "conflicts",
        "evidence_refs",
    }
    # Temporal status display surfaces the KU's temporal_status
    assert "historical" in str(full_sections["temporal_status"])
    # Conflict list surfaces the perspective/actual/conditional rows
    assert "Implementation A says X." in str(full_sections["conflicts"])


# ── test 3: rebuild equivalence (same topic + pub_v → same rendered_hash) ──


def test_rebuild_equivalence_same_topic_and_version_yields_same_hash() -> None:
    """Same inputs → same ``rendered_hash`` (B-3.5 delete+rebuild contract).

    The compiler must be deterministic: rebuilding the same WikiView from
    the same Core inputs yields byte-identical rendered content, so the
    delete-Wiki-then-rebuild-from-Core path is idempotent.
    """
    topic = {"concept_ids": ["c"], "context_filters": {"domain": "spec"}}
    kus = [make_knowledge_unit("ku-001"), make_knowledge_unit("ku-002", title="Second")]
    conflicts = [make_conflict("cf-001")]
    evidence = {
        "ku-001": make_evidence("ev-001"),
        "ku-002": make_evidence("ev-002", document_id="doc-002"),
    }
    t = _now_ms()

    compiler = WikiTemplateCompiler()
    v1 = compiler.compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=11,
        query_time=t,
    )
    v2 = compiler.compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=11,
        query_time=t,
    )

    assert v1.rendered_hash == v2.rendered_hash
    # Different publication_version → different hash
    v3 = compiler.compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=12,
        query_time=t,
    )
    assert v3.rendered_hash != v1.rendered_hash


# ── test 4: different perspectives NOT silently merged (spec §A7 Gate) ─────


def test_different_perspectives_not_silently_merged() -> None:
    """Each Conflict surfaces its own perspective/actual/conditional row.

    spec §A7 Gate: 不被静默合并 — when multiple Conflicts exist on the
    same topic, the rendered content must list each Conflict as a
    distinct row, preserving perspective + actual + conditional. A naive
    "merge into one summary" implementation must NOT collapse them.
    """
    topic = {"concept_ids": ["c"], "context_filters": {}}
    kus = [make_knowledge_unit("ku-001")]
    conflicts = [
        make_conflict(
            "cf-001",
            perspective="Source A says X.",
            actual="Production data shows Y.",
            conditional="If domain=finance, prefer Y.",
            ku_ids=("ku-001",),
        ),
        make_conflict(
            "cf-002",
            perspective="Source B says Z.",
            actual="Lab data shows W.",
            conditional="If platform=desktop, prefer W.",
            ku_ids=("ku-001",),
        ),
    ]
    evidence = {"ku-001": make_evidence("ev-001")}

    view = WikiTemplateCompiler().compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=1,
        query_time=_now_ms(),
    )

    rendered_conflicts = str(view.sections_content["conflicts"])
    # Both perspectives present (no silent merge)
    assert "Source A says X." in rendered_conflicts
    assert "Source B says Z." in rendered_conflicts
    # Both actual rows present
    assert "Production data shows Y." in rendered_conflicts
    assert "Lab data shows W." in rendered_conflicts
    # Both conditionals present
    assert "domain=finance" in rendered_conflicts
    assert "platform=desktop" in rendered_conflicts


# ── test 5: every fact has an Evidence entry point ─────────────────────────


def test_every_fact_has_evidence_entry_point() -> None:
    """Each knowledge unit surfaces an evidence_refs row (document_id + block_id).

    spec §A7 Gate: 每个事实都有 Evidence 入口. The rendered knowledge_units
    section must include the document_id + block_id pair for every KU
    that has an evidence_lookup entry.
    """
    topic = {"concept_ids": ["c"], "context_filters": {}}
    kus = [
        make_knowledge_unit("ku-001"),
        make_knowledge_unit("ku-002", title="Second claim"),
        make_knowledge_unit("ku-003", title="Unsupported claim"),
    ]
    conflicts: list = []
    evidence = {
        "ku-001": make_evidence("ev-001", document_id="doc-A", block_id="blk-1"),
        "ku-002": make_evidence("ev-002", document_id="doc-B", block_id="blk-2"),
        # ku-003 has no evidence — must be flagged as missing-entry, not
        # silently dropped (per spec §A7 Gate).
    }

    view = WikiTemplateCompiler().compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=conflicts,
        evidence_lookup=evidence,
        publication_version=1,
        query_time=_now_ms(),
    )

    rendered_ku_section = str(view.sections_content["knowledge_units"])
    # Each KU with evidence appears with its document_id + block_id.
    assert "ku-001" in rendered_ku_section
    assert "doc-A" in rendered_ku_section
    assert "blk-1" in rendered_ku_section
    assert "ku-002" in rendered_ku_section
    assert "doc-B" in rendered_ku_section
    assert "blk-2" in rendered_ku_section
    # KU without evidence must surface a "missing entry" flag, NOT be
    # silently dropped from the view (still listed but flagged).
    assert "ku-003" in rendered_ku_section
    assert "missing" in rendered_ku_section.lower() or "no-evidence" in rendered_ku_section.lower()


# ── test 6: WikiView carries enough state for B-3.5 delete + rebuild ────────


def test_wiki_view_carries_state_for_delete_and_rebuild() -> None:
    """WikiView exposes publication_version + knowledge_unit_ids + rendered_hash.

    B-3.5 contract: deleting a Wiki and rebuilding it from Core must be
    idempotent. The WikiView dataclass surface must therefore expose the
    three fields the rebuild path needs (publication_version parity with
    B-4, knowledge_unit_ids for provenance, rendered_hash for equivalence
    check). This is a dataclass-shape smoke test — no persistence path.
    """
    topic = {"concept_ids": ["c"], "context_filters": {}}
    kus = [make_knowledge_unit("ku-001"), make_knowledge_unit("ku-002")]
    evidence = {
        "ku-001": make_evidence("ev-001"),
        "ku-002": make_evidence("ev-002"),
    }

    view = WikiTemplateCompiler().compile(
        topic_scope=topic,
        knowledge_units=kus,
        conflicts=[],
        evidence_lookup=evidence,
        publication_version=42,
        query_time=_now_ms(),
    )

    # 1. publication_version must equal the B-4 watermark (here: 42)
    assert view.publication_version == 42
    # 2. knowledge_unit_ids must list every KU that contributed
    assert set(view.knowledge_unit_ids) == {"ku-001", "ku-002"}
    # 3. rendered_hash must be a non-empty hash string
    assert view.rendered_hash and len(view.rendered_hash) >= 16
    # 4. frozen-ness: dataclass is hashable + immutable for safe cache keys
    with pytest.raises(Exception):
        view.publication_version = 0  # type: ignore[misc]


# ── bonus: WikiTemplate default sections is the spec-mandated order ────────


def test_wiki_template_default_sections_order() -> None:
    """``WikiTemplate()`` default sections tuple is the spec §12.4 order.

    Locks the order: summary → context_filters → temporal_status →
    knowledge_units → conflicts → evidence_refs. Re-ordering the default
    is a spec break — it must be done explicitly via a custom template.
    """
    t = WikiTemplate()
    assert t.template_id == "default_v1"
    assert t.sections == (
        "summary",
        "context_filters",
        "temporal_status",
        "knowledge_units",
        "conflicts",
        "evidence_refs",
    )
