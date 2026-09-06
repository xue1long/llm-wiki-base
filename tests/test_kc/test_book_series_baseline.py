from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.partition import (
    GovernanceConfig,
    ReaderProfile,
    evaluate_series_gate,
)


def _page(i: int, page_type: str, taxonomy: str = "book-a", *, source: bool = True) -> PageRecord:
    return PageRecord(
        page_id=f"p{i}", title=f"Page {i}", page_type=page_type,
        path=f"{page_type}/p{i}.md", primary_taxonomy=taxonomy,
        summary="summary", content_blocks=(ContentBlock(f"p{i}:0", f"p{i}", None, "body", 0),),
        relation_targets=(), content_sha256=f"hash-{i}", char_count=10,
        token_count=None, sources=(f"source-{i}",) if source else (),
    )


def _snapshot(*pages: PageRecord) -> WikiSnapshot:
    return WikiSnapshot("snap-1", "wiki", "wiki-v3", tuple(pages), ())


def test_series_gate_emits_deterministic_ready_baseline() -> None:
    snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
    profile = ReaderProfile("reader", ("learn_concept", "apply"))
    governance = GovernanceConfig(external_authorized=True, budget_cap=100, approver="editor")

    result = evaluate_series_gate(snapshot, reader_profile=profile, governance=governance)

    assert result.status == "ready"
    assert result.generation_mode == "llm_allowed"
    assert result.metrics.estimated_chars == 30
    assert result.candidates[0].eligible_page_count == 3
    assert result.candidates[0].source_coverage == 1.0
    assert result.candidates[0].closure_status == "closed"


def test_series_gate_rejects_weak_candidate_without_provider() -> None:
    snapshot = _snapshot(_page(1, "concept", source=False))
    result = evaluate_series_gate(
        snapshot,
        reader_profile=ReaderProfile("reader", ("learn_concept",)),
        governance=GovernanceConfig(external_authorized=True, budget_cap=100, approver="editor"),
    )

    candidate = result.candidates[0]
    assert candidate.source_coverage == 0.0
    assert candidate.decision in {"merge", "reference", "cancel"}
    assert candidate.decision != "proceed"


def test_missing_governance_blocks_and_forces_rule_only() -> None:
    snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
    result = evaluate_series_gate(snapshot, reader_profile=ReaderProfile("reader", ("learn_concept",)))

    assert result.status == "blocked"
    assert result.generation_mode == "rule_only"
    assert {"external_authorized", "budget_cap", "approver"} <= set(result.block_reasons)


def test_same_snapshot_and_inputs_have_same_result() -> None:
    snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
    kwargs = dict(reader_profile=ReaderProfile("reader", ("learn_concept",)), governance=GovernanceConfig(True, 100, "editor"))
    assert evaluate_series_gate(snapshot, **kwargs) == evaluate_series_gate(snapshot, **kwargs)
