"""Semantic text chunking for large document ingestion.

Splits source_text on heading boundaries with overlap so the LLM has
structural context across chunk boundaries. Also provides a merge function
to recombine per-chunk KnowledgeCandidates into one.
"""
from __future__ import annotations

import re

from ..knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from ..knowledge.core.object import KnowledgeType


# ---------------------------------------------------------------------------
# Sentence-split fallback
# ---------------------------------------------------------------------------
_SENTENCE_RE = re.compile(r"(?<=[。.!?！？\n])\s*")


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text)
    return [p for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_source_text(
    text: str,
    target_chars: int = 6000,
    overlap_chars: int = 500,
    threshold: int = 12000,
) -> list[dict]:
    """Split text into semantically coherent chunks.

    Returns a list of dicts with keys ``text``, ``chunk_index``, ``chunk_total``.
    """
    if len(text) <= threshold:
        return [{"text": text, "chunk_index": 0, "chunk_total": 1}]

    # Step 1: split on heading boundaries
    heading_re = re.compile(r"(\n(?=#{1,3}\s))")
    sections = heading_re.split(text)

    # Merge the delimiter back into the following section
    merged: list[str] = []
    buf = ""
    for part in sections:
        if heading_re.match(part):
            if buf:
                merged.append(buf)
            buf = part
        else:
            buf += part
    if buf:
        merged.append(buf)

    if not merged:
        return [{"text": text, "chunk_index": 0, "chunk_total": 1}]

    # Step 2: greedy accumulate into chunks
    chunks: list[str] = []
    current = ""
    for sec in merged:
        if len(current) + len(sec) > target_chars and current:
            chunks.append(current.strip())
            # Overlap: keep tail of current chunk
            if len(current) > overlap_chars:
                tail = current[-overlap_chars:]
                # Walk back to a heading or paragraph boundary
                for sep in ("\n## ", "\n# ", "\n\n"):
                    idx = tail.find(sep)
                    if idx > 0:
                        tail = tail[idx + 1:]  # keep the \n prefix
                        break
                current = tail + sec
            else:
                current = sec
        else:
            current += sec

    if current.strip():
        chunks.append(current.strip())

    # Step 3: if still only 1 chunk but over threshold, fall back to paragraphs
    if len(chunks) == 1 and len(chunks[0]) > target_chars:
        paras = [p for p in chunks[0].split("\n\n") if p.strip()]
        chunks = []
        current = ""
        for para in paras:
            if len(current) + len(para) > target_chars and current:
                chunks.append(current.strip())
                current = para
            else:
                current += ("\n\n" + para) if current else para
        if current.strip():
            chunks.append(current.strip())

    # Step 4: if still only 1 chunk, hard-split on sentences
    if len(chunks) == 1 and len(chunks[0]) > target_chars:
        sentences = _split_sentences(chunks[0])
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) > target_chars and current:
                chunks.append(current.strip())
                current = sent
            else:
                current += sent
        if current.strip():
            chunks.append(current.strip())

    # Step 5: hard-char split as last resort
    if len(chunks) == 1 and len(chunks[0]) > target_chars:
        big = chunks[0]
        chunks = [
            big[i:i + target_chars]
            for i in range(0, len(big), target_chars)
        ]

    return [
        {"text": c, "chunk_index": i, "chunk_total": len(chunks)}
        for i, c in enumerate(chunks)
    ]


# ---------------------------------------------------------------------------
# Candidate merging
# ---------------------------------------------------------------------------

def _normalize_statement(stmt: str) -> str:
    """Normalize a claim statement for dedup comparison."""
    return stmt.strip().lower()[:80]


def _dedup_evidence(evidence_list: list[dict]) -> list[dict]:
    """Dedup evidence entries by quote text (first 200 chars). Returns re-indexed list."""
    seen: dict[str, int] = {}  # quote_key -> new_index
    result: list[dict] = []
    for ev in evidence_list:
        quote = ev.get("quote", "")
        key = quote[:200].strip().lower() if quote else ""
        if key and key in seen:
            # Merge: keep max page
            existing = result[seen[key]]
            existing_page = existing.get("page")
            this_page = ev.get("page")
            if this_page is not None and (existing_page is None or this_page > existing_page):
                existing["page"] = this_page
        else:
            if key:
                seen[key] = len(result)
            result.append(dict(ev))
    return result


def merge_candidates(
    candidates: list[KnowledgeCandidate],
    source_path: str,
) -> KnowledgeCandidate:
    """Merge candidates from multiple chunks into one combined candidate.

    - Claims: dedup by normalized statement (max confidence)
    - Evidence: dedup by quote, re-index evidence_refs
    - Title: first non-empty candidate title
    - Type: most common type across candidates
    - Confidence: weighted average by claims count
    """
    if len(candidates) == 1:
        return candidates[0]

    # Merge claims — dedup by normalized statement, keep max confidence
    claim_map: dict[str, dict] = {}
    for c in candidates:
        for claim in c.claims:
            stmt = claim.get("statement", "")
            key = _normalize_statement(stmt)
            if key not in claim_map or claim.get("confidence", 0) > claim_map[key].get("confidence", 0):
                claim_map[key] = dict(claim)

    # Merge evidence — dedup by quote
    all_evidence: list[dict] = []
    for c in candidates:
        all_evidence.extend(c.evidence)
    merged_evidence = _dedup_evidence(all_evidence)

    # Re-index evidence_refs in merged claims
    # Build a mapping: old (candidate_idx, evidence_idx) -> new_evidence_idx
    # Since evidence gets deduped, we need to find each claim's evidence_refs
    # in the merged evidence. The simplest approach: search by quote.
    _quote_to_new_idx: dict[str, int] = {}
    for i, ev in enumerate(merged_evidence):
        q = ev.get("quote", "")[:200].strip().lower()
        if q:
            _quote_to_new_idx[q] = i

    merged_claims: list[dict] = []
    for key, claim in claim_map.items():
        new_claim = dict(claim)
        new_refs: list[int] = []
        old_refs = claim.get("evidence_refs", [])
        for old_ref in old_refs:
            # old_ref is an index into the ORIGINAL candidate's evidence list.
            # We need to find which candidate it came from. Scan candidates.
            ref_found = False
            for c in candidates:
                if old_ref < len(c.evidence):
                    ev = c.evidence[old_ref]
                    q = ev.get("quote", "")[:200].strip().lower()
                    if q and q in _quote_to_new_idx:
                        new_idx = _quote_to_new_idx[q]
                        if new_idx not in new_refs:
                            new_refs.append(new_idx)
                        ref_found = True
                        break
            if not ref_found and old_ref < len(merged_evidence):
                if old_ref not in new_refs:
                    new_refs.append(old_ref)
        new_claim["evidence_refs"] = new_refs
        merged_claims.append(new_claim)

    # Title: first non-empty
    title = ""
    for c in candidates:
        if c.title:
            title = c.title
            break
    if not title:
        title = "Merged " + candidates[0].source_id

    # Type: most common
    type_counts: dict[KnowledgeType, int] = {}
    for c in candidates:
        type_counts[c.type] = type_counts.get(c.type, 0) + 1
    ctype = max(type_counts, key=lambda k: type_counts[k])

    # Confidence: weighted average by claims count
    total_claims = sum(len(c.claims) for c in candidates)
    if total_claims > 0:
        weighted_conf = sum(
            c.confidence * len(c.claims) for c in candidates
        ) / total_claims
    else:
        weighted_conf = sum(c.confidence for c in candidates) / len(candidates)

    import hashlib
    import uuid
    merged_id = "merged-" + hashlib.md5(source_path.encode()).hexdigest()[:12]

    return KnowledgeCandidate(
        id=merged_id,
        source_id=candidates[0].source_id,
        type=ctype,
        title=title,
        claims=merged_claims,
        confidence=round(weighted_conf, 4),
        evidence=merged_evidence,
        raw_llm_output={"merged": True, "chunk_count": len(candidates)},
        status=CandidateStatus.PENDING,
    )
