"""Small publication gate for newly extracted claims."""

from __future__ import annotations

from src.kc.compiler.normalize import CanonicalDocument
from src.kc.contracts.evidence import Evidence
from src.kc.contracts.status import PublicationState


def verify_claim(claim: dict, document: CanonicalDocument, evidence: tuple[Evidence, ...]) -> PublicationState:
    if not document.source or not claim.get("id") or not claim.get("text"):
        raise ValueError("claim requires source, id and text")
    if not evidence or any(
        item.status != "structurally_verified"
        or item.document_id != document.document_id
        for item in evidence
    ):
        raise ValueError("claim requires structurally verified document evidence")
    return PublicationState.STRUCTURALLY_VERIFIED
