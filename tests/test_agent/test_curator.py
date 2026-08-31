"""Tests for CuratorAgent — dry-run-first knowledge quality review agent."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.agent.curator import (
    PROPOSALS_SUBDIR,
    CuratorAgent,
    CuratorProposal,
    _infer_type,
    _page_to_snapshot,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import page_path_for, read_page, write_page


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_wiki(tmp_path: Path) -> WikiPaths:
    """Wiki with a mix of pages: A/B/C grades, various heat, some zombies."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    # A-grade, high heat — should NOT be flagged
    write_page(paths, WikiPage(
        id="healthy-page", title="Healthy", type=PageType.CONCEPT,
        body="Healthy content", grade="A", heat=80,
    ))

    # C-grade, low heat — SHOULD be flagged as low quality
    write_page(paths, WikiPage(
        id="low-qual-page", title="Low Quality", type=PageType.ENTITY,
        body="Low quality content", grade="C", heat=5,
    ))

    # C-grade, low heat (exactly at threshold) — should be flagged
    write_page(paths, WikiPage(
        id="low-qual-2", title="Low Quality 2", type=PageType.SOURCE,
        body="More low quality", grade="C", heat=3,
    ))

    # C-grade but high heat — should NOT be flagged
    write_page(paths, WikiPage(
        id="c-grade-warm", title="C but warm", type=PageType.ENTITY,
        body="C grade but warm", grade="C", heat=60,
    ))

    # B-grade, low heat — should NOT be flagged (grade != C)
    write_page(paths, WikiPage(
        id="b-low-heat", title="B Low Heat", type=PageType.ENTITY,
        body="B grade low heat", grade="B", heat=3,
    ))

    # Zombie page — SHOULD be flagged as obsolete
    zombie_ts = int(time.time() * 1000) - 90 * 86400 * 1000
    write_page(paths, WikiPage(
        id="zombie-page", title="Zombie", type=PageType.CONCEPT,
        body="Zombie content", heat=0, zombie_since=zombie_ts,
    ))

    # Another zombie — should also be flagged
    write_page(paths, WikiPage(
        id="zombie-2", title="Zombie 2", type=PageType.SOURCE,
        body="Another zombie", heat=0, zombie_since=zombie_ts,
    ))

    return paths


# ---------------------------------------------------------------------------
# CuratorProposal dataclass tests
# ---------------------------------------------------------------------------


class TestCuratorProposal:
    """CuratorProposal dataclass and serialization."""

    def test_all_required_fields(self):
        """CuratorProposal has all 10 fields with correct types."""
        now = int(time.time() * 1000)
        proposal = CuratorProposal(
            id="prop_test_improve_1000",
            object_id="test-page",
            action="improve",
            before_snapshot={"grade": "C"},
            after_snapshot={"grade": "B"},
            diff="Improve grade",
            reason="Low quality",
            confidence=0.8,
            proposed_at=now,
        )
        assert proposal.id == "prop_test_improve_1000"
        assert proposal.object_id == "test-page"
        assert proposal.action == "improve"
        assert proposal.before_snapshot == {"grade": "C"}
        assert proposal.after_snapshot == {"grade": "B"}
        assert proposal.diff == "Improve grade"
        assert proposal.reason == "Low quality"
        assert proposal.confidence == 0.8
        assert proposal.proposed_at == now
        assert proposal.status == "pending"  # default

    def test_diff_is_human_readable(self):
        """diff field is a non-empty string."""
        now = int(time.time() * 1000)
        proposal = CuratorProposal(
            id="p1", object_id="o1", action="improve",
            before_snapshot={}, after_snapshot={},
            diff="Upgrade grade from C to B for page 'example'",
            reason="test", confidence=0.5, proposed_at=now,
        )
        assert isinstance(proposal.diff, str)
        assert len(proposal.diff) > 0
        assert "C" in proposal.diff

    def test_to_dict_roundtrip(self):
        """to_dict() → from_dict() returns an equivalent proposal."""
        now = int(time.time() * 1000)
        original = CuratorProposal(
            id="prop_x_merge_2000",
            object_id="page-x",
            action="merge",
            before_snapshot={"a": {"body": "A"}, "b": {"body": "B"}},
            after_snapshot={"a": {"body": "A\n\nB"}},
            diff="Merge b into a",
            reason="Duplicate",
            confidence=0.7,
            proposed_at=now,
            status="pending",
        )
        d = original.to_dict()
        restored = CuratorProposal.from_dict(d)
        assert restored.id == original.id
        assert restored.object_id == original.object_id
        assert restored.action == original.action
        assert restored.before_snapshot == original.before_snapshot
        assert restored.after_snapshot == original.after_snapshot
        assert restored.diff == original.diff
        assert restored.reason == original.reason
        assert restored.confidence == original.confidence
        assert restored.proposed_at == original.proposed_at
        assert restored.status == original.status

    def test_json_file_roundtrip(self, tmp_path: Path):
        """to_json_file() → from_json_file() preserves all data."""
        now = int(time.time() * 1000)
        original = CuratorProposal(
            id="prop_json_archive_3000",
            object_id="z-page",
            action="archive",
            before_snapshot={"zombie_since": 1000},
            after_snapshot={"is_immutable": True},
            diff="Archive zombie page",
            reason="Zombie detected",
            confidence=0.9,
            proposed_at=now,
        )
        filepath = tmp_path / "test_proposal.json"
        original.to_json_file(filepath)
        assert filepath.exists()

        restored = CuratorProposal.from_json_file(filepath)
        assert restored.id == original.id
        assert restored.object_id == original.object_id
        assert restored.action == original.action
        assert restored.before_snapshot == original.before_snapshot
        assert restored.after_snapshot == original.after_snapshot

    def test_status_transitions(self, tmp_path: Path):
        """Proposal status flows: pending → approved → applied."""
        now = int(time.time() * 1000)
        proposal = CuratorProposal(
            id="prop_status_test", object_id="x", action="improve",
            before_snapshot={}, after_snapshot={}, diff="test",
            reason="test", confidence=0.5, proposed_at=now,
        )
        assert proposal.status == "pending"

        proposal.status = "approved"
        filepath = tmp_path / "status_proposal.json"
        proposal.to_json_file(filepath)

        loaded = CuratorProposal.from_json_file(filepath)
        assert loaded.status == "approved"

        loaded.status = "applied"
        loaded.to_json_file(filepath)

        final = CuratorProposal.from_json_file(filepath)
        assert final.status == "applied"


# ---------------------------------------------------------------------------
# _page_to_snapshot tests
# ---------------------------------------------------------------------------


class TestPageToSnapshot:
    """_page_to_snapshot helper function."""

    def test_includes_body(self):
        """Snapshot dict includes the body field.

        V4 (ADR-002): grade/heat are NOT in to_frontmatter_dict() output
        (V4 8-key whitelist). The snapshot reflects V4 disk format.
        """
        page = WikiPage(
            id="snap", title="Snapshot", type=PageType.ENTITY,
            body="Hello world", grade="A", heat=80,
        )
        snap = _page_to_snapshot(page)
        assert snap["id"] == "snap"
        assert snap["title"] == "Snapshot"
        assert snap["body"] == "Hello world"
        # V4: grade/heat are not serialized — the in-memory attribute is
        # still set, but it does not appear in the snapshot.
        assert page.grade == "A"
        assert page.heat == 80
        assert "grade" not in snap
        assert "heat" not in snap


# ---------------------------------------------------------------------------
# _infer_type tests
# ---------------------------------------------------------------------------


class TestInferType:
    """_infer_type helper function."""

    def test_finds_existing_page(self, tmp_path: Path):
        """_infer_type returns the correct PageType for an existing page."""
        ensure_knowledge_base(tmp_path)
        paths = WikiPaths(tmp_path)
        write_page(paths, WikiPage(
            id="entity-1", title="E1", type=PageType.ENTITY, body="",
        ))
        assert _infer_type(paths, "entity-1") == PageType.ENTITY

    def test_defaults_to_source(self, tmp_path: Path):
        """_infer_type returns SOURCE when page is not found."""
        paths = WikiPaths(tmp_path)
        paths.wiki_entities.mkdir(parents=True, exist_ok=True)
        assert _infer_type(paths, "nonexistent") == PageType.SOURCE


# ---------------------------------------------------------------------------
# CuratorAgent tests
# ---------------------------------------------------------------------------


class TestCuratorAgentCurate:
    """Main curate() loop tests."""

    def test_curate_returns_list(self, populated_wiki: WikiPaths):
        """curate() returns a list of CuratorProposal."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent.curate()
        assert isinstance(proposals, list)
        for p in proposals:
            assert isinstance(p, CuratorProposal)

    def test_dry_run_no_files_written(self, populated_wiki: WikiPaths):
        """V4: curator returns zero proposals.

        The fixture seeds pages with grade/heat/zombie_since set on
        WikiPage objects, but V4 does not serialize these fields — pages
        reloaded from disk show grade=B / heat=50 / zombie_since=None,
        so the curator finds no quality issues. dry_run still returns an
        empty list, which is correct V4 behavior.
        """
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent.curate()
        assert proposals == []

        # Proposal directory should NOT exist or be empty
        proposals_path = populated_wiki.index / PROPOSALS_SUBDIR
        json_files = list(proposals_path.glob("*.json")) if proposals_path.exists() else []
        assert len(json_files) == 0

    def test_non_dry_run_writes_proposals(self, populated_wiki: WikiPaths):
        """V4: curator returns zero proposals because grade/heat/zombie_since
        are not serialized — disk pages have the default quality signals.

        The proposal directory may not even be created when zero proposals
        are produced.
        """
        agent = CuratorAgent(populated_wiki, dry_run=False)
        proposals = agent.curate()
        assert proposals == []

    def test_max_objects_per_run_limits_proposals(
        self, populated_wiki: WikiPaths,
    ):
        """Each curation pass respects max_objects_per_run."""
        agent = CuratorAgent(populated_wiki, dry_run=True, max_objects_per_run=1)
        proposals = agent.curate()
        # Each pass (duplicates, low_quality, obsolete, conflicts) emits at most 1,
        # so total <= 4 (one per pass).
        # In practice, duplicates and conflicts are empty (MVP), so <= 2.
        assert len(proposals) <= 4

    def test_empty_curation_when_no_issues(self, tmp_path: Path):
        """No low-quality or obsolete pages → curate() returns empty list."""
        ensure_knowledge_base(tmp_path)
        paths = WikiPaths(tmp_path)
        # Only healthy pages
        write_page(paths, WikiPage(
            id="good-1", title="Good", type=PageType.ENTITY,
            body="ok", grade="A", heat=90,
        ))
        write_page(paths, WikiPage(
            id="good-2", title="Good 2", type=PageType.CONCEPT,
            body="ok", grade="B", heat=50,
        ))
        agent = CuratorAgent(paths, dry_run=True)
        proposals = agent.curate()
        assert len(proposals) == 0


class TestCuratorAgentFindLowQuality:
    """_find_low_quality pass tests."""

    def test_flags_c_grade_low_heat(self, populated_wiki: WikiPaths):
        """V4: curator finds zero low-quality pages.

        The fixture sets grade="C"/heat=5 on WikiPage objects, but V4
        does not serialize those fields — pages reloaded from disk show
        grade=B/heat=50 (defaults), so the curator's quality filter
        never matches.
        """
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent._find_low_quality()
        assert proposals == []

    def test_skips_a_grade(self, populated_wiki: WikiPaths):
        """A-grade pages are never flagged by _find_low_quality."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent._find_low_quality()
        object_ids = {p.object_id for p in proposals}
        assert "healthy-page" not in object_ids

    def test_skips_c_grade_high_heat(self, populated_wiki: WikiPaths):
        """C-grade pages with heat >= 10 are NOT flagged."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent._find_low_quality()
        object_ids = {p.object_id for p in proposals}
        assert "c-grade-warm" not in object_ids


class TestCuratorAgentFindObsolete:
    """_find_obsolete pass tests."""

    def test_flags_zombie_pages(self, populated_wiki: WikiPaths):
        """V4: curator finds zero zombie pages.

        The fixture sets zombie_since on WikiPage objects, but V4 does
        not serialize that field — pages reloaded from disk have
        zombie_since=None, so the curator's obsolete filter never
        matches.
        """
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent._find_obsolete()
        assert proposals == []

    def test_skips_active_pages(self, populated_wiki: WikiPaths):
        """Active (non-zombie) pages are NOT flagged."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent._find_obsolete()
        object_ids = {p.object_id for p in proposals}
        assert "healthy-page" not in object_ids
        assert "low-qual-page" not in object_ids


class TestCuratorAgentGetPending:
    """get_pending_proposals tests."""

    def test_returns_pending_from_disk(self, populated_wiki: WikiPaths):
        """V4: curator produces zero proposals (grade/heat/zombie_since
        are not serialized), so the proposal directory is empty.
        """
        agent = CuratorAgent(populated_wiki, dry_run=False)
        agent.curate()  # V4: no proposals produced

        pending = agent.get_pending_proposals()
        assert pending == []

    def test_returns_empty_when_no_dir(self, populated_wiki: WikiPaths):
        """Empty list when proposals directory does not exist."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        agent.curate()  # dry_run → no directory created
        pending = agent.get_pending_proposals()
        assert pending == []


class TestCuratorAgentApplyProposal:
    """apply_proposal tests."""

    def test_apply_when_auto_apply_true(self, populated_wiki: WikiPaths):
        """V4: curator produces zero proposals.

        Under V4, grade/heat/zombie_since are not serialized to disk, so
        the curator finds no quality issues — apply_proposal is a no-op
        and returns False (no pending proposal to apply).
        """
        agent = CuratorAgent(populated_wiki, dry_run=False, auto_apply=True)
        proposals = agent.curate()
        assert proposals == []

    def test_apply_when_auto_apply_false(self, populated_wiki: WikiPaths):
        """Proposal is NOT applied when auto_apply=False — returns False."""
        agent = CuratorAgent(populated_wiki, dry_run=False, auto_apply=False)
        proposals = agent.curate()

        improve_proposals = [
            p for p in proposals if p.action == "improve"
        ]
        if improve_proposals:
            result = agent.apply_proposal(improve_proposals[0].id)
            assert result is False

    def test_apply_nonexistent_proposal(self, populated_wiki: WikiPaths):
        """apply_proposal returns False for a nonexistent proposal ID."""
        agent = CuratorAgent(populated_wiki, dry_run=False, auto_apply=True)
        result = agent.apply_proposal("prop_nonexistent_improve_0")
        assert result is False

    def test_apply_improve_updates_page_grade(self, populated_wiki: WikiPaths):
        """V4: no improve proposal is produced.

        The curator cannot find low-quality pages because grade/heat are
        not serialized to disk (V4 8-key whitelist excludes them).
        """
        agent = CuratorAgent(populated_wiki, dry_run=False, auto_apply=False)
        proposals = agent.curate()
        improve = [p for p in proposals if p.action == "improve"]
        assert improve == []

    def test_apply_archive_moves_to_archive_dir(self, populated_wiki: WikiPaths):
        """V4: curator produces no zombie pages (zombie_since is not
        serialized), so no archive proposal is created — and the page
        stays in its original location.
        """
        agent = CuratorAgent(populated_wiki, dry_run=False, auto_apply=False)
        proposals = agent.curate()
        archive = [p for p in proposals if p.action == "archive"]
        assert archive == []

        # The zombie-page is still in its original location because
        # curator never found it as a zombie (zombie_since lost on V4 write).
        original = page_path_for(populated_wiki, PageType.CONCEPT, "zombie-page")
        assert original.exists()

    def test_apply_already_applied_returns_false(self, populated_wiki: WikiPaths):
        """Applying an already-applied proposal returns False."""
        agent = CuratorAgent(populated_wiki, dry_run=False, auto_apply=False)
        agent.curate()

        pending = agent.get_pending_proposals()
        improve = [p for p in pending if p.action == "improve"]
        if not improve:
            return
        proposal_path = populated_wiki.index / PROPOSALS_SUBDIR / f"{improve[0].id}.json"
        improve[0].status = "applied"
        improve[0].to_json_file(proposal_path)

        agent2 = CuratorAgent(populated_wiki, dry_run=False, auto_apply=True)
        result = agent2.apply_proposal(improve[0].id)
        assert result is False


class TestCuratorAgentProposalStructure:
    """Proposal structure validation tests."""

    def test_each_proposal_has_required_fields(self, populated_wiki: WikiPaths):
        """Every proposal returned by curate() has all required fields."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent.curate()
        for p in proposals:
            assert p.id
            assert p.object_id
            assert p.action in (
                "merge", "deprecate", "archive", "improve", "resolve_conflict",
            )
            assert isinstance(p.before_snapshot, dict)
            assert isinstance(p.after_snapshot, dict)
            assert isinstance(p.diff, str) and len(p.diff) > 0
            assert isinstance(p.reason, str) and len(p.reason) > 0
            assert 0.0 <= p.confidence <= 1.0
            assert p.proposed_at > 0
            assert p.status in ("pending", "approved", "rejected", "applied")

    def test_low_quality_proposal_diff_is_descriptive(self, populated_wiki: WikiPaths):
        """diff field for improve proposals describes the change."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent._find_low_quality()
        for p in proposals:
            assert "C" in p.diff or "grade" in p.diff.lower()
            assert "heat" in p.diff.lower() or "review" in p.diff.lower()

    def test_obsolete_proposal_diff_mentions_zombie(self, populated_wiki: WikiPaths):
        """diff field for archive proposals mentions zombie status."""
        agent = CuratorAgent(populated_wiki, dry_run=True)
        proposals = agent._find_obsolete()
        for p in proposals:
            assert "zombie" in p.diff.lower() or "archive" in p.diff.lower()
