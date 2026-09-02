from src.pipeline.text_preprocessing.api import preprocess_source
from src.pipeline.evidence_registry import EvidenceBlockRegistry


def test_registry_preserves_canonical_content_and_prompt_visibility():
    prepared = preprocess_source(
        "# 标题\n\n正文证据。\n\n来源：内部备注",
        source_id="raw/sources/a.md",
    )

    registry = EvidenceBlockRegistry.from_preprocess(prepared)

    visible = registry.visible_block_ids()
    assert visible
    block = registry.get(next(iter(visible)))
    assert block is not None
    assert block.visible is True
    assert block.canonical_content
    assert block.prompt_content
    assert block.canonical_content != ""


def test_registry_deduplicates_block_ids_and_rejects_hidden_blocks():
    prepared = preprocess_source(
        "正文证据。\n\n来源：https://example.test/source",
        source_id="raw/sources/a.md",
    )
    registry = EvidenceBlockRegistry.from_preprocess(prepared)

    assert len(registry) == len({block.block_id for block in registry.blocks()})
    hidden = [block for block in registry.blocks() if not block.visible]
    assert hidden
    assert registry.get(hidden[0].block_id).visible is False
