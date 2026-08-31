"""KC mainline integration contract tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.pipeline.ingest import _merge_candidate_chunks, run_ingest
from src.kc.compiler.normalize import normalize_text
from src.kc.mainline import CandidatePromoter, PromotionResult
from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base


@pytest.mark.asyncio
async def test_run_ingest_enters_kc_before_formal_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The formal ingest caller must invoke KC review before commit writes."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "kc-mainline.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("KC 主线测试源文档。", encoding="utf-8")
    block_id = normalize_text(
        raw.read_text(encoding="utf-8"),
        source="raw/sources/kc-mainline.md",
    ).blocks[0].block_id

    called: list[dict] = []

    async def fake_compile_source(source: str, *, document, candidate_json: str) -> dict:
        called.append({"source": source, "document": document, "candidate_json": candidate_json})
        return {
            "document_id": "doc-test",
            "projections": [{"evidence_ids": ["block-test"]}],
        }

    async def fake_analyze(**kwargs):
        return KnowledgeCandidate(
            id="candidate-test",
            source_id=str(raw),
            type=KnowledgeType.CONCEPT,
            title="KC 主线测试",
            claims=[{"statement": "KC 主线测试声明。", "evidence_refs": [0]}],
            confidence=0.8,
            evidence=[{
                "source_path": str(raw),
                "block_id": block_id,
                "quote": "KC 主线测试源文档。",
            }],
            raw_llm_output={},
            status=CandidateStatus.PENDING,
        )

    async def fake_generate_from_candidate(**kwargs):
        now = int(time.time() * 1000)
        return [
            WikiPage(
                id="kc-mainline-page",
                title="KC 主线测试页",
                type=PageType.CONCEPT,
                sources=["raw/sources/kc-mainline.md"],
                body="这是足够长的测试内容。",
                grade="B",
                created_at=now,
                updated_at=now,
            )
        ]

    monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
    monkeypatch.setattr("src.kc.api.compile_source", fake_compile_source)
    monkeypatch.setattr("src.pipeline.analyzer.analyze", fake_analyze)
    monkeypatch.setattr("src.pipeline.generator.generate_from_candidate", fake_generate_from_candidate)

    pages = await run_ingest(
        paths=paths,
        source_path=raw,
        source_text=raw.read_text(encoding="utf-8"),
        provider=object(),
        task_id="kc-mainline-test",
    )

    assert called, "formal ingest must enter KC before commit"
    assert called[0]["source"] == "raw/sources/kc-mainline.md"
    assert called[0]["document"].content == raw.read_text(encoding="utf-8")
    assert pages[0].evidence_refs == ["doc-test:block-test"]
    assert pages[0]._ko_extra["kc_document_id"] == "doc-test"
    assert pages[0]._ko_extra["kc_projection_version"] == "kc-wiki-v1"


def test_merge_candidate_chunks_reindexes_evidence_without_relocation() -> None:
    first = KnowledgeCandidate(
        id="first",
        source_id="raw/sources/chunked.md",
        type=KnowledgeType.CONCEPT,
        title="Chunked",
        claims=[{"statement": "第一条", "confidence": 0.9, "evidence_refs": [0]}],
        confidence=0.9,
        evidence=[{"source_path": "raw/sources/chunked.md", "block_id": "b1", "quote": "第一条"}],
        raw_llm_output={},
    )
    second = KnowledgeCandidate(
        id="second",
        source_id="raw/sources/chunked.md",
        type=KnowledgeType.CONCEPT,
        title="Chunked",
        claims=[{"statement": "第二条", "confidence": 0.8, "evidence_refs": [0]}],
        confidence=0.8,
        evidence=[{"source_path": "raw/sources/chunked.md", "block_id": "b2", "quote": "第二条"}],
        raw_llm_output={},
    )

    merged = _merge_candidate_chunks([first, second])

    assert [claim["evidence_refs"] for claim in merged.claims] == [[0], [1]]
    assert [item["block_id"] for item in merged.evidence] == ["b1", "b2"]


@pytest.mark.asyncio
async def test_run_ingest_blocks_generation_when_candidate_evidence_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid source evidence must stop before Generator or formal commit."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "kc-invalid-evidence.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("真实来源内容。", encoding="utf-8")
    block_id = normalize_text(
        raw.read_text(encoding="utf-8"),
        source="raw/sources/kc-invalid-evidence.md",
    ).blocks[0].block_id

    async def fake_analyze(**kwargs):
        return KnowledgeCandidate(
            id="candidate-invalid-evidence",
            source_id=str(raw),
            type=KnowledgeType.CONCEPT,
            title="非法证据",
            claims=[{"statement": "不应生成页面。", "evidence_refs": [0]}],
            confidence=0.8,
            evidence=[{
                "source_path": str(raw),
                "block_id": block_id,
                "quote": "不存在的引用。",
            }],
            raw_llm_output={},
            status=CandidateStatus.PENDING,
        )

    generated = False

    async def fake_generate_from_candidate(**kwargs):
        nonlocal generated
        generated = True
        return []

    monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
    monkeypatch.setattr("src.pipeline.analyzer.analyze", fake_analyze)
    monkeypatch.setattr(
        "src.pipeline.generator.generate_from_candidate",
        fake_generate_from_candidate,
    )

    with pytest.raises(ValueError, match="quote does not match"):
        await run_ingest(
            paths=paths,
            source_path=raw,
            source_text=raw.read_text(encoding="utf-8"),
            provider=object(),
            task_id="kc-invalid-evidence-test",
        )

    assert not generated
    assert not list(paths.wiki.rglob("*.md"))


@pytest.mark.asyncio
async def test_run_ingest_blocks_rejected_candidate_before_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected candidate must never reach Generator or Wiki commit."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "kc-rejected.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("可验证来源内容。", encoding="utf-8")

    async def fake_analyze(**kwargs):
        return KnowledgeCandidate(
            id="candidate-rejected",
            source_id="",
            type=KnowledgeType.CONCEPT,
            title="不可发布",
            claims=[{"statement": "可验证声明。", "evidence_refs": [0]}],
            confidence=0.8,
            evidence=[{"source_path": str(raw), "quote": "可验证来源内容。"}],
            raw_llm_output={},
            status=CandidateStatus.REJECTED,
        )

    generated = False

    async def fake_generate_from_candidate(**kwargs):
        nonlocal generated
        generated = True
        return []

    monkeypatch.setenv("RUFLO_PIPELINE_MODE", "candidate")
    monkeypatch.setattr("src.pipeline.analyzer.analyze", fake_analyze)
    monkeypatch.setattr(
        "src.pipeline.generator.generate_from_candidate",
        fake_generate_from_candidate,
    )

    with pytest.raises(ValueError, match="rejected"):
        await run_ingest(
            paths=paths,
            source_path=raw,
            source_text=raw.read_text(encoding="utf-8"),
            provider=object(),
            task_id="kc-rejected-candidate-test",
        )

    assert not generated
    assert not list(paths.wiki.rglob("*.md"))
