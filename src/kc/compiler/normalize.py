"""Convert text into stable, source-independent document objects."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from src.kc.domain.ids import block_id, document_id

NORMALIZATION_VERSION = "kc-text-v2"
LEGACY_NORMALIZATION_VERSION = "kc-text-v1"
PARSER_VERSION = "legacy-text-v1"


@dataclass(frozen=True)
class DocumentBlock:
    block_id: str
    ordinal: int
    content: str


@dataclass(frozen=True)
class CanonicalDocument:
    document_id: str
    title: str
    content: str
    source: str
    parser_version: str
    normalization_version: str
    blocks: tuple[DocumentBlock, ...]
    sources: tuple[str, ...] = ()


def _canonical_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.removeprefix("\ufeff")
    text = unicodedata.normalize("NFC", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _legacy_canonical_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _title(text: str, source: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[2:].strip() if line.startswith("# ") else line[:120]
    return source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]


def _build_document(content: str, *, source: str, normalization_version: str) -> CanonicalDocument:
    doc_id = document_id(content, normalization_version, PARSER_VERSION)
    blocks = tuple(
        DocumentBlock(
            block_id=block_id(doc_id, ordinal, value, normalization_version),
            ordinal=ordinal,
            content=value,
        )
        for ordinal, value in enumerate(part for part in content.split("\n\n") if part)
    )
    return CanonicalDocument(
        document_id=doc_id,
        title=_title(content, source),
        content=content,
        source=source,
        parser_version=PARSER_VERSION,
        normalization_version=normalization_version,
        blocks=blocks,
        sources=(source,) if source else (),
    )


def normalize_text(text: str, *, source: str = "") -> CanonicalDocument:
    return _build_document(
        _canonical_text(text),
        source=source,
        normalization_version=NORMALIZATION_VERSION,
    )


def normalize_text_legacy(text: str, *, source: str = "") -> CanonicalDocument:
    """Read old evidence using the v1 canonicalization contract."""
    return _build_document(
        _legacy_canonical_text(text),
        source=source,
        normalization_version=LEGACY_NORMALIZATION_VERSION,
    )


def with_sources(document: CanonicalDocument, sources: tuple[str, ...]) -> CanonicalDocument:
    """Attach additional raw references without changing deterministic IDs."""
    merged = tuple(dict.fromkeys((*document.sources, *sources)))
    return CanonicalDocument(
        document_id=document.document_id,
        title=document.title,
        content=document.content,
        source=document.source,
        parser_version=document.parser_version,
        normalization_version=document.normalization_version,
        blocks=document.blocks,
        sources=merged,
    )
