"""run_ingest — the full ingest pipeline orchestrator.

This is the IO-heavy business function that:
1. Resolves the project's WikiPaths (via _resolve_wiki_paths)
2. Resolves the LLM provider (via _get_provider)
3. Drives the Analyzer -> Generator stages
4. Appends a source page (Fix D logic from src/pipeline/pipeline.py:217-259)
5. Creates stub entity pages for missing slugs (Fix E, lines 261-343)
6. Writes pages under AtomicContext
7. Returns the list of generated WikiPage objects

run_ingest is NOT a pure function. It is an async coroutine with
significant IO side effects (LLM calls, wiki page writes, index updates,
log writes). The TDD refactor preserves this — do not change the
function's external signature.

The ``analyze`` and ``generate`` calls go through ``getattr`` on the
``analyzer`` and ``generator`` submodules so the existing
``test_pipeline_event_bus_integration.py`` monkey-patch pattern (which
patches ``pipeline_mod.run_ingest`` itself) continues to work, and so
future dispatchers can swap analyzer/generator implementations without
editing this file.

Note: the body below is a verbatim copy of
``src/pipeline/pipeline.py:180-360`` with two call-site replacements
(analyze -> getattr(_analyzer_module, "analyze"), generate ->
getattr(_generator_module, "generate")). The compat shim that re-exports
``run_ingest`` / ``_resolve_wiki_paths`` / ``_get_provider`` on
``src.pipeline.pipeline`` is added in Task 10.
"""
from __future__ import annotations
import hashlib
import logging
import re
import unicodedata
from pathlib import Path

from ..wiki.core.paths import WikiPaths
from ..utils.path import normalize_source_path
from ..wiki.core.types import PageType, WikiPage
from ..lib.atomic_ctx import AtomicContext
from ..lib.write_hooks import flush_pending_writes
from ..wiki.features.indexer import append_to_index
from ..wiki.features.logger import log_event
from ..wiki.features.tag_namespace import TAG_PREFIXES
from ..wiki.storage.page_writer import write_page
# Resolve analyze/generate via the pipeline package namespace so
# monkey-patches on `src.pipeline.pipeline.analyze` /
# `src.pipeline.pipeline.generate` (set by tests like
# test_e2e/test_ingest_happy_path.py) propagate into run_ingest.
# The package namespace ``src.pipeline`` always contains the compat
# shim's staticmethod-wrapped functions; ``getattr`` looks them up
# at call time, after the test patch has run.
from . import analyzer as _analyzer_module
from . import generator as _generator_module
from ._pipeline_common import clean_source_text, denoise_source_text

# ---------------------------------------------------------------------------
# Stub quality gate (P2 optimization — 2026-07-29).
# ---------------------------------------------------------------------------
# Maximum number of stub entity pages to create in a single ingest.  When
# the LLM references more missing slugs than this threshold, stub creation
# is suppressed to avoid polluting the wiki with placeholder pages for
# platform names, company names, and other non-domain entities.
# Set via env var ``RUFLO_MAX_STUBS_PER_INGEST`` (default 3).
# NOTE: wiring this cap into ``.index/quality_settings.json`` is deferred —
# the only existing loader (quality_cmd._load_settings) is CLI-private and
# has no shared hook for pipeline code; keep env + default until then.
_MAX_STUBS_ENV = "RUFLO_MAX_STUBS_PER_INGEST"


def _get_max_stubs_per_ingest() -> int:
    """Return the current max stubs threshold (re-reads env var at call time)."""
    return int(__import__("os").environ.get(_MAX_STUBS_ENV, "3"))


# Slugs that should never get stub entity pages because they represent
# platform / organisation / tool names rather than domain concepts.
# Extended via env var ``RUFLO_STUB_BLOCKLIST`` (comma-separated).
_DEFAULT_STUB_BLOCKLIST: set[str] = {
    "feishu-yunwendang",                  # 飞书云文档
    "beijing-shengdongfang-guoxin-keji-youxiangongsi",  # 北京圣东方国信科技有限公司
    "feishu",                              # 飞书
    "yunque",                              # 云雀
    "lark",                                # Lark (飞书国际版)
}


def _get_stub_blocklist() -> frozenset[str]:
    """Return the current stub blocklist (re-reads env var at call time)."""
    extra = __import__("os").environ.get("RUFLO_STUB_BLOCKLIST", "")
    if extra:
        return frozenset(
            _DEFAULT_STUB_BLOCKLIST
            | {s.strip() for s in extra.split(",") if s.strip()}
        )
    return frozenset(_DEFAULT_STUB_BLOCKLIST)


# ---------------------------------------------------------------------------
# 0.5.1 — missing-slug classification (stub suppression).
# ---------------------------------------------------------------------------
# A slug whose trailing 8-hex tail equals a real source page's deterministic
# hash ({stem}-{md5(path)[:8]}) is a broken source-page reference — the LLM
# referenced a source by a guessed slug instead of the on-disk one. Such
# slugs must never become stub pages.
_SOURCE_HASH_TAIL_RE = re.compile(r"-([0-9a-f]{8})$")

# Bad-morphology slugs: tag-namespace names (current CJK + legacy English
# that produced the observed pollution), PageType prefixes, `-entity`
# suffix, or raw-path-shaped slugs.
_TAG_NS_PREFIXES = tuple(TAG_PREFIXES) + (
    "genre", "func", "char", "event", "mood", "scene_phase", "status",
)
_TYPE_PREFIXES = ("source", "concept", "synthesis")


def _collect_source_hash_tails(existing_wiki: dict) -> set[str]:
    """Return the set of 8-hex md5 tails of all SOURCE pages on disk.

    Each tail is the ``md5(raw_path)[:8]`` from the deterministic source
    slug. Used as the hard criterion for detecting broken source-page
    references in ``missing``.
    """
    tails: set[str] = set()
    for slug, ptype in existing_wiki.items():
        if ptype == PageType.SOURCE:
            m = _SOURCE_HASH_TAIL_RE.search(slug)
            if m:
                tails.add(m.group(1))
    return tails


def _is_source_slug_variant(slug: str, source_hash_tails: set[str]) -> bool:
    """True if *slug* ends in an 8-hex tail that matches a real SOURCE page's
    deterministic hash — i.e. the LLM referenced a source by a wrong slug."""
    m = _SOURCE_HASH_TAIL_RE.search(slug)
    return bool(m and m.group(1) in source_hash_tails)


def _is_bad_morphology_slug(slug: str) -> bool:
    """True if *slug* looks like a tag name, a raw path, a type-prefixed id,
    or carries an ``-entity`` suffix — i.e. the LLM referenced a non-page."""
    if slug.endswith("-entity"):
        return True
    if any(slug.startswith(p + "-") for p in _TAG_NS_PREFIXES):
        return True
    if any(slug.startswith(p + "-") for p in _TYPE_PREFIXES):
        return True
    if slug.startswith("raw-") or "--" in slug or "-md-" in slug:
        return True
    return False


def _classify_missing_stubs(
    missing: set[str],
    source_hash_tails: set[str],
) -> tuple[set[str], set[str]]:
    """Split *missing* slugs into ``(create, suppressed)``.

    Suppressed slugs never get a stub page (the LLM referenced a non-page:
    a broken source-slug variant, a tag name, a path, a type-prefixed id, or
    an ``-entity`` suffix). Everything else is a genuine referenced entity
    and is returned in ``create`` (still subject to the caller's cap).
    """
    create: set[str] = set()
    suppressed: set[str] = set()
    for slug in missing:
        if _is_source_slug_variant(slug, source_hash_tails) or _is_bad_morphology_slug(slug):
            suppressed.add(slug)
        else:
            create.add(slug)
    return create, suppressed


# ---------------------------------------------------------------------------
# Existing-wiki index helpers (B9 / B11).
# ---------------------------------------------------------------------------
# Correct attribute names per typed wiki dir (matches WikiPaths and
# page_writer._TYPE_TO_DIR). Do NOT build these via f"wiki_{pt.value}s":
# PageType values are singular (source/entity/concept/synthesis), so that
# yields wiki_entitys / wiki_synthesiss which do not exist on WikiPaths and
# raise AttributeError (silently swallowed in Fix E's old loop).
_EXISTING_WIKI_DIRS = [
    (PageType.SOURCE, "wiki_sources"),
    (PageType.ENTITY, "wiki_entities"),
    (PageType.CONCEPT, "wiki_concepts"),
    (PageType.SYNTHESIS, "wiki_synthesis"),
]


def _collect_existing_wiki(paths: WikiPaths) -> dict:
    """Scan the 4 typed wiki directories; return ``{slug: PageType}`` for
    every page currently on disk.

    Reused for both the analyzer/generator ``existing_wiki_index`` prompt
    text (slug reuse — B9) and Fix E's stub de-duplication set (B11).
    """
    index = {}
    for pt, attr in _EXISTING_WIKI_DIRS:
        d = getattr(paths, attr, None)
        if d is None or not d.exists():
            continue
        for f in d.glob("*.md"):
            index[f.stem] = pt
    return index


def _format_wiki_index(index: dict) -> str:
    """Render the index as prompt text for the analyzer/generator.

    Format: ``- <slug> (<type>)`` — slug first, type in parens.
    The old ``- type: slug`` format leaked the type label into LLM-emitted
    wikilink targets (e.g. ``concept-穿越小说角色塑造套路``) because
    weaker models copied the prefix verbatim.
    """
    if not index:
        return "(empty)"
    return "\n".join(
        f"- {slug} ({pt.value})" for slug, pt in sorted(index.items())
    )


# B10: extract every [[wikilink]] target from a page body. A wikilink may
# carry an `|alias` and/or a `#section` suffix; both are stripped so the
# resulting target matches the slugified page id (which the generator also
# slugifies). Kept as a module-level pure helper so it is unit-testable
# against the real code (not a copy).
_WIKILINK_RE = re.compile(r"\[\[(.*?)\]\]")


def _extract_wikilink_targets(body: str) -> list[str]:
    """Return the de-suffixed target of each ``[[wikilink]]`` in *body*."""
    out: list[str] = []
    for _raw in _WIKILINK_RE.findall(body or ""):
        _tgt = _raw.split("|")[0].split("#")[0].strip()
        if _tgt:
            out.append(_tgt)
    return out


def _compute_reverse_relations(paths, pages):
    """Add inverse edges so the relation graph is bidirectional on disk.

    New pages (in ``pages``) are mutated in-place. Pre-existing target
    pages referenced by a new relation (but not created this run) are
    loaded from disk, merged with the new inverse edge, and returned so the
    caller writes them in the same atomic batch. Only pre-existing pages are
    returned; the caller must still append ``pages`` to the index (the
    returned pages are already indexed).

    Uses in-memory computation (not ``RelationSync.sync_page``) because
    sync_page resets a page's own relations to the passed list and would
    clobber an inverse edge that a prior page's sync just wrote.
    """
    from ..wiki.features.relations import Relation, SYMMETRIC_RELATIONS
    from ..wiki.storage.page_writer import read_page, page_path_for

    def _infer_type(slug):
        for t, prop in (
            (PageType.ENTITY, "wiki_entities"),
            (PageType.CONCEPT, "wiki_concepts"),
            (PageType.SOURCE, "wiki_sources"),
            (PageType.SYNTHESIS, "wiki_synthesis"),
        ):
            if (getattr(paths, prop) / f"{slug}.md").exists():
                return t
        return PageType.SOURCE

    by_id = {p.id: p for p in pages}
    extra = {}

    def _target_page(target_id):
        if target_id in by_id:
            return by_id[target_id]
        if target_id in extra:
            return extra[target_id]
        f = page_path_for(paths, _infer_type(target_id), target_id)
        if not f.exists():
            return None
        try:
            pg = read_page(f)
        except Exception:
            logger.warning("Failed to read page %s for relation target", target_id, exc_info=True)
            return None
        extra[target_id] = pg
        return pg

    for page in pages:
        for rel in list(page.relations or []):
            inv = rel.inverse()
            if inv is None or rel.type in SYMMETRIC_RELATIONS:
                continue
            inv.target_id = page.id
            target = _target_page(rel.target_id)
            if target is None:
                continue
            rels = list(target.relations or [])
            if any(r.target_id == inv.target_id and r.type == inv.type for r in rels):
                continue
            rels.append(inv)
            target.relations = rels

    return list(extra.values())


def _normalize_generated_pages(pages: list[WikiPage], paths: WikiPaths) -> list[WikiPage]:
    """Post-process LLM-generated pages: enforce valid enums, canonicalize relation targets."""
    import time
    try:
        from src.wiki.features.slug_aliases import SlugAliasRegistry
        reg = SlugAliasRegistry(str(paths.root))
    except Exception:
        reg = None

    now_ms = int(time.time() * 1000)
    for page in pages:
        if page.grade not in ("A", "B", "C"):
            page.grade = "B"
        if page.processing_depth not in ("concept", "memory", "stub"):
            page.processing_depth = "concept"
        if page.id:
            page.id = page.id.strip()
        if page.title:
            page.title = page.title.strip()
        if not page.created_at:
            page.created_at = now_ms
        if not page.updated_at:
            page.updated_at = now_ms
        if reg is not None:
            for rel in page.relations:
                canonical = reg.get_canonical(rel.target_id)
                if canonical and canonical != rel.target_id:
                    rel.target_id = canonical
    return pages


def _analyze(**kwargs):
    import sys
    return getattr(sys.modules["src.pipeline.pipeline"], "analyze")(**kwargs)


def _generate(**kwargs):
    import sys
    return getattr(sys.modules["src.pipeline.pipeline"], "generate")(**kwargs)


def _build_rejected_source_pages(
    paths: WikiPaths,
    source_path,
    source_text: str,
    result: "SanitizerResult",
    task_id: str,
) -> list[WikiPage]:
    """Build grade=C source page(s) when source quality is too low for LLM.

    Does NOT write to disk — the caller is responsible for committing.
    """
    import time as _time

    _t = _time.localtime()
    _stem = Path(str(source_path)).stem if hasattr(source_path, "stem") else str(source_path)
    _norm = unicodedata.normalize("NFC", _stem)
    _hash = hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:8]
    _slug = f"{_norm}-{_hash}"

    body = (
        f"## 来源\n\n"
        f"- 路径: `{source_path}`\n"
        f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S', _t)}\n"
        f"- 任务 ID: `{task_id}`\n\n"
        f"> ⚠️ **已跳过处理**: 源文本质量过低，未进行 LLM 分析。\n"
        f"> 质量评分: {result.quality_score:.0%}\n"
        f"> 原因: {'; '.join(result.warnings)}\n"
    )

    page = WikiPage(
        id=_slug,
        title=_stem[:120],
        type=PageType.SOURCE,
        sources=[normalize_source_path(str(source_path), paths.root)],
        body=body,
        grade="C",
    )

    return [page]


async def commit_ingest(
    paths: WikiPaths,
    source_path,
    pages: list[WikiPage],
    extra_pages: list[WikiPage] | None = None,
    task_id: str = "test",
    *,
    event: str = "ingest",
    detail: str | None = None,
    log_task_id: str | None = None,
) -> None:
    """Write generated pages to disk atomically.

    This is the "commit" half of the generate/commit split (NDG Phase 1).
    Callers that need a pre-write gate should call :func:`generate_ingest`,
    run their gate checks, then call this function only on pass.

    All writes happen inside a single ``AtomicContext`` so a partial failure
    does not leave the wiki in an inconsistent state.
    """
    _extra = extra_pages or []
    with AtomicContext(flush_callback=flush_pending_writes):
        for page in pages:
            write_page(paths, page)
        for page in _extra:
            write_page(paths, page)
        append_to_index(
            paths,
            [(p.id, p.type, p.title) for p in pages],
        )
        log_event(
            paths,
            event=event,
            task_id=log_task_id or task_id,
            detail=detail or f"generated {len(pages)} pages from {Path(str(source_path)).name}",
        )


async def _write_rejected_source_page(
    paths: WikiPaths,
    source_path,
    source_text: str,
    result: "SanitizerResult",
    task_id: str,
) -> list[WikiPage]:
    """Write a grade=C source page when source quality is too low for LLM.

    .. deprecated::
        Use :func:`_build_rejected_source_pages` + :func:`commit_ingest`
        instead.  Kept for backward compatibility with tests.
    """
    pages = _build_rejected_source_pages(paths, source_path, source_text, result, task_id)
    await commit_ingest(
        paths, source_path, pages, task_id=task_id,
        event="rejected", detail=", ".join(result.warnings),
        log_task_id=pages[0].id,
    )
    return pages


_logger = logging.getLogger(__name__)


# Note: this file used to define _resolve_wiki_paths and _get_provider as
# local helpers. They were moved to src.pipeline.__init__ as the canonical
# location so that the compat-shim mechanism in __init__.py can re-export
# them as class attributes on sys.modules['src.pipeline.pipeline']. Tests
# monkey-patch those attributes; service.py looks them up late through the
# src.pipeline package namespace, which is what propagates the patch.


async def generate_ingest(
    paths: WikiPaths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
) -> tuple[list[WikiPage], list[WikiPage], dict]:
    """Run the full ingest pipeline **without writing to disk**.

    This is the "generate" half of the generate/commit split (NDG Phase 1).
    It runs sanitize → unified/two-step LLM → source page construction →
    stub creation → reverse relations → quality gate — everything except
    the final disk write, which is deferred to :func:`commit_ingest`.

    Returns ``(pages, extra_pages, meta)`` where *meta* carries:
    - ``analysis``: the ``AnalysisResult`` (or ``None`` for unified path)
    - ``source_slug``: deterministic source-page id
    - ``downstream_count``: number of non-source generated pages
    - ``stub_count``: number of stub entity pages created
    - ``stubs_suppressed``: number of missing-ref slugs suppressed
    - ``extra_pages_count``: number of pre-existing pages touched by
      reverse relations (also returned as *extra_pages*)
    """
    # No pre-flight work needed: the 2026-07 cleanup removed the Inbox
    # staging layer. The collector reads ``raw/sources/<file>`` directly
    # and the wiki page's ``sources:`` field references that same
    # project-relative path.
    _ = paths  # keep the parameter for callers

    from .sanitizer import sanitize

    _result = sanitize(source_text)

    if _result.warnings:
        _logger.warning(
            "[generate_ingest] sanitizer: %s score=%.2f source=%s",
            _result.warnings, _result.quality_score, source_path,
        )

    _sanitized_source_text = _result.text

    # Hard-reject: skip LLM entirely for degraded sources (opt-in via
    # RUFLO_SANITIZER_SKIP_LLM=1; off by default).
    if _result.should_skip_llm and __import__("os").environ.get("RUFLO_SANITIZER_SKIP_LLM", "0") == "1":
        _logger.warning("[generate_ingest] skipping LLM for %s", source_path)
        _rejected_pages = _build_rejected_source_pages(
            paths, source_path, source_text, _result, task_id
        )
        return _rejected_pages, [], {
            "analysis": None,
            "source_slug": _rejected_pages[0].id if _rejected_pages else "",
            "source_page_id": _rejected_pages[0].id if _rejected_pages else "",
            "source_grade": "C",
            "downstream_count": 0,
            "stub_count": 0,
            "stubs_suppressed": 0,
            "extra_pages_count": 0,
            "rejected": True,
            "warnings": list(_result.warnings),
        }

    _ = source_text  # keep the parameter — body writes reference source_text directly

    # B9/B11: scan the existing wiki once and reuse it for both the
    # analyzer/generator prompt (slug reuse) and Fix E's stub de-dup.
    _existing_wiki = _collect_existing_wiki(paths)
    _existing_wiki_index = _format_wiki_index(_existing_wiki)

    # B-Fix (Plan v2.5): compute the deterministic source-page slug
    # BEFORE the Generator call so we can hand it to the prompt
    # (LLM should not have to guess the slug when emitting
    # ``[[wikilinks]]`` to source pages). The same value is reused
    # later when we actually write the source page file.
    _raw_stem_for_slug = (
        Path(str(source_path)).stem
        if hasattr(source_path, "stem") else str(source_path)
    )
    _norm_stem_for_slug = unicodedata.normalize("NFC", _raw_stem_for_slug)
    _path_hash_for_slug = hashlib.md5(
        str(source_path).encode("utf-8")
    ).hexdigest()[:8]
    _source_slug_for_map = (
        f"{_norm_stem_for_slug}-{_path_hash_for_slug}"
        if _norm_stem_for_slug else
        task_id if task_id.startswith("kb-") else f"kb-{task_id}"
    )
    _source_slug_map = {str(source_path): _source_slug_for_map}

    # Unified path: single LLM call (Analyzer + Generator merged).
    # Falls back to two-step on failure.
    analysis = None  # type: ignore[assignment]
    pages: list[WikiPage] = []
    try:
        from .generator import unified_generate
        pages = await unified_generate(
            source_text=_sanitized_source_text,
            source_path=str(source_path),
            folder_context=folder_context or "",
            paths=paths,
            existing_wiki_index=_existing_wiki_index,
            provider=provider,
            source_slug_map=_source_slug_map,
        )
        _logger.info(
            "[generate_ingest] unified path produced %d pages for %s",
            len(pages), source_path,
        )
        if not pages:
            raise RuntimeError("unified path returned 0 pages")
    except Exception as _unified_err:
        _logger.warning(
            "[generate_ingest] unified path failed (%s), falling back to two-step",
            _unified_err,
        )
        # Fallback: original two-step Analyze → Generate
        analysis = await _analyze(
            source_text=_sanitized_source_text,
            source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".pdf",
            existing_wiki_index=_existing_wiki_index,
            folder_context=folder_context,
            provider=provider,
            task_id=task_id,
            source_path=str(source_path),
        )
        pages = await _generate(
            paths=paths,
            analysis=analysis,
            existing_wiki_index=_existing_wiki_index,
            provider=provider,
            source_slug_map=_source_slug_map,
            source_text=_sanitized_source_text,
        )

    # Step 2.5 (P1 fix): optional LLM-as-judge quality gate.
    # Default OFF (QualitySettings.enabled=False) — must be explicitly
    # enabled in the per-project settings file. When enabled:
    #   - Decision A1: judge LLM failure → log warning, pass pages through
    #   - Decision B1: re-generate rejected pages up to max_retries
    #   - Decision C:  inline (this hook); async mode TBD via event bus
    # Latency cost when ON: +5-15s per ingest (single judge call;
    # retries multiply by max_retries+1 since the existing judge does
    # re-judge internally — deviation from strict B1 "re-generate"
    # noted in the 9-plan-bugfix plan).
    from ..quality.types import QualitySettings
    from ..quality.judge import QualityJudge
    # QualitySettings() default: enabled=False. To turn on, the
    # operator adds a "quality" section to the project settings file
    # OR sets RUFLO_QUALITY_ENABLED=1 (env override, NOT YET WIRED).
    _quality_settings = QualitySettings()
    if _quality_settings.enabled and pages:
        try:
            judge = QualityJudge(settings=_quality_settings)
            page_dicts = [
                {"id": p.id, "type": p.type.value, "body": p.body}
                for p in pages
            ]
            result = await judge.judge_batch(page_dicts, source_texts={p.id: source_text for p in pages})
            if result.pages_quarantined:
                from ..quality.quarantine import QuarantineStore
                _quarantine = QuarantineStore(paths)
                # Build a dict of page_id → page for the quarantined ones
                pages_by_id = {p.id: p for p in pages}
                for qid in result.pages_quarantined:
                    if qid in pages_by_id:
                        _quarantine.put(pages_by_id[qid], result.pages[qid])
                # Filter out quarantined pages from the write list
                pages = [p for p in pages if p.id not in result.pages_quarantined]
                _logger.info(
                    f"[generate_ingest] quality gate quarantined "
                    f"{len(result.pages_quarantined)} page(s); "
                    f"{len(pages)} passed"
                )
        except Exception as e:
            # Decision A1: judge LLM failure must NOT block ingest.
            # Log + pass pages through (graceful degradation).
            _logger.warning(
                f"[generate_ingest] quality gate unavailable: {e}; "
                f"passing {len(pages)} page(s) through without judgment"
            )

    # Normalize LLM-generated fields before writing to disk.
    pages = _normalize_generated_pages(pages, paths)

    # Fix D: guarantee one source page per ingested task.
    # The LLM may or may not include a ``source`` entry in
    # ``analysis.suggested_pages``; even when it does, the generator's
    # relation-aware rendering tends to drop it (the source page is just
    # an attachment point, not a "concept" worth writing prose about).
    # We unconditionally append a source page so the wiki has a stable
    # attachment point for ``wiki/<page>.md#sources: [Inbox/...]`` and
    # for cascade_delete to find.
    #
    # Phase 4 (Plan 25 v1 follow-up): build the body from the source.md
    # template via the resolver so the section headings stay in sync with
    # the bundled template (## 来源元数据 / ## 摘要 / ## 关键观点 /
    # ## 抽取的概念).
    import time as _time
    from ..wiki.core.types import PageType, WikiPage
    from ..wiki.templates import resolve as resolve_template

    # source page id and title:
    # - id is the source file's Chinese stem (no pinyin) with a short
    #   path-hash suffix to absorb race conditions and ensure uniqueness
    #   even when two raw files have identical stems. NFC normalisation
    #   keeps the hash stable across platforms (macOS HFS+ tends to
    #   produce NFD-decomposed filenames).
    # - title is the stem without the .md suffix.
    # - task_id is still recorded in the source-meta slot for audit
    #   traceability — the wiki filename no longer depends on it.
    raw_stem = (
        Path(str(source_path)).stem
        if hasattr(source_path, "stem") else str(source_path)
    )
    norm_stem = unicodedata.normalize("NFC", raw_stem)
    path_hash = hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:8]
    source_slug = f"{norm_stem}-{path_hash}" if norm_stem else (
        task_id if task_id.startswith("kb-") else f"kb-{task_id}"
    )
    source_title = norm_stem

    # Render via the bundled source.md template. Falls back to the
    # legacy inline body if the template is missing (operator deleted
    # bundled file).
    try:
        from ..wiki.templates import render_body
        source_tpl = resolve_template(PageType.SOURCE, paths.root)
        # Build key_points from the analyzer's extracted key_facts when
        # available; fall back to one bullet per generated downstream
        # page so the section is never blank. (Plan 27: required
        # slots must contain substantive content per the v2.3 schema.)
        #
        # Unified path (analysis=None): extract summary from the
        # already-generated source page if the LLM produced one.
        _has_analysis = analysis is not None
        key_facts = list(analysis.key_facts or []) if _has_analysis else []
        if key_facts:
            key_points_value: list[str] | str = [
                kf if isinstance(kf, str) else str(kf) for kf in key_facts
            ]
        else:
            key_points_value = [
                f"→ [[{p.id}]]" for p in pages if getattr(p, "id", None)
            ] or ["(无可抽取的要点，详见抽取的概念)"]
        extracted_concepts_value: list[str] = [
            f"→ [[{p.id}]]" for p in pages if getattr(p, "id", None)
        ] or ["(本摄取无下游页面)"]

        # Summary: prefer analyzer, then unified-generated source page's summary slot
        _summary_text = ""
        if _has_analysis:
            _summary_text = analysis.summary or ""
        else:
            # Unified path: look for source page with summary slot
            for _p in pages:
                if _p.type == PageType.SOURCE:
                    _summary_text = _p.body or ""
                    break
        source_body = render_body(
            template_body=source_tpl.body_markdown,
            slots={
                "source_meta": (
                    f"- 路径: `{source_path}`\n"
                    f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"- 任务 ID: `{task_id}`\n"
                ),
                "summary": _summary_text.strip() or "(无摘要)",
                "key_points": key_points_value,
                "extracted_concepts": extracted_concepts_value,
                "main_content": denoise_source_text(source_text),
            },
            page_type=PageType.SOURCE,
            template_version=source_tpl.version or "",
        )
    except FileNotFoundError:
        # Fallback: hardcoded legacy body (matches the previous
        # behaviour pre-template integration).
        _summary_fb = ""
        if _has_analysis:
            _summary_fb = (analysis.summary or "").strip() or "(无摘要)"
        else:
            for _p in pages:
                if _p.type == PageType.SOURCE:
                    _summary_fb = _p.body or ""
                    break
        source_body = (
            f"## 来源\n\n"
            f"- 路径: `{source_path}`\n"
            f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- 任务 ID: `{task_id}`\n\n"
            f"## 摘要\n\n"
            f"{_summary_fb}\n\n"
            f"## 抽取的概念\n\n"
            f"本次摄取共生成 **{len(pages)}** 个下游页面"
            f"{('（共 '+ str(len(analysis.suggested_pages)) + ' 个建议页）') if _has_analysis and analysis.suggested_pages else ''}。\n\n"
            f"## 正文内容\n\n"
            f"{denoise_source_text(source_text)}\n"
        )

    # Count non-source downstream pages to detect empty extractions.
    _downstream_count = sum(1 for p in pages if p.type != PageType.SOURCE)
    if _downstream_count == 0:
        _source_grade = "C"
        # Surface the empty extraction in the body so users/LLMs see it.
        _empty_warning = (
            "\n\n> ⚠️ **空摄取**: LLM 未从此文档提取到任何实体/概念/综合页面。"
            "内容可能过于简短、格式化程度低，或与 wiki 主题不相关。"
            "建议人工审核原始文档，或更换 LLM 模型后重新摄取。"
        )
        source_body += _empty_warning
    else:
        _source_grade = "A"

    # Warn when source text was truncated before LLM processing.
    # MAX_SOURCE_CHARS is the generator's truncation threshold; if the
    # original text exceeds it, downstream pages may miss information.
    from .generator import MAX_SOURCE_CHARS as _MAX_SOURCE_CHARS
    if len(source_text) > _MAX_SOURCE_CHARS:
        _size_kb = len(source_text) / 1024
        source_body += (
            f"\n\n> ⚠️ **文档过长**: 原始文档 {_size_kb:.0f} KB, "
            f"仅前 {_MAX_SOURCE_CHARS} 字符送 LLM 处理。"
            "下游页面可能缺失后半部分的关键信息，建议拆分文档后重新摄取。"
        )

    source_page = WikiPage(
        id=source_slug,
        title=source_title,
        type=PageType.SOURCE,
        sources=[normalize_source_path(str(source_path), paths.root)],
        body=source_body,
        grade=_source_grade,
        processing_depth="source",
        is_immutable=False,
        created_at=int(_time.time() * 1000),
        updated_at=int(_time.time() * 1000),
    )

    # Fix A (2026-07-26): dedup before unconditional append.
    # If the LLM already produced a source-type page for this same source
    # (e.g. via a proper-slug summary in addition to the kb-{task_id}
    # fallback), the kb-* version is redundant — both files would carry the
    # same `sources: [<raw>]` field, doubling the wiki's source attachments
    # and breaking cascade_delete cleanup. Keep the LLM's page, drop ours.
    def _norm_source(s: object) -> str:
        """Compare raw paths case-/separator-insensitively.

        Both the deterministic source path and the LLM-generated
        ``sources`` entries are always normalised relative to the
        project root via ``normalize_source_path``, so comparing
        the canonical relative forms is safe.
        """
        return normalize_source_path(str(s), paths.root).strip().lower()

    target_source_norm = _norm_source(source_path)
    llm_already_has_source = any(
        p.type == PageType.SOURCE
        and any(_norm_source(s) == target_source_norm for s in (p.sources or []))
        for p in pages
    )
    if llm_already_has_source:
        _logger.debug(
            f"[generate_ingest] source page already produced by LLM for "
            f"{source_path}; skipping task-id fallback (id={source_slug!r})"
        )
        # Adjust the LLM-generated source page's grade to reflect actual
        # downstream count — the LLM's own grade may be inconsistent.
        for p in pages:
            if p.type == PageType.SOURCE and any(
                _norm_source(s) == target_source_norm for s in (p.sources or [])
            ):
                p.grade = _source_grade
                break
    else:
        pages.append(source_page)

    # Fix E: scan every relation target across all generated pages
    # and create a stub entity page for any slug that has no matching
    # wiki page. Without this, references like ``[[佛本是道]]`` end up
    # as dangling wikilinks — the wiki graph can't be navigated to the
    # referenced page, the search index doesn't include the entity,
    # and Obsidian / downstream tools show broken links.
    #
    # Slug normalisation: slugify() strips leading/trailing hyphens
    # (2026-07-30 fix), so ``[[-家庭烧伤处理-]]`` and a concept page
    # with id ``家庭烧伤处理`` now share the same canonical slug and no
    # longer produce duplicate entity stubs.
    #
    # Strategy:
    #   1. Collect every slug referenced by any ``relations[].target``,
    #      plus the source page slug, plus the analyzer's
    #      ``links_to_existing`` (normalize through slugify so the same
    #      comparison is consistent with how generator named pages).
    #   2. Subtract the slugs that already have a page (either written
    #      this run, or pre-existing on disk).
    #   3. Emit a stub entity page for each remaining slug. Stubs are
    #      marked ``grade=C``, ``processing_depth=stub``, body
    #      explains that the entity was referenced but not described.
    #   4. Future ingests that include this entity in
    #      ``suggested_pages`` will replace the stub (write_page
    #      overwrites by default).
    from ..utils.slugify import slugify as _slugify

    # The LLM may produce slugs with a type prefix (e.g.
    # ``concept-穿越小说角色塑造套路``) because ``_format_wiki_index``
    # renders the existing-wiki list as ``- type: slug``.  Strip those
    # prefixes before stub-matching so we don't create bogus stubs with
    # ids like ``concept-some-real-concept``.
    _KNOWN_TYPE_PREFIXES = tuple(f"{pt.value}-" for pt in PageType)

    def _strip_type_prefix(raw: str) -> str:
        for _pfx in _KNOWN_TYPE_PREFIXES:
            if raw.startswith(_pfx) and len(raw) > len(_pfx):
                return raw[len(_pfx):]
        return raw

    referenced_slugs: set[str] = set()
    for page in pages:
        for rel in (page.relations or []):
            # Relation dataclass field is ``target_id`` (the YAML key is
            # ``target`` after to_dict() — see src/wiki/features/relations.py).
            tgt = getattr(rel, "target_id", None) or getattr(rel, "target", None)
            if tgt:
                referenced_slugs.add(_strip_type_prefix(_slugify(tgt) or tgt))
        for src in (page.sources or []):
            # Skip the source path itself — that's not a wiki slug.
            pass
    if _has_analysis:
        for link in (analysis.links_to_existing or []):
            referenced_slugs.add(_strip_type_prefix(_slugify(link) or link))

    # B10: scan each generated page's body for [[wikilinks]] that are not
    # captured by the structured `relations` list above. `_extract_wikilink_targets`
    # strips any `|alias` / `#section` suffix; slugify then makes the stub id
    # match the page id (which is also slugified). Bodies may reference pages
    # that exist or will be produced this run; Fix E subtracts both sets below.
    for page in pages:
        for _tgt in _extract_wikilink_targets(page.body):
            referenced_slugs.add(_strip_type_prefix(_slugify(_tgt) or _tgt))

    produced_slugs = {p.id for p in pages}
    # Existing wiki pages (across all four type directories) — reuse the
    # index scanned at the top of run_ingest (_existing_wiki). The previous
    # implementation built attribute names via f"wiki_{pt.value}s", which
    # yields wiki_entitys / wiki_synthesiss (PageType values are singular)
    # and raised AttributeError, silently swallowed, so ENTITY/SYNTHESIS
    # slugs were never counted (B11).
    existing_slugs: set[str] = set(_existing_wiki.keys())

    # Build a lookup from slug → {name, context} so stub titles can use
    # the original Chinese name from the analyzer rather than a mechanical
    # slug→title transform (which yields pinyin for CJK terms).
    _analyzer_name_map: dict[str, str] = {}
    _analyzer_context_map: dict[str, str] = {}
    if _has_analysis:
        for e in (analysis.entities or []):
            if e.slug:
                _analyzer_name_map[e.slug] = e.name or ""
                _analyzer_context_map[e.slug] = e.context or ""
        for e in (analysis.concepts or []):
            if e.slug:
                _analyzer_name_map[e.slug] = e.name or e.concept or ""
                _analyzer_context_map[e.slug] = e.context or ""
        for p in (analysis.suggested_pages or []):
            if p.slug:
                _analyzer_name_map[p.slug] = p.title or ""
                _analyzer_context_map[p.slug] = p.reasoning or ""

    missing = referenced_slugs - produced_slugs - existing_slugs

    # P2 quality gate: exclude non-domain slugs (platform names, org names).
    _blocklist = _get_stub_blocklist()
    if _blocklist:
        filtered = missing - _blocklist  # type: ignore[operator]
        if len(filtered) < len(missing):
            _logger.info(
                "[generate_ingest] filtered %d blocklisted slug(s) from stubs: %s",
                len(missing) - len(filtered),
                ", ".join(sorted(missing & _blocklist)),
            )
        missing = filtered

    # 0.5.1: classify missing slugs — only genuine referenced entities may
    # become stubs; broken source-slug variants and bad-morphology slugs are
    # suppressed (logged) instead of polluting the wiki.
    _stubs_suppressed_count = 0
    source_hash_tails = _collect_source_hash_tails(_existing_wiki)
    _stub_create, _stub_suppressed = _classify_missing_stubs(missing, source_hash_tails)
    if _stub_suppressed:
        _stubs_suppressed_count += len(_stub_suppressed)
        _logger.info(
            "[generate_ingest] suppressed %d non-domain stub slug(s): %s",
            len(_stub_suppressed),
            ", ".join(sorted(_stub_suppressed)[:10]),
        )
    missing = _stub_create

    # P2 quality gate: suppress excessive stub creation to avoid noise.
    _max_stubs = _get_max_stubs_per_ingest()
    if len(missing) > _max_stubs:
        _stubs_suppressed_count += len(missing)
        _logger.warning(
            "[generate_ingest] suppressing %d stub(s) (exceeds max %d): %s",
            len(missing), _max_stubs,
            ", ".join(sorted(missing)[:20]),
        )
        missing = set()

    if missing:
        _logger.info(
            f"[generate_ingest] creating {len(missing)} stub entity page(s): "
            f"{sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}"
        )
    for slug in sorted(missing):
        # Best-effort title: prefer the analyzer's original Chinese name
        # (e.g. "总裁文"); fall back to mechanical slug→text transform.
        analyzer_title = _analyzer_name_map.get(slug, "")
        if analyzer_title and any('一' <= c <= '鿿' for c in analyzer_title):
            # Analyzer gave us a real Chinese name — use it verbatim.
            title = analyzer_title
        elif analyzer_title:
            title = analyzer_title
        else:
            slug_text = slug.replace("-", " ")
            title = (
                slug_text.title()
                if all(c.islower() or c.isdigit() or c.isspace() for c in slug_text)
                else slug_text
            )

        # Stub body: include analyzer context when available so the stub
        # is at least somewhat informative.
        analyzer_ctx = _analyzer_context_map.get(slug, "")
        ctx_line = (
            f"\n\n**分析器上下文:** {analyzer_ctx}"
            if analyzer_ctx else ""
        )
        stub_body = (
            f"## 占位条目\n\n"
            f"此页面被其他页面引用（例如 `[[{slug}]]`），但本此摄取中 Generator 未生成"
            f"该实体的独立页面。{ctx_line}\n\n"
            f"来源摄取: `{source_path}` (task `{task_id}`)。\n\n"
            f"下次摄取如果包含此实体的详细内容，系统会自动用真实内容替换本占位页。\n"
        )
        pages.append(WikiPage(
            id=slug,
            title=title,
            type=PageType.ENTITY,
            sources=[normalize_source_path(str(source_path), paths.root)],
            body=stub_body,
            grade="C",               # stub → lower grade than generated pages
            processing_depth="stub",
            is_immutable=False,
            created_at=int(_time.time() * 1000),
            updated_at=int(_time.time() * 1000),
        ))

    # B13: compute reverse (inverse) edges in-memory so the relation graph
    # is bidirectional on disk. New pages are mutated in-place; pre-existing
    # target pages (referenced by a new relation but not themselves created
    # this run) are loaded, merged, and written in the same atomic batch.
    extra_pages = _compute_reverse_relations(paths, pages)

    # Q1-fix: defensive relation dedup on the final page set. Each page
    # must have at most one relation per target_id (highest weight wins).
    # The Generator already deduplicates, but _compute_reverse_relations
    # may add inverse edges that collide with existing relations.
    for page in pages + extra_pages:
        if not page.relations:
            continue
        deduped: list = []
        seen: set = set()
        for rel in sorted(page.relations, key=lambda r: r.weight or 1.0, reverse=True):
            if rel.target_id not in seen:
                seen.add(rel.target_id)
                deduped.append(rel)
        page.relations = deduped

    # Rule-based quality gate — catches ghost pages, empty bodies, intra-batch dupes.
    # Zero LLM cost; stub pages (processing_depth="stub") are exempt from
    # empty-body and duplicate checks.
    # check_pages modifies page objects in-place (grade=C for degraded pages)
    # and returns a filtered list (duplicates removed).
    from .quality_gate import check_pages
    _gate = check_pages(pages + extra_pages)
    for _pid, _reason in _gate.degraded.items():
        _logger.warning("[generate_ingest] quality gate: %s degraded — %s", _pid, _reason)
    _keep_ids = {p.id for p in _gate.pages}
    pages = [p for p in pages if p.id in _keep_ids]
    extra_pages = [p for p in extra_pages if p.id in _keep_ids]

    # NDG Phase 1: generate_ingest does NOT write to disk.
    # The caller (run_ingest or a batch runner with a gate) calls
    # commit_ingest to persist pages.
    _stub_count = sum(1 for p in pages if p.processing_depth == "stub")
    # Resolve the actual source page id — the LLM may have produced a
    # different source-page id than our deterministic source_slug
    # (llm_already_has_source path), and NDG Phase 3 P5 needs the real id.
    _source_page_id = next(
        (p.id for p in pages if p.type == PageType.SOURCE),
        source_slug,
    )
    meta = {
        "analysis": analysis,
        "source_slug": source_slug,
        "source_page_id": _source_page_id,
        "source_grade": _source_grade,
        "downstream_count": _downstream_count,
        "stub_count": _stub_count,
        "stubs_suppressed": _stubs_suppressed_count,
        "extra_pages_count": len(extra_pages),
        "rejected": False,
        "warnings": list(_result.warnings) if _result.warnings else [],
    }
    return pages, extra_pages, meta


async def run_ingest(
    paths: WikiPaths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
) -> list[WikiPage]:
    """Run full 2-step pipeline + write pages + update index + log.

    Thin wrapper around :func:`generate_ingest` + :func:`commit_ingest`.
    External signature and behaviour are unchanged.
    """
    pages, extra_pages, meta = await generate_ingest(
        paths=paths,
        source_path=source_path,
        source_text=source_text,
        provider=provider,
        folder_context=folder_context,
        task_id=task_id,
    )
    if meta.get("rejected"):
        await commit_ingest(
            paths, source_path, pages, task_id=task_id,
            event="rejected", detail=", ".join(meta["warnings"]),
            log_task_id=pages[0].id if pages else None,
        )
    else:
        await commit_ingest(paths, source_path, pages, extra_pages, task_id)
    return pages


async def run_batch_ingest(
    paths: WikiPaths,
    source_paths: list[Path],
    provider,
    folder_context: str = "",
    concurrency: int = 3,
) -> list[list[WikiPage]]:
    """Ingest multiple raw files concurrently.

    Each file is processed independently via ``run_ingest`` (unified path
    by default, with two-step fallback). A semaphore caps concurrency to
    avoid overwhelming the LLM provider.

    Returns a list of page-lists, one per input file (same order).
    """
    import asyncio

    _logger.info(
        "[batch_ingest] processing %d files with concurrency=%d",
        len(source_paths), concurrency,
    )
    sem = asyncio.Semaphore(concurrency)

    async def _ingest_one(idx: int, sp: Path) -> tuple[int, list[WikiPage]]:
        async with sem:
            _logger.info("[batch_ingest] [%d/%d] %s", idx + 1, len(source_paths), sp.name)
            source_text = sp.read_text(encoding="utf-8")
            pages = await run_ingest(
                paths=paths,
                source_path=sp,
                source_text=source_text,
                provider=provider,
                folder_context=folder_context,
            )
            _logger.info("[batch_ingest] [%d/%d] done — %d pages", idx + 1, len(source_paths), len(pages))
            return idx, pages

    tasks = [_ingest_one(i, sp) for i, sp in enumerate(source_paths)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Reconstruct ordered results, logging failures
    ordered: list[list[WikiPage]] = []
    for i in range(len(source_paths)):
        result = results[i]
        if isinstance(result, Exception):
            _logger.error("[batch_ingest] [%d/%d] FAILED: %s", i + 1, len(source_paths), result)
            ordered.append([])
        else:
            idx, pages = result
            ordered.append(pages)
    return ordered
