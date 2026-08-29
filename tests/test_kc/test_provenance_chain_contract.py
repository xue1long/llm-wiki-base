from __future__ import annotations

from src.kc.integrity.gates import ProvenanceGate
from src.kc.retrieval import normalize_result
from src.knowledge.core.adapter import (
    knowledge_object_to_wiki_page,
    wiki_page_to_knowledge_object,
)
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)


def test_normalize_result_keeps_missing_provenance_explicit() -> None:
    result = normalize_result(
        {
            "id": "page-1",
            "title": "Page 1",
            "score": 0.75,
            "evidence_refs": ["doc-1:block-1"],
        }
    )

    assert result.provenance is None
    assert result.evidence_refs == ("doc-1:block-1",)
    assert result.knowledge_mode is None
    assert result.context is None
    assert result.validity is None
    assert result.publication_version is None
    assert result.version is None


def test_normalize_result_preserves_additive_fields_when_present() -> None:
    result = normalize_result(
        {
            "id": "page-1",
            "title": "Page 1",
            "score": 0.75,
            "provenance": "raw/sources/demo.md",
            "knowledge_mode": "observed",
            "context": {"scope": "demo"},
            "validity": {"valid_from": 10, "valid_to": 20},
            "publication_version": 3,
            "version": 7,
            "evidence_refs": ["doc-1:block-1"],
        }
    )

    assert result.provenance == "raw/sources/demo.md"
    assert result.knowledge_mode == "observed"
    assert result.context == {"scope": "demo"}
    assert result.validity == {"valid_from": 10, "valid_to": 20}
    assert result.publication_version == 3
    assert result.version == 7
    assert result.evidence_refs == ("doc-1:block-1",)


def test_provenance_gate_blocks_synthesized_without_derived_from() -> None:
    obj = KnowledgeObject(
        id="ko-1",
        type=KnowledgeType.SYNTHESIS,
        title="Synthesis",
        content="Body",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path="raw/sources/demo.md"),
    )
    obj.knowledge_mode = "synthesized"
    obj.evidence_refs = ["doc-1:block-1"]
    obj.derived_from = []

    verdict = ProvenanceGate().check(obj)

    assert verdict.passed is False
    assert verdict.blocked is True
    assert "missing_derived_from:synthesized" in verdict.reasons


def test_adapter_round_trips_provenance_source_paths() -> None:
    obj = KnowledgeObject(
        id="ko-1",
        type=KnowledgeType.CONCEPT,
        title="Concept",
        content="Body",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.8,
        provenance=Provenance(
            source_path="raw/sources/a.md",
            source_paths=("raw/sources/a.md", "raw/sources/b.md"),
            quote="quoted",
        ),
    )

    page = knowledge_object_to_wiki_page(obj)
    restored = wiki_page_to_knowledge_object(page)

    assert restored.provenance.source_path == "raw/sources/a.md"
    assert restored.provenance.source_paths == (
        "raw/sources/a.md",
        "raw/sources/b.md",
    )
    assert restored.provenance.quote == "quoted"


def test_adapter_preserves_retrieval_boundary_metadata() -> None:
    obj = KnowledgeObject(
        id="ko-2",
        type=KnowledgeType.CONCEPT,
        title="Concept",
        content="Body",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.8,
        provenance=Provenance(source_path="raw/sources/a.md"),
    )
    obj.evidence_refs = ["doc-1:block-1"]
    obj._ko_extra = {
        "knowledge_mode": "observed",
        "context": {"scope": "demo"},
        "validity": {"valid_from": 10, "valid_to": 20},
        "publication_version": 3,
        "version": 7,
        "closure_report": {"passed": True},
    }

    page = knowledge_object_to_wiki_page(obj)
    restored = wiki_page_to_knowledge_object(page)

    assert page.evidence_refs == ["doc-1:block-1"]
    assert page._ko_extra["closure_report"] == {"passed": True}
    assert restored.evidence_refs == ["doc-1:block-1"]
    assert restored.knowledge_mode == "observed"
    assert restored.context == {"scope": "demo"}
    assert restored.validity == {"valid_from": 10, "valid_to": 20}
    assert restored.publication_version == 3
    assert restored.version == 7
