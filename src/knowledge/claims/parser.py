"""ClaimParser — Phase 1 opaque dicts to Phase 2 structured Claims bridge."""
import logging
import time

from src.knowledge.claims.model import Claim, ClaimStatus, ClaimType, Evidence
from src.knowledge.core.candidate import KnowledgeCandidate

logger = logging.getLogger(__name__)


class ClaimParser:
    """Convert KnowledgeCandidate opaque dicts into structured Claim objects.

    This is the sole bridge between Phase 1 (opaque list[dict] claims + evidence)
    and Phase 2 (structured Claim + Evidence dataclasses). The Analyzer prompt
    does not yet classify claim types (that's Phase 4), so all claims default
    to FACT and PENDING.
    """

    @staticmethod
    def extract(candidate: KnowledgeCandidate) -> list[Claim]:
        """Convert candidate.claims + candidate.evidence into structured list[Claim].

        For each claim dict:
        - Read 'statement' (required), 'confidence' (optional, default 0.5),
          'evidence_refs' (optional, default [])
        - Resolve evidence_refs indices into candidate.evidence list → Evidence objects
        - Default ClaimType is FACT; default ClaimStatus is PENDING
        - Claim id format: candidate.id + "_c" + index (0-based, sequential)
        - source_objects = [candidate.source_id]
        - If a claim dict is missing 'statement', skip it and log a warning
        """
        if not candidate.claims:
            return []

        now = int(time.time() * 1000)
        results: list[Claim] = []
        index = 0

        for claim_dict in candidate.claims:
            statement = claim_dict.get("statement")
            if not statement:
                logger.warning(
                    "ClaimParser: skipping claim at index %d in candidate %s "
                    "— missing 'statement' key",
                    index,
                    candidate.id,
                )
                continue

            confidence = claim_dict.get("confidence", 0.5)
            evidence_refs: list[int] = claim_dict.get("evidence_refs", [])

            # Resolve evidence_refs into Evidence objects
            evidence_list: list[Evidence] = []
            for ref in evidence_refs:
                if 0 <= ref < len(candidate.evidence):
                    ev = candidate.evidence[ref]
                    evidence_list.append(
                        Evidence(
                            source_path=ev.get("source_path", ""),
                            page=ev.get("page"),
                            quote=ev.get("quote", ""),
                            added_at=now,
                        )
                    )
                else:
                    logger.warning(
                        "ClaimParser: evidence_refs index %d out of range "
                        "(evidence has %d items) in claim %d of candidate %s",
                        ref,
                        len(candidate.evidence),
                        index,
                        candidate.id,
                    )

            claim = Claim(
                id=f"{candidate.id}_c{index}",
                statement=statement,
                type=ClaimType.FACT,
                confidence=confidence,
                evidence=evidence_list,
                status=ClaimStatus.PENDING,
                source_objects=[candidate.source_id],
                created_at=now,
                updated_at=now,
            )
            results.append(claim)
            index += 1

        return results
