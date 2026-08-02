"""CandidatePromoter — Candidate to KnowledgeObject bridge.

Converts a VALIDATED KnowledgeCandidate into a KnowledgeObject with
lifecycle=PROCESSING.  Does NOT write files — KnowledgeObject is persisted
later by commit_ingest.
"""
from __future__ import annotations

import time

from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
)


class CandidatePromoter:
    """Converts a VALIDATED KnowledgeCandidate into a KnowledgeObject.

    Candidate and KnowledgeObject share the same ID.  The candidate's status
    is mutated to PROMOTED on success.
    """

    def promote(self, candidate: KnowledgeCandidate) -> KnowledgeObject:
        """Promote a VALIDATED candidate to a KnowledgeObject.

        Args:
            candidate: A KnowledgeCandidate with status == VALIDATED.

        Returns:
            A new KnowledgeObject with lifecycle == PROCESSING.

        Raises:
            ValueError: If candidate.status is not VALIDATED.
        """
        if candidate.status != CandidateStatus.VALIDATED:
            raise ValueError(
                f"Cannot promote candidate {candidate.id!r}: "
                f"expected status VALIDATED, got {candidate.status.value!r}"
            )

        now_ms = int(time.time() * 1000)

        obj = KnowledgeObject(
            id=candidate.id,
            type=candidate.type,
            title=candidate.title,
            content="",
            lifecycle=LifecycleState.PROCESSING,
            confidence=candidate.confidence,
            provenance=Provenance(
                source_path=candidate.source_id,
                page=None,
                quote="",
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
                    change_description="created from candidate",
                )
            ],
            created_at=now_ms,
            updated_at=now_ms,
        )

        # Mutate candidate status to PROMOTED (terminal)
        candidate.status = CandidateStatus.PROMOTED

        return obj
