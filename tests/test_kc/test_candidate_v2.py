from src.kc.contracts.candidate_v2 import CandidateV2, ClaimV2
from src.kc.contracts.evidence_binding import EvidenceBinding


def test_candidate_v2_has_only_block_references():
    candidate = CandidateV2(
        source_id="raw/sources/a.md",
        type="concept",
        title="标题",
        claims=(ClaimV2("正文证据。", 0.9, ("block_1",)),),
    )
    assert candidate.claims[0].evidence_block_ids == ("block_1",)
    assert not hasattr(candidate.claims[0], "quote")


def test_evidence_binding_is_system_owned():
    binding = EvidenceBinding(
        evidence_id="evidence_1",
        block_id="block_1",
        quote="canonical",
        quote_hash="hash",
    )
    assert binding.status == "structurally_verified"
