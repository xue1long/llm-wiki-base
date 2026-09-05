"""Book snapshot materializer — project state → ``BookSnapshot`` (book-build wiring, Task 1).

Why this module exists
----------------------

``rebuild_book`` (B-T3c) consumes a **Book Snapshot**: a ``Book``, its
``Chapter``s, a ``KnowledgeCoreView``, a per-KU → evidence mapping and a
publication version. Before this module, the only way to obtain one was to
hand-write a JSON file and load it via ``scripts/kc_book_rebuild.py``. That is
why "generate book" was never a reachable runtime path even though every
downstream stage (compiler / renderer / rebuild) was implemented and tested.

This module derives the snapshot from a **real project's KC persistence**:

    <project_root>/.index/kc/bundles/<bundle_key>/manifest.json
                                     /objects/<object_id>.json     (type=claim)
                                     /evidence/<evidence_id>.json
    <project_root>/.index/kc/publication_state.json                (current_version)

Derivation decisions (approved 2026-08-31)
------------------------------------------

D-1 **Grouping = one KU per ``provenance.source_path``.**
    The real corpus stores bare claims (``ku_id`` is never populated), so the
    only honest grouping signal available is the source document. One source
    document → one KnowledgeUnit → one Chapter. Fallback chain for a claim
    with no ``source_path``: ``provenance.source_paths[0]`` → the bundle's
    ``manifest.source_path`` → ``<unknown-source>``.

D-2 **No invented semantics.** The corpus carries no KU ``unit_type`` signal,
    so every derived KU uses ``unit_type="principle"`` with
    ``knowledge_mode="observed"`` (the claims do carry raw quotes) and the
    snapshot is flagged ``derived=True`` with a
    ``derived_unit_type:principle`` warning code. Consumers can therefore tell
    "mapped by convention" apart from "authored by the pipeline". The KU
    ``question`` is a source-scoped template — no content is fabricated.

Determinism / idempotency
-------------------------

``id_policy.generate_book_id`` / ``generate_chapter_id`` mint a fresh
``uuid4()`` per call. That is unusable here: ``rebuild_book`` writes
``<chapter_id>.md`` / ``<chapter_id>.json``, so random ids would make every
run litter the output directory with new files instead of rewriting the same
ones. The materializer therefore emits ids of the same shape
(``<prefix>_<hash8>_<slug>``) but with the 8 hex chars derived from a
**content hash** of the anchoring identity:

    ku_id       sha256("source:<source_path>")
    chapter_id  sha256(chapter.stable_key)
    book_id     sha256("<template_id>::<sorted source paths>")

Two runs over an unchanged project produce byte-identical snapshots.

Purity
------

``materialize_book_snapshot`` is a **pure read**: it never writes, creates, or
mutates anything under ``project_root``. Writing is ``rebuild_book(..., apply=True)``'s
job (Task 2 wires it behind a CLI, Task 3 behind an HTTP route).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.kc.contracts.evidence import Evidence
from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.views.book.contract import Book, BookBuildManifest, BookIncrementalPlan, Chapter
from src.kc.views.book.core_view import SimpleKnowledgeCoreView
from src.lineage import LineageStore

# ─── Constants ─────────────────────────────────────────────────────────

#: Project-relative location of the KC persistence root.
KC_ROOT_RELPATH: tuple[str, ...] = (".index", "kc")

DEFAULT_TEMPLATE_ID: str = "default_v1"

#: D-2 — the corpus carries no unit_type signal; this is the convention.
DERIVED_UNIT_TYPE: str = "principle"
#: Claims in this corpus always carry a raw quote, so "observed" is honest.
DERIVED_KNOWLEDGE_MODE: str = "observed"
DERIVED_KU_STATUS: str = "candidate"

UNKNOWN_SOURCE: str = "<unknown-source>"

WARN_KC_ROOT_MISSING: str = "kc_root:missing"
WARN_DERIVED_UNIT_TYPE: str = f"derived_unit_type:{DERIVED_UNIT_TYPE}"


# ─── Snapshot value objects ────────────────────────────────────────────


@dataclass(frozen=True)
class BookSnapshotStats:
    """Counts describing what the materializer read (for CLI/HTTP reporting)."""

    bundle_count: int = 0
    claim_count: int = 0
    evidence_count: int = 0
    knowledge_unit_count: int = 0
    chapter_count: int = 0
    skipped_object_count: int = 0
    source_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class BookSnapshot:
    """A materialized Book view over a project's Knowledge Core.

    Fields:
        book                 The ``Book`` container (deterministic id).
        chapters             Ordered ``Chapter``s (one per source document).
        core_view            ``SimpleKnowledgeCoreView`` — KUs, evidences,
                             claims, per-KU evidence map, publication version.
        ku_evidence_map      The same mapping exposed directly (``ku_id`` →
                             sorted evidence ids) for reporting/diffing.
        publication_version  Read from ``publication_state.json``
                             (``current_version``); ``0`` when absent.
        stats                Read counts for CLI/HTTP reporting.
        warning_codes        Non-fatal signals (missing KC root, derived
                             conventions in effect).
        derived              D-2 flag: ``True`` when the KU layer was derived
                             by convention rather than authored by a pipeline.
    """

    book: Book
    chapters: tuple[Chapter, ...]
    core_view: SimpleKnowledgeCoreView
    ku_evidence_map: dict[str, tuple[str, ...]] = field(default_factory=dict)
    publication_version: int = 0
    stats: BookSnapshotStats = field(default_factory=BookSnapshotStats)
    warning_codes: tuple[str, ...] = ()
    derived: bool = True

    @property
    def is_empty(self) -> bool:
        """``True`` when the project produced no chapters (nothing to build)."""
        return not self.chapters


# ─── Deterministic ids ─────────────────────────────────────────────────


def _stable_slug(text: str, *, max_len: int = 40) -> str:
    """Normalize ``text`` into an id slug.

    Like ``id_policy._normalize_slug`` but **Unicode-aware**: the corpus is
    overwhelmingly Chinese, so collapsing CJK to ``-`` would turn every slug
    into ``untitled`` and make output filenames unreadable. Word characters
    (including CJK) are kept; everything else collapses to a single ``-``.
    """
    normalized = unicodedata.normalize("NFKC", text or "").strip().lower()
    slug = re.sub(r"[^\w-]+", "-", normalized)
    slug = slug.strip("-")
    if not slug:
        return "untitled"
    return slug[:max_len]


def _stable_id(prefix: str, seed: str, slug: str) -> str:
    """Return ``<prefix>_<sha8(seed)>_<slug>`` — deterministic across runs."""
    digest = sha256(seed.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}_{_stable_slug(slug)}"


# ─── Persistence readers (pure) ────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object; return ``None`` on missing/corrupt/non-object files.

    A corrupt sidecar must not abort the whole build — the materializer is a
    best-effort projection over on-disk state.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _kc_root(project_root: Path) -> Path:
    root = Path(project_root)
    for part in KC_ROOT_RELPATH:
        root = root / part
    return root


def _iter_bundle_dirs(kc_root: Path) -> list[Path]:
    bundles_root = kc_root / "bundles"
    if not bundles_root.is_dir():
        return []
    return sorted(
        (d for d in bundles_root.iterdir() if d.is_dir()),
        key=lambda d: d.name,
    )


def _source_path_of(claim: dict[str, Any], manifest_source: str | None) -> str:
    """Resolve the grouping key for a claim (D-1 fallback chain)."""
    provenance = claim.get("provenance")
    if isinstance(provenance, dict):
        direct = provenance.get("source_path")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        candidates = provenance.get("source_paths")
        if isinstance(candidates, list):
            for item in candidates:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    if isinstance(manifest_source, str) and manifest_source.strip():
        return manifest_source.strip()
    return UNKNOWN_SOURCE


def _title_for_source(source_path: str) -> str:
    """Human-readable chapter title: the source file's stem."""
    stem = Path(source_path).stem.strip()
    return stem or source_path or UNKNOWN_SOURCE


def _concept_id_for(source_path: str) -> str:
    """Top-of-pyramid anchor for a derived KU (D-1)."""
    return f"source:{source_path}"


def _evidence_from_dict(payload: dict[str, Any]) -> Evidence:
    supports = payload.get("supports")
    return Evidence(
        evidence_id=str(payload.get("evidence_id", "")),
        document_id=str(payload.get("document_id", "")),
        block_id=str(payload.get("block_id", "")),
        quote=str(payload.get("quote", "")),
        quote_hash=str(payload.get("quote_hash", "")),
        supports=tuple(str(s) for s in supports) if isinstance(supports, list) else (),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        status=str(payload.get("status", "candidate")),
        evidence_type=str(payload.get("evidence_type", "direct_quote")),
        structured_provenance=payload.get("structured_provenance"),
        computation_provenance=payload.get("computation_provenance"),
    )


# ─── Collection ────────────────────────────────────────────────────────


@dataclass
class _CollectedState:
    bundles: int = 0
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    claim_sources: dict[str, str] = field(default_factory=dict)
    evidences: dict[str, Evidence] = field(default_factory=dict)
    #: object_id → evidence ids that support it (inverse of Evidence.supports)
    supported_by: dict[str, set[str]] = field(default_factory=dict)
    skipped_objects: int = 0


def _collect(kc_root: Path) -> _CollectedState:
    """Walk every bundle once, accumulating claims / evidence / support index."""
    state = _CollectedState()

    for bundle_dir in _iter_bundle_dirs(kc_root):
        state.bundles += 1

        manifest = _read_json(bundle_dir / "manifest.json") or {}
        manifest_source = manifest.get("source_path")

        objects_dir = bundle_dir / "objects"
        if objects_dir.is_dir():
            for obj_path in sorted(objects_dir.glob("*.json")):
                payload = _read_json(obj_path)
                if payload is None:
                    state.skipped_objects += 1
                    continue
                # Only claims back KnowledgeUnits in this corpus; entities /
                # structured_facts are not part of the Book view (yet).
                if payload.get("type") != "claim":
                    state.skipped_objects += 1
                    continue
                object_id = str(payload.get("id", obj_path.stem))
                state.claims[object_id] = payload
                state.claim_sources[object_id] = _source_path_of(payload, manifest_source)

        evidence_dir = bundle_dir / "evidence"
        if evidence_dir.is_dir():
            for ev_path in sorted(evidence_dir.glob("*.json")):
                payload = _read_json(ev_path)
                if payload is None:
                    continue
                evidence = _evidence_from_dict(payload)
                if not evidence.evidence_id:
                    continue
                state.evidences[evidence.evidence_id] = evidence
                for object_id in evidence.supports:
                    state.supported_by.setdefault(object_id, set()).add(evidence.evidence_id)

    return state


# ─── KU / Chapter construction ─────────────────────────────────────────


def _build_knowledge_unit(
    source_path: str,
    claim_payloads: list[dict[str, Any]],
) -> KnowledgeUnit:
    """Derive one KU from every claim sharing ``source_path`` (D-1 + D-2)."""
    title = _title_for_source(source_path)
    concept_id = _concept_id_for(source_path)

    claim_ids = sorted(str(c.get("id", "")) for c in claim_payloads)
    confidences = [float(c.get("confidence", 0.0) or 0.0) for c in claim_payloads]
    mean_confidence = round(sum(confidences) / len(confidences), 6) if confidences else 0.0
    created_at = max((int(c.get("created_at") or 0) for c in claim_payloads), default=0)
    updated_at = max((int(c.get("updated_at") or 0) for c in claim_payloads), default=0)

    return KnowledgeUnit(
        ku_id=_stable_id("ku", concept_id, title),
        concept_id=concept_id,
        # Template question — scoped to the source, never to invented content.
        question=f"来源 {source_path} 中提出了哪些知识主张？",
        title=title,
        unit_type=DERIVED_UNIT_TYPE,  # type: ignore[arg-type]
        knowledge_mode=DERIVED_KNOWLEDGE_MODE,  # type: ignore[arg-type]
        claim_ids=tuple(claim_ids),
        structured_fact_ids=(),
        context_id=None,
        validity_id=None,
        confidence=mean_confidence,
        status=DERIVED_KU_STATUS,  # type: ignore[arg-type]
        version=1,
        created_at=created_at,
        updated_at=updated_at,
        resolution_event_id=None,
    )


def _build_chapter(
    ku: KnowledgeUnit,
    *,
    book_id: str,
    order: int,
    publication_version: int,
) -> Chapter:
    """One chapter per KU; ``stable_key`` follows the B-T2 derivation."""
    stable_key = f"{ku.concept_id}::{ku.unit_type}"
    return Chapter(
        id=_stable_id("ch", stable_key, ku.title),
        book_id=book_id,
        stable_key=stable_key,
        title=ku.title,
        order=order,
        knowledge_block_ids=[],
        source_knowledge_unit_ids=[ku.ku_id],
        publication_version=publication_version,
    )


def materialize_book_manifest(project_root: Path | str) -> BookBuildManifest:
    """Freeze the committed lineage closure for a Book build."""
    db_path = Path(project_root) / ".index" / "lineage" / "state.db"
    if not db_path.exists():
        return BookBuildManifest(blocking=("lineage:missing",))
    store = LineageStore.open(Path(project_root))
    sources = store.sources()
    source_ids = tuple(row["source_id"] for row in sources if row["status"] != "deleted")
    artifacts = store.artifacts(artifact_kind="wiki", status="committed")
    wiki_ids = tuple(row["artifact_id"] for row in artifacts)
    blocking = tuple(
        f"source:{row['source_id']}:{row['status']}"
        for row in sources
        if row["status"] in {"blocked", "failed", "stale"}
    )
    return BookBuildManifest(
        source_ids=source_ids,
        wiki_page_ids=wiki_ids,
        blocking=blocking,
        input_snapshot="\n".join(f"{row['source_id']}:{row['source_hash']}" for row in sources),
    )


def materialize_book_plan(project_root: Path | str) -> BookIncrementalPlan:
    current = materialize_book_manifest(project_root)
    active_path = Path(project_root) / "book" / "manifest.json"
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        previous = active.get("lineage", {})
    except (OSError, ValueError):
        previous = {}
    old_sources = set(previous.get("source_ids", ()))
    old_wiki = set(previous.get("wiki_page_ids", ()))
    return BookIncrementalPlan(
        added_source_ids=tuple(sorted(set(current.source_ids) - old_sources)),
        removed_source_ids=tuple(sorted(old_sources - set(current.source_ids))),
        added_wiki_page_ids=tuple(sorted(set(current.wiki_page_ids) - old_wiki)),
        removed_wiki_page_ids=tuple(sorted(old_wiki - set(current.wiki_page_ids))),
    )


# ─── Public entry point ────────────────────────────────────────────────


def materialize_book_snapshot(
    project_root: Path | str,
    *,
    book_title: str | None = None,
    template_id: str = DEFAULT_TEMPLATE_ID,
) -> BookSnapshot:
    """Derive a :class:`BookSnapshot` from a project's KC persistence.

    Pure read — never writes under ``project_root``.

    Args:
        project_root  Project root containing ``.index/kc``.
        book_title    Override the Book title (default:
                      ``"<project name> — Knowledge Book"``).
        template_id   Template reference stored on the ``Book``.

    Returns:
        A deterministic :class:`BookSnapshot`. When the project has no KC
        persistence (or no claims) the snapshot is empty
        (:attr:`BookSnapshot.is_empty` is ``True``) and
        ``warning_codes`` carries ``"kc_root:missing"`` when the root itself is
        absent — callers turn that into a non-zero exit code rather than
        silently publishing an empty book.
    """
    root = Path(project_root)
    kc_root = _kc_root(root)

    if not kc_root.is_dir():
        return BookSnapshot(
            book=_empty_book(root, book_title, template_id),
            chapters=(),
            core_view=SimpleKnowledgeCoreView(publication_version=0),
            ku_evidence_map={},
            publication_version=0,
            stats=BookSnapshotStats(),
            warning_codes=(WARN_KC_ROOT_MISSING,),
            derived=True,
        )

    state = _collect(kc_root)
    publication_version = _read_publication_version(kc_root)
    lineage_by_path: dict[str, tuple[str, tuple[str, ...]]] = {}
    lineage_db = root / ".index" / "lineage" / "state.db"
    if lineage_db.exists():
        lineage = LineageStore.open(root)
        for source in lineage.sources():
            if source["status"] == "deleted":
                continue
            lineage_by_path[source["source_path"]] = (
                source["source_id"],
                lineage.artifacts_for_source(source["source_id"], artifact_kind="wiki"),
            )

    # ── Group claims by source_path (D-1) ──────────────────────────────
    grouped: dict[str, list[dict[str, Any]]] = {}
    for object_id, payload in state.claims.items():
        grouped.setdefault(state.claim_sources[object_id], []).append(payload)

    source_paths = tuple(sorted(grouped))
    title = book_title or f"{root.name or 'project'} — Knowledge Book"
    book = Book(
        id=_stable_id("book", f"{template_id}::" + "\n".join(source_paths), title),
        title=title,
        template_id=template_id,
        outline_version=1,
        publication_version=publication_version,
        chapter_ids=[],
    )

    kus: dict[str, KnowledgeUnit] = {}
    chapters: list[Chapter] = []
    ku_evidence_map: dict[str, tuple[str, ...]] = {}

    for order, source_path in enumerate(source_paths):
        ku = _build_knowledge_unit(source_path, grouped[source_path])
        chapter = _build_chapter(
            ku, book_id=book.id, order=order, publication_version=publication_version
        )
        source_id, wiki_page_ids = lineage_by_path.get(source_path, ("", ()))
        chapter = Chapter(
            **{
                **chapter.__dict__,
                "source_ids": [source_id] if source_id else [],
                "wiki_page_ids": list(wiki_page_ids),
            }
        )
        kus[ku.ku_id] = ku
        chapters.append(chapter)

        # Inverse index: every evidence supporting any claim of this KU.
        evidence_ids: set[str] = set()
        for claim_id in ku.claim_ids:
            evidence_ids |= state.supported_by.get(claim_id, set())
        ku_evidence_map[ku.ku_id] = tuple(sorted(evidence_ids))

    book = Book(
        id=book.id,
        title=book.title,
        template_id=book.template_id,
        outline_version=book.outline_version,
        publication_version=publication_version,
        chapter_ids=[chapter.id for chapter in chapters],
    )

    core_view = SimpleKnowledgeCoreView(
        kus=kus,
        evidences=state.evidences,
        claims=state.claims,
        ku_evidence_map=ku_evidence_map,
        publication_version=publication_version,
    )

    warning_codes: list[str] = []
    if chapters:
        warning_codes.append(WARN_DERIVED_UNIT_TYPE)

    stats = BookSnapshotStats(
        bundle_count=state.bundles,
        claim_count=len(state.claims),
        evidence_count=len(state.evidences),
        knowledge_unit_count=len(kus),
        chapter_count=len(chapters),
        skipped_object_count=state.skipped_objects,
        source_paths=source_paths,
    )

    return BookSnapshot(
        book=book,
        chapters=tuple(chapters),
        core_view=core_view,
        ku_evidence_map=ku_evidence_map,
        publication_version=publication_version,
        stats=stats,
        warning_codes=tuple(warning_codes),
        derived=True,
    )


def _empty_book(root: Path, book_title: str | None, template_id: str) -> Book:
    """Placeholder Book returned when the project has no KC persistence."""
    title = book_title or f"{root.name or 'project'} — Knowledge Book"
    return Book(
        id=_stable_id("book", f"{template_id}::empty", title),
        title=title,
        template_id=template_id,
        outline_version=1,
        publication_version=0,
        chapter_ids=[],
    )


def _read_publication_version(kc_root: Path) -> int:
    """Read ``current_version`` from ``publication_state.json`` (spec §17 D-21).

    Book views MUST consume the PublicationGate's counter rather than invent
    their own; a missing/corrupt state file falls back to ``0`` (nothing
    published yet).
    """
    payload = _read_json(kc_root / "publication_state.json")
    if payload is None:
        return 0
    try:
        return int(payload.get("current_version", 0) or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "BookSnapshot",
    "BookSnapshotStats",
    "DEFAULT_TEMPLATE_ID",
    "DERIVED_KNOWLEDGE_MODE",
    "DERIVED_UNIT_TYPE",
    "KC_ROOT_RELPATH",
    "UNKNOWN_SOURCE",
    "WARN_DERIVED_UNIT_TYPE",
    "WARN_KC_ROOT_MISSING",
    "materialize_book_snapshot",
    "materialize_book_manifest",
    "materialize_book_plan",
]
