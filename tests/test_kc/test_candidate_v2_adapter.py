from src.kc.adapters.candidate_v2 import adapt_candidate
from src.kc.compiler.normalize import normalize_text
from src.pipeline.evidence_registry import EvidenceBlockRegistry
from src.pipeline.text_preprocessing.api import preprocess_source


def test_adapter_ignores_llm_quote_and_binds_visible_block():
    prepared = preprocess_source("标题\n\n正文证据。", source_id="raw/sources/a.md")
    document = prepared.canonical_document
    registry = EvidenceBlockRegistry.from_preprocess(prepared)
    block_id = next(
        block.block_id for block in registry.blocks() if block.canonical_content == "正文证据。"
    )
    candidate = {
        "source_id": "raw/sources/a.md",
        "type": "concept",
        "title": "标题",
        "claims": [{
            "statement": "正文证据。",
            "confidence": 0.9,
            "evidence_block_ids": [block_id],
            "quote": "模型伪造的引用",
        }],
    }

    result = adapt_candidate(candidate, document, registry)

    assert result.payload["claims"][0]["evidence"][0]["quote"] == "正文证据。"
    assert result.generator_candidate.claims[0]["evidence_refs"] == [0]


def test_adapter_isolates_invalid_and_hidden_claims():
    prepared = preprocess_source(
        "正文证据。\n\n来源：https://example.test/source",
        source_id="raw/sources/a.md",
    )
    document = prepared.canonical_document
    registry = EvidenceBlockRegistry.from_preprocess(prepared)
    visible = next(iter(registry.visible_block_ids()))
    hidden = next(block.block_id for block in registry.blocks() if not block.visible)

    result = adapt_candidate({
        "source_id": "raw/sources/a.md",
        "type": "concept",
        "title": "标题",
        "claims": [
            {"statement": "有效", "confidence": 0.9, "evidence_block_ids": [visible]},
            {"statement": "隐藏", "confidence": 0.9, "evidence_block_ids": [hidden]},
            {"statement": "未知", "confidence": 0.9, "evidence_block_ids": ["missing"]},
        ],
    }, document, registry)

    assert result.valid_claim_count == 1
    assert {item.reason_code for item in result.rejected_claims} == {
        "hidden_block", "invalid_block_id"
    }
