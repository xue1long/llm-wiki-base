"""Small durable Reviewer → Promoter seam for the default KC ingest path."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.kc import api as kc_api
from src.kc.contracts.evidence import evidence_for_quote
from src.kc.compiler.normalize import CanonicalDocument
from src.kc.publish import ObjectVersion, PublicationGate
from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import KnowledgeObject


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _write_text(path: Path, content: str) -> None:
    target = path
    if os.name == "nt":
        absolute = os.path.abspath(path)
        if len(absolute) >= 260:
            target = Path("\\\\?\\" + absolute)
    target.write_text(content, encoding="utf-8")


@dataclass(frozen=True)
class ReviewResult:
    candidate_id: str
    document_id: str
    status: str
    reason_codes: tuple[str, ...]
    objects: tuple[KnowledgeObject, ...] = ()
    projections: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class PromotionResult:
    bundle_key: str
    candidate_id: str
    object_ids: tuple[str, ...]
    manifest_path: Path


@dataclass(frozen=True)
class PublicationResult:
    bundle_key: str
    batch_id: str
    status: str
    publication_version: int


class CandidateReviewer:
    """Run the existing source/evidence compiler as the mandatory review."""

    async def review(
        self,
        candidate: KnowledgeCandidate,
        document: CanonicalDocument,
        *,
        source_root: Path | None = None,
        visible_block_ids: set[str] | None = None,
    ) -> ReviewResult:
        try:
            payload = kc_api.candidate_to_payload(
                asdict(candidate),
                document,
                source_root=source_root,
                allow_legacy_unique_quote=False,
                visible_block_ids=visible_block_ids,
            )
            result = await kc_api.compile_source(
                str(document.source),
                document=document,
                candidate_json=json.dumps(payload, ensure_ascii=False),
            )
        except (ValueError, KeyError, TypeError) as exc:
            candidate.status = CandidateStatus.REJECTED
            candidate.failure_reason = f"review:{type(exc).__name__}:{exc}"
            return ReviewResult(
                candidate_id=candidate.id,
                document_id=document.document_id,
                status="rejected",
                reason_codes=("review:structural_evidence_failed",),
            )

        candidate.status = CandidateStatus.VALIDATED
        document_id = str(result.get("document_id", document.document_id))
        return ReviewResult(
            candidate_id=candidate.id,
            document_id=document_id,
            status="validated",
            reason_codes=(),
            objects=tuple(result.get("objects", ())),
            projections=tuple(result["projections"]),
        )


class CandidatePromoter:
    """Persist a validated candidate bundle before any final publication."""

    projection_version = "kc-wiki-v1"

    def promote(
        self,
        candidate: KnowledgeCandidate,
        review: ReviewResult,
        *,
        project_root: Path,
        document: CanonicalDocument,
    ) -> PromotionResult:
        if review.status != "validated" or candidate.status != CandidateStatus.VALIDATED:
            raise ValueError("only a validated candidate can be promoted")
        bundle_key = hashlib.sha256(
            f"{document.document_id}:{candidate.id}:{self.projection_version}".encode()
        ).hexdigest()
        bundle_dir = Path(project_root) / ".index" / "kc" / "bundles"
        objects_dir = bundle_dir / bundle_key / "objects"
        evidence_dir = bundle_dir / bundle_key / "evidence"
        objects_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for obj in review.objects:
            _write_text(
                objects_dir / f"{obj.id}.json",
                json.dumps(_json_value(obj), ensure_ascii=False, indent=2),
            )
        for item in candidate.evidence:
            quote = item.get("quote", "")
            evidence = evidence_for_quote(
                document_id=document.document_id,
                block_id=str(item.get("block_id", "")),
                quote=str(quote),
                supports=tuple(
                    review.objects[index].id
                    for index, claim in enumerate(candidate.claims)
                    if item.get("source_path") == str(document.source)
                    and isinstance(claim.get("evidence_refs"), list)
                    and any(ref == candidate.evidence.index(item) for ref in claim["evidence_refs"])
                    and index < len(review.objects)
                ),
            )
            evidence_path = evidence_dir / f"{evidence.evidence_id}.json"
            _write_text(
                evidence_path,
                json.dumps(_json_value(evidence), ensure_ascii=False, indent=2),
            )
        candidate.status = CandidateStatus.PROMOTED
        candidate_path = bundle_dir / bundle_key / "candidate.json"
        _write_text(
            candidate_path,
            json.dumps(_json_value(candidate), ensure_ascii=False, indent=2),
        )
        manifest = {
            "bundle_key": bundle_key,
            "candidate_id": candidate.id,
            "document_id": document.document_id,
            "source_path": str(document.source),
            "normalization_version": document.normalization_version,
            "parser_version": document.parser_version,
            "projection_version": self.projection_version,
            "object_ids": [obj.id for obj in review.objects],
            "candidate_path": str(candidate_path.relative_to(bundle_dir)),
            "stores": {"knowledge_object": "ready", "wiki": "pending", "index": "pending", "vector": "pending"},
            "status": "staged",
        }
        manifest_path = bundle_dir / bundle_key / "manifest.json"
        _write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
        return PromotionResult(bundle_key, candidate.id, tuple(obj.id for obj in review.objects), manifest_path)


def finalize_bundle(
    project_root: Path,
    *,
    bundle_key: str,
    page_ids: tuple[str, ...],
    vector_ready: bool = False,
) -> PublicationResult:
    """Register Wiki/Core completion and publish only when vector is ready."""
    bundle_dir = Path(project_root) / ".index" / "kc" / "bundles" / bundle_key
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") == "published":
        return PublicationResult(
            bundle_key, manifest["batch_id"], "published", int(manifest["publication_version"])
        )
    gate = PublicationGate(Path(project_root) / ".index" / "kc" / "publication_state.json").load()
    batch = gate.get_batch(manifest.get("batch_id", ""))
    if batch is None:
        batch = gate.create_batch([
            ObjectVersion("knowledge_object", object_id, 1)
            for object_id in manifest.get("object_ids", [])
        ])
    manifest.update({
        "batch_id": batch.batch_id,
        "page_ids": list(page_ids),
        "stores": {"knowledge_object": "ready", "wiki": "ready", "index": "ready", "vector": "ready" if vector_ready else "pending"},
        "publication_version": batch.publication_version,
        "status": "staged" if not vector_ready else "published",
    })
    if vector_ready:
        gate.publish_batch(batch.batch_id)
    gate.persist()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return PublicationResult(
        bundle_key, batch.batch_id, manifest["status"], batch.publication_version
    )


async def index_and_publish_bundle(
    project_root: Path,
    *,
    bundle_key: str,
    pages: list[Any],
) -> PublicationResult:
    """Try vector indexing, then advance the bundle's publication waterline."""
    from src.utils.text import chunk_markdown
    from src.utils.path import normalize_source_path
    from src.wiki.core.paths import WikiPaths
    from src.types import VectorChunk
    from src.llm.embedding_runtime import get_embedding_provider
    from src.vector.upsert import vector_upsert_chunks
    from src.vector.pending import clear_pending
    from datetime import datetime, timezone

    try:
        provider = get_embedding_provider()
        chunks: list[tuple[Any, str]] = []
        for page in pages:
            for index, chunk in enumerate(chunk_markdown(page.body or page.title or "")):
                chunks.append((page, chunk))
        if chunks:
            results = await provider.embed([item[1] for item in chunks])
            embeddings = [item.embedding if hasattr(item, "embedding") else item for item in results]
            if len(embeddings) != len(chunks):
                raise ValueError("vector embedding count does not match chunks")
            now = int(datetime.now(timezone.utc).timestamp() * 1000)
            vector_upsert_chunks([
                VectorChunk(
                    id=f"{page.id}-chunk-{index}", task_id=page.id,
                    content=chunk, embedding=embedding,
                    path=normalize_source_path(page.id, project_root), updated_at=now,
                )
                for index, ((page, chunk), embedding) in enumerate(zip(chunks, embeddings))
            ])
        clear_pending(WikiPaths(project_root), [page.id for page in pages])
        return finalize_bundle(project_root, bundle_key=bundle_key, page_ids=tuple(page.id for page in pages), vector_ready=True)
    except Exception:
        return finalize_bundle(project_root, bundle_key=bundle_key, page_ids=tuple(page.id for page in pages), vector_ready=False)


async def recover_staged_bundles(project_root: Path) -> list[PublicationResult]:
    """Retry staged bundles after a process crash or vector outage."""
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import read_page

    paths = WikiPaths(project_root)
    bundle_root = Path(project_root) / ".index" / "kc" / "bundles"
    results: list[PublicationResult] = []
    if not bundle_root.exists():
        return results
    for manifest_path in sorted(bundle_root.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "staged" or manifest.get("stores", {}).get("vector") != "pending":
            continue
        pages = []
        for page_id in manifest.get("page_ids", []):
            matches = [p for p in paths.wiki.rglob("*.md") if p.stem == page_id]
            if matches:
                pages.append(read_page(matches[0]))
        if len(pages) != len(manifest.get("page_ids", [])):
            continue
        results.append(await index_and_publish_bundle(
            Path(project_root), bundle_key=manifest["bundle_key"], pages=pages
        ))
    return results


__all__ = ["CandidatePromoter", "CandidateReviewer", "PublicationResult", "PromotionResult", "ReviewResult", "finalize_bundle", "index_and_publish_bundle", "recover_staged_bundles"]
