"""Deterministic identifiers for canonical documents and blocks."""

from hashlib import sha256


def _digest(*parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return sha256(value.encode("utf-8")).hexdigest()[:24]


def document_id(raw_text: str, normalization_version: str, parser_version: str) -> str:
    return "doc_" + _digest(raw_text, normalization_version, parser_version)


def block_id(
    document: str,
    ordinal: int,
    block_text: str,
    normalization_version: str,
) -> str:
    return "block_" + _digest(document, ordinal, block_text, normalization_version)


def evidence_id(
    document_id: str,
    block_id: str,
    quote_hash: str = "",
    supports: tuple[str, ...] = (),
) -> str:
    """Return a stable identity for one claim-scoped evidence reference."""
    return "evidence_" + _digest(document_id, block_id, quote_hash, *supports)
