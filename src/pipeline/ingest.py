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
import asyncio
import hashlib
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sanitizer import SanitizerResult
import unicodedata
from pathlib import Path

from ..wiki.core.paths import WikiPaths
from ..utils.path import normalize_source_path
from ..utils.slugify import slugify
from ..wiki.core.types import PageType, WikiPage
from ..lib.atomic_ctx import AtomicContext
from ..lib.write_hooks import flush_pending_writes
from ..wiki.features.indexer import append_to_index
from ..wiki.features.logger import log_event
from ..wiki.storage.page_writer import write_page
# Resolve analyze/generate via the pipeline package namespace so
# monkey-patches on `src.pipeline.pipeline.analyze` /
# `src.pipeline.pipeline.generate` (set by tests like
# test_e2e/test_ingest_happy_path.py) propagate into run_ingest.
# The package namespace ``src.pipeline`` always contains the compat
# shim's staticmethod-wrapped functions; ``getattr`` looks them up
# at call time, after the test patch has run.
from ._pipeline_common import clean_source_text
from .prefilter import prefilter as _run_prefilter
from .retry import retry_with_backoff, RetryExhausted, PermanentFailure, CircuitBreakerOpen
from ..utils.timestamp import now_iso


async def _with_llm_timeout(coro, timeout: float, op: str):
    """Wrap a coroutine with an asyncio timeout guard.

    Returns the coroutine's value on success.  Raises ``RuntimeError``
    (with a *timed out* message) when the timeout fires, and propagates
    any inner exception unchanged.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"LLM {op} timed out after {timeout}s")


# ---------------------------------------------------------------------------
# Stub quality gate (P2 optimization — 2026-07-29).
# ---------------------------------------------------------------------------
# Maximum number of stub entity pages to create in a single ingest.  When
# the LLM references more missing slugs than this threshold, stub creation
# is suppressed to avoid polluting the wiki with placeholder pages for
# platform names, company names, and other non-domain entities.
# Set via env var ``RUFLO_MAX_STUBS_PER_INGEST`` (default 10).
_MAX_STUBS_ENV = "RUFLO_MAX_STUBS_PER_INGEST"


def _get_max_stubs_per_ingest() -> int:
    """Return the current max stubs threshold (re-reads env var at call time)."""
    return int(__import__("os").environ.get(_MAX_STUBS_ENV, "3"))


# Slugs that should never get stub entity pages because they represent
# platform / organisation / tool names rather than domain concepts.
# Applied to stub creation, relation filtering, and body wikilink cleanup.
# Extended via env var ``RUFLO_STUB_BLOCKLIST`` (comma-separated).
_DEFAULT_NOISE_BLOCKLIST: frozenset[str] = frozenset({
    "feishu-yunwendang",                  # 飞书云文档
    "beijing-shengdongfang-guoxin-keji-youxiangongsi",  # 北京圣东方国信科技有限公司
    "feishu",                              # 飞书
    "yunque",                              # 云雀
    "lark",                                # Lark (飞书国际版)
})


def _get_noise_blocklist() -> frozenset[str]:
    """Return the current noise blocklist for stub + relation + body filtering."""
    extra = __import__("os").environ.get("RUFLO_STUB_BLOCKLIST", "")
    if extra:
        return frozenset(
            _DEFAULT_NOISE_BLOCKLIST
            | {s.strip() for s in extra.split(",") if s.strip()}
        )
    return _DEFAULT_NOISE_BLOCKLIST


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
    from ..wiki.features.relations import SYMMETRIC_RELATIONS
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
            _logger.warning("Failed to read page %s for relation target", target_id, exc_info=True)
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


# ---------------------------------------------------------------------------
# Missing-stub classification helpers
# ---------------------------------------------------------------------------

def _is_source_slug_variant(slug: str, source_hashes: set) -> bool:
    """Return True when *slug* ends with an 8-hex tail matching a source hash."""
    if not slug or not source_hashes:
        return False
    parts = slug.rsplit("-", 1)
    if len(parts) != 2:
        return False
    tail = parts[1]
    if len(tail) == 8 and all(c in "0123456789abcdef" for c in tail):
        return tail in source_hashes
    return False


_TAG_PREFIXES = ("func-", "题材-", "genre-", "event-")
_TYPE_PREFIXES = ("source-", "concept-", "entity-", "synthesis-")


def _classify_missing_stubs(
    missing: set[str], source_hashes: set[str],
) -> tuple[set[str], set[str]]:
    """Classify missing slugs into (create, suppressed).

    Suppresses slugs that are source-page variants, tag-namespace names,
    type-prefixed ids, *-entity* suffixes, or path-like raw slugs — these
    are non-domain references that should not become stubs.  Clean entity
    references go into *create*.
    """
    create: set[str] = set()
    suppressed: set[str] = set()

    for slug in missing:
        if _is_source_slug_variant(slug, source_hashes):
            suppressed.add(slug)
        elif any(slug.startswith(p) for p in _TAG_PREFIXES):
            suppressed.add(slug)
        elif any(slug.startswith(p) for p in _TYPE_PREFIXES):
            suppressed.add(slug)
        elif slug.endswith("-entity"):
            suppressed.add(slug)
        elif slug.startswith("raw-") or "--" in slug or "-md-" in slug:
            suppressed.add(slug)
        else:
            create.add(slug)

    return create, suppressed


def _normalize_generated_pages(pages: list[WikiPage], paths: WikiPaths) -> list[WikiPage]:
    """Post-process LLM-generated pages: enforce valid enums, canonicalize relation targets."""
    import time
    try:
        from src.wiki.features.slug_aliases import SlugAliasRegistry
        reg = SlugAliasRegistry(str(paths.root))
    except Exception:
        reg = None

    now_ts = now_iso()

    _DEPTH_BY_TYPE = {
        PageType.SOURCE: "source",
        PageType.ENTITY: "entity",
        PageType.CONCEPT: "concept",
        PageType.SYNTHESIS: "synthesis",
    }

    for page in pages:
        if page.grade not in ("A", "B", "C"):
            page.grade = "B"
        _depth = _DEPTH_BY_TYPE.get(page.type)
        if _depth:
            page.processing_depth = _depth
        elif page.processing_depth not in ("concept", "memory", "stub"):
            page.processing_depth = "concept"
        if page.id:
            page.id = page.id.strip()
        if page.title:
            page.title = page.title.strip()
        if not page.created_at:
            page.created_at = now_ts
        if not page.updated_at:
            page.updated_at = now_ts
        if reg is not None:
            for rel in page.relations:
                canonical = reg.get_canonical(rel.target_id)
                if canonical and canonical != rel.target_id:
                    rel.target_id = canonical

    # 过滤平台/组织噪音：relation 拦截 + body wikilink 清理
    _noise = _get_noise_blocklist()
    if _noise:
        for page in pages:
            # 2a. 过滤 relation（target_id 已被 Relation.from_dict slugify，直接字符串比较）
            page.relations = [
                rel for rel in page.relations
                if rel.target_id not in _noise
            ]
            # 2b. 清除 body 中的噪音 wikilink（如 [[beijing-shengdongfang-...]]）
            for _slug in _noise:
                page.body = re.sub(
                    r"\[\[" + re.escape(_slug) + r"(?:\|[^\]]*)?\]\]",
                    "", page.body
                )

    return pages


def _analyze(**kwargs):
    import sys
    return sys.modules["src.pipeline.pipeline"].analyze(**kwargs)


def _generate(**kwargs):
    import sys
    return sys.modules["src.pipeline.pipeline"].generate(**kwargs)


async def _write_rejected_source_page(
    paths: WikiPaths,
    source_path,
    source_text: str,
    result: "SanitizerResult",
    task_id: str,
) -> list[WikiPage]:
    """Write a grade=C source page when source quality is too low for LLM."""
    import time as _time

    _t = _time.localtime()
    _stem = Path(str(source_path)).stem if hasattr(source_path, "stem") else str(source_path)
    _norm = unicodedata.normalize("NFC", _stem)
    _slug_stem = slugify(_norm)
    _hash = hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:8]
    _slug = f"{_slug_stem}-{_hash}"

    # Convert absolute path to project-relative path for sources field
    try:
        _rel_path = Path(str(source_path)).relative_to(paths.root).as_posix()
    except ValueError:
        _rel_path = str(source_path)

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
        sources=[_rel_path],
        body=body,
        grade="C",
    )

    with AtomicContext():
        write_page(paths, page)
        append_to_index(paths, [(page.id, page.type, page.title)])
        log_event(paths, "rejected", page.id, {"reason": result.warnings})

    # Return tuple for compatibility with generate_ingest return signature
    meta = {
        "rejected": True,
        "quality_score": result.quality_score,
        "warnings": result.warnings,
    }
    return [page], [], meta


def _create_source_only_page(
    paths: WikiPaths,
    source_path,
    source_text: str,
    task_id: str,
    reason: str = "",
) -> list[WikiPage]:
    """Create a single degraded source page when LLM processing fails.

    C1 fallback page format:
    - ``processing_depth: "stub"`` (not "concept" or "source")
    - ``grade: "C"``
    - body = sanitized source text first 2000 chars + metadata header

    This page is the degradation target when the LLM is unreachable
    (circuit breaker OPEN, all retries exhausted, 422 content moderation).
    """
    import time as _time
    import hashlib as _hashlib
    from ..utils.path import normalize_source_path as _norm_src_path

    _stem = (
        Path(str(source_path)).stem
        if hasattr(source_path, "stem")
        else str(source_path)
    )
    _norm = unicodedata.normalize("NFC", _stem)
    _slug_stem = slugify(_norm)
    _hash = _hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:8]
    _slug = f"{_slug_stem}-{_hash}" if _slug_stem else f"stub-{task_id}"

    _clean_body = clean_source_text(source_text)[:2000]

    _reason_line = f"\n> ⚠️ **LLM 处理失败**: {reason}\n" if reason else ""
    body = (
        f"## 来源\n\n"
        f"- 路径: `{source_path}`\n"
        f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 任务 ID: `{task_id}`\n"
        f"{_reason_line}\n"
        f"## 内容\n\n{_clean_body}\n"
    )

    return [
        WikiPage(
            id=_slug,
            title=_norm[:120],
            type=PageType.SOURCE,
            sources=[_norm_src_path(str(source_path), paths.root)],
            body=body,
            grade="C",
            processing_depth="stub",
            created_at=int(_time.time() * 1000),
            updated_at=int(_time.time() * 1000),
        )
    ]


def _create_review_item(candidate, review_result, paths, task_id):
    """Create a ReviewItem for a NEEDS_HUMAN_REVIEW candidate."""
    from ..wiki.features.review import add_review
    add_review(
        paths,
        type="candidate_review",
        title=candidate.title,
        detail=review_result.reason,
        confidence=candidate.confidence,
        source_task_id=task_id,
        search_queries=[],
        page_path="",
    )


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
):
    """Phase 1 (NDG split): LLM processing only — ZERO disk writes.

    Returns (pages, extra_pages, meta) where meta is a dict with keys
    ``analysis``, ``source_slug``, ``source_page_id``, ``source_grade``,
    ``downstream_count``, ``extra_pages_count``, ``rejected``, ``warnings``.
    The caller is responsible for calling ``commit_ingest`` to persist.
    """
    # No pre-flight work needed: the 2026-07 cleanup removed the Inbox
    # staging layer. The collector reads ``raw/sources/<file>`` directly
    # and the wiki page's ``sources:`` field references that same
    # project-relative path.
    _ = paths  # keep the parameter for callers
    candidate = None  # may be set by candidate pipeline path; used in meta enrichment

    from .sanitizer import sanitize

    _result = sanitize(source_text)

    if _result.warnings:
        _logger.warning(
            "[run_ingest] sanitizer: %s score=%.2f source=%s",
            _result.warnings, _result.quality_score, source_path,
        )

    _sanitized_source_text = _result.text

    # 数据收集：记录文件大小概况（积累 100+ 样本后建模调度策略）
    _source_bytes = len(_sanitized_source_text.encode("utf-8"))
    _logger.info(
        "[run_ingest] size_profile source=%s bytes=%d kb=%.1f",
        source_path, _source_bytes, round(_source_bytes / 1024, 1),
    )

    # Hard-reject: skip LLM entirely for degraded sources (opt-in via
    # RUFLO_SANITIZER_SKIP_LLM=1; off by default).
    if _result.should_skip_llm and __import__("os").environ.get("RUFLO_SANITIZER_SKIP_LLM", "0") == "1":
        _logger.warning("[run_ingest] skipping LLM for %s", source_path)
        return await _write_rejected_source_page(
            paths, source_path, source_text, _result, task_id
        )

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
    _slug_stem_for_map = slugify(_norm_stem_for_slug)
    _path_hash_for_slug = hashlib.md5(
        str(source_path).encode("utf-8")
    ).hexdigest()[:8]
    _source_slug_for_map = (
        f"{_slug_stem_for_map}-{_path_hash_for_slug}"
        if _slug_stem_for_map else
        task_id if task_id.startswith("kb-") else f"kb-{task_id}"
    )
    _source_slug_map = {str(source_path): _source_slug_for_map}

    # --- Chunking (large-doc gate) ---
    from .chunker import chunk_source_text as _chunk_source_text, merge_candidates as _merge_candidates

    CHUNK_THRESHOLD = 12000
    _chunks = _chunk_source_text(_sanitized_source_text, threshold=CHUNK_THRESHOLD)
    _is_chunked = len(_chunks) > 1

    # --- Pipeline mode selection ---
    _pipeline_mode = __import__("os").environ.get("RUFLO_PIPELINE_MODE", "candidate")

    if _pipeline_mode == "candidate":
        # ==================================================================
        # New path: json analyzer → Reviewer → Promoter → generate_from_candidate
        # ==================================================================
        analysis = None  # type: ignore[assignment]
        pages: list[WikiPage] = []

        # Step 1: JSON analyzer → KnowledgeCandidate
        from ..knowledge.core.candidate import KnowledgeCandidate as _KC

        if _is_chunked:
            _logger.info(
                "[run_ingest] chunked %s into %d parts (%.1f KB total)",
                source_path, len(_chunks), round(len(_sanitized_source_text.encode("utf-8")) / 1024, 1),
            )
            from .stages.reviewer import ReviewerStage
            _reviewer = ReviewerStage()
            _all_candidates: list = []

            for _ch in _chunks:
                _ch_text = _ch["text"]
                if not _ch_text.strip():
                    continue
                try:
                    # C1: wrap each chunk's analyzer call with retry.
                    # Transient errors retry; permanent (422) + circuit
                    # breaker OPEN propagate to fail the whole ingest.
                    _ch_candidate = await retry_with_backoff(
                        lambda _a=_analyze, _t=_ch_text, _c=_ch: _with_llm_timeout(
                            _a(
                                source_text=_t,
                                source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".md",
                                existing_wiki_index=_existing_wiki_index,
                                folder_context=folder_context,
                                provider=provider,
                                task_id=task_id,
                                source_path=str(source_path),
                                output_format="json",
                                chunk_index=_c["chunk_index"],
                                chunk_total=_c["chunk_total"],
                            ),
                            timeout=180.0,
                            op=f"analyzer chunk {_c['chunk_index']+1}/{_c['chunk_total']}",
                        ),
                        cb_name="ingest_llm",
                    )
                except (PermanentFailure, CircuitBreakerOpen):
                    raise
                except (RetryExhausted, Exception) as _ch_exc:
                    _logger.warning(
                        "[run_ingest] chunk %d/%d failed: %s",
                        _ch["chunk_index"] + 1, _ch["chunk_total"], _ch_exc,
                    )
                    continue

                if not isinstance(_ch_candidate, _KC):
                    continue

                _ch_result = _reviewer.review(_ch_candidate, paths.root)
                if _ch_result.status == "validated":
                    _all_candidates.append(_ch_candidate)
                elif _ch_result.status == "needs_human_review":
                    _create_review_item(_ch_candidate, _ch_result, paths, task_id)
                    _all_candidates.append(_ch_candidate)
                else:
                    _logger.warning(
                        "[run_ingest] chunk %d/%d REJECTED: %s",
                        _ch["chunk_index"] + 1, _ch["chunk_total"], _ch_result.reason,
                    )

            if not _all_candidates:
                _logger.warning("[run_ingest] all chunks rejected for %s", source_path)
                meta = {
                    "analysis": None,
                    "source_slug": "",
                    "source_page_id": "",
                    "source_grade": "C",
                    "downstream_count": 0,
                    "extra_pages_count": 0,
                    "rejected": True,
                    "reason": "all chunks rejected by reviewer",
                    "warnings": [],
                    "source_bytes": _source_bytes,
                    "chunks_count": len(_chunks),
                    "claims_count": 0,
                    "evidence_count": 0,
                    "candidate_confidence": 0.0,
                }
                return [], [], meta

            candidate = _merge_candidates(_all_candidates, source_path=str(source_path))
            analysis = None  # type: ignore[assignment]
            _has_fallback = False
        else:
            # C1: wrap the single-chunk analyzer call with retry + backoff.
            # Transient errors (timeout, disconnect, 5xx) retry up to 3x;
            # 429 waits for Retry-After; 422 → PermanentFailure;
            # circuit breaker OPEN → CircuitBreakerOpen.
            _analyze_fn = _analyze  # capture for the lambda closure below
            _raw_result = await retry_with_backoff(
                lambda: _with_llm_timeout(
                    _analyze_fn(
                        source_text=_sanitized_source_text,
                        source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".md",
                        existing_wiki_index=_existing_wiki_index,
                        folder_context=folder_context,
                        provider=provider,
                        task_id=task_id,
                        source_path=str(source_path),
                        output_format="json",
                    ),
                    timeout=180.0,
                    op="analyzer (json)",
                ),
                cb_name="ingest_llm",
            )

            # If analyze was monkeypatched to return AnalysisResult (legacy test
            # stubs), fall back to the two-step path transparently.
            if not isinstance(_raw_result, _KC):
                import warnings as _w
                _w.warn(
                    "analyze() returned AnalysisResult instead of KnowledgeCandidate; "
                    "falling back to legacy two-step path. "
                    "Update stubs to return KnowledgeCandidate when output_format='json'.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                analysis = _raw_result  # type: ignore[assignment]
                pages = await _generate(
                    paths=paths,
                    analysis=analysis,
                    existing_wiki_index=_existing_wiki_index,
                    provider=provider,
                    source_slug_map=_source_slug_map,
                    source_text=_sanitized_source_text,
                )
                _logger.info(
                    "[run_ingest] legacy fallback produced %d pages for %s",
                    len(pages), source_path,
                )
                # Jump to quality gate / source page generation below.
                _has_fallback = True
            else:
                candidate = _raw_result
                _has_fallback = False

            if not _has_fallback:
                # Step 2: Reviewer (4 rule checks)
                from .stages.reviewer import ReviewerStage
                reviewer = ReviewerStage()
                result = reviewer.review(candidate, paths.root)

                if result.status == "rejected":
                    _logger.warning("[run_ingest] candidate REJECTED: %s", result.reason)
                    meta = {
                        "analysis": None,
                        "source_slug": "",
                        "source_page_id": "",
                        "source_grade": "C",
                        "downstream_count": 0,
                        "extra_pages_count": 0,
                        "rejected": True,
                        "reason": result.reason,
                        "warnings": [],
                        "source_bytes": _source_bytes,
                        "chunks_count": 1,
                        "claims_count": 0,
                        "evidence_count": 0,
                        "candidate_confidence": 0.0,
                    }
                    return [], [], meta

                if result.status == "needs_human_review":
                    _logger.info("[run_ingest] candidate NEEDS_HUMAN_REVIEW: %s", result.reason)
                    _create_review_item(candidate, result, paths, task_id)
                    meta = {
                        "analysis": None,
                        "source_slug": "",
                        "source_page_id": "",
                        "source_grade": "C",
                        "downstream_count": 0,
                        "extra_pages_count": 0,
                        "needs_review": True,
                        "reason": result.reason,
                        "warnings": [],
                        "source_bytes": _source_bytes,
                        "chunks_count": 1,
                        "claims_count": 0,
                        "evidence_count": 0,
                        "candidate_confidence": 0.0,
                    }
                    return [], [], meta

            # Step 3: Promote Candidate → KnowledgeObject
            from .stages.candidate_promoter import CandidatePromoter
            promoter = CandidatePromoter()
            try:
                ko = promoter.promote(candidate)
            except ValueError as _promote_err:
                _logger.warning("[run_ingest] promotion failed: %s", _promote_err)
                meta = {
                    "analysis": None, "source_slug": "", "source_page_id": "",
                    "source_grade": "C", "downstream_count": 0,
                    "extra_pages_count": 0, "rejected": True,
                    "reason": str(_promote_err), "warnings": [],
                    "source_bytes": _source_bytes, "chunks_count": 1,
                    "claims_count": 0, "evidence_count": 0,
                    "candidate_confidence": 0.0,
                }
                return [], [], meta

            # Step 4: Generate pages from KnowledgeObject (frontmatter from KO, LLM renders body)
            from .generator import generate_from_knowledge_object
            # C1: wrap the generator LLM call with retry.  If the LLM
            # fails transiently during body generation, retry the whole
            # generate_from_knowledge_object call (stateless — it just
            # re-generates pages from the same KnowledgeObject).
            _gko_fn = generate_from_knowledge_object
            pages = await retry_with_backoff(
                lambda: _gko_fn(
                    ko=ko,
                    candidate=candidate,
                    paths=paths,
                    existing_wiki_index=_existing_wiki_index,
                    provider=provider,
                    source_slug_map=_source_slug_map,
                    source_text=_sanitized_source_text,
                ),
                cb_name="ingest_llm",
            )
            _logger.info(
                "[run_ingest] candidate path produced %d pages for %s",
                len(pages), source_path,
            )
    else:
        # ==================================================================
        # Legacy path: unified_generate (single-pass) or two-step fallback
        # ==================================================================
        import warnings
        warnings.warn(
            "Legacy pipeline mode is deprecated. "
            "Set RUFLO_PIPELINE_MODE=candidate to use the new pipeline.",
            DeprecationWarning,
            stacklevel=2,
        )

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
                "[run_ingest] unified path produced %d pages for %s",
                len(pages), source_path,
            )
            if not pages:
                raise RuntimeError("unified path returned 0 pages")
        except Exception as _unified_err:
            _logger.warning(
                "[run_ingest] unified path failed (%s), falling back to two-step",
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
    # Default OFF (QualitySettings mode="off") — must be explicitly
    # enabled in the per-project settings file. When active:
    #   - Decision A1: judge LLM failure → log warning, pass pages through
    #   - Decision B1: re-generate rejected pages up to max_retries
    #   - Decision C:  inline (this hook); async mode TBD via event bus
    # Latency cost when ON: +5-15s per ingest (single judge call;
    # retries multiply by max_retries+1 since the existing judge does
    # re-judge internally — deviation from strict B1 "re-generate"
    # noted in the 9-plan-bugfix plan).
    from ..quality.judge import QualityJudge
    _quality_settings = _load_quality_settings(paths)
    if _quality_settings.is_active() and pages:
        try:
            judge = QualityJudge(settings=_quality_settings)
            page_dicts = [
                {
                    "id": p.id, "type": p.type.value, "body": p.body,
                    "grade": p.grade,
                    "confidence": getattr(p, "confidence", None),
                }
                for p in pages
            ]
            result = await judge.judge_batch(page_dicts, source_texts={p.id: source_text for p in pages})
            if result.pages_quarantined:
                from ..quality.quarantine import QuarantineStore
                _quarantine = QuarantineStore(paths)
                pages_by_id = {p.id: p for p in pages}
                for qid in result.pages_quarantined:
                    if qid in pages_by_id:
                        _quarantine.put(
                            project_root=paths.root,
                            task_id="quality_gate",
                            page_id=qid,
                            content=pages_by_id[qid].body,
                            judgment=result.pages[qid],
                        )
                # Filter out quarantined pages from the write list
                pages = [p for p in pages if p.id not in result.pages_quarantined]
                _logger.info(
                    f"[run_ingest] quality gate quarantined "
                    f"{len(result.pages_quarantined)} page(s); "
                    f"{len(pages)} passed"
                )
        except Exception as e:
            # Decision A1: judge LLM failure must NOT block ingest.
            # Log + pass pages through (graceful degradation).
            _logger.warning(
                f"[run_ingest] quality gate unavailable: {e}; "
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
    slug_stem = slugify(norm_stem)
    path_hash = hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:8]
    source_slug = f"{slug_stem}-{path_hash}" if slug_stem else (
        task_id if task_id.startswith("kb-") else f"kb-{task_id}"
    )
    source_title = norm_stem.replace("_", " ")

    # Render via the bundled source.md template. Falls back to the
    # legacy inline body if the template is missing (operator deleted
    # bundled file).
    _has_analysis = analysis is not None
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
        # Count PDF page markers in source text for source_meta
        _page_marker_count = source_text.count("<!-- page:")
        _page_count_line = f"- 页数: {_page_marker_count}\n" if _page_marker_count > 1 else ""

        source_body = render_body(
            template_body=source_tpl.body_markdown,
            slots={
                "source_meta": (
                    f"- 路径: `{source_path}`\n"
                    f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"- 任务 ID: `{task_id}`\n"
                    f"- 分块数: {len(_chunks)}\n"
                    f"{_page_count_line}"
                ),
                "summary": _summary_text.strip() or "(无摘要)",
                "key_points": key_points_value,
                "extracted_concepts": extracted_concepts_value,
                "main_content": clean_source_text(source_text),
            },
            page_type=PageType.SOURCE,
            template_version=source_tpl.version or "",
        )
    except FileNotFoundError as e:
        # Fallback: hardcoded legacy body (matches the previous
        # behaviour pre-template integration).
        _logger.error("source.md template missing, using fallback body: %s", e)
        _summary_fb = ""
        if _has_analysis:
            _summary_fb = (analysis.summary or "").strip() or "(无摘要)"
        else:
            for _p in pages:
                if _p.type == PageType.SOURCE:
                    _summary_fb = _p.body or ""
                    break
        _page_marker_count = source_text.count("<!-- page:")
        _page_count_line_fb = f"- 页数: {_page_marker_count}\n" if _page_marker_count > 1 else ""
        source_body = (
            f"## 来源\n\n"
            f"- 路径: `{source_path}`\n"
            f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- 任务 ID: `{task_id}`\n"
            f"- 分块数: {len(_chunks)}\n"
            f"{_page_count_line_fb}\n"
            f"## 摘要\n\n"
            f"{_summary_fb}\n\n"
            f"## 关键观点\n\n"
            f"- (无抽取的要点，详见抽取的概念)\n\n"
            f"## 抽取的概念\n\n"
            f"本次摄取共生成 **{len(pages)}** 个下游页面"
            f"{('（共 '+ str(len(analysis.suggested_pages)) + ' 个建议页）') if _has_analysis and analysis.suggested_pages else ''}。\n"
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

    # Chunked ingest note: replaces the old single-truncation warning.
    if _is_chunked:
        _size_kb = len(source_text) / 1024
        source_body += (
            f"\n\n> 📦 **分块摄取**: 原始文档 {_size_kb:.0f} KB, "
            f"已拆分为 {len(_chunks)} 块逐块送 LLM 处理后合并。"
        )
    else:
        from .generator import DEFAULT_MAX_SOURCE_CHARS as _MAX_SOURCE_CHARS
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
            f"[run_ingest] source page already produced by LLM for "
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
    # 兜底：LLM 可能引用 source page 标题但不带 -<8hex> hash 后缀，
    # 加入去 hash 变体确保 referenced_slugs 能匹配 produced_slugs
    for sid in list(produced_slugs):
        no_hash = re.sub(r"-[0-9a-f]{8}$", "", sid)
        if no_hash != sid:
            produced_slugs.add(no_hash)
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
    _blocklist = _get_noise_blocklist()
    if _blocklist:
        filtered = missing - _blocklist  # type: ignore[operator]
        if len(filtered) < len(missing):
            _logger.info(
                "[run_ingest] filtered %d blocklisted slug(s) from stubs: %s",
                len(missing) - len(filtered),
                ", ".join(sorted(missing & _blocklist)),
            )
        missing = filtered

    # C3: reference-list detection — suppress stubs entirely for list-heavy
    # documents to prevent stub explosion from encyclopedic reference lists.
    from .stub_quality import detect_reference_list_density as _detect_list_density
    _list_density = _detect_list_density(source_text)
    if _list_density > 0.6:
        _logger.info(
            "[run_ingest] list-heavy doc detected (density=%.2f); suppressing stubs",
            _list_density,
        )
        missing = set()

    # C3: score stub importance and filter low-importance slugs.
    from .stub_quality import (
        filter_low_importance_stubs as _filter_stubs,
        split_by_importance as _split_stubs,
        sort_stubs_by_importance as _sort_stubs,
        StubImportance as _StubImportance,
    )
    _stub_scores: dict[str, "_StubImportance"] = {}
    _inlined_slugs: set[str] = set()
    if missing and pages:
        _stub_scores = _filter_stubs(missing, pages)
        _kept_slugs, _inlined_slugs = _split_stubs(_stub_scores)
        if _inlined_slugs:
            _logger.info(
                "[run_ingest] inlining %d low-importance stub(s) as related_entities: %s",
                len(_inlined_slugs),
                ", ".join(sorted(_inlined_slugs)[:10]),
            )
            # Attach to the source page (find it in the pages list — may be
            # the LLM-generated version if llm_already_has_source was True).
            _target_source_page = source_page
            if llm_already_has_source:
                for _p in pages:
                    if _p.type == PageType.SOURCE:
                        _target_source_page = _p
                        break
            _target_source_page.related_entities = sorted(_inlined_slugs)
            # Append related entities section to source page body
            _rel_lines = "\n".join(f"  - [[{s}]]" for s in sorted(_inlined_slugs))
            _target_source_page.body += (
                f"\n\n## 相关实体（低优先级引用）\n\n"
                f"以下实体被引用但重要性较低，未生成独立占位页面：\n\n"
                f"{_rel_lines}\n"
            )
        missing = _kept_slugs

    # P2 quality gate: suppress excessive stub creation to avoid noise.
    # C3: MAX_STUBS only counts high+medium stubs (low are already inlined above).
    _max_stubs = _get_max_stubs_per_ingest()
    if len(missing) > _max_stubs:
        _logger.warning(
            "[run_ingest] suppressing %d stub(s) (exceeds max %d): %s",
            len(missing), _max_stubs,
            ", ".join(sorted(missing)[:20]),
        )
        missing = set()

    # C3: sort remaining stubs by importance (HIGH before MEDIUM) before creation.
    _sorted_missing = _sort_stubs(missing, _stub_scores) if _stub_scores else sorted(missing)

    if _sorted_missing:
        _logger.info(
            f"[run_ingest] creating {len(_sorted_missing)} stub entity page(s): "
            f"{_sorted_missing[:5]}{'...' if len(_sorted_missing) > 5 else ''}"
        )
    for slug in _sorted_missing:
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
        _logger.warning("[run_ingest] quality gate: %s degraded — %s", _pid, _reason)
    _keep_ids = {p.id for p in _gate.pages}
    pages = [p for p in pages if p.id in _keep_ids]
    extra_pages = [p for p in extra_pages if p.id in _keep_ids]

    # C2: C-grade page handling — classify root cause and attempt regeneration
    # for STRUCTURAL pages (one LLM call per page, max 3 per document).
    # Non-structural C-grade pages are marked as stubs.
    from .c_grade_handler import handle_c_grade_pages as _handle_c_grades
    pages = await _handle_c_grades(
        pages, provider, source_text=source_text,
    )
    if extra_pages:
        extra_pages = await _handle_c_grades(
            extra_pages, provider, source_text=source_text,
        )

    # Collect candidate metrics for observability report
    _candidate_claims = getattr(candidate, "claims", []) if candidate else []
    _candidate_evidence = getattr(candidate, "evidence", []) if candidate else []
    _candidate_conf = getattr(candidate, "confidence", 0.0) if candidate else 0.0

    meta = {
        "analysis": analysis,
        "source_slug": source_slug,
        "source_page_id": source_slug,
        "source_grade": _source_grade,
        "downstream_count": _downstream_count,
        "extra_pages_count": len(extra_pages),
        "rejected": False,
        "warnings": [],
        "source_bytes": _source_bytes,
        "chunks_count": len(_chunks) if _is_chunked else 1,
        "claims_count": len(_candidate_claims) if isinstance(_candidate_claims, list) else 0,
        "evidence_count": len(_candidate_evidence) if isinstance(_candidate_evidence, list) else 0,
        "candidate_confidence": float(_candidate_conf) if _candidate_conf else 0.0,
    }
    return pages, extra_pages, meta


async def commit_ingest(
    paths: WikiPaths,
    source_path,
    pages: list[WikiPage],
    extra_pages: list[WikiPage] | None = None,
    task_id: str = "test",
    event: str = "ingest",
    detail: str | None = None,
    log_task_id: str | None = None,
):
    """Phase 2 (NDG split): write pages + index update + log.

    The I/O half that was previously at the tail of ``run_ingest``.
    ``extra_pages`` are pre-existing pages that gained inverse edges
    (written to disk but NOT re-appended to the index).
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
        _detail = detail or f"generated {len(pages)} pages from {Path(str(source_path)).name}"
        log_event(
            paths,
            event=event,
            task_id=log_task_id or task_id,
            detail=_detail,
        )


def _load_quality_settings(paths: WikiPaths) -> "QualitySettings":  # noqa: F821
    """Load QualitySettings from per-project JSON or fall back to defaults."""
    import json

    from ..quality.types import QualitySettings

    cfg = paths.index / "quality_settings.json"
    if not cfg.exists():
        return QualitySettings()
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return QualitySettings(
            mode=data.get("mode", "off"),
            sample_rate=float(data.get("sample_rate", 0.2)),
            always_judge_grade_a=bool(data.get("always_judge_grade_a", True)),
            always_judge_low_confidence=float(data.get("always_judge_low_confidence", 0.7)),
            weights=data.get("weights", QualitySettings().weights),
            threshold_pass=float(data.get("threshold_pass", 0.7)),
            max_retries=int(data.get("max_retries", 1)),
        )
    except (json.JSONDecodeError, OSError, ValueError):
        return QualitySettings()


async def run_ingest(
    paths: WikiPaths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
) -> list[WikiPage]:
    """Run full pipeline (generate + commit). Behaviour-preserving wrapper.

    Returns list of generated WikiPage objects.
    """
    import time as _time
    _started_at = int(_time.time() * 1000)

    # D3: Rule-based document pre-filtering — runs before any LLM work.
    # Evaluates file size, sanitizer quality, list density, and language
    # to decide whether to process, skip, or downgrade the document.
    from .sanitizer import sanitize as _prefilter_sanitize

    _pf_sanitize_result = _prefilter_sanitize(source_text)
    _pf_file_size = len(source_text.encode("utf-8"))
    _prefilter_result = _run_prefilter(
        source_text=_pf_sanitize_result.text,
        file_size=_pf_file_size,
        sanitizer_score=_pf_sanitize_result.quality_score,
    )

    if _prefilter_result.action == "skip":
        _logger.info(
            "[run_ingest] prefilter skip: %s — %s",
            source_path, _prefilter_result.reason,
        )
        return []

    if _prefilter_result.action == "source_only":
        _logger.info(
            "[run_ingest] prefilter source_only: %s — %s",
            source_path, _prefilter_result.reason,
        )
        _pf_pages = _create_source_only_page(
            paths, source_path, source_text, task_id,
            reason=_prefilter_result.reason,
        )
        await commit_ingest(
            paths=paths,
            source_path=source_path,
            pages=_pf_pages,
            task_id=task_id,
        )
        return _pf_pages

    if _prefilter_result.action == "reference_list":
        _logger.info(
            "[run_ingest] prefilter reference_list density=%.2f: %s",
            _prefilter_result.metadata.get("list_density", 0.0),
            source_path,
        )
        # Proceed to generate_ingest; C3's detect_reference_list_density
        # already handles list-heavy documents by suppressing stubs.

    # C1: wrap generate_ingest with retry-awareness.  If the LLM is
    # unreachable (circuit breaker OPEN, all retries exhausted, 422
    # content moderation), fall back to a source-only stub page.
    try:
        pages, extra_pages, _meta = await generate_ingest(
            paths=paths,
            source_path=source_path,
            source_text=source_text,
            provider=provider,
            folder_context=folder_context,
            task_id=task_id,
        )
    except (RetryExhausted, PermanentFailure, CircuitBreakerOpen) as _retry_exc:
        _logger.warning(
            "[run_ingest] LLM call failed (%s), creating source-only stub page",
            type(_retry_exc).__name__,
        )
        _source_only_pages = _create_source_only_page(
            paths, source_path, source_text, task_id,
            reason=str(_retry_exc),
        )
        await commit_ingest(
            paths=paths,
            source_path=source_path,
            pages=_source_only_pages,
            task_id=task_id,
        )
        # D2: record failed-verdict metrics
        _duration = (int(_time.time() * 1000) - _started_at) / 1000.0
        _fail_reason = type(_retry_exc).__name__.lower()
        from ..metrics import INGEST_DURATION_SECONDS, INGEST_VERDICT_TOTAL
        INGEST_DURATION_SECONDS.observe(_duration, verdict="failed")
        INGEST_VERDICT_TOTAL.inc(verdict="failed", reason=_fail_reason)
        return _source_only_pages

    # Handle the case where generate_ingest succeeded but produced no
    # downstream pages (all chunks rejected, quality gate filter, etc.).
    if not pages and _meta.get("rejected"):
        _logger.warning(
            "[run_ingest] all chunks/claims rejected, creating source-only stub page"
        )
        _source_only_pages = _create_source_only_page(
            paths, source_path, source_text, task_id,
            reason=_meta.get("reason", "all chunks rejected"),
        )
        await commit_ingest(
            paths=paths,
            source_path=source_path,
            pages=_source_only_pages,
            task_id=task_id,
        )
        # D2: record rejected-verdict metrics
        _duration = (int(_time.time() * 1000) - _started_at) / 1000.0
        _reject_reason = _meta.get("reason", "unknown")
        from ..metrics import INGEST_DURATION_SECONDS, INGEST_VERDICT_TOTAL
        INGEST_DURATION_SECONDS.observe(_duration, verdict="rejected")
        INGEST_VERDICT_TOTAL.inc(verdict="rejected", reason=_reject_reason)
        return _source_only_pages

    await commit_ingest(
        paths=paths,
        source_path=source_path,
        pages=pages,
        extra_pages=extra_pages,
        task_id=task_id,
    )

    _finished_at = int(_time.time() * 1000)

    # --- Ingest observability: report + metrics ---
    try:
        _pipeline_mode = __import__("os").environ.get("RUFLO_PIPELINE_MODE", "candidate")
        _pages_by_type: dict[str, int] = {}
        for p in pages:
            _pt = p.type.value if hasattr(p.type, "value") else str(p.type)
            _pages_by_type[_pt] = _pages_by_type.get(_pt, 0) + 1
        for p in (extra_pages or []):
            _pt = p.type.value if hasattr(p.type, "value") else str(p.type)
            _pages_by_type[_pt] = _pages_by_type.get(_pt, 0) + 1

        _verdict = "validated"
        _verdict_reason = ""
        if _meta.get("rejected"):
            _verdict = "rejected"
            _verdict_reason = _meta.get("reason", "")
        elif _meta.get("needs_review"):
            _verdict = "needs_human_review"
            _verdict_reason = _meta.get("reason", "")

        # Bump rejected-candidate counter for Prometheus /metrics
        if _verdict == "rejected":
            from ..metrics import INGEST_CANDIDATE_REJECTED_TOTAL
            _reason_label = _verdict_reason[:80] if _verdict_reason else "unknown"
            INGEST_CANDIDATE_REJECTED_TOTAL.inc(reason=_reason_label)

        # D2: record ingest duration histogram + verdict counter
        _duration_sec = (_finished_at - _started_at) / 1000.0
        _d2_verdict = "success" if _verdict == "validated" else "rejected"
        _d2_reason = _verdict_reason or ""
        from ..metrics import INGEST_DURATION_SECONDS, INGEST_VERDICT_TOTAL
        INGEST_DURATION_SECONDS.observe(_duration_sec, verdict=_d2_verdict)
        INGEST_VERDICT_TOTAL.inc(verdict=_d2_verdict, reason=_d2_reason)

        from .ingest_report import build_report, write_ingest_report
        _report = build_report(
            task_id=task_id,
            source_path=str(source_path),
            started_at=_started_at,
            finished_at=_finished_at,
            source_bytes=_meta.get("source_bytes", 0),
            pipeline_mode=_pipeline_mode,
            chunks_count=_meta.get("chunks_count", 1),
            claims_count=_meta.get("claims_count", 0),
            evidence_count=_meta.get("evidence_count", 0),
            candidate_confidence=_meta.get("candidate_confidence", 0.0),
            verdict=_verdict,
            verdict_reason=_verdict_reason,
            pages_total=len(pages) + len(extra_pages or []),
            pages_by_type=_pages_by_type,
            warnings=_meta.get("warnings", []),
        )
        write_ingest_report(paths, _report)
    except Exception as _report_exc:
        _logger.warning("[run_ingest] report generation failed: %s", _report_exc)

    # Shadow mode: run the non-default pipeline path for comparison.
    # Main path output goes to wiki; shadow output goes to .index/shadow/<task_id>/.
    if __import__("os").environ.get("RUFLO_SHADOW_MODE", "") == "true":
        from .shadow import run_shadow_ingest, write_comparison_report

        _current_mode = __import__("os").environ.get("RUFLO_PIPELINE_MODE", "candidate")
        _shadow_mode = "legacy" if _current_mode == "candidate" else "candidate"

        _logger.info(
            "[shadow] mode=%s task=%s — running shadow ingest in background",
            _shadow_mode, task_id,
        )
        try:
            shadow_pages, shadow_meta = await run_shadow_ingest(
                paths=paths,
                source_path=source_path,
                source_text=source_text,
                provider=provider,
                folder_context=folder_context,
                task_id=task_id,
                shadow_mode=_shadow_mode,
            )
            shadow_dir = paths.index / "shadow" / task_id
            write_comparison_report(
                shadow_dir=shadow_dir,
                main_pages=pages,
                shadow_pages=shadow_pages,
                main_meta=_meta,
                shadow_meta=shadow_meta,
                task_id=task_id,
            )
        except Exception as _shadow_exc:
            _logger.warning(
                "[shadow] shadow run failed for %s: %s", task_id, _shadow_exc,
            )

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
