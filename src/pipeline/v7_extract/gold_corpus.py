"""Gold corpus framework for V7 pipeline regression (Task 46, Commit 1).

Each V7 stage is a regression surface that may silently break across
prompt changes / refactors. Gold corpus is the safety net: a
``tests/corpus/v7_gold/<stage>_<n>.json`` directory of small fixtures
(input + expected output), run by ``CorpusRunner`` to verify the stage
behaves correctly end-to-end.

This commit ships the framework + Stage 1 (classify) corpus. Other
stages (segment / completeness / cluster / fill / write / 6R /
reconciliation) are added incrementally as separate commits.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from src.pipeline.v7_extract.llm_client import LLMClient


log = logging.getLogger(__name__)


# Default corpus root (relative to repo root).
DEFAULT_CORPUS_ROOT = Path("tests/corpus/v7_gold")


@dataclass
class CorpusFixture:
    id: str
    stage: str
    description: str
    input: dict[str, Any]
    expected: dict[str, Any]


@dataclass
class CorpusRunResult:
    fixture_id: str
    stage: str
    passed: bool
    diff: str = ""


class CorpusLoader:
    """Discover and parse JSON fixtures under a root directory."""

    @staticmethod
    def discover(root: Path | str = DEFAULT_CORPUS_ROOT) -> list[Path]:
        root_path = Path(root)
        if not root_path.exists():
            return []
        return sorted(p for p in root_path.rglob("*.json") if p.is_file())

    @staticmethod
    def load(path: Path) -> CorpusFixture | None:
        """Parse a single fixture file. None on missing required fields."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("CorpusLoader: cannot read %s: %s", path, e)
            return None
        try:
            payload = json.loads(text)
        except ValueError as e:
            log.warning("CorpusLoader: %s is not valid JSON: %s", path, e)
            return None
        if not isinstance(payload, dict):
            return None
        required = ("id", "stage", "description", "input", "expected")
        for key in required:
            if key not in payload:
                log.warning("CorpusLoader: %s missing field %r", path, key)
                return None
        return CorpusFixture(
            id=str(payload["id"]),
            stage=str(payload["stage"]),
            description=str(payload["description"]),
            input=dict(payload["input"]),
            expected=dict(payload["expected"]),
        )


# ---------------------------------------------------------------------------
# Stage-specific runners
# ---------------------------------------------------------------------------


def _diff_strings(expected: Any, actual: Any, *, indent: int = 0) -> str:
    """Render a short diff between expected and actual values."""
    pad = "  " * indent
    if expected == actual:
        return ""
    e = repr(expected)
    a = repr(actual)
    return f"{pad}expected: {e}\n{pad}actual:   {a}"


def _script_llm_for_fixture(
    fixture: CorpusFixture, llm: LLMClient, prompt_kind: str
) -> LLMClient:
    """If the fixture provides an LLM response for ``prompt_kind`` and
    ``llm`` is a FakeLLMClient, return a new FakeLLMClient with the
    response queued. Otherwise return ``llm`` unchanged.
    """
    from src.pipeline.v7_extract.llm_client import FakeLLMClient

    response = fixture.input.get("llm_responses", {}).get(prompt_kind)
    if response is None:
        return llm
    if not isinstance(llm, FakeLLMClient):
        return llm
    new = FakeLLMClient()
    new.script(prompt_kind, json.dumps(response, ensure_ascii=False))
    return new


async def run_stage1(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
) -> CorpusRunResult:
    """Run Stage 1 (classify_doc) and compare to expected.

    Expected fields supported:
      - doc_type: str (one of the 6 valid doc_types)
      - failed: bool
      - traits_subset: list[str] (subset check; actual may be a superset)
      - min_confidence: float

    If ``fixture.input.llm_response`` is set, the runner first ensures
    the LLM returns that response (no-op if it's a FakeLLMClient; real
    clients will be called normally).
    """
    from src.pipeline.v7_extract.doc_classifier import classify_doc

    content = str(fixture.input.get("content", ""))
    filename_hint = str(fixture.input.get("filename_hint", ""))
    active_llm = _script_llm_for_fixture(fixture, llm, "classify")

    result = await classify_doc(
        content, filename_hint=filename_hint, llm=active_llm, project_root=None,
    )
    diffs: list[str] = []
    if "doc_type" in fixture.expected:
        if result.doc_type != fixture.expected["doc_type"]:
            diffs.append(_diff_strings(
                fixture.expected["doc_type"], result.doc_type, indent=1,
            ))
    if "failed" in fixture.expected:
        if result.failed != fixture.expected["failed"]:
            diffs.append(_diff_strings(
                fixture.expected["failed"], result.failed, indent=1,
            ))
    if "traits_subset" in fixture.expected:
        expected_traits = set(fixture.expected["traits_subset"])
        actual_traits = set(result.traits or [])
        if not expected_traits.issubset(actual_traits):
            diffs.append(
                f"  expected traits superset {sorted(expected_traits)}; "
                f"actual traits = {sorted(actual_traits)}"
            )
    if "min_confidence" in fixture.expected:
        min_c = float(fixture.expected["min_confidence"])
        if result.confidence < min_c:
            diffs.append(
                f"  expected confidence >= {min_c}; got {result.confidence:.3f}"
            )
    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


async def run_stage2(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
) -> CorpusRunResult:
    """Run Stage 2 (segment_articles) and compare to expected.

    Expected fields supported:
      - article_count_min: int (>= this many articles)
      - article_count_max: int (<= this many articles)
      - first_article_title_contains: str (substring check on first article)
      - boundaries_touching: bool (article[i].end == article[i+1].start)
    """
    from src.pipeline.v7_extract.article_segmenter import segment_articles

    content = str(fixture.input.get("content", ""))
    doc_type = fixture.input.get("doc_type_hint")
    active_llm = _script_llm_for_fixture(fixture, llm, "segment_articles")

    articles = await segment_articles(
        content, llm=active_llm, doc_type=doc_type, project_root=None,
    )

    diffs: list[str] = []
    n = len(articles)

    if "article_count_min" in fixture.expected:
        min_n = int(fixture.expected["article_count_min"])
        if n < min_n:
            diffs.append(f"  expected >= {min_n} articles; got {n}")

    if "article_count_max" in fixture.expected:
        max_n = int(fixture.expected["article_count_max"])
        if n > max_n:
            diffs.append(f"  expected <= {max_n} articles; got {n}")

    if "first_article_title_contains" in fixture.expected and articles:
        needle = str(fixture.expected["first_article_title_contains"])
        title = articles[0].title or ""
        if needle not in title:
            diffs.append(
                f"  expected first article title to contain {needle!r}; got {title!r}"
            )

    if fixture.expected.get("boundaries_touching") and n > 1:
        for i in range(n - 1):
            if articles[i].char_end != articles[i + 1].char_start:
                diffs.append(
                    f"  boundaries not touching: article[{i}].char_end={articles[i].char_end} "
                    f"!= article[{i + 1}].char_start={articles[i + 1].char_start}"
                )

    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


async def run_stage3(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
) -> CorpusRunResult:
    """Run Stage 3 (check_completeness) and compare to expected.

    Expected fields supported:
      - status: str — one of the four CompletenessStatus values, or
        the special string ``"none"`` which means check_completeness
        returned None (technical failure path).
    """
    from src.pipeline.v7_extract.completeness_checker import (
        check_completeness,
        CompletenessStatus,
    )

    content = str(fixture.input.get("content", ""))
    doc_type_hint = str(fixture.input.get("doc_type_hint", "unknown"))
    active_llm = _script_llm_for_fixture(fixture, llm, "completeness")

    result = await check_completeness(
        content, doc_type_hint, llm=active_llm, project_root=None,
    )

    diffs: list[str] = []
    expected_status = str(fixture.expected.get("status", ""))
    if expected_status == "none":
        if result is not None:
            diffs.append(
                f"  expected None (technical failure); got {result.status.value}"
            )
    else:
        if result is None:
            diffs.append(
                f"  expected {expected_status}; got None (technical failure)"
            )
        else:
            try:
                expected_enum = CompletenessStatus(expected_status)
            except ValueError:
                expected_enum = None
            if expected_enum is not None and result.status is not expected_enum:
                diffs.append(_diff_strings(expected_status, result.status.value))

    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


async def run_stage4(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
) -> CorpusRunResult:
    """Run Stage 4 (cluster_topics) and compare to expected.

    Expected fields supported:
      - status: str — one of CLUSTERED / DEGRADED / UNCERTAIN / FAILED / EMPTY
      - topic_count_min: int
      - topic_count_max: int
      - first_topic_title_contains: str
    """
    from src.pipeline.v7_extract.topic_clusterer import cluster_topics

    items = fixture.input.get("items", [])
    source_id = str(fixture.input.get("source_id", ""))
    active_llm = _script_llm_for_fixture(fixture, llm, "cluster")

    result = await cluster_topics(
        items, llm=active_llm, project_root=None, source_id=source_id,
    )

    diffs: list[str] = []
    if "status" in fixture.expected:
        expected_status = str(fixture.expected["status"])
        if result.status.value != expected_status:
            diffs.append(_diff_strings(expected_status, result.status.value))

    n = len(result.topics)
    if "topic_count_min" in fixture.expected:
        min_n = int(fixture.expected["topic_count_min"])
        if n < min_n:
            diffs.append(f"  expected >= {min_n} topics; got {n}")
    if "topic_count_max" in fixture.expected:
        max_n = int(fixture.expected["topic_count_max"])
        if n > max_n:
            diffs.append(f"  expected <= {max_n} topics; got {n}")

    if "first_topic_title_contains" in fixture.expected and result.topics:
        needle = str(fixture.expected["first_topic_title_contains"])
        title = result.topics[0].title or ""
        if needle not in title:
            diffs.append(
                f"  expected first topic title to contain {needle!r}; got {title!r}"
            )

    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


async def run_stage5(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
) -> CorpusRunResult:
    """Run Stage 5A (extract_slot_claims) and compare to expected.

    Fixture input schema:
      - source_bytes: str (the source text)
      - slot_name: str (e.g. "definition")
      - topic_label: str
      - spans: list of {item_id, start_byte, end_byte, char_start, char_end}
        (source-absolute byte offsets)

    Expected fields supported:
      - claim_count_min: int
      - claim_count_max: int
      - status: one of SUPPORTED / NOT_APPLICABLE / INSUFFICIENT_EVIDENCE / CONFLICTING
        (ClaimSupport enum values)
    """
    from src.pipeline.v7_extract.claim import ClaimSupport
    from src.pipeline.v7_extract.claim_extractor import extract_slot_claims
    from src.pipeline.v7_extract.canonical_spans import CanonicalSpan

    source_bytes = fixture.input.get("source_bytes", "").encode("utf-8")
    slot_name = str(fixture.input.get("slot_name", "definition"))
    topic_label = str(fixture.input.get("topic_label", "topic"))
    spans_data = fixture.input.get("spans", [])
    spans = [
        CanonicalSpan(
            span_id=f"span-{i}",
            item_id=s.get("item_id", f"item-{i}"),
            item_index=int(s.get("item_index", 0)),
            start_byte=int(s.get("start_byte", 0)),
            end_byte=int(s.get("end_byte", 0)),
            char_start=int(s.get("char_start", 0)),
            char_end=int(s.get("char_end", 0)),
        )
        for i, s in enumerate(spans_data)
    ]
    active_llm = _script_llm_for_fixture(fixture, llm, "fill_slots_extract")

    try:
        result = await extract_slot_claims(
            slot_name,
            topic_label=topic_label,
            spans=spans,
            llm=active_llm,
            project_root=None,
            source_bytes=source_bytes,
        )
    except RuntimeError as e:
        # Failure Contract §1: technical failure must surface as a
        # failed result (never as a fake "0 claims" success).
        return CorpusRunResult(
            fixture_id=fixture.id,
            stage=fixture.stage,
            passed=False,
            diff=f"technical_failure: {e}",
        )

    diffs: list[str] = []
    n = len(result.claims)
    if "claim_count_min" in fixture.expected:
        min_n = int(fixture.expected["claim_count_min"])
        if n < min_n:
            diffs.append(f"  expected >= {min_n} claims; got {n}")
    if "claim_count_max" in fixture.expected:
        max_n = int(fixture.expected["claim_count_max"])
        if n > max_n:
            diffs.append(f"  expected <= {max_n} claims; got {n}")
    if "status" in fixture.expected:
        expected_status = str(fixture.expected["status"])
        try:
            expected_enum = ClaimSupport(expected_status)
        except ValueError:
            expected_enum = None
        if expected_enum is not None and result.status is not expected_enum:
            diffs.append(_diff_strings(expected_status, result.status.value))

    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


def _build_concept_page_for_stage7(page_data: dict[str, Any]) -> Any:
    """Construct a ConceptPage for Stage 7 corpus fixtures.

    page_data schema:
      - id, title, sources (list[str])
      - slots: dict[slot_name -> body text]
      - evidence: dict[slot_name -> {item_id, source_text_excerpt, has_evidence}]
    """
    from src.pipeline.v7_extract.slot_filler import (
        ConceptPage,
        Slot,
        SlotEvidence,
        CONCEPT_SLOTS,
    )
    slots = page_data.get("slots", {})
    evidence = page_data.get("evidence", {})
    slot_objs: dict[str, Slot] = {}
    for name in CONCEPT_SLOTS:
        body = slots.get(name, "")
        ev = evidence.get(name, {})
        item_id = ev.get("item_id", page_data.get("sources", ["src"])[0])
        excerpt = ev.get("source_text_excerpt", "excerpt")
        slot_objs[name] = Slot(
            name=name,
            body=body,
            evidence=SlotEvidence(
                item_id=item_id,
                source_text_excerpt=excerpt,
                has_evidence=ev.get("has_evidence", True),
                needs_review=ev.get("needs_review", False),
            ),
            needs_review=ev.get("needs_review", False),
        )
    return ConceptPage(
        id=page_data["id"],
        title=page_data.get("title", page_data["id"]),
        slots=slots,
        sources=page_data.get("sources", ["src"]),
        slot_evidence=slot_objs,
        needs_review_slots=(),
        topic_id=page_data.get("topic_id", page_data["id"]),
    )


def run_stage7(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
    project_root: Path,
) -> CorpusRunResult:
    """Run Stage 7 (WikiWriter.commit_and_index) and compare to expected.

    The CorpusRunner passes a per-test project_root (tmp_path) so
    Stage 7's filesystem side effects are isolated to that root.

    Fixture input:
      - pages: list of page dicts (see _build_concept_page_for_stage7)
    Expected:
      - written_count_min: int
      - blocked_count_min: int
      - durable_failure_log_exists: bool
    """
    from src.pipeline.v7_extract.wiki_writer import WikiWriter

    pages_data = fixture.input.get("pages", [])
    pages = [_build_concept_page_for_stage7(p) for p in pages_data]

    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)
    (project_root / ".index").mkdir(parents=True, exist_ok=True)

    writer = WikiWriter(project_root, pipeline_fingerprint="fp-corpus")
    durable_failure_path = project_root / ".index" / "durable_failure.jsonl"
    writer.durable_failure_path = durable_failure_path
    report = writer.commit_and_index(pages)

    diffs: list[str] = []
    n_written = len(report.written)
    n_blocked = len(report.blocked)
    if "written_count_min" in fixture.expected:
        min_n = int(fixture.expected["written_count_min"])
        if n_written < min_n:
            diffs.append(f"  expected >= {min_n} written; got {n_written}")
    if "blocked_count_min" in fixture.expected:
        min_n = int(fixture.expected["blocked_count_min"])
        if n_blocked < min_n:
            diffs.append(f"  expected >= {min_n} blocked; got {n_blocked}")
    if fixture.expected.get("durable_failure_log_exists") is True:
        if not durable_failure_path.exists():
            diffs.append("  expected durable_failure.jsonl to exist")
    elif fixture.expected.get("durable_failure_log_exists") is False:
        if durable_failure_path.exists() and durable_failure_path.read_text(
            encoding="utf-8"
        ).strip():
            diffs.append("  expected durable_failure.jsonl to be empty/absent")

    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


async def run_stage6r(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
) -> CorpusRunResult:
    """Run Stage 6R (relation extraction, deterministic heuristic path).

    Fixture input:
      - pages: list of {id, title, slots: dict[str,str]}

    The runner deliberately passes ``llm=None`` so the extractor uses its
    deterministic ``_heuristic_relations`` path (substring mention of a
    target's id/title inside the source's title+slots; ``refines`` when a
    refinement marker appears, else ``supported_by``). This keeps the
    Stage 6R corpus LLM-free and reproducible.

    Expected:
      - relation_count_min / relation_count_max: int
      - relation_predicates_subset: list[str] of PageRelation.type values
    """
    from src.pipeline.v7_extract.relation_extractor import extract_relations

    pages = fixture.input.get("pages", [])
    relations = extract_relations(pages, llm=None)

    diffs: list[str] = []
    n = len(relations)
    if "relation_count_min" in fixture.expected:
        min_n = int(fixture.expected["relation_count_min"])
        if n < min_n:
            diffs.append(f"  expected >= {min_n} relations; got {n}")
    if "relation_count_max" in fixture.expected:
        max_n = int(fixture.expected["relation_count_max"])
        if n > max_n:
            diffs.append(f"  expected <= {max_n} relations; got {n}")
    if "relation_predicates_subset" in fixture.expected:
        expected_types = set(fixture.expected["relation_predicates_subset"])
        actual_types = {r.type for r in relations}
        if not expected_types.issubset(actual_types):
            diffs.append(
                f"  expected relation types superset {sorted(expected_types)}; "
                f"got {sorted(actual_types)}"
            )

    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


async def run_reconciliation(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
    project_root: Path,
) -> CorpusRunResult:
    """Run Reconciliation Phase 1 (reconcile_pages) and compare to expected.

    Fixture input:
      - pages: list of {id, title, body} (pages to reconcile)
      - canonical_seed: optional list of {canonical_id, preferred_label,
        member_page_ids} seeded into the registry before the run
      - llm_verdicts: optional list of {page_id, canonical_id, decision,
        confidence} the LLM is scripted to return per page

    Expected:
      - processed_min / created_new_min / joined_existing_min: int
    """
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationStatus,
    )
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.reconcile_job import reconcile_pages

    # prompt_kind used by the identity resolver (see
    # src/reconciliation/prompts/builtin/identity_resolve.toml).
    identity_prompt_kind = "identity_resolve"

    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / ".index").mkdir(parents=True, exist_ok=True)

    # Seed canonicals if requested.
    seed = fixture.input.get("canonical_seed", [])
    if seed:
        registry = CanonicalRegistry(project_root)
        concepts = {}
        for entry in seed:
            cid = str(entry["canonical_id"])
            concepts[cid] = CanonicalConcept(
                canonical_id=cid,
                preferred_label=str(entry.get("preferred_label", cid)),
                member_page_ids=list(entry.get("member_page_ids", [])),
                status=ReconciliationStatus.ACTIVE,
                resolver_fingerprint="fp-corpus",
            )
        registry._save_concepts(concepts)

    # Scripted LLM verdicts (one per page).
    verdicts = fixture.input.get("llm_verdicts", [])
    if verdicts:
        from src.pipeline.v7_extract.llm_client import FakeLLMClient
        batch: list[dict[str, Any]] = []
        for v in verdicts:
            batch.append({
                "canonical_id": v.get("canonical_id", ""),
                "decision": v.get("decision", "unresolved"),
                "confidence": float(v.get("confidence", 0.5)),
                "reason": "corpus",
            })
        scripter = FakeLLMClient()
        scripter.script(identity_prompt_kind, json.dumps({"verdicts": batch}, ensure_ascii=False))
        active_llm: Any = scripter
    else:
        active_llm = llm

    pages_raw = fixture.input.get("pages", [])

    # reconcile_pages reads page.id / page.title / page.body via getattr,
    # so dict fixtures must be wrapped in a simple attribute holder.
    class _Page:
        __slots__ = ("id", "title", "body")

        def __init__(self, page_id: str, title: str, body: str) -> None:
            self.id = page_id
            self.title = title
            self.body = body

    pages = [
        _Page(
            str(p.get("id", "")),
            str(p.get("title", "")),
            str(p.get("body", "")),
        )
        for p in pages_raw
    ]

    result = await reconcile_pages(
        pages,
        project_root=project_root,
        llm=active_llm,
        body_by_page={
            str(p.get("id", "")): str(p.get("body", ""))
            for p in pages_raw
        },
        resolver_fingerprint="fp-corpus",
    )

    diffs: list[str] = []
    for key, attr in (
        ("processed_min", "processed"),
        ("created_new_min", "created_new"),
        ("joined_existing_min", "joined_existing"),
        ("unresolved_min", "unresolved"),
    ):
        if key in fixture.expected:
            min_n = int(fixture.expected[key])
            actual = int(getattr(result, attr))
            if actual < min_n:
                diffs.append(f"  expected {attr} >= {min_n}; got {actual}")

    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


# Per-stage dispatcher. New stages add their runner here.
STAGE_RUNNERS: dict[str, Callable[..., Awaitable[CorpusRunResult]]] = {
    "stage1_classify": run_stage1,
    "stage2_segment": run_stage2,
    "stage3_completeness": run_stage3,
    "stage4_cluster": run_stage4,
    "stage5_extract_claims": run_stage5,
    "stage7_write": run_stage7,
    "stage6r_relations": run_stage6r,
    "reconciliation": run_reconciliation,
}


class CorpusRunner:
    """Run a set of fixtures through their stage-specific runners.

    Use ``run(fixtures)`` to execute all (or ``run_stage(stage)`` for
    a subset). The runner returns per-fixture ``CorpusRunResult`` so
    tests can assert pass/fail and surface a useful diff on failure.
    """

    def __init__(self, *, llm: LLMClient, project_root: Path | None = None) -> None:
        self.llm = llm
        self.project_root = project_root

    def run(self, fixtures: Sequence[CorpusFixture]) -> list[CorpusRunResult]:
        return self._run_sync(fixtures)

    def _run_sync(self, fixtures: Sequence[CorpusFixture]) -> list[CorpusRunResult]:
        import asyncio
        results: list[CorpusRunResult] = []
        for fx in fixtures:
            runner = STAGE_RUNNERS.get(fx.stage)
            if runner is None:
                results.append(CorpusRunResult(
                    fixture_id=fx.id, stage=fx.stage, passed=False,
                    diff=f"no runner registered for stage {fx.stage!r}",
                ))
                continue
            try:
                # Stage 7 / Reconciliation need a project root; other
                # stages ignore it. Stage 7's run_stage7 is sync;
                # everything else is async.
                needs_root = fx.stage in ("stage7_write", "reconciliation")
                if needs_root:
                    if self.project_root is None:
                        # No project_root supplied by caller — fall back to
                        # creating a fresh staging dir (caller should
                        # pass tmp_path for hermetic tests).
                        import tempfile
                        proj = Path(tempfile.mkdtemp(prefix="corpus_"))
                    else:
                        proj = self.project_root
                if fx.stage == "stage7_write":
                    result = runner(fx, llm=self.llm, project_root=proj)
                elif fx.stage == "reconciliation":
                    result = asyncio.run(
                        runner(fx, llm=self.llm, project_root=proj)
                    )
                else:
                    result = asyncio.run(runner(fx, llm=self.llm))
            except Exception as e:  # noqa: BLE001
                results.append(CorpusRunResult(
                    fixture_id=fx.id, stage=fx.stage, passed=False,
                    diff=f"runner raised: {type(e).__name__}: {e}",
                ))
                continue
            results.append(result)
        return results

    def run_stage(self, stage: str) -> list[CorpusRunResult]:
        all_fixtures = [
            CorpusLoader.load(p) for p in CorpusLoader.discover()
            if True
        ]
        stage_fixtures = [f for f in all_fixtures if f is not None and f.stage == stage]
        return self.run(stage_fixtures)


__all__ = [
    "CorpusFixture",
    "CorpusLoader",
    "CorpusRunResult",
    "CorpusRunner",
    "DEFAULT_CORPUS_ROOT",
    "STAGE_RUNNERS",
]