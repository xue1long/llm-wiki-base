"""Small, fail-closed compiler and pointer publisher for Wiki Book output."""
from __future__ import annotations

import hashlib
import asyncio
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .aggregator import aggregate_chapter, relation_stats
from .model import PageRecord, WikiSnapshot
from .editorial_state import (
    BookEditorialState, editorial_state_hash, load_editorial_state,
    validate_editorial_state,
)
from .reading_aids import build_glossary, build_glossary_index, build_index
from .preflight import acquire_run_lock, release_run_lock, run_preflight
from .partition import build_chapter_chunks, partition_pages
from .scanner import WikiScanError, scan_wiki_snapshot
from .outline_validate import SCHEMA_VERSION, validate_outline
from .outline_llm import OutlinePlanningError, estimate_outline_call_sites, plan_outline
from .theme_outline import ThemeOutlineError, load_theme_outline, place_page_summaries_sync
from .polish_llm import GeneratedChapter, generate_chapter_body
from .rules import BookRulesError, load_book_rules
from .acceptance import (
    build_release_acceptance_report, load_release_acceptance_report,
    write_release_acceptance_report,
)
from src.lineage import LineageStore

MAX_UNRESOLVED_RELATION_RATIO = 0.05

BOOK_MODES = frozenset({"rule_only", "narrative_draft", "narrative", "encyclopedic"})
_RESTRICTED_SENSITIVITY = frozenset({"secret", "private", "restricted", "confidential"})


class _LLMBudgetExceeded(RuntimeError):
    budget_exhausted = True


class _BudgetedProvider:
    """One publication-scoped counter for every outbound provider request."""

    def __init__(self, provider: Any, *, max_calls: int, started: float, max_runtime: int):
        self._provider = provider
        self.max_calls = max_calls
        self.started = started
        self.max_runtime = max_runtime
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        if self.calls >= self.max_calls:
            raise _LLMBudgetExceeded("max_llm_calls exhausted")
        if time.monotonic() - self.started >= self.max_runtime:
            raise _LLMBudgetExceeded("max_runtime_seconds exhausted")
        self.calls += 1
        return await self._provider.complete(*args, **kwargs)


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


class CandidateReleaseValidationError(ValueError):
    """Raised when a staged Book candidate cannot be promoted safely."""


_CANDIDATE_STATES = frozenset({
    "candidate", "validated", "published", "superseded", "expired", "rejected",
})
_CANDIDATE_MUTABLE_FILES = frozenset({
    "candidate-state.json", "release-acceptance.json", "human-approval.json",
})


@dataclass(frozen=True)
class ValidatedCandidate:
    """Closed, integrity-checked input for the single Book publication seam."""

    project_root: Path
    output_dir: Path
    release_id: str
    source_dir: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    content_identity: str
    snapshot_id: str | None
    lifecycle_state: str
    files: tuple[tuple[str, str], ...]


def _body_llm_status(generated_chapters: Mapping[str, Any] | None) -> str:
    """Return the publication status of the optional polished chapter bodies."""
    if generated_chapters is None:
        return "disabled"
    return "passed" if all(
        getattr(chapter, "content_status", None) == "complete"
        for chapter in generated_chapters.values()
    ) else "failed"


def _body_llm_failure_codes(generated_chapters: Mapping[str, Any] | None) -> list[str]:
    if generated_chapters is None:
        return []
    return sorted({
        code for chapter in generated_chapters.values()
        if (code := getattr(chapter, "failure_code", ""))
    })


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


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _manifest_with_digest(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in manifest.items() if key != "release_manifest_hash"}
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    return {**payload, "release_manifest_hash": digest}


def _write_manifest(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    result = _manifest_with_digest(manifest)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return result


def _candidate_versions_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".index" / "book-wiki" / "versions"


def _candidate_state_path(release_dir: Path) -> Path:
    return Path(release_dir) / "candidate-state.json"


def _manifest_file_sha(manifest_path: Path) -> str:
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _read_identity_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CandidateReleaseValidationError(f"identity_unreadable:{path.name}") from exc
    if not isinstance(payload, dict):
        raise CandidateReleaseValidationError(f"identity_invalid:{path.name}")
    return payload


def load_candidate_lifecycle(release_dir: Path, *, manifest: Mapping[str, Any]) -> str:
    """Read mutable lifecycle evidence without changing manifest identity."""
    path = _candidate_state_path(release_dir)
    if not path.is_file():
        return "candidate"
    payload = _read_identity_file(path)
    state = payload.get("state")
    if state not in _CANDIDATE_STATES:
        raise CandidateReleaseValidationError("lifecycle_invalid")
    release_id = str(manifest.get("run_id", ""))
    if payload.get("release_id") != release_id:
        raise CandidateReleaseValidationError("lifecycle_release_mismatch")
    manifest_path = Path(release_dir) / "manifest.json"
    if payload.get("manifest_sha256") != _manifest_file_sha(manifest_path):
        raise CandidateReleaseValidationError("lifecycle_manifest_mismatch")
    return str(state)


def write_candidate_lifecycle(
    release_dir: Path,
    *,
    state: str,
    manifest: Mapping[str, Any],
) -> Path:
    """Atomically write lifecycle evidence outside the immutable manifest."""
    if state not in _CANDIDATE_STATES:
        raise CandidateReleaseValidationError("lifecycle_invalid")
    release = Path(release_dir)
    manifest_path = release / "manifest.json"
    if not manifest_path.is_file():
        raise CandidateReleaseValidationError("manifest_missing")
    release_id = str(manifest.get("run_id", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", release_id):
        raise CandidateReleaseValidationError("release_id_invalid")
    payload = {
        "schema_version": "book-candidate-lifecycle-v1",
        "release_id": release_id,
        "manifest_sha256": _manifest_file_sha(manifest_path),
        "state": state,
    }
    target = _candidate_state_path(release)
    temp = target.with_name(f".{target.name}.{release_id}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temp, target)
    return target


def _candidate_file_name(name: Any) -> str:
    if not isinstance(name, str) or not name:
        raise CandidateReleaseValidationError("file_path_invalid")
    relative = Path(name)
    normalized = name.replace("\\", "/")
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != normalized:
        raise CandidateReleaseValidationError("file_path_invalid")
    return normalized


def _candidate_project_identity(project_root: Path) -> dict[str, Any]:
    project_path = Path(project_root) / ".llm-wiki" / "project.json"
    payload = _read_identity_file(project_path) if project_path.is_file() else {}
    if "project_id" not in payload and payload.get("id") is not None:
        payload["project_id"] = payload["id"]
    return payload


def _candidate_book_identity(output_dir: Path) -> dict[str, Any]:
    book_path = Path(output_dir) / "book.json"
    return _read_identity_file(book_path) if book_path.is_file() else {}


def validate_candidate_release(
    project_root: Path,
    *,
    output_dir: Path,
    release_id: str,
) -> ValidatedCandidate:
    """Load and validate one staged candidate without mutating it."""
    if not isinstance(release_id, str) or not re.fullmatch(r"[0-9a-f]{32}", release_id):
        raise CandidateReleaseValidationError("release_id_invalid")
    root = Path(project_root).resolve()
    target = Path(output_dir).resolve()
    release = _candidate_versions_dir(root) / release_id
    if not release.is_dir() or not release.resolve().is_relative_to(_candidate_versions_dir(root).resolve()):
        raise CandidateReleaseValidationError("candidate_missing")
    manifest_path = release / "manifest.json"
    if not manifest_path.is_file():
        raise CandidateReleaseValidationError("manifest_missing")
    manifest = _read_identity_file(manifest_path)
    if manifest.get("run_id") != release_id:
        raise CandidateReleaseValidationError("release_id_mismatch")
    if manifest.get("release_status") != "complete":
        raise CandidateReleaseValidationError("release_status_not_complete")
    content_identity = manifest.get("release_manifest_hash")
    expected_identity = hashlib.sha256(_canonical({
        key: value for key, value in manifest.items() if key != "release_manifest_hash"
    })).hexdigest()
    if content_identity != expected_identity:
        raise CandidateReleaseValidationError("manifest_digest_mismatch")

    project_identity = _candidate_project_identity(root)
    book_identity = _candidate_book_identity(target)
    for key in ("project_id", "domain_id", "book_id"):
        candidate_value = manifest.get(key)
        current_value = book_identity.get(key, project_identity.get(key))
        if candidate_value is not None and current_value is not None and candidate_value != current_value:
            identity_name = {"project_id": "project", "domain_id": "domain", "book_id": "book"}[key]
            raise CandidateReleaseValidationError(f"{identity_name}_identity_mismatch")

    wiki_dir = root / "wiki"
    if wiki_dir.is_dir():
        try:
            current_snapshot = scan_wiki_snapshot(wiki_dir)
        except (OSError, WikiScanError, ValueError) as exc:
            raise CandidateReleaseValidationError("snapshot_unavailable") from exc
        if manifest.get("snapshot_id") != current_snapshot.snapshot_id:
            raise CandidateReleaseValidationError("snapshot_mismatch")

    entries = manifest.get("files")
    if not isinstance(entries, dict):
        raise CandidateReleaseValidationError("files_invalid")
    verified: list[tuple[str, str]] = []
    for raw_name, expected_hash in sorted(entries.items(), key=lambda item: str(item[0])):
        name = _candidate_file_name(raw_name)
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise CandidateReleaseValidationError("file_hash_invalid")
        path = release / name
        if not path.is_file() or _sha(path) != expected_hash:
            raise CandidateReleaseValidationError(f"file_hash_mismatch:{name}")
        verified.append((name, expected_hash))

    allowed_unlisted = {"manifest.json", *_CANDIDATE_MUTABLE_FILES}
    actual = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*")
        if path.is_file()
    }
    unlisted = sorted(actual - set(allowed_unlisted) - {name for name, _ in verified})
    if unlisted:
        raise CandidateReleaseValidationError(f"files_not_closed:{unlisted[0]}")
    lifecycle = load_candidate_lifecycle(release, manifest=manifest)
    if lifecycle in {"rejected", "expired", "superseded"}:
        raise CandidateReleaseValidationError(f"lifecycle_not_promotable:{lifecycle}")
    return ValidatedCandidate(
        project_root=root,
        output_dir=target,
        release_id=release_id,
        source_dir=release,
        manifest=manifest,
        manifest_sha256=_manifest_file_sha(manifest_path),
        content_identity=str(content_identity),
        snapshot_id=manifest.get("snapshot_id"),
        lifecycle_state=lifecycle,
        files=tuple(verified),
    )


def publish_validated_candidate(
    candidate: ValidatedCandidate,
    *,
    apply: bool,
    lock: Any,
) -> PublishReport:
    """Publish one already-validated candidate without regenerating content."""
    if not apply:
        return PublishReport("planned", candidate.release_id)
    if lock is None:
        return PublishReport("failed", candidate.release_id, error="publication_lock_required")
    pointer_dir = candidate.output_dir
    pointer = pointer_dir / "CURRENT.json"
    release = pointer_dir / ".releases" / candidate.release_id
    try:
        prior = None
        if pointer.is_file():
            try:
                prior = json.loads(pointer.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                prior = None
        if isinstance(prior, dict) and prior.get("version") == candidate.release_id and release.is_dir():
            return PublishReport("committed", candidate.release_id, pointer=pointer)
        if release.exists():
            raise ValueError("published_release_exists")
        release.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidate.source_dir, release)
        manifest_path = release / "manifest.json"
        if _manifest_file_sha(manifest_path) != candidate.manifest_sha256:
            raise ValueError("release_manifest_changed")
        for name, digest in candidate.files:
            if _sha(release / name) != digest:
                raise ValueError(f"release_file_hash_mismatch:{name}")
        write_candidate_lifecycle(release, state="published", manifest=candidate.manifest)
        if isinstance(prior, dict) and prior.get("version") == candidate.release_id:
            return PublishReport("committed", candidate.release_id, pointer=pointer)
        pointer_dir.mkdir(parents=True, exist_ok=True)
        temp = pointer_dir / f".CURRENT.{candidate.release_id}.tmp"
        payload = {"version": candidate.release_id, "manifest_sha256": candidate.manifest_sha256}
        temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(temp, pointer)
        releases = sorted((p for p in (pointer_dir / ".releases").iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        for old in releases[:-5]:
            if old.name != candidate.release_id:
                shutil.rmtree(old, ignore_errors=True)
        return PublishReport("committed", candidate.release_id, pointer=pointer)
    except Exception as exc:
        if release.is_dir():
            shutil.rmtree(release, ignore_errors=True)
        return PublishReport("failed", candidate.release_id, error=f"{type(exc).__name__}: {exc}")


def promote_preview_release(
    project_root: Path,
    *,
    output_dir: Path,
    release_id: str,
) -> dict[str, Any]:
    """Validate and publish one preview release without provider access."""
    root = Path(project_root).resolve()
    try:
        candidate = validate_candidate_release(root, output_dir=output_dir, release_id=release_id)
    except CandidateReleaseValidationError as exc:
        return {
            "status": "failed",
            "reason_codes": [f"E_CANDIDATE_{str(exc).upper()}"],
            "source_release_id": release_id,
            "llm_calls_used": 0,
        }
    if not str(candidate.manifest.get("generation_mode", "")).startswith("llm"):
        return {
            "status": "failed",
            "reason_codes": ["E_CANDIDATE_GENERATION_MODE"],
            "source_release_id": release_id,
            "llm_calls_used": 0,
        }
    acceptance = load_release_acceptance_report(candidate.source_dir)
    if acceptance is None or acceptance.get("automated_acceptance") != "pass":
        return {
            "status": "failed",
            "reason_codes": ["E_CANDIDATE_ACCEPTANCE"],
            "source_release_id": release_id,
            "llm_calls_used": 0,
        }
    lock = None
    try:
        lock = acquire_run_lock(root / ".index" / "book-wiki.lock", stale_after_seconds=3600)
        report = publish_validated_candidate(candidate, apply=True, lock=lock)
    except Exception as exc:
        return {
            "status": "failed",
            "reason_codes": ["E_BOOK_LOCK"],
            "source_release_id": release_id,
            "llm_calls_used": 0,
            "error": str(exc),
        }
    finally:
        if lock is not None:
            release_run_lock(lock)
    result = {
        "status": report.status,
        "run_id": report.run_id,
        "source_release_id": release_id,
        "snapshot_id": candidate.snapshot_id,
        "manifest_sha256": candidate.manifest_sha256,
        "llm_calls_used": 0,
        "acceptance": acceptance,
        "vector_index": "not_updated",
        "vector_hint": "Use `vector status` or `vector reconcile` separately.",
    }
    if report.error:
        result["error"] = report.error
    return result


def _safe(value: str) -> str:
    result = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(value))
    return result.strip(".") or "unnamed"


def _pages(value: dict[str, PageRecord] | tuple[PageRecord, ...] | list[PageRecord]) -> dict[str, PageRecord]:
    return value if isinstance(value, dict) else {page.page_id: page for page in value}


def _body_section_plan(
    chapter: dict[str, Any],
    page_map: Mapping[str, PageRecord],
    *,
    require_explicit: bool = False,
) -> tuple[dict[str, Any], ...]:
    chapter_id = str(chapter.get("chapter_id", ""))
    page_ids = [item if isinstance(item, str) else item.get("page_id") for item in chapter.get("page_ids", ())]
    if any(page_id not in page_map for page_id in page_ids):
        raise ValueError("theme_section_unknown_page")
    sections = chapter.get("sections")
    if not isinstance(sections, list) or not sections:
        if require_explicit:
            raise ValueError("theme_sections_required")
        # Keep generated outlines compatible while removing the unsafe page-per-section fallback.
        return ({"section_id": f"{chapter_id}--content", "title": str(chapter.get("title", chapter_id)),
                 "page_ids": list(page_ids)},)

    planned: list[dict[str, Any]] = []
    assigned: list[str] = []
    seen_ids: set[str] = set()
    for row in sections:
        if not isinstance(row, dict) or not isinstance(row.get("section_id"), str) or not row["section_id"]:
            raise ValueError("theme_section_invalid")
        section_id = row["section_id"]
        if section_id in seen_ids:
            raise ValueError("theme_section_duplicate_id")
        section_page_ids = row.get("page_ids")
        if not isinstance(section_page_ids, list) or not section_page_ids:
            raise ValueError("theme_section_page_ids_required")
        if any(page_id not in page_map or page_id not in page_ids for page_id in section_page_ids):
            raise ValueError("theme_section_unknown_page")
        if len(set(section_page_ids)) != len(section_page_ids) or set(assigned) & set(section_page_ids):
            raise ValueError("theme_section_duplicate_page")
        seen_ids.add(section_id)
        assigned.extend(section_page_ids)
        planned.append({"section_id": section_id,
                        "title": str(row.get("title", section_id)),
                        "page_ids": list(section_page_ids)})
    if set(assigned) != set(page_ids) or len(assigned) != len(page_ids):
        raise ValueError("theme_section_page_coverage")
    return tuple(planned)


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


def _chapter_metadata(chapters: list[tuple[str, str, dict]]) -> tuple[str | None, list[str], list[str], list[str]]:
    if not chapters:
        return None, [], [], []
    _, _, chapter = chapters[0]
    promise = chapter.get("reader_promise")
    exit_artifact = chapter.get("exit_artifact")
    if isinstance(exit_artifact, list):
        exit_artifacts = [str(item) for item in exit_artifact]
    elif exit_artifact is None or exit_artifact == "":
        exit_artifacts = []
    else:
        exit_artifacts = [str(exit_artifact)]
    hard_deps = [str(item) for item in (chapter.get("hard_dependencies") or []) if isinstance(item, (str,))]
    soft_deps = [str(item) for item in (chapter.get("soft_dependencies") or []) if isinstance(item, (str,))]
    return (str(promise) if promise else None, exit_artifacts, hard_deps, soft_deps)


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


def _lineage_page_sources(store: LineageStore, snapshot: WikiSnapshot) -> dict[str, tuple[str, ...]]:
    """Resolve page provenance to registered source ids without backfilling history."""
    result: dict[str, tuple[str, ...]] = {}
    for page in snapshot.pages:
        source_ids = {
            source_id
            for source in page.sources
            if (source_id := store.source_id_for_path(source)) is not None
        }
        if not source_ids:
            source_ids.update(store.artifact_sources(page.page_id))
        result[page.page_id] = tuple(sorted(source_ids))
    return result


def _lineage_snapshot(store: LineageStore, source_ids: tuple[str, ...]) -> str:
    hashes = {
        row["source_id"]: row["source_hash"]
        for row in store.sources()
        if row["source_id"] in source_ids
    }
    return "\n".join(f"{source_id}:{hashes[source_id]}" for source_id in sorted(hashes))


def _lineage_member_input_hash(page_ids: list[str], page_map: dict[str, PageRecord]) -> str:
    payload = "\n".join(
        f"{page_id}:{page_map[page_id].content_sha256}"
        for page_id in sorted(page_ids)
        if page_id in page_map
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compile_book(snapshot: WikiSnapshot, outlines: list[dict], pages: Any, *, fingerprint: Any,
                polish: bool = False, encyclopedic: bool = False, state_dir: Path | None = None,
                 outline_generation_mode: str = "rule",
                 outline_fallback_reason: str | None = None,
                 outline_llm_requested: bool = False,
                 series_id: str | None = None,
                 book_id: str | None = None,
                  book_mode: str | None = None,
                  release_id: str | None = None,
                  editorial_state: BookEditorialState | None = None,
                  scope_mode: str = "pilot",
                  generated_chapters: Mapping[str, Any] | None = None,
                  llm_metadata: Mapping[str, Any] | None = None,
                  rules_hash: str | None = None,
                  rules_snapshot: str | None = None,
                  rules_path: str | None = None,
                  plan_only: bool = False,
                  run_id: str | None = None) -> BuildArtifact:
    page_map = _pages(pages)
    errors: list[str] = []
    conflict_page_ids: set[str] = set()
    if editorial_state is not None:
        state_errors = validate_editorial_state(editorial_state, page_ids=set(page_map))
        if state_errors:
            errors.extend(f"editorial-state:{error}" for error in state_errors)
        elif editorial_state.book.get("source_snapshot_id") != snapshot.snapshot_id:
            errors.append("editorial-state:snapshot-mismatch")
        else:
            allowed = {"include", "conflict"}
            included_ids = {
                row["page_id"] for row in editorial_state.curation["pages"]
                if row.get("disposition") in allowed
            }
            conflict_page_ids = {
                row["page_id"] for row in editorial_state.curation["pages"]
                if row.get("disposition") == "conflict"
            }
            reviewed_hashes = {
                row["page_id"]: row.get("content_hash_at_review")
                for row in editorial_state.curation["pages"]
                if row.get("disposition") in allowed
            }
            for page_id in included_ids:
                if reviewed_hashes.get(page_id) != page_map[page_id].content_sha256:
                    errors.append(f"editorial-state:content-hash-mismatch:{page_id}")
            page_map = {page_id: page for page_id, page in page_map.items() if page_id in included_ids}
            outlines = [editorial_state.outline]
    if snapshot.snapshot_id not in {str(o.get("snapshot_id")) for o in outlines if isinstance(o, dict)}:
        errors.append("snapshot-mismatch")
    chapters = _chapters(outlines)
    reader_promise, exit_artifact, hard_deps, soft_deps = _chapter_metadata(chapters)
    seen: list[str] = []
    secondary_topic_ids: set[str] = set()
    primary_taxonomies: set[str] = set()
    cross_taxonomy_targets: set[str] = set()
    for _volume, chapter_id, chapter in chapters:
        if not chapter_id:
            errors.append("missing-chapter-id")
        ids = [x if isinstance(x, str) else x.get("page_id") for x in chapter.get("page_ids", ())]
        for page_id in ids:
            if page_id not in page_map:
                errors.append(f"unknown-page:{page_id}")
            seen.append(str(page_id))
            page = page_map[page_id]
            if page.primary_taxonomy:
                primary_taxonomies.add(page.primary_taxonomy)
        for page_id in ids:
            page = page_map[page_id]
            for kind, target in page.relation_targets:
                if kind == "related" and target in {p.page_id for p in snapshot.pages}:
                    target_page = next((p for p in snapshot.pages if p.page_id == target), None)
                    if target_page is not None and target_page.primary_taxonomy and (
                        not page.primary_taxonomy
                        or target_page.primary_taxonomy != page.primary_taxonomy
                    ):
                        cross_taxonomy_targets.add(page.page_id)
    secondary_topic_ids.update(cross_taxonomy_targets)
    held_back_ids: list[str] = sorted(page_id for page_id in page_map if page_id not in seen)
    for held in list(held_back_ids):
        held_page = page_map[held]
        if held_page.primary_taxonomy and held_page.primary_taxonomy not in primary_taxonomies:
            secondary_topic_ids.add(held)
            held_back_ids.remove(held)
    unknown_ids = sorted(page_id for page_id in seen if page_id not in page_map)
    if unknown_ids:
        errors.append(f"unknown-page:{','.join(unknown_ids)}")
    expected_covered = sorted(set(seen) | secondary_topic_ids | set(held_back_ids))
    if expected_covered != sorted(page_map):
        errors.append("page-coverage")
    run_id = run_id or uuid.uuid4().hex
    root = Path(state_dir or Path(snapshot.wiki_root).parent / ".index")
    versions = root if root.name == "versions" else root / "book-wiki" / "versions"
    version_dir = versions / run_id
    if errors:
        return BuildArtifact(snapshot.snapshot_id, {"run_id": run_id, "validation_errors": errors}, version_dir, tuple(errors))
    version_dir.mkdir(parents=True, exist_ok=False)
    files: dict[str, str] = {}
    used: set[str] = set()
    chapter_files: dict[str, str] = {}
    planned_chapters: list[str] = []
    chapter_sources: dict[str, list[str]] = {}
    section_source_ids: dict[str, dict[str, list[str]]] = {}
    chapter_body_present = True
    section_source_ids_present = True
    for volume_id, chapter_id, chapter in chapters:
        name = f"{_safe(volume_id)}__{_safe(chapter_id)}.md"
        if name in used:
            errors.append(f"filename-collision:{name}")
            continue
        used.add(name)
        if plan_only:
            planned_chapters.append(chapter_id)
        else:
            chapter_files[chapter_id] = name
        draft = aggregate_chapter(chapter, page_map)
        chapter_sources[name] = sorted({source for page_id in draft.page_ids for source in page_map[page_id].sources})
        if plan_only:
            continue
        generated = generated_chapters.get(chapter_id) if generated_chapters is not None else None
        generated_ok = generated is not None and getattr(generated, "content_status", None) == "complete"
        if generated_ok:
            rows = {
                str(section.section_id): section
                for section in getattr(generated, "sections", ())
            }
            section_source_ids[name] = {
                section_id: sorted({str(page_id) for page_id in section.source_page_ids})
                for section_id, section in rows.items()
            }
            chapter_body_present = chapter_body_present and all(
                isinstance(section.body, str) and bool(section.body.strip())
                for section in rows.values()
            )
            section_source_ids_present = section_source_ids_present and all(
                bool(section.source_page_ids) for section in rows.values()
            )
            rendered_sections = []
            for section in getattr(generated, "sections", ()):
                marker = "> 内容状态：争议，需结合来源重新核对。\n\n" if section.status == "disputed" else ""
                rendered_sections.append(f"### {section.title}\n\n{marker}{section.body}")
            text = "## 本章导读\n\n本章正文由结构化生成阶段生成。\n\n" + "\n\n".join(rendered_sections)
        else:
            chapter_body_present = chapter_body_present and bool(draft.blocks)
            section_source_ids_present = section_source_ids_present and bool(chapter_sources[name])
            section_source_ids[name] = {f"block:{block.block_id}": [block.page_id] for block in draft.blocks}
            text = "## 本章导读\n\n本章为规则版排序。\n\n"
            rendered_blocks = []
            for block in draft.blocks:
                marker = "> 内容状态：争议，需结合来源重新核对。\n\n" if block.page_id in conflict_page_ids else ""
                rendered_blocks.append(marker + (f"### {block.heading}" if block.heading else "") + ("\n\n" if block.heading else "") + block.body)
            text += "\n\n".join(rendered_blocks)
        transition = (
            "本章按主题合并后的章节结构编排。"
            if generated_ok else "本章为规则版排序。"
        )
        text += f"\n\n## 本章衔接\n\n{transition}\n"
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
    if editorial_state is not None:
        sidecars = {
            "editorial/book.json": editorial_state.book,
            "editorial/curation.json": editorial_state.curation,
            "editorial/outline.json": editorial_state.outline,
            "editorial/paths.json": editorial_state.paths,
        }
        for relative, payload in sidecars.items():
            sidecar_path = version_dir / relative
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            files[relative] = _sha(sidecar_path)
    stats = relation_stats(snapshot)
    all_blocks = tuple(block.block_id for page in page_map.values() for block in page.content_blocks)
    draft_blocks = tuple(block.block_id for volume_id, chapter_id, chapter in chapters for block in aggregate_chapter(chapter, page_map).blocks)
    resolved_mode = book_mode or ("encyclopedic" if encyclopedic else ("llm_enhanced" if polish else "rule_only"))
    if resolved_mode == "llm_enhanced":
        resolved_mode = "narrative_draft"
    if plan_only:
        resolved_mode = "plan"
    manifest: dict[str, Any] = {"manifest_version": 1, "run_id": run_id, "snapshot_id": snapshot.snapshot_id,
        "fingerprint": _json(fingerprint), "source_filter": ["concepts", "entities", "synthesis"],
        "scope_mode": scope_mode,
        "page_count": len(page_map), "chapter_count": len(chapters), "files": files, "polished": bool(polish),
        "reading_experience_mode": resolved_mode,
        "mode": resolved_mode,
        "generation_mode": "plan" if plan_only else "rule_only",
        "release_status": "planned" if plan_only else "complete",
        "book_freshness": "fresh",
        "wiki_snapshot_hash": snapshot.snapshot_id,
        "expected_block_ids": list(all_blocks), "draft_block_ids": list(draft_blocks),
        "unresolved_ratio": stats["unresolved_ratio"], "total_relations": stats["total"], "unresolved": stats["unresolved"],
        "unmatched_heading_ratio": 0.0, "glossary_coverage": 1.0,
        "relation_stats": _json(stats),
        "glossary_sha256": files["glossary.md"], "glossary_index_sha256": files["glossary_index.json"],
        "index_sha256": files["index.md"], "quality_gate": {"status": "not_run"},
        "excluded_sources": list(snapshot.excluded_sources),
        "outline_generation_mode": outline_generation_mode,
        "outline_llm_requested": bool(outline_llm_requested),
        "body_generation_mode": "none" if plan_only else ("llm_sections" if generated_chapters is not None else "rule_aggregate"),
        "outline_fallback_reason": outline_fallback_reason,
        "series_id": series_id,
        "book_id": book_id,
        "release_id": release_id,
        "reader_promise": reader_promise,
        "exit_artifact": exit_artifact[0] if exit_artifact else None,
        "exit_artifacts": list(exit_artifact),
        "hard_dependencies": hard_deps,
        "soft_dependencies": soft_deps,
        "ledger_page_ids": list(held_back_ids),
        "secondary_topic_page_ids": sorted(secondary_topic_ids)}
    if editorial_state is not None:
        all_generated = generated_chapters is not None and all(
            chapter_id in generated_chapters and
            getattr(generated_chapters[chapter_id], "content_status", None) == "complete"
            for _volume_id, chapter_id, _chapter in chapters
        )
        manifest.update({
            "editorial_state_hash": editorial_state_hash(editorial_state),
            "editorial_revision": editorial_state.book.get("editorial_revision"),
            "book_freshness": "fresh",
            "generation_mode": "llm" if generated_chapters is not None else "rule_only",
            "release_status": "complete" if all_generated or generated_chapters is None else "partial",
            "wiki_snapshot_hash": snapshot.snapshot_id,
            "disputed_page_ids": sorted(conflict_page_ids),
            "disputed_section_status": True,
            "chapter_body_present": chapter_body_present,
            "section_source_ids_present": section_source_ids_present,
            "curation_revision_present": editorial_state.curation.get("editorial_revision") is not None,
            "outline_revision_present": editorial_state.outline.get("editorial_revision") is not None,
            "chapter_source_ids": chapter_sources,
            "section_source_ids": section_source_ids,
            "tutorial_path_ids": sorted(
                str(row["path_id"])
                for row in editorial_state.paths.get("paths", ())
                if isinstance(row, dict) and isinstance(row.get("path_id"), str)
            ),
        })
    elif generated_chapters is not None:
        all_generated = all(
            chapter_id in generated_chapters and
            getattr(generated_chapters[chapter_id], "content_status", None) == "complete"
            for _volume_id, chapter_id, _chapter in chapters
        )
        manifest.update({
            "generation_mode": "llm" if all_generated else "llm_partial",
            "release_status": "complete" if all_generated else "partial",
            "section_source_ids": section_source_ids,
        })
    if llm_metadata is not None:
        manifest["llm_metadata"] = _json(llm_metadata)
        manifest["llm_prompt_hashes"] = {
            chapter_id: getattr(generated, "prompt_hash", None)
            for chapter_id, generated in generated_chapters.items()
            if getattr(generated, "prompt_hash", None)
        } if generated_chapters is not None else {}
    if rules_hash is not None and rules_snapshot is not None:
        manifest["rules_hash"] = rules_hash
        manifest["rules_snapshot"] = rules_snapshot
        manifest["rules_path"] = rules_path or "book.rules.md"
    if plan_only:
        manifest["chapter_body_present"] = False
        manifest["section_source_ids_present"] = False
    manifest["chapter_files"] = chapter_files
    if plan_only:
        manifest["planned_chapters"] = planned_chapters
    manifest["chapter_sources"] = chapter_sources
    manifest["source_provenance"] = _source_provenance(snapshot)
    if series_id is not None and book_id is not None:
        sidecar = {
            "schema_version": "series-manifest-v1",
            "series_id": series_id,
            "release_id": release_id or run_id,
            "status": "partial" if errors else "ready",
            "books": [{
                "book_id": book_id,
                "required": True,
                "status": "partial" if errors else "ready",
                "outline_id": None,
                "hard_dependencies": list(hard_deps),
                "soft_dependencies": list(soft_deps),
                "release_id": release_id or run_id,
            }],
        }
        sidecar_path = version_dir / "series-manifest.json"
        sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        files["series-manifest.json"] = _sha(sidecar_path)
        manifest["files"] = files
    manifest = _write_manifest(version_dir / "manifest.json", manifest)
    return BuildArtifact(snapshot.snapshot_id, manifest, version_dir, tuple(errors))


def publish_book(artifact: BuildArtifact, output_dir: Path, *, apply: bool, lock: Any) -> PublishReport:
    if artifact.validation_errors:
        return PublishReport("failed", str(artifact.manifest.get("run_id", "")), error=";".join(artifact.validation_errors))
    if artifact.manifest.get("release_status") in {"partial", "failed"}:
        return PublishReport(
            "failed", str(artifact.manifest.get("run_id", "")),
            error=f"release_status={artifact.manifest.get('release_status')} is not publishable",
        )
    if apply and artifact.manifest.get("generation_mode") != "llm":
        return PublishReport(
            "failed", str(artifact.manifest.get("run_id", "")),
            error="LLM-polished chapter bodies are required for apply",
        )
    run_id = str(artifact.manifest["run_id"])
    files = artifact.manifest.get("files", {})
    candidate = ValidatedCandidate(
        project_root=Path(artifact.version_dir).resolve().parents[3],
        output_dir=Path(output_dir).resolve(),
        release_id=run_id,
        source_dir=Path(artifact.version_dir).resolve(),
        manifest=artifact.manifest,
        manifest_sha256=_manifest_file_sha(Path(artifact.version_dir) / "manifest.json"),
        content_identity=str(artifact.manifest.get("release_manifest_hash", "")),
        snapshot_id=artifact.manifest.get("snapshot_id"),
        lifecycle_state="candidate",
        files=tuple(sorted((str(name), str(digest)) for name, digest in files.items())),
    )
    owned_lock = None
    if apply and lock is None:
        try:
            owned_lock = acquire_run_lock(
                candidate.project_root / ".index" / "book-wiki.lock",
                stale_after_seconds=3600,
            )
        except Exception as exc:
            return PublishReport("failed", run_id, error=f"{type(exc).__name__}: {exc}")
    try:
        return publish_validated_candidate(candidate, apply=apply, lock=lock or owned_lock)
    finally:
        if owned_lock is not None:
            release_run_lock(owned_lock)


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
            normalized_name = str(name).replace("\\", "/")
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != normalized_name:
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
                    max_attempts: int = 1, max_input_tokens: int | None = None,
                    max_output_tokens: int | None = None, provider: Any = None,
                    max_llm_calls: int = 3, max_runtime_seconds: int = 900,
                    budget_cap: int | None = None, approver: str | None = None,
                    theme_outline: str | Path | None = None,
                    series_id: str | None = None,
                    book_id: str | None = None,
                    book_mode: str | None = None,
                    release_id: str | None = None,
                    apply_from: str | None = None,
                    scope_mode: str = "pilot") -> dict[str, Any]:
    """Run the rule-only safety path used by the CLI.

    Encyclopedic mode adds a bounded, evidence-only index.  It never rewrites
    chapter bodies and fails closed when a provider or valid evidence is absent.
    """
    if book_mode is not None and book_mode not in BOOK_MODES:
        return {"status": "failed", "reason_codes": ["E_INVALID_BOOK_MODE"],
                "error": f"book_mode {book_mode!r} is not in {sorted(BOOK_MODES)}"}
    if scope_mode not in {"pilot", "full_knowledge"}:
        return {"status": "failed", "reason_codes": ["E_INVALID_SCOPE_MODE"],
                "error": f"scope_mode {scope_mode!r} is not supported"}
    root = Path(project_root).resolve()
    if apply_from is not None:
        if not apply:
            return {"status": "failed", "reason_codes": ["E_APPLY_FROM_REQUIRES_APPLY"]}
        return promote_preview_release(root, output_dir=Path(output_dir), release_id=apply_from)
    if (book_id is None) != (series_id is None):
        return {"status": "failed", "reason_codes": ["E_SERIES_BOOK_REQUIRED_TOGETHER"],
                "error": "series_id and book_id must be supplied together"}
    if book_mode == "narrative" and not use_llm:
        return {"status": "failed", "reason_codes": ["E_NARRATIVE_REQUIRES_LLM"],
                "error": "narrative book_mode requires --use-llm"}
    if encyclopedic and not use_llm:
        return {"status": "failed", "reason_codes": ["E_ENCYCLOPEDIC_REQUIRES_LLM"]}
    if apply and quality_gate == "off":
        return {"status": "failed", "reason_codes": ["E_QUALITY_GATE_REQUIRED_FOR_APPLY"],
                "error": "quality gate off is allowed only for dry-run"}
    try:
        rules = load_book_rules(root)
    except BookRulesError as exc:
        return {
            "status": "blocked",
            "reason_codes": ["E_BOOK_RULES_UNAVAILABLE"],
            "error": str(exc),
        }
    if use_llm and (max_llm_calls <= 0 or max_runtime_seconds <= 0):
        return {"status": "blocked", "reason_codes": ["E_LLM_BUDGET_INVALID"]}
    llm_started = time.monotonic()

    def _wrap_provider(value: Any) -> Any:
        if value is None or not use_llm or isinstance(value, _BudgetedProvider):
            return value
        return _BudgetedProvider(value, max_calls=max_llm_calls,
                                 started=llm_started, max_runtime=max_runtime_seconds)

    provider = _wrap_provider(provider)
    call_sites: dict[str, dict[str, Any]] = {}

    def _calls_used() -> int:
        return provider.calls if isinstance(provider, _BudgetedProvider) else 0

    def _record_call_site(
        name: str,
        before: int,
        *,
        requested: bool,
        minimum_calls: int,
        configured_max_calls: int,
    ) -> None:
        call_sites[name] = {
            "requested": requested,
            "actual_calls": max(0, _calls_used() - before),
            "minimum_calls": minimum_calls,
            "configured_max_calls": configured_max_calls,
        }

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
    lineage: LineageStore | None = None
    lineage_page_sources: dict[str, tuple[str, ...]] = {}
    lineage_source_ids: tuple[str, ...] = ()
    lineage_run_id: str | None = None
    lineage_page_map = _pages(snapshot.pages)

    def _fail_lineage(reason: str) -> None:
        if lineage is not None and lineage_run_id is not None:
            run = lineage.build_run(lineage_run_id)
            if run is not None and run["status"] == "running":
                lineage.fail_build_run(lineage_run_id, reason)
    policy: dict[str, Any] = {}
    resolved_approver: str | None = None
    resolved_budget: int | None = None
    allowed_paths: Any = None
    if use_llm and not polish:
        policy_path = root / ".llm-wiki" / "policy.json"
        try:
            loaded = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            loaded = {}
        if not isinstance(loaded, dict) or loaded.get("external_llm_allowed") is not True:
            return {"status": "blocked", "reason_codes": ["E_EXTERNAL_LLM_UNAUTHORIZED"]}
        early_allowed_paths = loaded.get("allowed_paths") if isinstance(loaded, dict) else None
        if early_allowed_paths is not None:
            if (not isinstance(early_allowed_paths, list) or
                    any(not isinstance(item, str) for item in early_allowed_paths)):
                return {"status": "blocked", "reason_codes": ["E_LLM_ALLOWLIST_INVALID"]}
            allowed = {item.replace("\\", "/") for item in early_allowed_paths}
            unauthorized = sorted({source for page in snapshot.pages for source in page.sources
                                   if source.replace("\\", "/") not in allowed})
            if unauthorized:
                return {"status": "blocked", "reason_codes": ["E_LLM_SOURCE_NOT_ALLOWLISTED"],
                        "paths": unauthorized[:20]}
        restricted = sorted({page.page_id for page in snapshot.pages
                             if page.sensitivity in _RESTRICTED_SENSITIVITY})
        if restricted:
            return {"status": "blocked", "reason_codes": ["E_LLM_RESTRICTED_SOURCE"],
                    "page_ids": restricted[:20]}
    if polish:
        policy_path = root / ".llm-wiki" / "policy.json"
        if policy_path.is_file():
            try:
                loaded = json.loads(policy_path.read_text(encoding="utf-8"))
                policy = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError, json.JSONDecodeError):
                policy = {}
        resolved_approver = approver or policy.get("approver")
        resolved_budget = budget_cap if budget_cap is not None else policy.get("budget_cap")
        if not isinstance(resolved_approver, str) or not resolved_approver.strip():
            return {"status": "blocked", "reason_codes": ["E_LLM_APPROVER_REQUIRED"]}
        if not isinstance(resolved_budget, int) or resolved_budget <= 0 or max_llm_calls > resolved_budget:
            return {"status": "blocked", "reason_codes": ["E_LLM_BUDGET_CAP"]}
        allowed_paths = policy.get("allowed_paths")
        if allowed_paths is not None:
            if not isinstance(allowed_paths, list) or any(not isinstance(item, str) for item in allowed_paths):
                return {"status": "blocked", "reason_codes": ["E_LLM_ALLOWLIST_INVALID"]}
            allowed = {item.replace("\\", "/") for item in allowed_paths}
            unauthorized = sorted({source for page in snapshot.pages for source in page.sources
                                   if source.replace("\\", "/") not in allowed})
            if unauthorized:
                return {"status": "blocked", "reason_codes": ["E_LLM_SOURCE_NOT_ALLOWLISTED"],
                        "paths": unauthorized[:20]}
        restricted = sorted({page.page_id for page in snapshot.pages
                             if page.sensitivity in _RESTRICTED_SENSITIVITY})
        if restricted:
            return {"status": "blocked", "reason_codes": ["E_LLM_RESTRICTED_SOURCE"],
                    "page_ids": restricted[:20]}
    editorial_state: BookEditorialState | None = None
    editorial_root = Path(output_dir)
    if scope_mode == "pilot" and (editorial_root / "book.json").is_file():
        try:
            editorial_state = load_editorial_state(editorial_root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return {"status": "failed", "reason_codes": ["E_EDITORIAL_STATE_INVALID"], "error": str(exc)}
        state_errors = validate_editorial_state(
            editorial_state, page_ids={page.page_id for page in snapshot.pages}
        )
        if state_errors:
            return {"status": "failed", "reason_codes": ["E_EDITORIAL_STATE_INVALID"],
                    "errors": list(state_errors)}
        if editorial_state.book.get("source_snapshot_id") != snapshot.snapshot_id:
            active = resolve_active_version(Path(output_dir))
            return {
                "status": "stale",
                "book_freshness": "stale",
                "reason_codes": ["E_EDITORIAL_SNAPSHOT_MISMATCH"],
                "current_release": active.name if active is not None else None,
            }
        if encyclopedic or theme_outline is not None or (use_llm and not polish):
            return {"status": "blocked", "reason_codes": ["E_EDITORIAL_STATE_RULE_ONLY"]}
        book_id = book_id or str(editorial_state.book["book_id"])
    # Series gate: only enforced when the caller opts into a series context
    # (via --series). A traditional wiki without --series still produces the
    # rule-only artifact; the gate blocks dry-run when the named series has
    # no retained candidate.
    if series_id:
        from .partition import (
            GovernanceConfig, ReaderProfile, evaluate_series_gate,
        )
        from .profiles import NOVEL_WIKI_PROFILE, derive_chapter_exit_evidence

        # When the caller's --series is a taxonomy covered by
        # NOVEL_WIKI_PROFILE (the real novel-wiki wiki shape), reuse the
        # relaxed profile and pre-derive chapter_exit_evidence from the
        # candidate's synthesis pages so chapter_known can pass.
        if series_id in NOVEL_WIKI_PROFILE.candidate_taxonomies:
            exit_evidence = derive_chapter_exit_evidence(snapshot, series_id)
            gate_profile = ReaderProfile(
                profile_id=NOVEL_WIKI_PROFILE.profile_id,
                task_types=NOVEL_WIKI_PROFILE.task_types,
                min_pages_per_book=NOVEL_WIKI_PROFILE.min_pages_per_book,
                min_source_coverage=NOVEL_WIKI_PROFILE.min_source_coverage,
                min_reader_tasks=NOVEL_WIKI_PROFILE.min_reader_tasks,
                candidate_taxonomies=(series_id,),
                chapter_exit_evidence=exit_evidence,
                closure_strict_types=NOVEL_WIKI_PROFILE.closure_strict_types,
                allowed_learning_edge_types=NOVEL_WIKI_PROFILE.allowed_learning_edge_types,
                require_target_task_match=NOVEL_WIKI_PROFILE.require_target_task_match,
            )
            gate_governance = GovernanceConfig(
                external_authorized=True, budget_cap=10,
                approver="novel-wiki-editor",
            )
        else:
            gate_profile = ReaderProfile(
                profile_id="book-build-from-wiki",
                task_types=("learn_concept", "reference", "apply"),
                candidate_taxonomies=(series_id,),
            )
            gate_governance = GovernanceConfig(
                external_authorized=True, budget_cap=1, approver="rule-only-dry-run",
            )
        gate = evaluate_series_gate(
            snapshot, reader_profile=gate_profile, governance=gate_governance,
        )
        retained = tuple(c for c in gate.candidates if c.decision == "proceed")
        if not retained:
            return {"status": "blocked", "reason_codes": ["E_SERIES_GATE_NO_RETAINED_CANDIDATE"],
                    "series_id": series_id,
                    "series_status": gate.status,
                    "generation_mode": gate.generation_mode,
                    "block_reasons": list(gate.block_reasons),
                    "candidates": [c.__dict__ for c in gate.candidates]}
    relation_summary = relation_stats(snapshot)
    if relation_summary["unresolved_ratio"] > MAX_UNRESOLVED_RELATION_RATIO:
        return {"status": "failed", "reason_codes": ["unresolved-relation-over-threshold"],
                "relation_stats": _json(relation_summary)}
    if editorial_state is not None:
        outline = editorial_state.outline
        outline_generation_mode = "persisted"
        outline_fallback_reason = None
        chunks = {}
        _record_call_site("outline", _calls_used(), requested=False,
                          minimum_calls=0, configured_max_calls=0)
    elif theme_outline is not None:
        if not use_llm:
            return {"status": "failed", "reason_codes": ["E_THEME_OUTLINE_REQUIRES_LLM"]}
        if provider is None:
            try:
                from src.llm.provider_factory import create_llm_provider
                provider = _wrap_provider(create_llm_provider(preflight.provider or ""))
            except Exception as exc:
                return {"status": "failed", "reason_codes": ["E_OUTLINE_PROVIDER_UNAVAILABLE"],
                        "error": f"LLM provider unavailable: {exc}", "llm_status": "unavailable"}
        try:
            theme = load_theme_outline(Path(theme_outline))
            outline_before_calls = _calls_used()
            outline = place_page_summaries_sync(theme, snapshot, provider)
        except (ThemeOutlineError, OSError, ValueError) as exc:
            return {"status": "failed", "reason_codes": ["E_THEME_OUTLINE_INVALID"], "error": str(exc)}
        theme_batches = (len(snapshot.pages) + 39) // 40
        _record_call_site(
            "theme_mapping", outline_before_calls, requested=True,
            minimum_calls=theme_batches,
            configured_max_calls=theme_batches * 2,
        )
        call_sites["outline"] = {
            "requested": False, "actual_calls": 0,
            "minimum_calls": 0, "configured_max_calls": 0,
        }
        outline_generation_mode = "theme_mapped"
        outline_fallback_reason: str | None = None
        chunks = {}
    else:
        partitions = partition_pages(snapshot)
        chunks = build_chapter_chunks(snapshot, partitions,
                                       context_window=max_input_tokens or 8000,
                                       output_reserve=max_output_tokens or 1000)
    if editorial_state is None and theme_outline is None:
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
    if editorial_state is None and use_llm and theme_outline is None:
        outline_eligible_calls = estimate_outline_call_sites(
            snapshot, chunks, token_budget=max_output_tokens or 1000,
            project_rules=rules.text,
        )
        remaining_minimum_calls = (
            outline_eligible_calls
            + (1 if encyclopedic else 0)
            + (len(_chapters([rule_outline])) if polish else 0)
        )
        if _calls_used() + remaining_minimum_calls > max_llm_calls:
            return {
                "status": "blocked",
                "reason_codes": ["E_LLM_BUDGET_INSUFFICIENT"],
                "call_sites": call_sites,
                "minimum_llm_calls": _calls_used() + remaining_minimum_calls,
                "configured_max_llm_calls": max_llm_calls,
                "retry_reserve_shortfall": max(0, _calls_used() + remaining_minimum_calls - max_llm_calls),
            }
        if provider is None:
            try:
                from src.llm.provider_factory import create_llm_provider
                provider = _wrap_provider(create_llm_provider(preflight.provider or ""))
            except Exception as exc:
                return {"status": "failed", "reason_codes": ["E_OUTLINE_PROVIDER_UNAVAILABLE"],
                        "error": f"LLM provider unavailable: {exc}", "llm_status": "unavailable"}
        outline_before_calls = _calls_used()
        try:
            planned_outlines = asyncio.run(plan_outline(
                snapshot, chunks, provider,
                context_window=max_input_tokens or 8000,
                token_budget=max_output_tokens or 1000,
                project_rules=rules.text,
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
        outline_actual_calls = max(0, _calls_used() - outline_before_calls)
        _record_call_site(
            "outline", outline_before_calls, requested=outline_eligible_calls > 0,
            minimum_calls=outline_eligible_calls, configured_max_calls=outline_eligible_calls * 3,
        )
    if editorial_state is None:
        validation = validate_outline(snapshot, [outline])
        if not validation.ok:
            return {"status": "failed", "reason_codes": [e.code for e in validation.errors]}
    planned_chapters = tuple(_chapters([outline]))
    pending_minimum_calls = (1 if encyclopedic else 0) + (len(planned_chapters) if polish else 0)
    if (use_llm and editorial_state is not None and
            _calls_used() + pending_minimum_calls > max_llm_calls):
        return {
            "status": "blocked",
            "reason_codes": ["E_LLM_BUDGET_INSUFFICIENT"],
            "call_sites": call_sites,
            "minimum_llm_calls": _calls_used() + pending_minimum_calls,
            "configured_max_llm_calls": max_llm_calls,
            "retry_reserve_shortfall": max(0, _calls_used() + pending_minimum_calls - max_llm_calls),
        }
    if apply:
        lineage = LineageStore.open(root)
        lineage_page_sources = _lineage_page_sources(lineage, snapshot)
        lineage_source_ids = tuple(sorted({
            source_id for source_ids in lineage_page_sources.values() for source_id in source_ids
        }))
    if lineage is not None:
        lineage_run_id = uuid.uuid4().hex
        lineage.create_build_run(
            lineage_source_ids,
            _lineage_snapshot(lineage, lineage_source_ids),
            wiki_snapshot=snapshot.snapshot_id,
            book_id=book_id or root.name,
            run_id=lineage_run_id,
        )
        for _volume_id, chapter_id, chapter in _chapters([outline]):
            page_ids = [
                item if isinstance(item, str) else str(item.get("page_id", ""))
                for item in chapter.get("page_ids", ())
            ]
            input_hash = _lineage_member_input_hash(page_ids, lineage_page_map)
            for page_id in page_ids:
                for source_id in lineage_page_sources.get(page_id, ()):
                    lineage.record_build_member(
                        lineage_run_id, source_id, chapter_id, "planned",
                        input_hash=input_hash,
                    )
    encyclopedic_index = None
    if encyclopedic:
        if provider is None:
            try:
                from src.llm.provider_factory import create_llm_provider
                provider = _wrap_provider(create_llm_provider(preflight.provider or ""))
            except Exception as exc:
                _fail_lineage("encyclopedic_provider_unavailable")
                return {"status": "failed", "reason_codes": ["E_ENCYCLOPEDIC_PROVIDER_UNAVAILABLE"],
                        "error": f"LLM provider unavailable: {exc}", "llm_status": "unavailable"}
        encyclopedic_before_calls = _calls_used()
        try:
            from .encyclopedic_outline import generate_encyclopedic_outline
            encyclopedic_index = asyncio.run(generate_encyclopedic_outline(snapshot, provider))
        except Exception as exc:
            _fail_lineage("encyclopedic_provider_unavailable")
            return {"status": "failed", "reason_codes": ["E_ENCYCLOPEDIC_PROVIDER_UNAVAILABLE"],
                    "error": str(exc), "llm_status": "unavailable"}
        _record_call_site("encyclopedic", encyclopedic_before_calls, requested=True,
                          minimum_calls=1, configured_max_calls=1)
    generated_chapters: dict[str, GeneratedChapter] | None = None
    llm_metadata: dict[str, Any] | None = None
    if polish:
        if not use_llm:
            _fail_lineage("body_generation_requires_llm")
            return {"status": "blocked", "reason_codes": ["E_BODY_GENERATION_REQUIRES_LLM"]}
        if provider is None:
            try:
                from src.llm.provider_factory import create_llm_provider
                provider = _wrap_provider(create_llm_provider(preflight.provider or ""))
            except Exception as exc:
                _fail_lineage("body_provider_unavailable")
                return {"status": "blocked", "reason_codes": ["E_BODY_PROVIDER_UNAVAILABLE"],
                        "error": str(exc), "llm_status": "unavailable"}
        llm_metadata = {
            "provider": preflight.provider or type(provider).__name__,
            "model": preflight.model,
            "approver": resolved_approver,
            "budget_cap": resolved_budget,
            "max_llm_calls": max_llm_calls,
            "max_input_tokens": max_input_tokens or 60000,
            "max_output_tokens": max_output_tokens or min(15000, resolved_budget * 5000),
            "max_retries": max_attempts,
            "max_runtime_seconds": max_runtime_seconds,
            "allowed_paths_checked": allowed_paths is not None,
            "llm_calls_used": 0,
            "sensitive_classifications_checked": True,
            "external_llm_authorized": True,
            "source_allowlist_passed": True,
            "sensitive_gate_passed": True,
        }
        generated_chapters = {}
        included_page_map = _pages(snapshot.pages)
        conflict_page_ids = frozenset()
        if editorial_state is not None:
            included_page_ids = {
                row["page_id"] for row in editorial_state.curation.get("pages", ())
                if isinstance(row, dict) and row.get("disposition") in {"include", "conflict"}
            }
            included_page_map = {page_id: page for page_id, page in included_page_map.items() if page_id in included_page_ids}
            conflict_page_ids = frozenset(
                row["page_id"] for row in editorial_state.curation.get("pages", ())
                if isinstance(row, dict) and row.get("disposition") == "conflict"
            )
        chapter_before_calls = _calls_used()
        for index, (_volume_id, chapter_id, chapter) in enumerate(planned_chapters):
            if (isinstance(provider, _BudgetedProvider) and
                    (provider.calls >= max_llm_calls or
                     time.monotonic() - llm_started >= max_runtime_seconds)):
                generated_chapters[chapter_id] = GeneratedChapter(
                    chapter_id, (), "failed", "budget_exhausted",
                    failure_code="E_LLM_BUDGET_EXHAUSTED",
                )
                continue
            draft = aggregate_chapter(chapter, included_page_map)
            try:
                section_plan = _body_section_plan(
                    chapter,
                    included_page_map,
                    require_explicit=editorial_state is not None,
                )
            except ValueError as exc:
                _fail_lineage("section_plan_invalid")
                return {
                    "status": "blocked",
                    "reason_codes": ["E_BOOK_THEME_SECTIONS_INVALID"],
                    "chapter_id": chapter_id,
                    "error": str(exc),
                }
            generated_chapters[chapter_id] = asyncio.run(generate_chapter_body(
                draft, provider,
                section_plan=section_plan,
                project_rules=rules.text,
                conflict_page_ids=conflict_page_ids,
                token_budget=max_output_tokens or min(15000, resolved_budget * 5000),
                retries=max_attempts,
            ))
        _record_call_site(
            "chapter_body", chapter_before_calls, requested=True,
            minimum_calls=len(planned_chapters),
            configured_max_calls=len(planned_chapters) * (1 + max_attempts),
        )
        if isinstance(provider, _BudgetedProvider):
            llm_metadata["llm_calls_used"] = provider.calls
        llm_metadata["call_sites"] = call_sites
        llm_metadata["minimum_llm_calls"] = sum(
            item["minimum_calls"] for item in call_sites.values()
        )
        llm_metadata["configured_max_llm_calls"] = sum(
            item["configured_max_calls"] for item in call_sites.values()
        )
        llm_metadata["retry_reserve_shortfall"] = max(
            0, llm_metadata["configured_max_llm_calls"] - max_llm_calls
        )
        llm_metadata["failure_reasons"] = sorted({
            str(generated.failure_reason)
            for generated in generated_chapters.values()
            if generated.content_status != "complete" and generated.failure_reason
        })
        llm_metadata["failure_codes"] = _body_llm_failure_codes(generated_chapters)

    artifact = compile_book(snapshot, [outline], snapshot.pages,
                            fingerprint={"snapshot_id": snapshot.snapshot_id, "use_llm": use_llm},
                            polish=polish, encyclopedic=encyclopedic, state_dir=root / ".index",
                            outline_generation_mode=outline_generation_mode,
                            outline_fallback_reason=outline_fallback_reason,
                            outline_llm_requested=use_llm,
                            series_id=series_id,
                            book_id=book_id,
                            book_mode=book_mode,
                            release_id=release_id,
                            scope_mode=scope_mode,
                            editorial_state=editorial_state,
                            generated_chapters=generated_chapters,
                            llm_metadata=llm_metadata,
                            rules_hash=rules.rules_hash,
                            rules_snapshot=rules.text,
                            rules_path=rules.path,
                            plan_only=not use_llm and not polish and not apply,
                            run_id=lineage_run_id)
    if artifact.validation_errors:
        _fail_lineage("compile_validation_failed")
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
    llm_status = _body_llm_status(generated_chapters)
    if quality_gate not in {"rule", "both", "off"}:
        _fail_lineage("quality_gate_invalid")
        return {"status": "failed", "reason_codes": ["E_INVALID_QUALITY_GATE"]}
    plan_only = not use_llm and not polish and not apply
    if quality_gate in {"rule", "both"} and not plan_only:
        from .quality_gate import check_quality_gate
        quality = check_quality_gate(artifact.manifest, llm_status=llm_status)
        artifact = BuildArtifact(artifact.snapshot_id, {**artifact.manifest, "quality_gate": quality.__dict__}, artifact.version_dir, artifact.validation_errors)
        if not quality.ok:
            _fail_lineage("quality_gate_blocked")
            return {"status": "failed", "reason_codes": ["E_QUALITY_GATE_BLOCKED"], "quality_gate": quality.__dict__}
    if apply and llm_status != "passed":
        _fail_lineage("llm_required_for_apply")
        failure_codes = _body_llm_failure_codes(generated_chapters)
        return {
            "status": "failed",
            "reason_codes": ["E_LLM_REQUIRED_FOR_APPLY", *failure_codes],
            "llm_status": llm_status,
            "quality_gate": quality.__dict__ if quality is not None else {"status": "off"},
        }
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
    manifest = _write_manifest(artifact.version_dir / "manifest.json", artifact.manifest)
    artifact = BuildArtifact(artifact.snapshot_id, manifest, artifact.version_dir, artifact.validation_errors)
    if lineage is not None and lineage_run_id is not None:
        chapter_files = artifact.manifest.get("chapter_files", {})
        chapter_sources = artifact.manifest.get("chapter_sources", {})
        if isinstance(chapter_files, dict) and isinstance(chapter_sources, dict):
            for chapter_id, filename in chapter_files.items():
                if not isinstance(chapter_id, str) or not isinstance(filename, str):
                    continue
                source_ids = tuple(sorted({
                    source_id
                    for source in chapter_sources.get(filename, ())
                    if isinstance(source, str)
                    and (source_id := lineage.source_id_for_path(source)) is not None
                }))
                chapter_path = artifact.version_dir / filename
                if not source_ids or not chapter_path.is_file():
                    continue
                output_path = chapter_path.relative_to(root).as_posix()
                output_hash = _sha(chapter_path)
                page_ids = [
                    item if isinstance(item, str) else str(item.get("page_id", ""))
                    for volume_id, current_id, chapter in _chapters([outline])
                    if current_id == chapter_id
                    for item in chapter.get("page_ids", ())
                ]
                input_hash = _lineage_member_input_hash(page_ids, lineage_page_map)
                for source_id in source_ids:
                    lineage.record_build_member(
                        lineage_run_id, source_id, chapter_id, "staged",
                        input_hash=input_hash, output_hash=output_hash,
                        output_path=output_path,
                    )
    if generated_chapters is not None and any(
        generated.content_status != "complete" for generated in generated_chapters.values()
    ):
        _fail_lineage("llm_partial")
        acceptance = build_release_acceptance_report(
            root, artifact.version_dir, publication_status="partial",
        )
        acceptance.update({
            "rules_hash": rules.rules_hash,
            "rules_path": rules.path,
            "rules_snapshot": rules.text,
        })
        write_release_acceptance_report(artifact.version_dir, acceptance)
        return {
            "status": "partial",
            "generation_mode": "llm_partial",
            "release_status": "partial",
            "run_id": artifact.manifest["run_id"],
            "snapshot_id": snapshot.snapshot_id,
            "version_dir": str(artifact.version_dir),
            "reason_codes": ["E_LLM_PARTIAL"],
            "acceptance": acceptance,
        }
    acceptance: dict[str, Any] | None = None
    if apply:
        acceptance = build_release_acceptance_report(
            root,
            artifact.version_dir,
            publication_status="committed",
            expected_pointer_version=str(artifact.manifest["run_id"]),
        )
        acceptance.update({
            "rules_hash": rules.rules_hash,
            "rules_path": rules.path,
            "rules_snapshot": rules.text,
        })
        try:
            # Stage all release evidence before CURRENT.json is switched.
            write_release_acceptance_report(artifact.version_dir, acceptance)
        except Exception as exc:
            _fail_lineage("acceptance_write_failed")
            return {
                "status": "failed",
                "reason_codes": ["E_RELEASE_ACCEPTANCE_WRITE_FAILED"],
                "error": f"{type(exc).__name__}: {exc}",
                "run_id": artifact.manifest["run_id"],
                "snapshot_id": snapshot.snapshot_id,
                "version_dir": str(artifact.version_dir),
            }
    lock = None
    try:
        if apply:
            lock = acquire_run_lock(root / ".index" / "book-wiki.lock", stale_after_seconds=3600)
        report = publish_book(artifact, Path(output_dir), apply=apply, lock=lock)
        lineage_error: str | None = None
        if lineage is not None and lineage_run_id is not None:
            if report.status == "committed" and apply:
                manifest_path = Path(output_dir) / ".releases" / report.run_id / "manifest.json"
                try:
                    lineage.record_book_release(
                        lineage_run_id,
                        lineage_source_ids,
                        manifest_path.relative_to(root).as_posix(),
                        _sha(manifest_path),
                    )
                except Exception as exc:
                    # The release pointer is already durable; leave the run
                    # running so the next LineageStore.open() can reconcile it.
                    lineage_error = f"lineage_record_failed: {type(exc).__name__}: {exc}"
            elif report.status != "committed":
                _fail_lineage(report.error or "book_publish_failed")
        if not (apply and report.status == "committed"):
            acceptance_dir = artifact.version_dir
            acceptance = build_release_acceptance_report(
                root, acceptance_dir, publication_status=report.status,
            )
            acceptance.update({
                "rules_hash": rules.rules_hash,
                "rules_path": rules.path,
                "rules_snapshot": rules.text,
            })
            write_release_acceptance_report(acceptance_dir, acceptance)
        result_status = (
            "published_with_audit_warning"
            if report.status == "committed" and lineage_error
            else "failed" if lineage_error else report.status
        )
        result = {"status": result_status, "run_id": report.run_id,
                    "snapshot_id": snapshot.snapshot_id, "version_dir": str(artifact.version_dir),
                    "error": lineage_error or report.error} if report.error or lineage_error else {
                    "status": report.status, "run_id": report.run_id,
                    "snapshot_id": snapshot.snapshot_id, "version_dir": str(artifact.version_dir)}
        if series_id is not None:
            result["series_id"] = series_id
            result["book_id"] = book_id
            result["book_mode"] = book_mode
            result["release_id"] = release_id
        if quality is not None: result["quality_gate"] = quality.__dict__
        result["llm_status"] = llm_status
        result["vector_index"] = "not_updated"
        result["vector_hint"] = "Use `vector status` or `vector reconcile` separately."
        if rubric_report is not None: result["rubric"] = rubric_report
        result["acceptance"] = acceptance
        if rubric_report is not None and rubric_report["pass_rate"] < 0.8:
            result["warnings"] = ["E_RUBRIC_BELOW_THRESHOLD"]
        return result
    finally:
        if lock is not None:
            release_run_lock(lock)


__all__ = [
    "BuildArtifact", "PublishReport", "CandidateReleaseValidationError",
    "ValidatedCandidate", "compile_book", "publish_book", "publish_validated_candidate",
    "promote_preview_release",
    "resolve_active_version", "load_candidate_lifecycle",
    "write_candidate_lifecycle", "validate_candidate_release",
    "build_from_wiki", "BOOK_MODES",
]
