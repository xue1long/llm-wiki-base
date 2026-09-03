from src.pipeline.evidence_registry import EvidenceBlock, EvidenceBlockRegistry
from src.pipeline.render_contract import RenderBundle, RenderDraft
from src.pipeline.wiki_compiler import compile_bundle


def test_compiler_returns_canonical_evidence_binding():
    registry = EvidenceBlockRegistry((EvidenceBlock("b1", "canonical quote", "prompt", True),))
    draft = RenderDraft("t", "s", "p", 0, "tpl", "Title", "concept", "Body", referenced_block_ids=("b1",))
    result = compile_bundle(RenderBundle("t", "s", "tpl", (draft,)), evidence_registry=registry)
    binding = result.pages[0].evidence[0]
    assert binding.quote == "canonical quote"
    assert binding.quote_hash
    assert binding.evidence_id
