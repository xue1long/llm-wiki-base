from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.partition import (
    GovernanceConfig,
    ReaderProfile,
    evaluate_series_gate,
)
import inspect


def _page(i: int, page_type: str, taxonomy: str = "book-a", *, source: bool = True, target: str | None = None, task_type: str | None = None) -> PageRecord:
    return PageRecord(
        page_id=f"p{i}", title=f"Page {i}", page_type=page_type,
        path=f"{page_type}/p{i}.md", primary_taxonomy=taxonomy,
        summary="summary", content_blocks=(ContentBlock(f"p{i}:0", f"p{i}", None, "body", 0),),
        relation_targets=(("supports", target),) if target else (), content_sha256=f"hash-{i}", char_count=10,
        token_count=None, sources=(f"source-{i}",) if source else (), task_type=task_type,
    )


def _snapshot(*pages: PageRecord) -> WikiSnapshot:
    return WikiSnapshot("snap-1", "wiki", "wiki-v3", tuple(pages), ())


def test_series_gate_emits_deterministic_ready_baseline() -> None:
    snapshot = _snapshot(*[_page(i, kind, target="p3" if i == 2 else None) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
    profile = ReaderProfile("reader", ("learn_concept", "reference", "apply"), min_pages_per_book=3, min_reader_tasks=2, chapter_exit_evidence=("chapter-1",))
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
    snapshot = _snapshot(*[_page(i, kind, target="p1" if i > 1 else None) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
    result = evaluate_series_gate(snapshot, reader_profile=ReaderProfile("reader", ("learn_concept",)))

    assert result.status == "blocked"
    assert result.generation_mode == "rule_only"
    assert {"external_authorized", "budget_cap", "approver"} <= set(result.block_reasons)


def test_same_snapshot_and_inputs_have_same_result() -> None:
    snapshot = _snapshot(*[_page(i, kind) for i, kind in enumerate(("concept", "entity", "synthesis"), 1)])
    kwargs = dict(reader_profile=ReaderProfile("reader", ("learn_concept",), min_pages_per_book=3, min_reader_tasks=1, chapter_exit_evidence=("chapter-1",)), governance=GovernanceConfig(True, 100, "editor"))
    assert evaluate_series_gate(snapshot, **kwargs) == evaluate_series_gate(snapshot, **kwargs)


def _complete_snapshot(*, relation: tuple[str, str] = ("supports", "p3")) -> WikiSnapshot:
    pages = [_page(1, "concept", target=relation[1] or None, task_type="learn_concept"), _page(2, "entity", task_type="reference")]
    pages += [_page(i, "synthesis", task_type="apply") for i in range(3, 21)]
    pages[0] = PageRecord(**{**pages[0].__dict__, "relation_targets": (relation,) if relation[0] else ()})
    return _snapshot(*pages)


def test_strict_positive_closure_needs_six_tasks_and_exit_evidence() -> None:
    result = evaluate_series_gate(_complete_snapshot(), reader_profile=ReaderProfile("reader", ("learn_concept", "apply"), chapter_exit_evidence=("ch-1",)), governance=GovernanceConfig(True, 100, "editor"))
    assert result.candidates[0].closure_status == "closed"
    assert result.candidates[0].reader_task_count == 19
    assert result.candidates[0].closure_evidence


def test_reverse_and_self_relations_do_not_close() -> None:
    for relation in (("supports", "p1"), ("supports", "p2")):
        result = evaluate_series_gate(_complete_snapshot(relation=relation), reader_profile=ReaderProfile("r", ("learn_concept", "apply"), chapter_exit_evidence=("ch",)), governance=GovernanceConfig(True, 1, "a"))
        assert result.candidates[0].closure_status != "closed"


def test_no_relation_is_unknown_and_blocks_rule_only() -> None:
    result = evaluate_series_gate(_complete_snapshot(relation=("", "")), reader_profile=ReaderProfile("r", ("learn_concept", "apply"), chapter_exit_evidence=("ch",)), governance=GovernanceConfig(True, 1, "a"))
    assert result.metrics.relation_parse_rate is None
    assert result.status == "blocked" and result.generation_mode == "rule_only"


def test_three_candidates_have_cancel_and_merge_paths() -> None:
    pages = [_page(1, "concept", "book-a", target="p3"), _page(2, "concept", "book-a", target="p3")]
    pages += [_page(3, "concept", "book-b", target="p1")]
    result = evaluate_series_gate(_snapshot(*pages), reader_profile=ReaderProfile("r", ("learn_concept",), min_pages_per_book=20), governance=GovernanceConfig(True, 1, "a"))
    decisions = {candidate.candidate_id: candidate.decision for candidate in result.candidates}
    assert {"book-a", "book-b", "book-c"} <= set(decisions)
    assert decisions["book-c"] == "cancel"
    assert decisions["book-a"] == "merge"


def test_hard_dependency_blocks_and_soft_dependency_is_reported() -> None:
    result = evaluate_series_gate(_snapshot(_page(1, "concept")), reader_profile=ReaderProfile("r", ("learn_concept",)), governance=GovernanceConfig(True, 1, "a", ("missing",), ("optional",)))
    assert result.status == "blocked"
    assert result.hard_reference_dependencies == ("missing",)
    assert result.soft_reference_dependencies == ("optional",)


def test_gate_surface_has_no_provider_and_blocks_rule_only() -> None:
    assert "provider" not in inspect.signature(evaluate_series_gate).parameters
    result = evaluate_series_gate(_snapshot(_page(1, "concept")), reader_profile=ReaderProfile("r", ("learn_concept",)), governance=GovernanceConfig(True, 1, "a"))
    assert result.generation_mode == "rule_only"
