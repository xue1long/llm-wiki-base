from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.pipeline.v7_extract.relation_extractor import PageRelation
from src.pipeline.v7_extract.slot_filler import (
    CONCEPT_SLOTS,
    ConceptPage,
    Slot,
    SlotEvidence,
)
from src.pipeline.v7_extract.audit_logger import AuditLogger
from src.pipeline.v7_extract.wiki_writer import WriteReport, WikiWriter


def _page(page_id: str, source: str) -> ConceptPage:
    """Construct a ConceptPage that survives v3 WikiWriter's three guards:

    - ``topic_id`` is NOT ``__other__`` (so Guard A passes).
    - All slots carry evidence and none are flagged needs_review
      (so Guard B / C pass).
    """
    slots = {name: f"{name} 内容" for name in CONCEPT_SLOTS}
    slot_evidence = {
        name: Slot(
            name=name,
            body=slots[name],
            evidence=SlotEvidence(
                item_id=source,
                source_text_excerpt="...",
                has_evidence=True,
                needs_review=False,
            ),
            needs_review=False,
        )
        for name in CONCEPT_SLOTS
    }
    return ConceptPage(
        id=page_id,
        title=f"标题-{page_id}",
        slots=slots,
        sources=[source],
        slot_evidence=slot_evidence,
        needs_review_slots=(),
        topic_id=page_id,
    )


def test_writer_creates_pages_index_checkpoint_and_audit_report(tmp_path: Path) -> None:
    writer = WikiWriter(tmp_path)
    pages = [_page("concept-a", "raw-a"), _page("concept-b", "raw-a")]
    relations = [PageRelation("concept-b", "concept-a", "refines")]

    report = writer.commit_and_index(pages, relations)
    second = writer.commit_and_index(pages, relations)

    assert isinstance(report, WriteReport)
    assert report.written == ["concept-a", "concept-b"]
    assert second.written == []
    assert set(second.skipped) == {"concept-a", "concept-b"}
    assert (tmp_path / "wiki" / "concepts" / "concept-a.md").exists()
    index = (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
    assert index.count("- **concept-a**") == 1
    assert index.count("- **concept-b**") == 1
    checkpoint = json.loads(
        (tmp_path / ".index" / "v7_checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["completed"] == ["concept-a", "concept-b"]
    audit = json.loads(
        (tmp_path / ".index" / "extract_report.json").read_text(encoding="utf-8")
    )
    assert audit["raw-a"] == ["concept-a", "concept-b"]


def test_writer_retries_three_times_then_reports_failure(tmp_path: Path) -> None:
    attempts: list[str] = []

    def always_fails(page: ConceptPage, path: Path) -> None:
        attempts.append(page.id)
        raise OSError("disk full")

    writer = WikiWriter(tmp_path, page_writer=always_fails)
    report = writer.commit_and_index([_page("broken", "raw-b")])

    assert attempts == ["broken", "broken", "broken"]
    assert report.written == []
    assert report.failed == {"broken": "disk full"}
    assert not (tmp_path / "wiki" / "concepts" / "broken.md").exists()


def test_writer_checkpoint_does_not_hide_a_missing_page(tmp_path: Path) -> None:
    writer = WikiWriter(tmp_path)
    page = _page("recover", "raw-c")
    writer.commit_and_index([page])
    (tmp_path / "wiki" / "concepts" / "recover.md").unlink()

    report = writer.commit_and_index([page])

    assert report.written == ["recover"]
    assert (tmp_path / "wiki" / "concepts" / "recover.md").exists()


def test_writer_blocks_pages_with_other_topic_id(tmp_path: Path) -> None:
    """P4 (Guard A): ``__other__`` is the Stage 4 sentinel bucket for items
    the LLM forgot to assign. WikiWriter refuses to write those pages —
    they go to ``report.blocked`` instead and never touch disk."""
    writer = WikiWriter(tmp_path)
    page = _page("orphan", "raw-d")
    # Force the sentinel: ``__other__`` topic id triggers Guard A.
    page.topic_id = "__other__"

    report = writer.commit_and_index([page])

    assert report.written == []
    assert report.blocked == ["orphan"]
    assert not (tmp_path / "wiki" / "concepts" / "orphan.md").exists()


def test_audit_logger_merges_source_mappings_idempotently(tmp_path: Path) -> None:
    logger = AuditLogger(tmp_path / "extract_report.json")

    logger.record("raw-a", ["concept-a"])
    logger.record("raw-a", ["concept-a", "concept-b"])

    assert logger.read() == {"raw-a": ["concept-a", "concept-b"]}


# ---------------------------------------------------------------------------
# Task 19 (Stage 7 CommitManifest + phase machine — crash consistency)
# ---------------------------------------------------------------------------


def test_manifest_persists_at_each_phase(tmp_path: Path) -> None:
    """commit_and_index writes a CommitManifest under ``.index/commit_manifests``
    whose top-level phase ends as ``COMMITTED`` and whose per-page record
    carries the on-disk path + a sha1-derived ``revision_hash``.
    """
    writer = WikiWriter(tmp_path)
    pages = [_page("concept-a", "raw-a")]

    writer.commit_and_index(pages)

    manifest_dir = tmp_path / ".index" / "commit_manifests"
    manifests = sorted(manifest_dir.glob("*.json"))
    assert manifests, f"expected at least one manifest under {manifest_dir}"

    payload = json.loads(manifests[-1].read_text(encoding="utf-8"))
    assert payload["phase"] == "committed"
    assert payload["pages"], "page records must be persisted"
    record = payload["pages"]["concept-a"]
    assert record["phase"] == "committed"
    assert record["written_path"], "written_path must point to the persisted page file"
    assert record["revision_hash"], "revision_hash must be populated"
    assert (tmp_path / record["written_path"]).exists()
    # sha1 of the rendered body (Task 19 placeholder) — sanity check
    import hashlib as _hashlib
    body = _page("concept-a", "raw-a").body
    expected = _hashlib.sha1(body.encode("utf-8")).hexdigest()
    assert record["revision_hash"] == expected


def test_reconcile_unfinished_commits_handles_partial_state(tmp_path: Path) -> None:
    """``reconcile_unfinished_commits`` distinguishes two crash scenarios:

    * Scenario A — crash *before* publish: manifest is still ``PREPARED``
      with no page records. Reconcile must NOT force-commit; the caller
      must re-run ``commit_and_index``.
    * Scenario B — crash *after* publish / *before* index: page file is
      on disk + sha1 matches the recorded ``revision_hash``. Reconcile
      marks the page ``COMMITTED`` and the overall manifest ``RECONCILED``.
    """
    import hashlib as _hashlib
    from src.pipeline.v7_extract.commit_manifest import (
        CommitManifest,
        CommitPhase,
        PageCommitRecord,
        list_unfinished_manifests,
        manifest_dir,
        reconcile_unfinished_commits,
        write_manifest,
    )

    # ----- Scenario A: prepared but no pages written -----
    now_ms = 1_700_000_000_000
    manifest_a = CommitManifest(
        commit_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        source_id="raw-a",
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
        pipeline_fingerprint="",
        phase=CommitPhase.STAGING,
    )
    write_manifest(tmp_path, manifest_a)

    # ----- Scenario B: page file on disk, sha1 matches the recorded hash -----
    page_id = "concept-b"
    body = _page(page_id, "raw-b").body
    sha1 = _hashlib.sha1(body.encode("utf-8")).hexdigest()
    page_path = tmp_path / "wiki" / "concepts" / f"{page_id}.md"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(f"# {page_id}\nbody\n", encoding="utf-8")

    manifest_b = CommitManifest(
        commit_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        source_id="raw-b",
        created_at_ms=now_ms + 1,
        updated_at_ms=now_ms + 1,
        pipeline_fingerprint="",
        phase=CommitPhase.PUBLISHING,
        pages={
            page_id: PageCommitRecord(
                page_id=page_id,
                topic_id=page_id,
                source_paths=["raw-b"],
                phase=CommitPhase.COMMITTED,
                revision_hash=sha1,
                written_path=str(page_path),
                committed_at_ms=now_ms + 1,
            )
        },
    )
    write_manifest(tmp_path, manifest_b)

    # Sanity: both manifests are visible as unfinished.
    unfinished = list_unfinished_manifests(tmp_path)
    assert {m.commit_id for m in unfinished} == {
        manifest_a.commit_id,
        manifest_b.commit_id,
    }

    reconciled = reconcile_unfinished_commits(tmp_path)
    by_id = {m.commit_id: m for m in reconciled}

    a = by_id[manifest_a.commit_id]
    assert a.phase == CommitPhase.PREPARED  # crash before publish — not force-committed
    assert a.pages == {}

    b = by_id[manifest_b.commit_id]
    assert b.phase == CommitPhase.RECONCILED
    assert b.pages[page_id].phase == CommitPhase.COMMITTED

    # Persisted to disk too (reconcile must update the manifest file)
    on_disk = json.loads(
        (manifest_dir(tmp_path) / f"{manifest_b.commit_id}.json").read_text(encoding="utf-8")
    )
    assert on_disk["phase"] == "reconciled"
    assert on_disk["pages"][page_id]["phase"] == "committed"


def test_idempotent_page_commit_skips_when_revision_hash_matches(tmp_path: Path) -> None:
    """Running ``commit_and_index`` twice with the same pages must report the
    second batch as ``skipped`` (not ``written``) and leave the manifest's
    per-page phase at ``COMMITTED`` with a revision_hash matching the
    on-disk sha1.
    """
    import itertools as _itertools
    from src.pipeline.v7_extract.commit_manifest import (
        CommitManifest,
        CommitPhase,
        list_unfinished_manifests,
        manifest_dir,
    )

    counter = _itertools.count()

    def _factory() -> str:
        return f"commit-{next(counter):04d}-aaaa"

    writer = WikiWriter(tmp_path, commit_id_factory=_factory)
    pages = [_page("concept-a", "raw-a")]

    first = writer.commit_and_index(pages)
    second = writer.commit_and_index(pages)

    assert first.written == ["concept-a"]
    assert second.written == []
    assert second.skipped == ["concept-a"]

    manifests = list(manifest_dir(tmp_path).glob("*.json"))
    # Two distinct commits (one per call)
    assert len(manifests) == 2

    # Both manifests agree: concept-a is COMMITTED with a sha1 that matches
    # the on-disk file.
    import hashlib as _hashlib
    body = _page("concept-a", "raw-a").body
    expected_sha1 = _hashlib.sha1(body.encode("utf-8")).hexdigest()
    for path in manifests:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["phase"] == "committed"
        assert payload["pages"]["concept-a"]["phase"] == "committed"
        assert payload["pages"]["concept-a"]["revision_hash"] == expected_sha1

    # Both manifests are now terminal — list_unfinished_manifests is empty.
    assert list_unfinished_manifests(tmp_path) == []


# ---------------------------------------------------------------------------
# Task 20 (Stage 7 — page frontmatter ownership + revision_hash)
# ---------------------------------------------------------------------------


def _parse_page_frontmatter(path: Path) -> tuple[dict, str]:
    """Read a page file written by WikiWriter and split into (frontmatter, body).

    Frontmatter is the YAML block between the first pair of ``---`` lines;
    body is everything after the closing ``---``. The writer emits
    ``"---\\n<fm>---\\n\\n<body>"`` so two newlines sit between the closing
    fence and the body — strip them both before handing the body to callers
    so the bytes match what the writer actually hashed.
    """
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"page file missing YAML header: {path}"
    closing = text.find("\n---", 4)
    assert closing != -1, f"page file missing YAML closing fence: {path}"
    fm_block = text[4:closing]
    body = text[closing + 4 :]
    # The writer emits ``\n---\n\n<body>`` so two leading newlines need
    # to go — only then does ``body`` equal ``page.body``.
    while body.startswith("\n"):
        body = body[1:]
    frontmatter = yaml.safe_load(fm_block)
    assert isinstance(frontmatter, dict), "frontmatter must deserialize to a mapping"
    return frontmatter, body


def test_page_frontmatter_has_owner_v7(tmp_path: Path) -> None:
    """Every page written by WikiWriter carries the v7 ownership triple:
    ``owner``, ``pipeline`` (constants) and ``committed_at`` (per-write
    unix ms). Without these, downstream consumers (e.g. Tier B/C tooling)
    cannot tell which pipeline produced the page.
    """
    writer = WikiWriter(tmp_path)
    page = _page("concept-a", "raw-a")

    writer.commit_and_index([page])

    page_path = tmp_path / "wiki" / "concepts" / "concept-a.md"
    frontmatter, _ = _parse_page_frontmatter(page_path)

    assert frontmatter["owner"] == "v7"
    assert frontmatter["pipeline"] == "v7"
    committed_at = frontmatter["committed_at"]
    assert isinstance(committed_at, int)
    assert committed_at > 0


def test_page_frontmatter_has_revision_hash(tmp_path: Path) -> None:
    """``revision_hash`` is a sha1 of the rendered page with the hash
    field first serialised as ``""``. The two-pass dump must be
    byte-identical (same field order, same quoting, same Unicode flags)
    so the hash verification round-trips without human intervention.
    """
    writer = WikiWriter(tmp_path)
    page = _page("concept-a", "raw-a")

    writer.commit_and_index([page])

    page_path = tmp_path / "wiki" / "concepts" / "concept-a.md"
    frontmatter, body = _parse_page_frontmatter(page_path)

    actual_hash = frontmatter["revision_hash"]
    assert isinstance(actual_hash, str) and len(actual_hash) == 40

    # Reconstruct the byte stream the writer hashed:
    #   frontmatter_with_empty_hash + body
    # ``yaml.safe_dump`` settings must mirror the writer exactly so the
    # field order is preserved (sort_keys=False).
    fm_for_hash = dict(frontmatter)
    fm_for_hash["revision_hash"] = ""
    dumped = yaml.safe_dump(fm_for_hash, allow_unicode=True, sort_keys=False)
    expected = hashlib.sha1(dumped.encode("utf-8") + body.encode("utf-8")).hexdigest()
    assert actual_hash == expected


def test_page_frontmatter_has_pipeline_fingerprint(tmp_path: Path) -> None:
    """``pipeline_fingerprint`` is sourced from the WikiWriter constructor
    kwarg and must appear on every page (including pages written by a
    second ``commit_and_index`` call — idempotency must not drop the
    field).
    """
    writer = WikiWriter(tmp_path, pipeline_fingerprint="abc123")
    page = _page("concept-a", "raw-a")

    writer.commit_and_index([page])
    page_path = tmp_path / "wiki" / "concepts" / "concept-a.md"
    frontmatter, _ = _parse_page_frontmatter(page_path)
    assert frontmatter["pipeline_fingerprint"] == "abc123"

    # Second run (idempotent skip) — pipeline_fingerprint must still be
    # readable from the on-disk page file.
    writer.commit_and_index([page])
    frontmatter2, _ = _parse_page_frontmatter(page_path)
    assert frontmatter2["pipeline_fingerprint"] == "abc123"
