"""ClaimExtractorStage — extract structured Claims from validated candidates.

Sits after Analyzer (JSON output mode) + Reviewer. Listens for the
``candidate:validated`` event, runs ClaimParser on the candidate, converts
each Claim to a KnowledgeObject → WikiPage, writes to ``wiki/claims/``,
and emits ``claims:extracted`` with the results.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from src.events.event_bus import event_bus
from src.knowledge.claims.model import Claim, ClaimType, Evidence
from src.knowledge.claims.parser import ClaimParser
from src.knowledge.core.adapter import knowledge_object_to_wiki_page
from src.knowledge.core.candidate import KnowledgeCandidate
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import WikiPage

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event names
# ---------------------------------------------------------------------------

CANDIDATE_VALIDATED_EVENT = "candidate:validated"
CLAIMS_EXTRACTED_EVENT = "claims:extracted"


# ---------------------------------------------------------------------------
# ClaimExtractorStage
# ---------------------------------------------------------------------------


class ClaimExtractorStage:
    """Extracts structured Claims from Analyzer JSON output via ClaimParser.

    Only activates when analyzer output_format is ``"json"`` (the Analyzer
    returns a KnowledgeCandidate, not an AnalysisResult).  The Analyzer
    prompt is UNCHANGED — ClaimParser does the post-processing.

    Two modes of use:

    1. **Direct call** — ``extract(candidate)`` + ``store_claims(claims, paths)``
       for programmatic / test use.

    2. **EventBus handler** — register via :meth:`register` to listen for
       ``candidate:validated`` events. When fired, claims are extracted and
       stored automatically, and a ``claims:extracted`` event is emitted.
    """

    def __init__(self, claim_parser: ClaimParser | None = None):
        self.parser = claim_parser or ClaimParser()
        self._registered = False

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def extract(self, candidate: KnowledgeCandidate) -> list[Claim]:
        """Run ClaimParser on a VALIDATED candidate. Returns structured Claims."""
        return self.parser.extract(candidate)

    def claim_to_knowledge_object(self, claim: Claim) -> KnowledgeObject:
        """Convert a single Claim to a KnowledgeObject(type=claim).

        The claim's ``statement`` becomes the title (truncated to 80 chars).
        Evidence and metadata become the markdown body.
        """
        now_ms = int(time.time() * 1000)

        # Build evidence section
        evidence_md = ""
        if claim.evidence:
            for i, ev in enumerate(claim.evidence):
                page_str = f" (page {ev.page})" if ev.page is not None else ""
                evidence_md += f"- 来源: `{ev.source_path}`{page_str}\n"
                if ev.quote:
                    evidence_md += f"  > {ev.quote}\n"
                evidence_md += "\n"
        else:
            evidence_md = "(无证据)\n\n"

        # Build source objects section
        sources_md = "\n".join(f"- `{s}`" for s in claim.source_objects) if claim.source_objects else "(无)"

        body = (
            f"## 声明\n\n{claim.statement}\n\n"
            f"## 元数据\n\n"
            f"- **类型:** {claim.type.value}\n"
            f"- **置信度:** {claim.confidence}\n"
            f"- **状态:** {claim.status.value}\n"
            f"- **来源对象:** \n{sources_md}\n\n"
            f"## 证据\n\n{evidence_md}"
        )

        return KnowledgeObject(
            id=claim.id,
            type=KnowledgeType.CLAIM,
            title=claim.statement[:80],
            content=body,
            lifecycle=LifecycleState.CREATED,
            confidence=claim.confidence,
            provenance=Provenance(
                source_path=claim.source_objects[0] if claim.source_objects else "",
                ingested_at=now_ms,
                ingestor_version="2.0.0",
            ),
            grade="B",
            heat=50,
            relations=[],
            versions=[
                VersionRef(
                    version_id="v1",
                    timestamp=now_ms,
                    change_description="extracted from candidate claim",
                )
            ],
            created_at=claim.created_at or now_ms,
            updated_at=claim.updated_at or now_ms,
        )

    def store_claims(
        self,
        claims: list[Claim],
        paths: WikiPaths,
    ) -> list[WikiPage]:
        """Convert claims to KnowledgeObjects → WikiPages and write to disk.

        Each claim becomes a ``wiki/claims/<claim_id>.md`` page via
        :func:`knowledge_object_to_wiki_page` + :func:`write_page`.

        Returns the list of written WikiPage objects.
        """
        from src.wiki.storage.page_writer import write_page

        pages: list[WikiPage] = []
        for claim in claims:
            ko = self.claim_to_knowledge_object(claim)
            wp = knowledge_object_to_wiki_page(ko)
            write_page(paths, wp)
            pages.append(wp)

        _logger.info(
            "ClaimExtractorStage: stored %d claim page(s) in %s",
            len(pages), paths.wiki_claims,
        )
        return pages

    # ------------------------------------------------------------------
    # EventBus integration
    # ------------------------------------------------------------------

    def handle_candidate_validated(self, payload: dict) -> None:
        """EventBus handler for ``candidate:validated``.

        Expected payload keys:
        - ``candidate``: KnowledgeCandidate (status == VALIDATED)
        - ``paths``: WikiPaths for the project
        """
        candidate = payload.get("candidate")
        paths = payload.get("paths")

        if not isinstance(candidate, KnowledgeCandidate):
            _logger.warning(
                "ClaimExtractorStage: candidate:validated payload missing "
                "'candidate' or wrong type"
            )
            return

        if not isinstance(paths, WikiPaths):
            _logger.warning(
                "ClaimExtractorStage: candidate:validated payload missing "
                "'paths' or wrong type"
            )
            return

        claims = self.extract(candidate)
        if not claims:
            _logger.debug(
                "ClaimExtractorStage: no claims extracted from candidate %s",
                candidate.id,
            )
            event_bus.emit(CLAIMS_EXTRACTED_EVENT, {"claims": [], "pages": []})
            return

        pages = self.store_claims(claims, paths)
        event_bus.emit(
            CLAIMS_EXTRACTED_EVENT,
            {"claims": claims, "pages": pages, "candidate_id": candidate.id},
        )

    def register(self) -> None:
        """Register the event handler on the global EventBus. Idempotent."""
        if self._registered:
            return
        event_bus.on(CANDIDATE_VALIDATED_EVENT, self.handle_candidate_validated)
        self._registered = True
        _logger.debug(
            "ClaimExtractorStage: registered handler for %s",
            CANDIDATE_VALIDATED_EVENT,
        )

    def unregister(self) -> None:
        """Remove the event handler from the global EventBus."""
        if not self._registered:
            return
        event_bus.off(CANDIDATE_VALIDATED_EVENT, self.handle_candidate_validated)
        self._registered = False
