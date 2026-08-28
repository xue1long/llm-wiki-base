"""Local, fail-closed validation for candidate Evidence."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from src.kc.compiler.normalize import CanonicalDocument
from src.kc.contracts.evidence import Evidence

MIN_SHORT_QUOTE_CHARS = 8


class EvidenceValidationError(ValueError):
    pass


def canonical_quote(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def validate_evidence(document: CanonicalDocument, value: dict[str, Any]) -> Evidence:
    block_id = value.get("block_id")
    quote = value.get("quote")
    if not isinstance(quote, str) or not quote:
        raise EvidenceValidationError("evidence quote is empty")
    quote = canonical_quote(quote)
    block = next((item for item in document.blocks if item.block_id == block_id), None)
    matches = [item for item in document.blocks if quote in item.content]
    if len(matches) > 1:
        raise EvidenceValidationError("evidence quote must match a unique block")
    if block is None or not matches or matches[0].block_id != block.block_id:
        raise EvidenceValidationError("evidence does not match a document block")
    quote_hash = value.get("quote_hash", sha256(quote.encode("utf-8")).hexdigest())
    if quote_hash != sha256(quote.encode("utf-8")).hexdigest():
        raise EvidenceValidationError("evidence quote hash mismatch")
    return Evidence(
        document_id=document.document_id,
        block_id=block.block_id,
        quote=quote,
        quote_hash=quote_hash,
        supports=tuple(value.get("supports", ())),
        confidence=float(value.get("confidence", 0.0)),
        status="structurally_verified",
    )
