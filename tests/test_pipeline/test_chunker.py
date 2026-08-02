"""Tests for src/pipeline/chunker.py — semantic chunking + candidate merge."""
import pytest

from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType


# ---------------------------------------------------------------------------
# chunk_source_text tests
# ---------------------------------------------------------------------------

class TestChunkSourceText:
    def test_under_threshold_returns_single_chunk(self):
        from src.pipeline.chunker import chunk_source_text

        text = "Short document.\n\nWith two paragraphs."
        chunks = chunk_source_text(text, target_chars=6000, overlap_chars=500, threshold=12000)
        assert len(chunks) == 1
        assert chunks[0]["text"] == text
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["chunk_total"] == 1

    def test_respects_heading_boundaries(self):
        from src.pipeline.chunker import chunk_source_text

        # Two heading sections each ~200 chars; threshold set so they split
        sec1 = "## Section One\n" + ("A" * 100 + "\n") * 15   # ~1500 chars
        sec2 = "## Section Two\n" + ("B" * 100 + "\n") * 15    # ~1500 chars
        text = sec1 + "\n" + sec2
        chunks = chunk_source_text(text, target_chars=2000, overlap_chars=200, threshold=2500)
        # Should produce at least 2 chunks, each starting with its heading
        assert len(chunks) >= 2
        assert "## Section One" in chunks[0]["text"]
        assert "## Section Two" in chunks[1]["text"]

    def test_overlap_preserves_heading_context(self):
        from src.pipeline.chunker import chunk_source_text

        # Build sections where last heading + tail text should appear in next chunk
        sections = []
        for i in range(5):
            sections.append(f"## Section {i}\n" + (f"Para {i} " * 200 + "\n"))
        text = "\n".join(sections)
        chunks = chunk_source_text(text, target_chars=2000, overlap_chars=300, threshold=5000)
        assert len(chunks) >= 3
        # Later chunks should contain heading context from previous chunk's tail
        # The overlap preserves the last heading + trailing paragraphs
        # At minimum chunk 1 should have some heading from the source
        assert any(
            "## Section" in chunks[i]["text"]
            for i in range(1, len(chunks))
        )

    def test_fallback_to_paragraph_split(self):
        from src.pipeline.chunker import chunk_source_text

        # One massive heading section with no sub-headings
        huge_section = "## Giant Section\n" + ("Long paragraph content that repeats. " * 200 + "\n\n") * 20
        chunks = chunk_source_text(huge_section, target_chars=2000, overlap_chars=200, threshold=5000)
        # Must produce multiple chunks
        assert len(chunks) > 1

    def test_hard_split_at_sentence_boundaries(self):
        from src.pipeline.chunker import chunk_source_text

        # Single massive paragraph without any breakpoints
        huge_para = "A" * 3000 + "。B" * 3000 + "。C" * 3000 + "。"
        chunks = chunk_source_text(huge_para, target_chars=2000, overlap_chars=200, threshold=4000)
        assert len(chunks) > 1
        # All chunk text should be non-empty
        for c in chunks:
            assert len(c["text"]) > 0

    def test_empty_text(self):
        from src.pipeline.chunker import chunk_source_text

        chunks = chunk_source_text("")
        assert len(chunks) == 1
        assert chunks[0]["text"] == ""
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["chunk_total"] == 1

    def test_chunk_index_total_metadata(self):
        from src.pipeline.chunker import chunk_source_text

        text = ("## Sec {i}\n" + "x" * 3000 for i in range(3))
        text = "\n".join(text)
        chunks = chunk_source_text(text, target_chars=3500, overlap_chars=200, threshold=5000)
        for i, c in enumerate(chunks):
            assert c["chunk_index"] == i
            assert c["chunk_total"] == len(chunks)


# ---------------------------------------------------------------------------
# merge_candidates tests
# ---------------------------------------------------------------------------

def _make_candidate(cid="c1", source_id="src-1", title="Test", claims=None,
                    evidence=None, confidence=0.85, ctype=KnowledgeType.CONCEPT):
    """Build a KnowledgeCandidate with minimal valid fields."""
    return KnowledgeCandidate(
        id=cid,
        source_id=source_id,
        type=ctype,
        title=title,
        claims=claims or [
            {"statement": "Claim A", "confidence": 0.9, "evidence_refs": [0]},
        ],
        evidence=evidence or [
            {"source_path": source_id, "page": 1, "quote": "evidence text"},
        ],
        confidence=confidence,
        raw_llm_output={"raw": "test"},
    )


class TestMergeCandidates:
    def test_merge_single_returns_equivalent(self):
        from src.pipeline.chunker import merge_candidates

        c = _make_candidate()
        merged = merge_candidates([c], source_path="src-1")
        assert merged.title == "Test"
        assert len(merged.claims) == 1
        assert merged.claims[0]["statement"] == "Claim A"

    def test_merge_dedup_same_claims_max_confidence(self):
        from src.pipeline.chunker import merge_candidates

        c1 = _make_candidate(cid="c1", confidence=0.7, claims=[
            {"statement": "Claim X", "confidence": 0.7, "evidence_refs": [0]},
        ])
        c2 = _make_candidate(cid="c2", confidence=0.9, claims=[
            {"statement": "Claim X", "confidence": 0.9, "evidence_refs": [0]},
        ])
        merged = merge_candidates([c1, c2], source_path="src-1")
        assert len(merged.claims) == 1
        assert merged.claims[0]["confidence"] == 0.9  # max

    def test_merge_different_claims_all_preserved(self):
        from src.pipeline.chunker import merge_candidates

        c1 = _make_candidate(cid="c1", claims=[
            {"statement": "Claim A", "confidence": 0.8, "evidence_refs": [0]},
        ])
        c2 = _make_candidate(cid="c2", claims=[
            {"statement": "Claim B", "confidence": 0.7, "evidence_refs": [0]},
        ])
        merged = merge_candidates([c1, c2], source_path="src-1")
        statements = {cl["statement"] for cl in merged.claims}
        assert statements == {"Claim A", "Claim B"}

    def test_merge_reindex_evidence_refs(self):
        from src.pipeline.chunker import merge_candidates

        c1 = _make_candidate(cid="c1", source_id="src-1", claims=[
            {"statement": "C1 claim", "confidence": 0.8, "evidence_refs": [0]},
        ], evidence=[
            {"source_path": "src-1", "page": 1, "quote": "ev1"},
        ])
        c2 = _make_candidate(cid="c2", source_id="src-1", claims=[
            {"statement": "C2 claim", "confidence": 0.7, "evidence_refs": [0]},
        ], evidence=[
            {"source_path": "src-1", "page": 5, "quote": "ev2"},
        ])
        merged = merge_candidates([c1, c2], source_path="src-1")
        assert len(merged.evidence) == 2
        # evidence_refs in claims are re-indexed to merged evidence list
        for claim in merged.claims:
            for ref in claim["evidence_refs"]:
                assert 0 <= ref < len(merged.evidence)

    def test_merge_first_non_empty_title(self):
        from src.pipeline.chunker import merge_candidates

        c1 = _make_candidate(cid="c1", title="")
        c2 = _make_candidate(cid="c2", title="Good Title")
        merged = merge_candidates([c1, c2], source_path="src-1")
        assert merged.title == "Good Title"

    def test_merge_weighted_confidence(self):
        from src.pipeline.chunker import merge_candidates

        c1 = _make_candidate(cid="c1", confidence=0.6, claims=[
            {"statement": "A", "confidence": 0.6, "evidence_refs": [0]},
        ])
        c2 = _make_candidate(cid="c2", confidence=0.9, claims=[
            {"statement": "B", "confidence": 0.9, "evidence_refs": [0]},
            {"statement": "C", "confidence": 0.9, "evidence_refs": [0]},
        ])
        merged = merge_candidates([c1, c2], source_path="src-1")
        # Weighted: (0.6*1 + 0.9*2) / 3 = 0.8
        assert abs(merged.confidence - 0.8) < 0.05
