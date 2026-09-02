"""Small synchronous API seam used by CLI and HTTP adapters."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import Any

from src.kc.adapters.legacy_collector import LegacyCollector
from src.kc.adapters.wiki_projection import project_wiki
from src.kc.compiler.compile import compile_claim
from src.kc.compiler.evidence import canonical_quote, quote_matches_content, validate_evidence
from src.kc.compiler.extract import parse_candidate_json
from src.kc.compiler.normalize import normalize_text
from src.utils.path import canonical_raw_key


def candidate_to_payload(
    candidate: dict[str, Any],
    document,
    *,
    source_root=None,
    allow_legacy_unique_quote: bool = False,
    visible_block_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Adapt pipeline candidate evidence refs to the strict KC payload."""
    source = str(document.source)
    if source_root is not None:
        source = canonical_raw_key(source, source_root)
    raw_evidence = candidate.get("evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError("candidate evidence must be a list")

    evidence_by_ref: list[dict[str, Any]] = []
    for item in raw_evidence:
        item_source = item.get("source_path") if isinstance(item, dict) else None
        if source_root is not None and isinstance(item_source, str):
            try:
                item_source = canonical_raw_key(item_source, source_root)
            except ValueError:
                item_source = None
        if not isinstance(item, dict) or item_source != source:
            raise ValueError("evidence source_path does not match document source")
        quote = item.get("quote")
        quote = canonical_quote(quote) if isinstance(quote, str) else quote
        declared_block_id = item.get("block_id")
        if "block_id" in item:
            if not isinstance(declared_block_id, str) or not declared_block_id:
                raise ValueError("evidence block_id is required")
            block = next(
                (candidate_block for candidate_block in document.blocks
                 if candidate_block.block_id == declared_block_id),
                None,
            )
            if block is None:
                raise ValueError("evidence block_id does not exist")
            if not isinstance(quote, str) or not quote or not quote_matches_content(quote, block.content):
                visible_blocks = [
                    candidate_block for candidate_block in document.blocks
                    if visible_block_ids is None
                    or candidate_block.block_id in visible_block_ids
                ]
                quote_matches = [
                    candidate_block for candidate_block in visible_blocks
                    if isinstance(quote, str)
                    and quote
                    and quote_matches_content(quote, candidate_block.content)
                ]
                if len(quote_matches) != 1:
                    raise ValueError("evidence quote does not match declared block")
                block = quote_matches[0]
        elif allow_legacy_unique_quote:
            matches = [
                block for block in document.blocks
                if isinstance(quote, str) and quote and quote_matches_content(quote, block.content)
            ]
            if len(matches) > 1:
                raise ValueError("evidence quote must match a unique block")
            block = matches[0] if matches else None
            if block is None:
                raise ValueError("evidence quote does not match a document block")
        else:
            raise ValueError("evidence block_id is required")
        if visible_block_ids is not None and block.block_id not in visible_block_ids:
            raise ValueError("evidence block_id is not visible in prompt")
        evidence_by_ref.append({
            "block_id": block.block_id,
            "quote": quote,
            "quote_hash": sha256(quote.encode("utf-8")).hexdigest(),
            "confidence": float(candidate.get("confidence", 0.0)),
        })

    claims: list[dict[str, Any]] = []
    for index, claim in enumerate(candidate.get("claims", [])):
        if not isinstance(claim, dict) or not isinstance(claim.get("statement"), str):
            raise ValueError("candidate claim requires statement")
        refs = claim.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, int) or ref < 0 or ref >= len(evidence_by_ref)
            for ref in refs
        ):
            raise ValueError("claim evidence_refs are invalid")
        text = claim["statement"].strip()
        if not text:
            raise ValueError("candidate claim requires statement")
        claim_id = sha256(
            f"{candidate.get('source_id', source)}:{index}:{text}".encode("utf-8")
        ).hexdigest()[:16]
        claims.append({
            "id": claim_id,
            "text": text,
            "evidence": [evidence_by_ref[ref] for ref in refs],
        })
    return {"claims": claims}


async def compile_source(
    source: str,
    *,
    content: bytes | None = None,
    candidate_json: str,
    document=None,
) -> dict:
    if document is None:
        if content is None:
            raise ValueError("compile_source requires content or document")
        document = await LegacyCollector().collect(source, content=content)
    candidate = parse_candidate_json(candidate_json)
    projections = []
    objects = []
    for claim in candidate["claims"]:
        evidence = tuple(
            validate_evidence(
                document,
                {**item, "supports": (claim["id"],)},
                require_unique_match=item.get("binding_mode") != "system",
            )
            for item in claim["evidence"]
        )
        obj = compile_claim(claim, document, evidence)
        objects.append(obj)
        projection = project_wiki(
            obj,
            evidence_ids=tuple(item.evidence_id for item in evidence),
            evidence=evidence,
        )
        projection["document_id"] = document.document_id
        projections.append(projection)
    return {"document_id": document.document_id, "projections": projections, "objects": objects}


def compile_text(source: str, text: str, candidate: dict) -> dict:
    return asyncio.run(compile_source(
        source,
        document=normalize_text(text, source=source),
        candidate_json=json.dumps(candidate),
    ))


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Compile one text source through Knowledge Compiler")
    parser.add_argument("source")
    parser.add_argument("candidate_json")
    args = parser.parse_args()
    path = Path(args.source)
    print(json.dumps(compile_text(str(path), path.read_text(encoding="utf-8"), json.loads(args.candidate_json)), ensure_ascii=False))
