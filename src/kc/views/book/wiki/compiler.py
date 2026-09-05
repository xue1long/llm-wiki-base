"""Small, fail-closed compiler and pointer publisher for Wiki Book output."""
from __future__ import annotations

import hashlib
import asyncio
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .aggregator import aggregate_chapter, relation_stats
from .model import PageRecord, WikiSnapshot
from .reading_aids import build_glossary, build_glossary_index, build_index
from .preflight import LockBusyError, acquire_run_lock, release_run_lock, run_preflight
from .partition import build_chapter_chunks, partition_pages
from .scanner import WikiScanError, scan_wiki_snapshot
from .outline_validate import SCHEMA_VERSION, validate_outline
from .outline_llm import OutlinePlanningError, plan_outline

MAX_UNRESOLVED_RELATION_RATIO = 0.05


@dataclass(frozen=True)
class BuildArtifact:
    snapshot_id: str
    manifest: dict[str, Any]
    version_dir: Path
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishReport:
    status: str
    run_id: str
    pointer: Path | None = None
    error: str | None = None


def _json(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {k: _json(v) for k, v in value.__dict__.items()}
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe(value: str) -> str:
    result = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(value))
    return result.strip(".") or "unnamed"


def _pages(value: dict[str, PageRecord] | tuple[PageRecord, ...] | list[PageRecord]) -> dict[str, PageRecord]:
    return value if isinstance(value, dict) else {page.page_id: page for page in value}


def _chapters(outlines: list[dict]) -> list[tuple[str, str, dict]]:
    result = []
    for outline in outlines:
        for volume in outline.get("volumes", ()) if isinstance(outline, dict) else ():
            if not isinstance(volume, dict):
                continue
            for chapter in volume.get("chapters", ()) if isinstance(volume.get("chapters"), list) else ():
                if isinstance(chapter, dict):
                    result.append((str(volume.get("volume_id", "")), str(chapter.get("chapter_id", "")), chapter))
    return result


def _source_provenance(snapshot: WikiSnapshot) -> list[dict[str, str]]:
    excluded = set(snapshot.excluded_sources)
    rows: list[dict[str, str]] = []
    for page in snapshot.pages:
        for source in page.sources:
            rows.append({"page_id": page.page_id, "source": source})
        for relation_type, target_id in page.relation_targets:
            if target_id in excluded:
                rows.append({"page_id": page.page_id, "relation_type": relation_type,
                             "target_id": target_id})
    return sorted(rows, key=lambda row: tuple(row.get(k, "") for k in ("page_id", "source", "relation_type", "target_id")))


def compile_book(snapshot: WikiSnapshot, outlines: list[dict], pages: Any, *, fingerprint: Any,
                 polish: bool = False, encyclopedic: bool = False, state_dir: Path | None = None,
                 outline_generation_mode: str = "rule",
                 outline_fallback_reason: str | None = None,
                 outline_llm_requested: bool = False) -> BuildArtifact:
    page_map = _pages(pages)
    errors: list[str] = []
    if snapshot.snapshot_id not in {str(o.get("snapshot_id")) for o in outlines if isinstance(o, dict)}:
        errors.append("snapshot-mismatch")
    chapters = _chapters(outlines)
    seen: list[str] = []
    for _volume, chapter_id, chapter in chapters:
        if not chapter_id:
            errors.append("missing-chapter-id")
        ids = [x if isinstance(x, str) else x.get("page_id") for x in chapter.get("page_ids", ())]
        for page_id in ids:
            if page_id not in page_map:
                errors.append(f"unknown-page:{page_id}")
            seen.append(str(page_id))
    expected = sorted(page_map)
    if sorted(seen) != expected:
        errors.append("page-coverage")
    run_id = uuid.uuid4().hex
    root = Path(state_dir or Path(snapshot.wiki_root).parent / ".index")
    versions = root if root.name == "versions" else root / "book-wiki" / "versions"
    version_dir = versions / run_id
    if errors:
        return BuildArtifact(snapshot.snapshot_id, {"run_id": run_id, "validation_errors": errors}, version_dir, tuple(errors))
    version_dir.mkdir(parents=True, exist_ok=False)
    files: dict[str, str] = {}
    used: set[str] = set()
    chapter_sources: dict[str, list[str]] = {}
    for volume_id, chapter_id, chapter in chapters:
        name = f"{_safe(volume_id)}__{_safe(chapter_id)}.md"
        if name in used:
            errors.append(f"filename-collision:{name}")
            continue
        used.add(name)
        draft = aggregate_chapter(chapter, page_map)
        chapter_sources[name] = sorted({source for page_id in draft.page_ids for source in page_map[page_id].sources})
        text = "## 本章导读\n\n本章为规则版排序。\n\n"
        text += "\n\n".join((f"### {block.heading}" if block.heading else "") + ("\n\n" if block.heading else "") + block.body for block in draft.blocks)
        text += "\n\n## 本章衔接\n\n本章为规则版排序。\n"
        path = version_dir / name
        path.write_text(text, encoding="utf-8")
        files[name] = _sha(path)
    glossary = build_glossary(snapshot)
    glossary_text = "# 术语表\n\n" + "\n".join(f"- {e.page_id}: {e.title}（{e.page_type}，等级 {e.grade}）" for e in glossary.values()) + "\n"
    (version_dir / "glossary.md").write_text(glossary_text, encoding="utf-8")
    files["glossary.md"] = _sha(version_dir / "glossary.md")
    glossary_index = build_glossary_index(glossary)
    (version_dir / "glossary_index.json").write_text(json.dumps(glossary_index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    files["glossary_index.json"] = _sha(version_dir / "glossary_index.json")
    index = build_index(snapshot, outlines)
    index_text = "# 索引\n\n" + "\n".join(f"- {e.page_id}: {e.title} ({e.chapter_id or '未分配'}，{e.page_type}，等级 {e.grade})" for e in index.entries.values()) + "\n"
    (version_dir / "index.md").write_text(index_text, encoding="utf-8")
    files["index.md"] = _sha(version_dir / "index.md")
    outline_path = version_dir / "outline.json"
    outline_path.write_text(json.dumps(outlines, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    files["outline.json"] = _sha(outline_path)
    stats = relation_stats(snapshot)
    all_blocks = tuple(block.block_id for page in page_map.values() for block in page.content_blocks)
    draft_blocks = tuple(block.block_id for volume_id, chapter_id, chapter in chapters for block in aggregate_chapter(chapter, page_map).blocks)
    manifest: dict[str, Any] = {"manifest_version": 1, "run_id": run_id, "snapshot_id": snapshot.snapshot_id,
        "fingerprint": _json(fingerprint), "source_filter": ["concepts", "entities", "synthesis"],
        "page_count": len(page_map), "chapter_count": len(chapters), "files": files, "polished": bool(polish),
        "reading_experience_mode": "encyclopedic" if encyclopedic else ("llm_enhanced" if polish else "rule_only"),
        "expected_block_ids": list(all_blocks), "draft_block_ids": list(draft_blocks),
        "unresolved_ratio": stats["unresolved_ratio"], "total_relations": stats["total"], "unresolved": stats["unresolved"],
        "unmatched_heading_ratio": 0.0, "glossary_coverage": 1.0,
        "relation_stats": _json(stats),
        "glossary_sha256": files["glossary.md"], "glossary_index_sha256": files["glossary_index.json"],
        "index_sha256": files["index.md"], "quality_gate": {"status": "not_run"},
        "excluded_sources": list(snapshot.excluded_sources),
        "outline_generation_mode": outline_generation_mode,
        "outline_llm_requested": bool(outline_llm_requested),
        "body_generation_mode": "rule_aggregate",
        "outline_fallback_reason": outline_fallback_reason}
    manifest["chapter_sources"] = chapter_sources
    manifest["source_provenance"] = _source_provenance(snapshot)
    (version_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return BuildArtifact(snapshot.snapshot_id, manifest, version_dir, tuple(errors))


def publish_book(artifact: BuildArtifact, output_dir: Path, *, apply: bool, lock: Any) -> PublishReport:
    if artifact.validation_errors:
        return PublishReport("failed", str(artifact.manifest.get("run_id", "")), error=";".join(artifact.validation_errors))
    run_id = str(artifact.manifest["run_id"])
    if not apply:
        return PublishReport("planned", run_id)
    release = Path(output_dir) / ".releases" / run_id
    try:
        release.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(artifact.version_dir, release)
        manifest_path = release / "manifest.json"
        expected = artifact.manifest.get("files", {})
        if any(_sha(release / name) != digest for name, digest in expected.items()):
            raise ValueError("release file hash mismatch")
        pointer_dir = Path(output_dir)
        pointer_dir.mkdir(parents=True, exist_ok=True)
        pointer = pointer_dir / "CURRENT.json"
        temp = pointer_dir / f".CURRENT.{run_id}.tmp"
        payload = {"version": run_id, "manifest_sha256": _sha(manifest_path)}
        temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(temp, pointer)
        # Keep a small bounded history; the active release is never eligible.
        releases = sorted((p for p in (pointer_dir / ".releases").iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        for old in releases[:-5]:
            if old.name != run_id:
                shutil.rmtree(old, ignore_errors=True)
        return PublishReport("committed", run_id, pointer=pointer)
    except Exception as exc:
        shutil.rmtree(release, ignore_errors=True)
        return PublishReport("failed", run_id, error=f"{type(exc).__name__}: {exc}")


def resolve_active_version(output_dir: Path) -> Path | None:
    root = Path(output_dir)
    book = root if root.name == "book-wiki" else root / "book-wiki"
    pointer = book / "CURRENT.json"
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
        run_id, digest = data["version"], data["manifest_sha256"]
        if not isinstance(run_id, str) or not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
            return None
        release = book / ".releases" / run_id
        manifest = release / "manifest.json"
        if not manifest.is_file() or _sha(manifest) != digest:
            return None
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        files = payload.get("files", {})
        if not isinstance(files, dict):
            return None
        for name, expected in files.items():
            relative = Path(str(name))
            if relative.is_absolute() or ".." in relative.parts or relative.name != str(name):
                return None
            target = release / relative
            if not target.is_file() or _sha(target) != expected:
                return None
        return release
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def build_from_wiki(project_root: Path, *, output_dir: Path, use_llm: bool = False,
                    polish: bool = False, apply: bool = False,
                    encyclopedic: bool = False, quality_gate: str = "rule", rubric: str | Path | None = None,
                    max_attempts: int = 3, max_input_tokens: int | None = None,
                    max_output_tokens: int | None = None, provider: Any = None) -> dict[str, Any]:
    """Run the rule-only safety path used by the CLI.

    Encyclopedic mode adds a bounded, evidence-only index.  It never rewrites
    chapter bodies and fails closed when a provider or valid evidence is absent.
    """
    del max_attempts
    if encyclopedic and not use_llm:
        return {"status": "failed", "reason_codes": ["E_ENCYCLOPEDIC_REQUIRES_LLM"]}
    if apply and quality_gate == "off":
        return {"status": "failed", "reason_codes": ["E_QUALITY_GATE_REQUIRED_FOR_APPLY"],
                "error": "quality gate off is allowed only for dry-run"}
    root = Path(project_root).resolve()
    # An injected provider is an explicit in-process dependency (used by
    # callers/tests); registry validation still applies to CLI/env-driven use.
    preflight = run_preflight(str(root), output_dir=Path(output_dir), use_llm=use_llm,
                              provider_name=None, polish=polish) if provider is None else run_preflight(
                                  str(root), output_dir=Path(output_dir), use_llm=False,
                                  provider_name=None, polish=polish)
    if not preflight.ok:
        return {"status": "blocked", "errors": [e.code for e in preflight.errors]}
    try:
        snapshot = scan_wiki_snapshot(root / "wiki")
    except WikiScanError as exc:
        return {"status": "failed", "reason_codes": [exc.code], "error": str(exc)}
    if not snapshot.pages:
        return {"status": "failed", "reason_codes": ["no-pages"], "error": "no eligible wiki pages"}
    relation_summary = relation_stats(snapshot)
    if relation_summary["unresolved_ratio"] > MAX_UNRESOLVED_RELATION_RATIO:
        return {"status": "failed", "reason_codes": ["unresolved-relation-over-threshold"],
                "relation_stats": _json(relation_summary)}
    partitions = partition_pages(snapshot)
    chunks = build_chapter_chunks(snapshot, partitions,
                                   context_window=max_input_tokens or 8000,
                                   output_reserve=max_output_tokens or 1000)
    volumes: dict[str, list[dict[str, Any]]] = {}
    for chapter_id, page_ids in sorted(chunks.items()):
        volume_id = chapter_id.rsplit(":", 1)[0]
        volumes.setdefault(volume_id, []).append({"chapter_id": chapter_id,
            "title": chapter_id, "page_ids": list(page_ids), "overview_refs": [page_ids[0]]})
    rule_outline = {"schema_version": SCHEMA_VERSION, "snapshot_id": snapshot.snapshot_id,
                    "volumes": [{"volume_id": vid, "title": vid, "chapters": chapters,
                                  "is_fallback": vid == "fallback"}
                                 for vid, chapters in sorted(volumes.items())]}
    outline = rule_outline
    outline_generation_mode = "rule"
    outline_fallback_reason: str | None = None
    if use_llm:
        if provider is None:
            try:
                from src.llm.provider_factory import create_llm_provider
                provider = create_llm_provider(preflight.provider or "")
            except Exception as exc:
                return {"status": "failed", "reason_codes": ["E_OUTLINE_PROVIDER_UNAVAILABLE"],
                        "error": f"LLM provider unavailable: {exc}"}
        try:
            planned_outlines = asyncio.run(plan_outline(
                snapshot, chunks, provider,
                context_window=max_input_tokens or 8000,
                token_budget=max_output_tokens or 1000,
            ))
            outline = planned_outlines[0]
            outline_generation_mode = str(outline.get("generation_mode", "llm"))
            if outline_generation_mode == "rule_fallback":
                outline_fallback_reason = "all_chunks_fallback"
            elif outline_generation_mode == "llm_partial":
                outline_fallback_reason = "some_chunks_fallback"
        except OutlinePlanningError as exc:
            outline = rule_outline
            outline_generation_mode = "rule_fallback"
            outline_fallback_reason = type(exc).__name__
    validation = validate_outline(snapshot, [outline])
    if not validation.ok:
        return {"status": "failed", "reason_codes": [e.code for e in validation.errors]}
    encyclopedic_index = None
    if encyclopedic:
        if provider is None:
            try:
                from src.llm.provider_factory import create_llm_provider
                provider = create_llm_provider(preflight.provider or "")
            except Exception as exc:
                return {"status": "failed", "reason_codes": ["E_ENCYCLOPEDIC_PROVIDER_UNAVAILABLE"],
                        "error": f"LLM provider unavailable: {exc}"}
        try:
            from .encyclopedic_outline import generate_encyclopedic_outline
            encyclopedic_index = asyncio.run(generate_encyclopedic_outline(snapshot, provider))
        except Exception as exc:
            return {"status": "failed", "reason_codes": ["E_ENCYCLOPEDIC_PROVIDER_UNAVAILABLE"],
                    "error": str(exc)}
    artifact = compile_book(snapshot, [outline], snapshot.pages,
                            fingerprint={"snapshot_id": snapshot.snapshot_id, "use_llm": use_llm},
                            polish=polish, encyclopedic=encyclopedic, state_dir=root / ".index",
                            outline_generation_mode=outline_generation_mode,
                            outline_fallback_reason=outline_fallback_reason,
                            outline_llm_requested=use_llm)
    if artifact.validation_errors:
        return {"status": "failed", "reason_codes": list(artifact.validation_errors)}
    if encyclopedic_index is not None:
        from .cross_links import build_cross_link_candidates
        index_path = artifact.version_dir / "encyclopedic_outline.json"
        index_path.write_text(json.dumps(encyclopedic_index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        index_hash = _sha(index_path)
        manifest = {**artifact.manifest}
        files = {**manifest.get("files", {}), index_path.name: index_hash}
        manifest.update({"files": files, "encyclopedic_outline_sha256": index_hash,
                         "cross_link_candidates": build_cross_link_candidates(encyclopedic_index, {p.page_id for p in snapshot.pages})})
        artifact = BuildArtifact(artifact.snapshot_id, manifest, artifact.version_dir, artifact.validation_errors)
    quality = None
    rubric_report = None
    if quality_gate not in {"rule", "both", "off"}:
        return {"status": "failed", "reason_codes": ["E_INVALID_QUALITY_GATE"]}
    if quality_gate in {"rule", "both"}:
        from .quality_gate import check_quality_gate
        quality = check_quality_gate(artifact.manifest, llm_status="disabled" if quality_gate == "rule" else "unavailable")
        artifact = BuildArtifact(artifact.snapshot_id, {**artifact.manifest, "quality_gate": quality.__dict__}, artifact.version_dir, artifact.validation_errors)
        if not quality.ok:
            return {"status": "failed", "reason_codes": ["E_QUALITY_GATE_BLOCKED"], "quality_gate": quality.__dict__}
    if rubric:
        from .rubric import load_rubric
        from .reader_tasks import run_reader_tasks, task_pass_rate
        specs = load_rubric(rubric)
        reports = run_reader_tasks(specs, artifact.version_dir)
        rubric_report = {"pass_rate": task_pass_rate(reports), "tasks": [r.to_dict() for r in reports]}
        if rubric_report["pass_rate"] < 0.8:
            artifact = BuildArtifact(artifact.snapshot_id, {**artifact.manifest, "rubric": rubric_report}, artifact.version_dir, artifact.validation_errors)
    if quality is None:
        artifact = BuildArtifact(artifact.snapshot_id, {**artifact.manifest, "quality_gate": {"status": "off"}}, artifact.version_dir, artifact.validation_errors)
    # Rewrite manifest after optional gate/rubric metadata is known.
    (artifact.version_dir / "manifest.json").write_text(json.dumps(artifact.manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    lock = None
    try:
        if apply:
            lock = acquire_run_lock(root / ".index" / "book-wiki.lock", stale_after_seconds=3600)
        report = publish_book(artifact, Path(output_dir), apply=apply, lock=lock)
        result = {"status": report.status, "run_id": report.run_id,
                    "snapshot_id": snapshot.snapshot_id, "version_dir": str(artifact.version_dir),
                    "error": report.error} if report.error else {
                    "status": report.status, "run_id": report.run_id,
                    "snapshot_id": snapshot.snapshot_id, "version_dir": str(artifact.version_dir)}
        if quality is not None: result["quality_gate"] = quality.__dict__
        if rubric_report is not None: result["rubric"] = rubric_report
        if rubric_report is not None and rubric_report["pass_rate"] < 0.8:
            result["warnings"] = ["E_RUBRIC_BELOW_THRESHOLD"]
        return result
    finally:
        if lock is not None:
            release_run_lock(lock)


__all__ = ["BuildArtifact", "PublishReport", "compile_book", "publish_book", "resolve_active_version", "build_from_wiki"]
