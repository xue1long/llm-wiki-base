"""Per-ingest registry joining canonical blocks to their prompt visibility."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from src.kc.contracts.candidate_v2 import BoundClaim, RejectedClaim
from src.kc.contracts.evidence_binding import EvidenceBinding
from src.pipeline.text_preprocessing.types import PreprocessResult

MAX_EVIDENCE_QUOTE_CHARS = 4000


@dataclass(frozen=True)
class EvidenceBlock:
    block_id: str
    canonical_content: str
    prompt_content: str
    visible: bool


class EvidenceBlockRegistry:
    def __init__(self, blocks: tuple[EvidenceBlock, ...]):
        unique: dict[str, EvidenceBlock] = {}
        for block in blocks:
            unique.setdefault(block.block_id, block)
        self._blocks = tuple(unique.values())
        self._by_id = {block.block_id: block for block in self._blocks}
        self._bindings: dict[str, EvidenceBinding] = {}

    @classmethod
    def from_preprocess(cls, prepared: PreprocessResult) -> "EvidenceBlockRegistry":
        prompt_by_id = {block.block_id: block for block in prepared.prompt_blocks}
        return cls(
            tuple(
                EvidenceBlock(
                    block_id=block.block_id,
                    canonical_content=block.content,
                    prompt_content=prompt_by_id.get(block.block_id, block).prompt_content
                    if block.block_id in prompt_by_id
                    else "",
                    visible=block.block_id in prompt_by_id,
                )
                for block in prepared.canonical_document.blocks
            )
        )

    def __len__(self) -> int:
        return len(self._blocks)

    def blocks(self) -> tuple[EvidenceBlock, ...]:
        return self._blocks

    def get(self, block_id: str) -> EvidenceBlock | None:
        return self._by_id.get(block_id)

    def visible_block_ids(self) -> frozenset[str]:
        return frozenset(block.block_id for block in self._blocks if block.visible)

    def bind_claim(
        self, statement: str, block_ids: list[str] | tuple[str, ...]
    ) -> BoundClaim | RejectedClaim:
        bindings: list[EvidenceBinding] = []
        invalid: list[str] = []
        reasons: set[str] = set()
        for block_id in dict.fromkeys(block_ids):
            block = self._by_id.get(block_id)
            if block is None:
                invalid.append(block_id)
                reasons.add("invalid_block_id")
                continue
            if not block.visible:
                invalid.append(block_id)
                reasons.add("hidden_block")
                continue
            bindings.append(self._bind_block(block))
        if not bindings:
            reason = next(iter(sorted(reasons)), "no_valid_evidence")
            return RejectedClaim(statement, reason, tuple(invalid))
        return BoundClaim(statement, 0.0, tuple(bindings))

    def _bind_block(self, block: EvidenceBlock) -> EvidenceBinding:
        existing = self._bindings.get(block.block_id)
        if existing is not None:
            return existing
        quote = block.canonical_content[:MAX_EVIDENCE_QUOTE_CHARS]
        quote_hash = sha256(quote.encode("utf-8")).hexdigest()
        binding = EvidenceBinding(
            evidence_id=f"evidence_{sha256((block.block_id + quote_hash).encode('utf-8')).hexdigest()[:24]}",
            block_id=block.block_id,
            quote=quote,
            quote_hash=quote_hash,
            quote_truncated=len(block.canonical_content) > MAX_EVIDENCE_QUOTE_CHARS,
        )
        self._bindings[block.block_id] = binding
        return binding
