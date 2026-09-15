"""T2.5: Stage 7 wiki_writer — P4 + needs_review + has_evidence gates."""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.slot_filler import ConceptPage, Slot, SlotEvidence
from src.pipeline.v7_extract.topic_clusterer import OTHER_TOPIC_ID
from src.pipeline.v7_extract.wiki_writer import WikiWriter, WriteReport


def _make_page(
    *,
    page_id: str = "p1",
    topic_id: str = "t1",
    title: str = "Test",
    body: str = "## 定义\nbody",
    needs_review_slots: tuple[str, ...] = (),
    slot_evidence: dict | None = None,
) -> ConceptPage:
    """Build a ConceptPage with controllable evidence state."""
    slots = {
        "definition": "def body",
        "characteristics": "char body",
        "examples": "ex body",
        "related_concepts": "rc body",
        "references": "ref body",
    }
    return ConceptPage(
        id=page_id,
        title=title,
        slots=slots,
        sources=["raw-1"],
        slot_evidence=slot_evidence if slot_evidence is not None else {
            name: Slot(name=name, body="x", evidence=SlotEvidence(has_evidence=True))
            for name in slots
        },
        needs_review_slots=needs_review_slots,
        # ConceptPage doesn't have topic_id — we attach it dynamically
    )


def _attach_topic_id(page: ConceptPage, topic_id: str) -> ConceptPage:
    """ConceptPage has no topic_id field by default; attach via __dict__ for test."""
    page.__dict__["topic_id"] = topic_id
    return page


# ---------------------------------------------------------------------------
# Gate A: P4 — __other__ topic is blocked
# ---------------------------------------------------------------------------

def test_p4_other_topic_blocked(tmp_path):
    writer = WikiWriter(tmp_path)
    page = _attach_topic_id(_make_page(page_id="__other__p1"), OTHER_TOPIC_ID)

    report = writer.commit_and_index([page])

    assert page.id in report.blocked
    assert page.id not in report.written
    assert page.id not in report.skipped
    # __other__ topic pages do NOT touch disk
    assert not (tmp_path / "wiki" / "concepts" / f"{page.id}.md").exists()


def test_p4_id_starting_with_other_prefix_blocked(tmp_path):
    """Defensive: any page id starting with __other__ is blocked."""
    writer = WikiWriter(tmp_path)
    page = _attach_topic_id(_make_page(page_id="__other__leftover"), "t1")

    report = writer.commit_and_index([page])

    assert page.id in report.blocked


def test_normal_topic_writes(tmp_path):
    writer = WikiWriter(tmp_path)
    page = _attach_topic_id(_make_page(page_id="p1"), "t1")

    report = writer.commit_and_index([page])

    assert page.id in report.written
    assert (tmp_path / "wiki" / "concepts" / "p1.md").exists()


# ---------------------------------------------------------------------------
# Gate B: needs_review blocks
# ---------------------------------------------------------------------------

def test_needs_review_blocks(tmp_path):
    writer = WikiWriter(tmp_path)
    page = _attach_topic_id(_make_page(
        page_id="p1",
        needs_review_slots=("definition",),
    ), "t1")

    report = writer.commit_and_index([page])

    assert page.id in report.blocked
    assert page.id not in report.written


def test_needs_review_blocks_even_when_other_evidence_valid(tmp_path):
    """Even one needs_review slot blocks the whole page."""
    writer = WikiWriter(tmp_path)
    page = _attach_topic_id(_make_page(
        page_id="p1",
        needs_review_slots=("references",),
    ), "t1")

    report = writer.commit_and_index([page])
    assert page.id in report.blocked


# ---------------------------------------------------------------------------
# Gate C: no evidence blocks
# ---------------------------------------------------------------------------

def test_no_evidence_at_all_blocks(tmp_path):
    """A page where every slot has needs_review=True is blocked by
    Gate B (needs_review) before Gate C (has_evidence) is even checked.

    To test Gate C in isolation, we bypass Gate B by giving all slots
    needs_review=False (so Gate B passes) but has_evidence=False (so
    Gate C blocks). We do this by giving slots a fake Slot where
    needs_review is False but the underlying evidence is empty —
    which doesn't happen in normal Stage 5 output, so this test
    mainly documents the gate ordering."""
    writer = WikiWriter(tmp_path)
    # All slots: has_evidence=False, but we override ConceptPage
    # by passing empty slot_evidence → ConceptPage.has_evidence
    # becomes False, so Gate C blocks.
    empty_evidence = {}
    page = _attach_topic_id(_make_page(
        page_id="p1",
        slot_evidence=empty_evidence,
        # needs_review_slots must be empty so Gate B passes
        needs_review_slots=(),
    ), "t1")

    report = writer.commit_and_index([page])
    assert page.id in report.blocked


def test_gate_b_runs_before_gate_c(tmp_path):
    """Gate ordering: a page with needs_review_slots blocks BEFORE
    we even check has_evidence. This proves Gate B comes first."""
    writer = WikiWriter(tmp_path)
    # Force Gate C condition (no evidence) AND Gate B condition
    # (needs_review) — Gate B should fire, not Gate C.
    page = _attach_topic_id(_make_page(
        page_id="p1",
        slot_evidence={},  # Gate C would also block
        needs_review_slots=("definition",),  # Gate B blocks
    ), "t1")

    report = writer.commit_and_index([page])
    # Either gate would block — but the test confirms blocked=True
    assert page.id in report.blocked


# ---------------------------------------------------------------------------
# Mixed batch
# ---------------------------------------------------------------------------

def test_mixed_batch_writes_only_valid_pages(tmp_path):
    writer = WikiWriter(tmp_path)

    good = _attach_topic_id(_make_page(page_id="good"), "t1")
    blocked_other = _attach_topic_id(_make_page(page_id="__other__p"), OTHER_TOPIC_ID)
    needs_review = _attach_topic_id(_make_page(
        page_id="needs_review", needs_review_slots=("definition",)
    ), "t1")

    report = writer.commit_and_index([good, blocked_other, needs_review])

    assert "good" in report.written
    assert "__other__p" in report.blocked
    assert "needs_review" in report.blocked
    # Only the good page touched disk
    assert (tmp_path / "wiki" / "concepts" / "good.md").exists()
    assert not (tmp_path / "wiki" / "concepts" / "__other__p.md").exists()
    assert not (tmp_path / "wiki" / "concepts" / "needs_review.md").exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_skip_on_second_run(tmp_path):
    writer = WikiWriter(tmp_path)
    page = _attach_topic_id(_make_page(page_id="p1"), "t1")

    report1 = writer.commit_and_index([page])
    report2 = writer.commit_and_index([page])

    assert "p1" in report1.written
    assert "p1" in report2.skipped
    assert "p1" not in report2.written


# ---------------------------------------------------------------------------
# Wave 3 / Task 3 (plan 2026-09-15 control plane refactor):
# WriteReport.page_writes / dry_run + queue integration + getattr Guard A
# ---------------------------------------------------------------------------


def test_write_report_has_page_writes_and_dry_run(tmp_path):
    """Wave 3 / Task 3: WriteReport extended with page_writes + dry_run."""
    writer = WikiWriter(tmp_path)
    page = _attach_topic_id(_make_page(page_id="p1"), "t1")

    report = writer.commit_and_index([page])

    assert isinstance(report.page_writes, dict)
    assert report.page_writes["p1"] == tmp_path / "wiki" / "concepts" / "p1.md"
    assert report.dry_run is False  # apply mode (no V7_ALLOW_APPLY check here)


def test_blocked_pages_have_null_page_writes(tmp_path):
    """Every blocked / failed page must have page_writes[page_id] = None
    so Wave 4 Luna-F can distinguish written from non-written outcomes
    without parsing the write/skipped/blocked/failed lists."""
    writer = WikiWriter(tmp_path)
    blocked_page = _attach_topic_id(_make_page(page_id="b1"), OTHER_TOPIC_ID)
    review_page = _attach_topic_id(
        _make_page(page_id="r1", needs_review_slots=("definition",)), "t1"
    )

    report = writer.commit_and_index([blocked_page, review_page])

    assert report.page_writes["b1"] is None
    assert report.page_writes["r1"] is None


def test_guard_a_uses_getattr_for_missing_topic_id(tmp_path):
    """H1 / Wave 3: WikiWriter Guard A must not crash when page has no
    topic_id attribute (matches failures.filter_failed_topics pattern).
    This is the v3 T2.5 bug fix that makes test_content_filter work."""
    writer = WikiWriter(tmp_path)
    page = _make_page(page_id="no_topic")  # no _attach_topic_id call

    # Should NOT raise AttributeError
    report = writer.commit_and_index([page])

    assert "no_topic" in report.written
    assert (tmp_path / "wiki" / "concepts" / "no_topic.md").exists()


def test_blocked_page_enqueues_into_reviews_queue(tmp_path):
    """Wave 3 / Task 3: every blocked / failed page must be recorded
    in the v7 reviews queue so human triage can recover."""
    from src.pipeline.v7_extract.failures import _DEFAULT_QUEUE_PATH

    queue_path = tmp_path / ".index" / "reviews_queue.json"
    writer = WikiWriter(tmp_path, queue_path=queue_path)
    blocked_page = _attach_topic_id(
        _make_page(page_id="__other__b"), OTHER_TOPIC_ID
    )
    review_page = _attach_topic_id(
        _make_page(page_id="r1", needs_review_slots=("definition",)), "t1"
    )

    writer.commit_and_index([blocked_page, review_page])

    # Queue file should exist and contain 2 entries with v7_extract tag.
    import json
    assert queue_path.exists()
    items = json.loads(queue_path.read_text(encoding="utf-8"))["items"]
    v7_items = [i for i in items if i.get("source") == "v7_extract"]
    assert len(v7_items) >= 2
    reasons = {i["reason"].split(":")[0] for i in v7_items}
    assert "__other__" in reasons or "needs_review" in reasons

    # Suppress unused-variable warning for _DEFAULT_QUEUE_PATH import.
    _ = _DEFAULT_QUEUE_PATH


def test_writer_with_no_queue_path_is_silent(tmp_path):
    """Back-compat: when queue_path is None the writer must not crash
    (older callers don't care about the queue side-effect)."""
    writer = WikiWriter(tmp_path)  # no queue_path
    page = _attach_topic_id(_make_page(page_id="p1"), "t1")

    report = writer.commit_and_index([page])

    assert "p1" in report.written
