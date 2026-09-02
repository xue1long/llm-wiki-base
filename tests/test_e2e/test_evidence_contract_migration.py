import json
from pathlib import Path

import pytest

from src.kc.contracts.candidate_v2 import CandidateV2, ClaimV2
from src.pipeline.ingest import generate_ingest
from src.pipeline.text_preprocessing.api import preprocess_source
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base


@pytest.mark.asyncio
async def test_v2_ingest_keeps_writer_input_compatible(tmp_path: Path, monkeypatch):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    source = paths.raw_sources / "migration.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    text = "正文证据。"
    source.write_text(text, encoding="utf-8")
    prepared = preprocess_source(text, source_id="raw/sources/migration.md")
    block_id = prepared.canonical_document.blocks[0].block_id
    candidate = CandidateV2(
        source_id="raw/sources/migration.md",
        type="concept",
        title="迁移测试",
        claims=(ClaimV2("正文证据。", 0.9, (block_id,)),),
    )

    async def fake_generate_from_candidate(**kwargs):
        return [WikiPage(
            id="migration-page",
            title="迁移测试",
            type=PageType.CONCEPT,
            sources=["raw/sources/migration.md"],
            body="迁移测试正文。",
            grade="B",
        )]

    monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
    monkeypatch.setenv("RUFLO_EVIDENCE_CONTRACT", "v2")
    monkeypatch.setattr(
        "src.pipeline.generator.generate_from_candidate",
        fake_generate_from_candidate,
    )

    pages, _, meta = await generate_ingest(
        paths=paths,
        source_path=source,
        source_text=text,
        provider=object(),
        task_id="migration-test",
        candidate_override=candidate,
    )

    assert pages
    manifest = json.loads(
        (paths.index / "kc" / "bundles" / meta["kc_bundle_key"] / "manifest.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["contract_version"] == "v2"
