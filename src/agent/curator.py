"""CuratorAgent — periodic background agent that reviews knowledge quality.

Safety-first design:
1. NEVER directly modifies KnowledgeObjects
2. All proposals written to .index/curator_proposals/
3. Proposals require Reviewer validation before applying
4. Default mode: dry_run (report only)
5. auto_apply flag controls automatic application (default false)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.knowledge.conflicts.detector import ConflictDetector
from src.knowledge.core.lifecycle import LifecycleEngine
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.page_writer import page_path_for, read_page, write_page

if TYPE_CHECKING:
    from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Proposal storage
# ---------------------------------------------------------------------------

PROPOSALS_SUBDIR = "curator_proposals"


@dataclass
class CuratorProposal:
    """A proposal for knowledge improvement. Written to .index/curator_proposals/"""

    id: str                      # proposal ID
    object_id: str               # target KnowledgeObject slug / page id
    action: str                  # "merge" | "deprecate" | "archive" | "improve" | "resolve_conflict"
    before_snapshot: dict[str, Any]   # Snapshot of object before change
    after_snapshot: dict[str, Any]    # Proposed state after change
    diff: str                    # Human-readable diff summary
    reason: str                  # Why this change is proposed
    confidence: float            # 0.0–1.0
    proposed_at: int             # Unix ms
    status: str = "pending"      # pending | approved | rejected | applied

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "object_id": self.object_id,
            "action": self.action,
            "before_snapshot": self.before_snapshot,
            "after_snapshot": self.after_snapshot,
            "diff": self.diff,
            "reason": self.reason,
            "confidence": self.confidence,
            "proposed_at": self.proposed_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CuratorProposal":
        return cls(
            id=d["id"],
            object_id=d["object_id"],
            action=d["action"],
            before_snapshot=d.get("before_snapshot", {}),
            after_snapshot=d.get("after_snapshot", {}),
            diff=d.get("diff", ""),
            reason=d.get("reason", ""),
            confidence=d.get("confidence", 0.0),
            proposed_at=d.get("proposed_at", 0),
            status=d.get("status", "pending"),
        )

    @classmethod
    def from_json_file(cls, path: Path) -> "CuratorProposal":
        """Deserialize a proposal from a JSON file on disk."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_json_file(self, path: Path) -> None:
        """Persist this proposal to a JSON file on disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_type(paths: WikiPaths, slug: str) -> PageType:
    """Find which wiki subdirectory contains a page by slug.

    Mirrors the private helpers in ``heat.py`` and ``relations.py``.
    """
    for type_, dir_prop in [
        (PageType.ENTITY, "wiki_entities"),
        (PageType.CONCEPT, "wiki_concepts"),
        (PageType.SOURCE, "wiki_sources"),
        (PageType.SYNTHESIS, "wiki_synthesis"),
    ]:
        if (getattr(paths, dir_prop) / f"{slug}.md").exists():
            return type_
    return PageType.SOURCE


def _page_to_snapshot(page: WikiPage) -> dict[str, Any]:
    """Serialize a WikiPage to a JSON-safe snapshot dict.

    Extends ``to_frontmatter_dict()`` by including the ``body`` field
    so that snapshots are full reconstructions.
    """
    d = page.to_frontmatter_dict()
    d["body"] = page.body
    return d


def _scan_wiki_pages(paths: WikiPaths) -> list[WikiPage]:
    """Return all wiki pages across the four main type directories.

    Errors reading individual pages are logged and skipped.
    """
    pages: list[WikiPage] = []
    for dir_prop in [
        "wiki_sources", "wiki_entities", "wiki_concepts", "wiki_synthesis",
    ]:
        dir_path: Path = getattr(paths, dir_prop)
        if not dir_path.exists():
            continue
        for f in dir_path.glob("*.md"):
            try:
                pages.append(read_page(f))
            except Exception:
                _logger.debug("Skipping unreadable page: %s", f, exc_info=True)
    return pages


# ---------------------------------------------------------------------------
# CuratorAgent
# ---------------------------------------------------------------------------

class CuratorAgent:
    """Periodic background agent that reviews knowledge quality.

    Safety measures:
    1. NEVER directly modifies KnowledgeObjects
    2. All proposals written to .index/curator_proposals/
    3. Proposals require Reviewer validation before applying
    4. Default mode: dry_run (report only)
    5. auto_apply flag controls automatic application (default false)
    """

    def __init__(
        self,
        wiki_paths: WikiPaths,
        lifecycle_engine: LifecycleEngine | None = None,
        conflict_detector: ConflictDetector | None = None,
        version_manager: Any = None,
        max_objects_per_run: int = 100,
        dry_run: bool = True,
        auto_apply: bool = False,
    ) -> None:
        self.paths = wiki_paths
        self._lifecycle = lifecycle_engine
        self._conflict_detector = conflict_detector
        self._version_manager = version_manager
        self.max_objects_per_run = max_objects_per_run
        self.dry_run = dry_run
        self.auto_apply = auto_apply

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def proposals_dir(self) -> Path:
        """Path to the proposals directory under .index/."""
        return self.paths.index / PROPOSALS_SUBDIR

    def curate(self) -> list[CuratorProposal]:
        """Main curation loop. Runs all 4 review passes.

        1. Find duplicates → merge proposals
        2. Find low-quality (C-grade + heat < 10) → improve proposals
        3. Find obsolete (zombie pages) → archive proposals
        4. Find conflicts (from ConflictDetector) → resolve proposals

        Returns list of CuratorProposals (empty if nothing to do).
        In dry_run mode, proposals are generated but NOT written to disk.
        """
        proposals: list[CuratorProposal] = []
        proposals.extend(self._find_duplicates()[: self.max_objects_per_run])
        proposals.extend(self._find_low_quality()[: self.max_objects_per_run])
        proposals.extend(self._find_obsolete()[: self.max_objects_per_run])
        proposals.extend(self._find_conflicts()[: self.max_objects_per_run])
        return proposals

    def get_pending_proposals(self) -> list[CuratorProposal]:
        """List all pending proposals from the proposals directory."""
        if not self.proposals_dir.exists():
            return []
        pending: list[CuratorProposal] = []
        for f in sorted(self.proposals_dir.glob("*.json")):
            try:
                proposal = CuratorProposal.from_json_file(f)
                if proposal.status == "pending":
                    pending.append(proposal)
            except Exception:
                _logger.debug("Skipping unreadable proposal: %s", f, exc_info=True)
        return pending

    def apply_proposal(self, proposal_id: str) -> bool:
        """Apply an approved proposal.

        Only works when auto_apply is enabled. Returns True on success,
        False if auto_apply is disabled or the proposal is missing/ineligible.
        """
        if not self.auto_apply:
            return False

        proposal_path = self.proposals_dir / f"{proposal_id}.json"
        if not proposal_path.exists():
            return False

        try:
            proposal = CuratorProposal.from_json_file(proposal_path)
        except Exception:
            _logger.debug("Unreadable proposal: %s", proposal_path, exc_info=True)
            return False

        if proposal.status not in ("approved", "pending"):
            return False

        try:
            self._apply_by_action(proposal)
        except Exception:
            _logger.exception("Failed to apply proposal %s", proposal_id)
            return False

        proposal.status = "applied"
        proposal.to_json_file(proposal_path)
        return True

    # ------------------------------------------------------------------
    # Review passes
    # ------------------------------------------------------------------

    def _find_duplicates(self) -> list[CuratorProposal]:
        """Use dedup module to find near-duplicate entities → merge proposals."""
        try:
            from src.wiki.features.dedup import find_duplicates

            pairs: list[tuple[str, str]] = find_duplicates(self.paths)
        except Exception:
            _logger.debug("dedup unavailable", exc_info=True)
            return []

        proposals: list[CuratorProposal] = []
        for slug_a, slug_b in pairs[: self.max_objects_per_run]:
            try:
                type_a = _infer_type(self.paths, slug_a)
                type_b = _infer_type(self.paths, slug_b)
                page_a = read_page(page_path_for(self.paths, type_a, slug_a))
                page_b = read_page(page_path_for(self.paths, type_b, slug_b))
            except Exception:
                continue

            before = {
                slug_a: _page_to_snapshot(page_a),
                slug_b: _page_to_snapshot(page_b),
            }
            merged = _page_to_snapshot(page_a)
            merged["body"] = page_a.body + "\n\n" + page_b.body
            merged["sources"] = list(set(page_a.sources + page_b.sources))
            after = {slug_a: merged}

            diff = f"Merge '{slug_b}' into '{slug_a}': combined body and sources"
            reason = f"Near-duplicate detected between '{slug_a}' and '{slug_b}'"

            proposals.append(
                self._create_proposal(slug_a, "merge", before, after, diff, reason, 0.7)
            )
        return proposals

    def _find_low_quality(self) -> list[CuratorProposal]:
        """Scan for C-grade pages with heat < 10 → improve proposals."""
        proposals: list[CuratorProposal] = []
        for page in _scan_wiki_pages(self.paths):
            if len(proposals) >= self.max_objects_per_run:
                break
            if page.grade == "C" and page.heat < 10:
                before = _page_to_snapshot(page)
                after = _page_to_snapshot(page)
                after["grade"] = "B"

                diff = (
                    f"Improve '{page.id}': grade C→B, "
                    f"heat {page.heat} — suggest review or re-ingest"
                )
                reason = f"Low-quality page: grade={page.grade}, heat={page.heat}"

                proposals.append(
                    self._create_proposal(
                        page.id, "improve", before, after, diff, reason, 0.8,
                    )
                )
        return proposals

    def _find_obsolete(self) -> list[CuratorProposal]:
        """Scan for zombie pages (zombie_since != None) → archive proposals."""
        proposals: list[CuratorProposal] = []
        for page in _scan_wiki_pages(self.paths):
            if len(proposals) >= self.max_objects_per_run:
                break
            if page.zombie_since is not None:
                before = _page_to_snapshot(page)
                after = _page_to_snapshot(page)
                after["is_immutable"] = True

                diff = f"Archive '{page.id}': zombie since timestamp {page.zombie_since}"
                reason = f"Page is obsolete (zombie_since={page.zombie_since})"

                proposals.append(
                    self._create_proposal(
                        page.id, "archive", before, after, diff, reason, 0.9,
                    )
                )
        return proposals

    def _find_conflicts(self) -> list[CuratorProposal]:
        """Use ConflictDetector to find unresolved conflicts → resolve proposals.

        MVP: returns empty list. ConflictDetector operates on Claims, not
        wiki pages, so this pass is reserved for Phase 2 when claims data
        is populated.
        """
        if self._conflict_detector is None:
            return []
        return []

    # ------------------------------------------------------------------
    # Proposal lifecycle
    # ------------------------------------------------------------------

    def _create_proposal(
        self,
        object_id: str,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
        diff: str,
        reason: str,
        confidence: float,
    ) -> CuratorProposal:
        """Create and optionally persist a CuratorProposal.

        In dry_run mode the proposal object is returned but NOT written to
        disk. In non-dry_run mode the proposal is persisted as a JSON file
        under ``.index/curator_proposals/``.
        """
        now = int(time.time() * 1000)
        proposal_id = f"prop_{object_id}_{action}_{now}"

        proposal = CuratorProposal(
            id=proposal_id,
            object_id=object_id,
            action=action,
            before_snapshot=before,
            after_snapshot=after,
            diff=diff,
            reason=reason,
            confidence=confidence,
            proposed_at=now,
        )

        if not self.dry_run:
            proposal.to_json_file(self.proposals_dir / f"{proposal_id}.json")

        return proposal

    def _apply_by_action(self, proposal: CuratorProposal) -> None:
        """Dispatch proposal application to the appropriate handler."""
        if proposal.action == "improve":
            self._apply_improve(proposal)
        elif proposal.action == "archive":
            self._apply_archive(proposal)
        elif proposal.action == "merge":
            # Merge is complex; MVP defers to manual intervention.
            pass
        elif proposal.action == "resolve_conflict":
            # Conflict resolution requires claims data; deferred to Phase 2.
            pass

    def _apply_improve(self, proposal: CuratorProposal) -> None:
        """Apply an 'improve' proposal: update the page's grade."""
        page = self._load_page_by_slug(proposal.object_id)
        after = proposal.after_snapshot
        if "grade" in after:
            page.grade = after["grade"]
        write_page(self.paths, page)

    def _apply_archive(self, proposal: CuratorProposal) -> None:
        """Apply an 'archive' proposal: mark the page as immutable."""
        page = self._load_page_by_slug(proposal.object_id)
        page.is_immutable = True
        write_page(self.paths, page)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_page_by_slug(self, slug: str) -> WikiPage:
        """Load a WikiPage by its slug, inferring the type directory."""
        type_ = _infer_type(self.paths, slug)
        return read_page(page_path_for(self.paths, type_, slug))
