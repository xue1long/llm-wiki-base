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
import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict
from pathlib import Path

from ..wiki.core.paths import WikiPaths
from ..wiki.core.id_generator import normalize_id_chars
from ..wiki.schema_registry import SchemaRegistry
from ..utils.path import canonical_raw_key, normalize_source_path
from ..wiki.core.types import PageType, WikiPage
from ..lib.atomic_ctx import AtomicContext
from ..lib.write_hooks import flush_pending_writes
from ..wiki.features.indexer import append_to_index
from ..wiki.features.logger import log_event
from ..wiki.features.tag_namespace import normalize_tags
from ..wiki.storage.page_writer import write_page
from .retry import PermanentFailure
from .readiness_gate import apply_readiness_gate, resolve_specialist, route_after_readiness

# Resolve analyze/generate via the pipeline package namespace so
# monkey-patches on `src.pipeline.pipeline.analyze` /
# `src.pipeline.pipeline.generate` (set by tests like
# test_e2e/test_ingest_happy_path.py) propagate into run_ingest.
# The package namespace ``src.pipeline`` always contains the compat
# shim's staticmethod-wrapped functions; ``getattr`` looks them up
# at call time, after the test patch has run.
from . import analyzer as _analyzer_module
from . import generator as _generator_module
from ._pipeline_common import (
    clean_source_text,
    _read_purpose_text,
    _read_schema_text,
    _read_taxonomy_text,
)

# ---------------------------------------------------------------------------
# Stub quality gate (P2 optimization — 2026-07-29).
# ---------------------------------------------------------------------------
# Maximum number of stub entity pages to create in a single ingest.  When
# the LLM references more missing slugs than this threshold, stub creation
# is suppressed to avoid polluting the wiki with placeholder pages for
# platform names, company names, and other non-domain entities.
# Set via env var ``RUFLO_MAX_STUBS_PER_INGEST`` (default 10).
_MAX_STUBS_ENV = "RUFLO_MAX_STUBS_PER_INGEST"


def _source_format(source_path) -> str:
    suffix = Path(str(source_path)).suffix.lower().removeprefix(".")
    if suffix in {"md", "txt", "pdf", "docx", "xlsx", "html", "htm"}:
        return "html" if suffix == "htm" else suffix
    if suffix in {"png", "jpg", "jpeg", "webp", "tiff", "bmp"}:
        return "image"
    return suffix or "unknown"


def _source_extraction_method(source_path) -> str:
    format = _source_format(source_path)
    return {
        "md": "native_text",
        "txt": "native_text",
        "html": "html_text",
        "pdf": "pdf_text",
        "docx": "docx_text",
        "xlsx": "xlsx_cells",
        "image": "ocr",
    }.get(format, "unsupported")


def _get_max_stubs_per_ingest() -> int:
    """Return the current max stubs threshold (re-reads env var at call time)."""
    return int(__import__("os").environ.get(_MAX_STUBS_ENV, "10"))


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
    """Scan every wiki page directory (built-in typed + schema custom dirs);
    return ``{slug: PageType}`` for each page currently on disk.

    Reused for both the analyzer/generator ``existing_wiki_index`` prompt
    text (slug reuse — B9) and Fix E's stub de-duplication set (B11).
    Directory discovery delegates to ``SchemaRegistry.iter_page_dirs``
    (Task 0.4) so custom-type pages are never missed; built-in dirs keep
    their PageType, custom dirs fall back to ``SOURCE`` for reuse purposes.
    """
    from ..wiki.schema_registry import SchemaRegistry
    registry = SchemaRegistry.from_project(paths.root)
    typed_dirs = {
        getattr(paths, attr): pt for pt, attr in _EXISTING_WIKI_DIRS
    }
    index = {}
    for d in registry.iter_page_dirs(paths):
        if d is None or not d.exists():
            continue
        pt = typed_dirs.get(d, PageType.SOURCE)
        for f in d.glob("*.md"):
            index[f.stem] = pt
    return index


def _build_resolution_context(paths, source_path, source_slug: str, raw_stem: str):
    """Task 2：冻结一次生成操作的不可变 ResolutionContext。

    canonical raw key + 当前 source 候选 + 全库 index（slug/title）与
    alias 快照。body wikilink 与 relation target 共用此上下文解析。
    """
    from src.utils.path import canonical_raw_key
    from src.wiki.features.slug_utils import normalize_reconcile_slug
    from src.wiki.features.target_resolver import ResolutionContext

    try:
        canon_key = canonical_raw_key(source_path, paths.root)
    except ValueError:
        canon_key = str(source_path)

    aliases = {}
    try:
        from src.wiki.features.slug_aliases import SlugAliasRegistry
        for _a, _c in (SlugAliasRegistry(paths.root).aliases or {}).items():
            if _c:
                aliases[_a] = _c
    except Exception:
        pass

    existing: set[str] = set()
    title_index: dict[str, list[str]] = {}
    try:
        from src.wiki.features.indexer import read_index
        _type_dirs = {
            PageType.SOURCE: "sources",
            PageType.ENTITY: "entities",
            PageType.CONCEPT: "concepts",
            PageType.SYNTHESIS: "synthesis",
        }
        for _slug, _pt, _title in read_index(paths):
            existing.add(normalize_reconcile_slug(_slug))
            _pt_value = _pt.value if isinstance(_pt, PageType) else str(_pt)
            _dir = _type_dirs.get(_pt) or {
                "source": "sources", "entity": "entities",
                "concept": "concepts", "synthesis": "synthesis",
            }.get(_pt_value)
            if _dir:
                existing.add(normalize_reconcile_slug(f"{_dir}/{_slug}"))
            _key = normalize_reconcile_slug(_title or _slug)
            title_index.setdefault(_key, []).append(_slug)
    except Exception:
        pass

    return ResolutionContext(
        source_candidates=((canon_key, source_slug, raw_stem),),
        existing_index=frozenset(existing),
        title_index=title_index,
        aliases=aliases,
    )


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
# carry an `|alias` and/or a `#section` suffix. The reconciliation helper in
# ``src/pipeline/reconcile.py`` owns the canonical implementation now (its
# ``_extract_wikilink_targets`` is shared by resolver + gap collection);
# this module-level helper was removed with the old auto-stub block.

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


def finalize_generated_page(page: WikiPage, paths: WikiPaths, *,
                            now: int | None = None) -> WikiPage:
    """Task 3：生成管线字段 owner 边界 —— 系统字段由脚本最终裁定，不信任 LLM。

    覆盖：``grade``、``processing_depth``、``id/title`` 清洗、
    ``created_at/updated_at``。语义字段（body/tags/relations/category/
    taxonomy_sub/custom_type）由各自规范化器或 Schema 路由处理；通用
    ``write_page()`` 只做结构校验与序列化，不在此改写人工页面。
    """
    if now is None:
        now = int(__import__("time").time() * 1000)
    if page.grade not in ("A", "B", "C"):
        page.grade = "B"
    if page.processing_depth not in ("concept", "memory", "operation", "stub"):
        page.processing_depth = "concept"
    if page.id:
        page.id = page.id.strip()
    if page.title:
        page.title = page.title.strip()
    if not page.created_at:
        page.created_at = now
    if not page.updated_at:
        page.updated_at = now
    # Task 4：relation 元数据归一化 —— weight 有限且 clamp 到 [0,1]
    for rel in (page.relations or []):
        try:
            w = float(rel.weight)
        except (TypeError, ValueError):
            w = 1.0
        if w != w or w < 0.0 or w > 1.0:  # NaN 或越界 → 默认 1.0
            w = 1.0
        rel.weight = round(w, 4)
    return page


def _normalize_generated_pages(
    pages: list[WikiPage],
    paths: WikiPaths,
    resolution_context=None,
) -> list[WikiPage]:
    """Post-process LLM-generated pages: enforce valid enums, canonicalize
    relation targets, and rewrite body wikilinks via the unified Target
    Resolver (plan Task 2)."""
    import re as _re
    import time
    try:
        from src.wiki import SlugAliasRegistry
        reg = SlugAliasRegistry(str(paths.root))
    except Exception:
        reg = None

    now = int(__import__("time").time() * 1000)
    from src.wiki.features.gbrain_compat import (
        build_target_slugs, materialize_relations, rewrite_wikilinks,
    )
    from src.wiki.storage.page_writer import page_path_for

    # GBrain imports wiki/ directly, so its canonical slug is the path below
    # wiki/, not the ruflo page ID. Build this once for the whole publication
    # and use it for every generated body/link.
    from src.wiki.schema_registry import SchemaRegistry
    registry = SchemaRegistry.from_project(paths.root)
    current_page_paths = []
    for page in pages:
        try:
            page_path = page_path_for(paths, page.type, page.id,
                                      registry=registry,
                                      custom_type=page.custom_type)
            current_page_paths.append((page.id, page_path))
        except (ValueError, OSError):
            continue
    target_slugs = build_target_slugs(paths, current_page_paths)
    from src.pipeline.generator import RELATION_TYPES as _RELATION_TYPES
    _valid_relation_types = set(_RELATION_TYPES)
    for page in pages:
        # Task 3：字段 owner —— 系统字段先经 finalize_generated_page 裁定
        finalize_generated_page(page, paths, now=now)
        # M9（Phase 3 实测）：过滤非法 relation 类型——LLM 或历史页可能输出
        # `related_to` / `contrasts` / `part_of` 等非 17 型（+ x-*）类型。
        # JSON schema enum 只约束新 LLM 输出；存量页（extras）合并时也须清理。
        if page.relations:
            page.relations = [
                r for r in page.relations
                if r.type in _valid_relation_types or r.type.startswith("x-")
            ]
        if reg is not None:
            for rel in page.relations:
                canonical = reg.get_canonical(rel.target_id)
                if canonical and canonical != rel.target_id:
                    rel.target_id = canonical

        # Task 2：统一 Target Resolver —— body wikilink + relation target
        # 共用同一 ResolutionContext，消除各 Generator 入口的独立猜名/替换。
        if resolution_context is not None:
            from src.wiki.features.target_resolver import resolve_wiki_target
            if page.body:
                def _rewrite(m: object) -> str:
                    inner = m.group(1)
                    target = inner.split("|")[0].split("#")[0].strip()
                    res = resolve_wiki_target(target, context=resolution_context)
                    if res.canonical_target and res.changed:
                        _logger.warning(
                            "[normalize] TARGET-REWRITE page=%s %s -> %s (%s)",
                            page.id, target, res.canonical_target, res.kind,
                        )
                        return f"[[{res.canonical_target}{inner[len(target):]}]]"
                    return m.group(0)
                page.body = _re.sub(r"\[\[(.*?)\]\]", _rewrite, page.body)
            if page.relations:
                for rel in page.relations:
                    res = resolve_wiki_target(rel.target_id, context=resolution_context)
                    if res.canonical_target and res.changed:
                        _logger.warning(
                            "[normalize] TARGET-REWRITE page=%s rel %s -> %s (%s)",
                            page.id, rel.target_id, res.canonical_target, res.kind,
                        )
                        rel.target_id = res.canonical_target
        if page.body:
            page.body = rewrite_wikilinks(page.body, target_slugs)
        page.body = materialize_relations(page.body, page.relations, target_slugs)
    return pages


def _analyze(**kwargs):
    import sys
    return getattr(sys.modules["src.pipeline.pipeline"], "analyze")(**kwargs)


def _generate(**kwargs):
    import sys
    return getattr(sys.modules["src.pipeline.pipeline"], "generate")(**kwargs)


async def _write_rejected_source_page(
    paths: WikiPaths,
    source_path,
    source_text: str,
    result,
    task_id: str,
    assessment=None,
) -> list[WikiPage]:
    """Build a grade=C source page; persistence happens in commit_ingest()."""
    import time as _time

    _t = _time.localtime()
    _src_path = Path(str(source_path))
    # R4: the slug must derive from the *basename* only — an absolute or
    # project-relative path contains path separators which page_path_for
    # would otherwise interpret as nested directories, writing the page
    # outside wiki/sources/.
    _stem = _src_path.stem if _src_path.stem else str(source_path)
    _norm = unicodedata.normalize("NFC", _stem)
    _hash = hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:8]
    _slug = f"{_norm}-{_hash}"

    reason_codes = list(getattr(assessment, "reason_codes", ()))
    reason = "; ".join(reason_codes or getattr(result, "warnings", ())) or "unavailable"
    body = (
        f"## 来源\n\n"
        f"- 路径: `{source_path}`\n"
        f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S', _t)}\n"
        f"- 任务 ID: `{task_id}`\n\n"
        f"> ⚠️ **已跳过处理**: 内容可用性门禁未通过，未进行 LLM 分析。\n"
        f"> 质量评分: {result.quality_score:.0%}\n"
        f"> 原因: {reason}\n"
    )

    page = WikiPage(
        id=_slug,
        title=_stem[:120],
        type=PageType.SOURCE,
        sources=[str(source_path)],
        body=body,
        grade="C",
    )

    # Gate 前禁止写盘。生成阶段只返回页面，统一由 commit_ingest()
    # 在 Gate 通过后提交，避免 reject + Gate fail 污染 wiki/index/log。
    return [page]


_logger = logging.getLogger(__name__)


# Note: this file used to define _resolve_wiki_paths and _get_provider as
# local helpers. They were moved to src.pipeline.__init__ as the canonical
# location so that the compat-shim mechanism in __init__.py can re-export
# them as class attributes on sys.modules['src.pipeline.pipeline']. Tests
# monkey-patch those attributes; service.py looks them up late through the
# src.pipeline package namespace, which is what propagates the patch.


async def _analyze_chunked(
    *,
    source_text: str,
    source_ext: str,
    existing_wiki_index: str,
    folder_context: str,
    provider,
    task_id: str,
    source_path: str,
    schema_content: str,
    purpose_content: str,
    taxonomy_content: str,
    chunk_size: int | None = None,
) -> "AnalysisResult":
    """Analyze a large source in chunks and merge the per-chunk results.

    batch-50 regression: >MAX_SOURCE_CHARS sources were hard-truncated,
    losing 65-97% of content. Splitting keeps the full document visible to
    the analyzer (chunk_index/chunk_total are passed through) and the
    merged AnalysisResult drives one generation pass.
    """
    from .generator import get_max_source_chars

    chunk_size = chunk_size or get_max_source_chars()
    chunks = _split_source_chunks(source_text, chunk_size)
    _logger.info(
        "[run_ingest] large source (%d chars) split into %d chunk(s) for analysis",
        len(source_text), len(chunks),
    )
    results = []
    for i, chunk in enumerate(chunks):
        ar = await _analyze(
            source_text=chunk,
            source_ext=source_ext,
            existing_wiki_index=existing_wiki_index,
            folder_context=folder_context,
            provider=provider,
            task_id=task_id,
            source_path=source_path,
            schema_content=schema_content,
            purpose_content=purpose_content,
            taxonomy_content=taxonomy_content,
            chunk_index=i,
            chunk_total=len(chunks),
        )
        results.append(ar)
    return _merge_analysis_results(results)


async def generate_ingest(
    paths: WikiPaths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
    schema_registry: SchemaRegistry | None = None,
) -> tuple[list[WikiPage], list[WikiPage], dict]:
    """Phase 1 (NDG split): LLM processing only — ZERO disk writes.

    Returns ``(pages, extra_pages, meta)`` where ``meta`` is a dict with
    keys ``analysis``, ``source_slug``, ``source_page_id``, ``source_grade``,
    ``downstream_count``, ``extra_pages_count``, ``rejected``, ``warnings``.
    The caller is responsible for calling ``commit_ingest`` to persist.
    """
    # Resolve schema registry once and pass to all downstream calls.
    if schema_registry is None:
        schema_registry = SchemaRegistry.from_project(paths.root)
    # Read schema/purpose text for prompt injection
    _schema_text = _read_schema_text(paths)
    _purpose_text = _read_purpose_text(paths)
    _taxonomy_text = _read_taxonomy_text(paths)

    from .text_preprocessing import preprocess_source
    from .readiness_replay import serialize_audit
    from .triage import triage

    try:
        _source_key = canonical_raw_key(str(source_path), paths.root)
    except ValueError:
        _source_key = str(source_path)
    _source_file = Path(str(source_path))
    try:
        _file_size = _source_file.stat().st_size
        _source_bytes_sha256 = hashlib.sha256(_source_file.read_bytes()).hexdigest()
    except OSError:
        _file_size = len(source_text.encode("utf-8"))
        _source_bytes_sha256 = None
    _result = preprocess_source(
        source_text,
        source_id=_source_key,
        source_bytes_sha256=_source_bytes_sha256,
        skip_llm_on_degraded=os.environ.get("RUFLO_SANITIZER_SKIP_LLM", "0") == "1",
        format=_source_format(source_path),
        extraction_method=_source_extraction_method(source_path),
    )
    _readiness = apply_readiness_gate(_result.artifact)
    _readiness_audit = serialize_audit(
        _readiness.assessment,
        _result.report,
        analyzer_called=False,
        failure_reason=None,
    )
    _readiness_disposition = await route_after_readiness(
        _readiness, provider=provider, paths=paths, task_id=task_id
    )
    if _readiness_disposition.value == "specialist":
        _readiness = await resolve_specialist(_readiness)
        _readiness_disposition = await route_after_readiness(
            _readiness, provider=provider, paths=paths, task_id=task_id
        )
        _readiness_audit = serialize_audit(
            _readiness.assessment,
            _result.report,
            analyzer_called=False,
            failure_reason=_readiness.assessment.failure_reason,
        )
    _triage = triage(
        str(source_path),
        _result.prompt_text,
        file_size=_file_size,
        sanitizer_score=_result.report.quality_score,
    )

    if _result.report.warnings:
        _logger.warning(
            "[run_ingest] sanitizer: %s score=%.2f source=%s",
            _result.report.warnings, _result.report.quality_score, source_path,
        )

    _sanitized_source_text = _result.prompt_text

    # Q26: compute processing_depth_hint from sanitized source text.
    # This is a HINT passed to generator functions, not a forced override —
    # LLM can still choose a different processing_depth in its output.
    from .short_form import detect_short_form
    _depth_decision = detect_short_form(_sanitized_source_text)
    _processing_depth_hint = _depth_decision.processing_depth
    _logger.debug(
        "[generate_ingest] processing_depth_hint=%s chars=%d steps=%d timed_out=%s",
        _processing_depth_hint, _depth_decision.char_count,
        _depth_decision.step_count, _depth_decision.timed_out,
    )

    # Hard-reject: skip LLM entirely for degraded sources (opt-in via
    # RUFLO_SANITIZER_SKIP_LLM=1; off by default).
    from .text_preprocessing import ReadinessDecision
    if _result.report.should_skip_llm or _readiness_disposition.value == "audit_only":
        _logger.warning("[run_ingest] skipping LLM for %s", source_path)
        # R4: the rejection branch must return the same (pages, extra,
        # meta) triple as the main path — it previously returned a bare
        # list, which broke every caller's tuple unpacking.
        return [], [], {
            "analysis": None,
            "source_slug": None,
            "source_page_id": None,
            "source_grade": "C",
            "triage": None,
            "downstream_count": 0,
            "extra_pages_count": 0,
            "rejected": True,
            "warnings": list(_result.report.warnings),
            "content_assessment": asdict(_readiness.assessment),
            "readiness_audit": _readiness_audit,
            "missing_slugs": [],
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
    _norm_stem_for_slug = normalize_id_chars(
        unicodedata.normalize("NFC", _raw_stem_for_slug)
    )
    _path_hash_for_slug = hashlib.md5(
        str(source_path).encode("utf-8")
    ).hexdigest()[:8]
    _source_slug_for_map = (
        f"{_norm_stem_for_slug}-{_path_hash_for_slug}"
        if _norm_stem_for_slug else
        task_id if task_id.startswith("kb-") else f"kb-{task_id}"
    )
    _source_slug_map = {str(source_path): _source_slug_for_map}

    # Task 2：冻结 ResolutionContext（canonical raw key + source 候选 +
    # 全库 index/标题/alias 快照），供 _normalize_generated_pages 的 body
    # wikilink 与 relation target 统一解析（各 Generator 入口共享）。
    _resolution_context = _build_resolution_context(
        paths, source_path, _source_slug_for_map, _raw_stem_for_slug)

    # Unified path: single LLM call (Analyzer + Generator merged).
    # Falls back to two-step on failure. For sources larger than
    # MAX_SOURCE_CHARS, skip the truncating unified path entirely and use
    # chunked analysis (S1 — batch-50 regression: 40% of the pool was
    # truncated to 8000 chars, losing most content).
    analysis = None  # type: ignore[assignment]
    pages: list[WikiPage] = []
    _kc_review: dict | None = None
    _kc_promotion = None
    _pilot_audit: dict | None = None
    from .generator import get_max_source_chars as _get_max_source_chars
    # 1.3 H6：单调用内闭环 resolver —— 缺失 slug 反馈进 generator，不整链重跑。
    from .reconcile import make_missing_slugs_resolver
    _missing_resolver = make_missing_slugs_resolver(
        paths, produced_prefix={_source_slug_for_map},
    )
    _candidate_mode = os.environ.get("RUFLO_PIPELINE_MODE", "candidate") == "candidate"
    if _candidate_mode:
        from .analyzer import analyze
        from .generator import generate_from_candidate
        from src.kc.mainline import CandidatePromoter, CandidateReviewer
        from .text_preprocessing import chunk_prompt_blocks

        _prompt_chunks = chunk_prompt_blocks(
            _result.prompt_blocks,
            max_chars=_get_max_source_chars(),
        ) or ((),)
        _chunk_candidates = []
        for _chunk_index, _prompt_chunk in enumerate(_prompt_chunks):
            _chunk_text = "\n\n".join(
                block.prompt_content for block in _prompt_chunk
            )
            _chunk_candidates.append(await analyze(
                source_text=_chunk_text,
                source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".md",
                existing_wiki_index=_existing_wiki_index,
                folder_context=folder_context,
                provider=provider,
                task_id=task_id,
                source_path=_source_key,
                output_format="json",
                chunk_index=_chunk_index if len(_prompt_chunks) > 1 else None,
                chunk_total=len(_prompt_chunks) if len(_prompt_chunks) > 1 else None,
                schema_content=_schema_text,
                purpose_content=_purpose_text,
                taxonomy_content=_taxonomy_text,
                prompt_blocks=_prompt_chunk,
            ))
        candidate = _merge_candidate_chunks(_chunk_candidates)
        if not hasattr(candidate, "claims") or not candidate.claims or not candidate.evidence:
            raise ValueError("candidate requires non-empty claims and evidence")
        _source_key = canonical_raw_key(str(source_path), paths.root)
        _candidate_status = getattr(candidate, "status", None)
        if getattr(_candidate_status, "value", _candidate_status) == "rejected":
            raise ValueError("candidate status is rejected")
        _candidate_source_id = getattr(candidate, "source_id", "")
        if not _candidate_source_id:
            raise ValueError("candidate requires source_id")
        if canonical_raw_key(str(_candidate_source_id), paths.root) != _source_key:
            raise ValueError("candidate source_id does not match source")
        document = _result.canonical_document
        review = await CandidateReviewer().review(
            candidate,
            document,
            source_root=paths.root,
            visible_block_ids={block.block_id for block in _result.prompt_blocks},
        )
        if review.status != "validated" or not review.projections:
            raise ValueError(
                candidate.failure_reason or "KC structural review rejected candidate"
            )
        _kc_review = {
            "document_id": review.document_id,
            "projections": list(review.projections),
        }
        _kc_promotion = CandidatePromoter().promote(
            candidate,
            review,
            project_root=paths.root,
            document=document,
        )
        from src.kc.compiler.evidence import canonical_quote
        from .readiness_replay import serialize_audit
        _audit_evidence = []
        for item in candidate.evidence:
            quote = canonical_quote(str(item.get("quote", "")))
            _audit_evidence.append({
                "source_id": _source_key,
                "block_id": str(item.get("block_id", "")),
                "quote": quote,
                "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            })
        _pilot_audit = serialize_audit(
            _readiness.assessment,
            _result.report,
            analyzer_called=True,
            failure_reason=None,
        )
        _readiness_audit = _pilot_audit
        _pilot_audit.update({
            "binding_mode": "explicit_block_binding",
            "noise_warnings": list(_result.report.warnings),
            "applied_rules": [
                {
                    "rule_id": rule.rule_id,
                    "removed_line_count": rule.removed_line_count,
                    "removed_char_count": rule.removed_char_count,
                }
                for rule in _result.report.applied_rules
            ],
            "evidence": _audit_evidence,
            "evidence_refs": [
                evidence_id
                for projection in review.projections
                for evidence_id in projection.get("evidence_ids", ())
            ],
        })
        if _audit_evidence:
            _pilot_audit.update({
                "block_id": _audit_evidence[0]["block_id"],
                "exact_quote": _audit_evidence[0]["quote"],
                "quote_hash": _audit_evidence[0]["quote_hash"],
            })
        pages = await generate_from_candidate(
            candidate=candidate,
            paths=paths,
            existing_wiki_index=_existing_wiki_index,
            provider=provider,
            source_slug_map=_source_slug_map,
            source_text=_sanitized_source_text,
            schema_registry=schema_registry,
            taxonomy_content=_taxonomy_text,
            missing_slugs_resolver=_missing_resolver,
            processing_depth_hint=_processing_depth_hint,
        )
        analysis = None
    elif len(_sanitized_source_text) > _get_max_source_chars():
        try:
            analysis = await _analyze_chunked(
                source_text=_sanitized_source_text,
                source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".pdf",
                existing_wiki_index=_existing_wiki_index,
                folder_context=folder_context,
                provider=provider,
                task_id=task_id,
                source_path=str(source_path),
                schema_content=_schema_text,
                purpose_content=_purpose_text,
                taxonomy_content=_taxonomy_text,
            )
            pages = await _generate(
                paths=paths,
                analysis=analysis,
                existing_wiki_index=_existing_wiki_index,
                provider=provider,
                source_slug_map=_source_slug_map,
                source_text=_sanitized_source_text,
                schema_registry=schema_registry,
                taxonomy_content=_taxonomy_text,
                missing_slugs_resolver=_missing_resolver,
                processing_depth_hint=_processing_depth_hint,
            )
            _logger.info(
                "[run_ingest] chunked path produced %d pages for %s",
                len(pages), source_path,
            )
            if not pages:
                raise RuntimeError("chunked path returned 0 pages")
        except PermanentFailure:
            # 422 content moderation —— 永久失败，禁止 fallback 级联再发 LLM 调用
            # （B2：每批空耗 LLM 的浪费消除；直接冒泡到批级 permanent_failed）。
            raise
        except Exception as _chunked_err:
            _logger.warning(
                "[run_ingest] chunked path failed (%s), falling back to unified",
                _chunked_err,
            )
            analysis = None
    if analysis is None and not _candidate_mode:
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
                schema_registry=schema_registry,
                purpose_content=_purpose_text,
                taxonomy_content=_taxonomy_text,
                missing_slugs_resolver=_missing_resolver,
                processing_depth_hint=_processing_depth_hint,
            )
            _logger.info(
                "[run_ingest] unified path produced %d pages for %s",
                len(pages), source_path,
            )
            if not pages:
                raise RuntimeError("unified path returned 0 pages")
        except PermanentFailure:
            # 422 content moderation —— 永久失败，禁止 fallback 级联再发 LLM 调用
            # （B2：每批空耗 LLM 的浪费消除；直接冒泡到批级 permanent_failed）。
            raise
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
                schema_content=_schema_text,
                purpose_content=_purpose_text,
                taxonomy_content=_taxonomy_text,
            )
            pages = await _generate(
                paths=paths,
                analysis=analysis,
                existing_wiki_index=_existing_wiki_index,
                provider=provider,
                source_slug_map=_source_slug_map,
                source_text=_sanitized_source_text,
                schema_registry=schema_registry,
                taxonomy_content=_taxonomy_text,
                missing_slugs_resolver=_missing_resolver,
                processing_depth_hint=_processing_depth_hint,
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
    pages = _normalize_generated_pages(pages, paths, resolution_context=_resolution_context)

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
    norm_stem = normalize_id_chars(unicodedata.normalize("NFC", raw_stem))
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
        # Phase 1.6 (F5): deterministic transcription-quality + credibility
        # signals (no LLM). ASR marker comes from the pipeline denoise line;
        # UGC-carrier detection reuses lint's header heuristic.
        _asr_marker = "*此文档由 GPU 加速转录生成*" in source_text
        transcription_quality_value = (
            "ASR 转录（自动转写含错漏，需人工复核）"
            if _asr_marker else "人工整理"
        )
        try:
            from ..wiki.features.lint import _is_ugc_carrier
            _ugc = _is_ugc_carrier(source_text[:4000])
        except Exception:
            _ugc = False
        credibility_value = (
            "UGC 网络来源（可信度/ugc）"
            if _ugc else "未标注来源类型（默认按普通素材）"
        )
        source_body = render_body(
            template_body=source_tpl.body_markdown,
            slots={
                "source_meta": (
                    f"- 路径: `{source_path}`\n"
                    f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"- 任务 ID: `{task_id}`\n"
                ),
                "transcription_quality": transcription_quality_value,
                "summary": _summary_text.strip() or "(无摘要)",
                "key_points": key_points_value,
                "credibility": credibility_value,
                # extracted_concepts kept for bundled 2.0.0 templates;
                # v3.0.0 project templates drop it via the slot renderer.
                "extracted_concepts": extracted_concepts_value,
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
            f"{clean_source_text(source_text)}\n"
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
        created_at=int(__import__("time").time() * 1000),
        updated_at=int(__import__("time").time() * 1000),
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

    # ── 1.3 H9：引用-产出对账（替代旧的 Fix E 自动建 stub）──────────────
    # 不再自动创建 stub entity 页（H9 整改——stub 与 gap 语义重叠，M11 门禁
    # 会被 165 个存量 stub 淹没）。未解析的引用写入 KnowledgeGapStore
    # （在 commit 路径落盘；generate_ingest 保持零磁盘写）。判定集合 =
    # 产出 ∪ 磁盘页 ∪ SlugAliasRegistry 可解析 ∪ 索引，全部经统一归一函数
    # normalize_reconcile_slug 比对（B-H3，消解 CJK 顿号假断链）。
    # 采集时机在 _compute_reverse_relations 之后（见下方 1.3 O6 注记）。

    # B13: compute reverse (inverse) edges in-memory so the relation graph
    # is bidirectional on disk. New pages are mutated in-place; pre-existing
    # target pages (referenced by a new relation but not themselves created
    # this run) are loaded, merged, and written in the same atomic batch.
    extra_pages = _compute_reverse_relations(paths, pages)

    # Q1-fix: defensive relation dedup on the final page set. Each page
    # must have at most one relation per target_id (highest weight wins).
    # The Generator already deduplicates, but _compute_reverse_relations
    # may add inverse edges that collide with existing relations.
    # M9（Phase 3 实测）：extras（存量页反向边合并）也可能携带历史非法 relation
    # （如 `related_to` / `contrasts`）——与 pages 一起过滤，保证批内页 relation
    # 类型合规（lint LINT-ILLEGAL-RELATION = 0）。
    from src.pipeline.generator import RELATION_TYPES as _RELATION_TYPES
    _valid_relation_types = set(_RELATION_TYPES)
    for page in pages + extra_pages:
        if page.relations:
            page.relations = [
                r for r in page.relations
                if r.type in _valid_relation_types or r.type.startswith("x-")
            ]

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

    # 1.3 O6 (Phase 3 实测修复)：missing_slugs 采集必须在
    # _compute_reverse_relations 之后——反向边会给存量页（extras）加上指向
    # 不存在页的 relation（如 `玄幻小说` 被 extras 反向引用 `玄幻与仙侠区分对比`），
    # 若在 reverse 之前 collect 则这些断链永远不入 gap 账本（M1 残留）。
    # 对 pages + extra_pages 一起 collect，避免 extras 引入的断链漏检。
    from .reconcile import collect_missing_slugs
    _missing_gaps: list[tuple[str, str]] = collect_missing_slugs(
        pages + extra_pages, paths,
        produced_slugs={p.id for p in pages} | {p.id for p in extra_pages},
    )
    _missing_slugs = [s for s, _ in _missing_gaps]
    if _missing_slugs:
        _logger.info(
            f"[run_ingest] {len(_missing_slugs)} unresolved reference(s) → gap ledger: "
            f"{_missing_slugs[:5]}{'...' if len(_missing_slugs) > 5 else ''}"
        )

    # L2: keep page-level provenance for the KC structural review without
    # inventing a claim-to-page mapping.  Existing WikiPage serialization
    # already round-trips evidence_refs and _ko_extra.
    if _kc_review is not None:
        _evidence_refs = [
            f"{_kc_review['document_id']}:{evidence_id}"
            for projection in _kc_review["projections"]
            for evidence_id in projection.get("evidence_ids", ())
        ]
        _evidence_refs = list(dict.fromkeys(_evidence_refs))
        for _page in pages:
            _page.evidence_refs = _evidence_refs.copy()
            _page._ko_extra = {
                **(getattr(_page, "_ko_extra", {}) or {}),
                "kc_document_id": _kc_review["document_id"],
                "kc_projection_version": "kc-wiki-v1",
                "knowledge_object_ids": list(getattr(_kc_promotion, "object_ids", ())),
            }

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

    # M4（Phase 3 实测）：extras（存量页反向边）写入前清洗 body 占位符。
    # pages 已在 render_body 后经 _clean_placeholder_text；extras 是磁盘加载
    # 的存量页，body 可能含历史占位符（如「来源未提供具体例子」），直接写盘
    # 会残留 → lint LINT-PLACEHOLDER。此处统一清洗，保证批内页 M4 达标。
    from .generator import _clean_placeholder_text
    for _ep in extra_pages:
        if _ep.body:
            _ep.body = _clean_placeholder_text(_ep.body)

    return pages, extra_pages, {
        "analysis": analysis,
        "source_slug": source_slug,
        "source_page_id": source_slug,
        "source_grade": _source_grade,
        "triage": {
            "source_id": _triage.source_id,
            "grade": _triage.grade,
            "action": _triage.action,
            "reason": _triage.reason,
            "rule_version": _triage.rule_version,
            "metadata": _triage.metadata,
        },
        "downstream_count": _downstream_count,
        "extra_pages_count": len(extra_pages),
        "rejected": bool(_result.report.warnings),
        "warnings": list(_result.report.warnings),
        "kc_bundle_key": getattr(_kc_promotion, "bundle_key", None),
        "kc_object_ids": list(getattr(_kc_promotion, "object_ids", ())),
        "kc_manifest_path": str(getattr(_kc_promotion, "manifest_path", "")) if _kc_promotion else None,
        "pilot_audit": _pilot_audit,
        "readiness_audit": _readiness_audit,
        # 1.3 O6：未解析引用（commit 路径写 KnowledgeGapStore）
        "missing_slugs": [
            {"slug": s, "referenced_by": [r]} for s, r in _missing_gaps
        ],
    }


MAX_PAGES_PER_DOC = 15

# Trailing 8-hex hash in deterministic source-page slugs (Fix B).
_SOURCE_HASH_RE = re.compile(r"-([0-9a-f]{8})$")


def _rank_stub_candidates(
    missing: set[str],
    max_stubs: int,
    source_slug: str,
    ref_counts: dict[str, int],
    analyzer_named: set[str],
) -> list[str]:
    """Filter + rank stub candidates; return the stub slugs to create.

    batch-50 regression:
    - Document-title variants: the LLM sometimes references the source doc
      under a differently-hyphenated slug (``必备资料-15-...-43c5df10`` vs the
      source page ``必备资料15...-43c5df10``), creating a duplicate entity stub
      for the document itself. Any stub ending with the SAME trailing hash as
      the source page is such a variant — the source page already represents it.
    - All-or-nothing suppression: over the cap the old code dropped ALL stubs.
      Now keep the *max_stubs* highest-confidence ones, preferring slugs
      referenced by more pages and slugs the analyzer named.
    """
    src_hash = _SOURCE_HASH_RE.search(source_slug or "")
    src_suffix = src_hash.group(1) if src_hash else None

    def _is_doc_variant(slug: str) -> bool:
        if src_suffix is None:
            return False
        m = _SOURCE_HASH_RE.search(slug)
        return bool(m) and m.group(1) == src_suffix

    ranked = sorted(
        missing,
        key=lambda s: (
            ref_counts.get(s, 0),        # more references first
            1 if s in analyzer_named else 0,  # analyzer-named next
        ),
        reverse=True,
    )
    kept: list[str] = []
    for slug in ranked:
        if len(kept) >= max_stubs:
            break
        if _is_doc_variant(slug):
            continue
        kept.append(slug)
    return kept


# ---------------------------------------------------------------------------
# Large-doc chunked analysis (S1 — batch-50 regression).
# >MAX_SOURCE_CHARS sources were hard-truncated to 8000 chars, losing
# 65-97% of content. Split → analyze per chunk (the analyzer supports
# chunk_index/chunk_total) → merge → generate from the merged analysis.
# ---------------------------------------------------------------------------

def _merge_candidate_chunks(candidates: list) -> object:
    """Merge chunk candidates while preserving each local evidence index."""
    if not candidates:
        raise ValueError("candidate chunk merge requires at least one result")
    if len(candidates) == 1:
        return candidates[0]

    from copy import deepcopy

    source_id = candidates[0].source_id
    merged = deepcopy(candidates[0])
    merged.claims = []
    merged.evidence = []
    merged.confidence = min(candidate.confidence for candidate in candidates)
    merged.chunk_index = None
    merged.chunk_total = len(candidates)
    merged.raw_llm_output = {"chunks": [candidate.raw_llm_output for candidate in candidates]}

    for candidate in candidates:
        if candidate.source_id != source_id:
            raise ValueError("candidate chunk source_id mismatch")
        if getattr(candidate.status, "value", candidate.status) == "rejected":
            raise ValueError(candidate.failure_reason or "candidate chunk was rejected")
        evidence_offset = len(merged.evidence)
        merged.evidence.extend(deepcopy(candidate.evidence))
        for claim in candidate.claims:
            refs = claim.get("evidence_refs")
            if not isinstance(refs, list) or any(not isinstance(ref, int) for ref in refs):
                raise ValueError("candidate chunk evidence_refs are invalid")
            merged.claims.append({
                **deepcopy(claim),
                "evidence_refs": [ref + evidence_offset for ref in refs],
            })
    return merged

def _split_source_chunks(text: str, chunk_size: int) -> list[str]:
    """Split *text* into whole-paragraph chunks of at most *chunk_size* chars.

    Greedy paragraph packing: paragraphs (split on blank lines) accumulate
    until adding the next would exceed the budget; oversized single
    paragraphs are hard-split as a last resort so the whole document is
    always covered.
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current and current_len + len(para) + 2 > chunk_size:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        # A single paragraph longer than the budget: hard-split it.
        if len(para) > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
                current, current_len = [], 0
            for i in range(0, len(para), chunk_size):
                chunks.append(para[i:i + chunk_size])
            continue
        current.append(para)
        current_len += len(para) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _merge_analysis_results(results: list) -> "AnalysisResult":
    """Merge per-chunk AnalysisResults into one (dedup by slug).

    key_facts concatenate; entities/concepts/suggested_pages dedup by slug
    keeping the highest confidence; links_to_existing union. The first
    result's task_id/source_path are kept; summaries are joined.
    """
    from .schemas import AnalysisResult  # local import keeps module light

    if not results:
        raise ValueError("_merge_analysis_results requires >=1 result")
    if len(results) == 1:
        return results[0]

    key_facts: list[str] = []
    entities: dict[str, object] = {}
    concepts: dict[str, object] = {}
    pages: dict[tuple[str, str], object] = {}
    links: set[str] = set()
    summaries: list[str] = []

    for ar in results:
        summaries.append(ar.summary or "")
        key_facts.extend(ar.key_facts or [])
        for e in (ar.entities or []):
            prev = entities.get(e.slug)
            if prev is None or e.confidence > prev.confidence:
                entities[e.slug] = e
        for c in (ar.concepts or []):
            prev = concepts.get(c.slug)
            if prev is None or c.confidence > prev.confidence:
                concepts[c.slug] = c
        for p in (ar.suggested_pages or []):
            pages.setdefault((p.type, p.slug), p)
        links.update(ar.links_to_existing or [])

    return AnalysisResult(
        task_id=results[0].task_id,
        source_path=results[0].source_path,
        summary="\n".join(s for s in summaries if s),
        key_facts=key_facts,
        entities=list(entities.values()),
        concepts=list(concepts.values()),
        suggested_pages=list(pages.values()),
        links_to_existing=sorted(links),
        folder_context=results[0].folder_context,
    )


def _apply_page_cap_note(
    pages: list[WikiPage],
    source_name: str,
    cap: int = MAX_PAGES_PER_DOC,
) -> list[WikiPage]:
    """Warn + annotate the source page when a doc generates too many pages.

    batch-10/50 observation: per-doc page count varies 4-17 with no guard;
    a 3.5KB doc produced 17 pages. This does NOT drop pages (stub
    governance handles inflation) — it surfaces the anomaly in the source
    page so operators can merge thin pages manually.
    """
    if len(pages) <= cap:
        return pages
    _logger.warning(
        "[run_ingest] %s produced %d pages (cap %d) — likely over-split",
        source_name, len(pages), cap,
    )
    for page in pages:
        if page.type == PageType.SOURCE:
            note = (
                f"\n\n> ⚠️ **页面数超限**: 本文档生成了 {len(pages)} 页（上限 {cap}），"
                f"可能过度拆分。建议人工检查并合并薄页。\n"
            )
            page.body = (page.body or "").rstrip() + note
            break
    return pages


async def commit_ingest(
    paths: WikiPaths,
    source_path,
    pages: list[WikiPage],
    extra_pages: list[WikiPage] | None = None,
    task_id: str = "test",
    triage_result=None,
    missing_slugs: list | None = None,
    event: str = "ingest",
    expected_page_hashes: dict[str, str] | None = None,
    kc_bundle_key: str | None = None,
    readiness_audit: dict | None = None,
):
    """Phase 2 (NDG split): write pages + index update + log.

    The I/O half that was previously at the tail of ``run_ingest``.
    ``extra_pages`` are pre-existing pages that gained inverse edges
    (written to disk but NOT re-appended to the index).

    ``missing_slugs`` (plan 1.3 O6): ``[{"slug", "referenced_by": [...]}]``
    from the reconciliation — persisted to ``.index/knowledge_gaps.json``
    so Phase 4 gap-priority batches can resolve them by ingesting the
    referencing raw file.

    ``event`` (Phase 3 实测修复): the audit-log event name.  Defaults to
    ``"ingest"``; callers committing pre-existing extras (e.g.
    phase4_batch's ``event="reverse-relation"``) pass a distinct event so
    the log distinguishes them from fresh ingests.
    """
    from .quality_gate import check_pages
    from .triage import TriageResult, write_triage_result
    if readiness_audit is not None:
        from .readiness_audit import write_readiness_record
        write_readiness_record(paths.root, readiness_audit)
    _extra = extra_pages or []
    if isinstance(triage_result, dict):
        triage_result = TriageResult(**triage_result)
    _gate = check_pages(pages + _extra)
    for _pid, _reason in _gate.degraded.items():
        _logger.warning("[run_ingest] quality gate: %s degraded — %s", _pid, _reason)
    _keep_ids = {p.id for p in _gate.pages}
    pages = [p for p in pages if p.id in _keep_ids]
    _extra = [p for p in _extra if p.id in _keep_ids]

    # Page-count guard: surface over-splitting (batch-10: 3.5KB doc → 17 pages).
    pages = _apply_page_cap_note(pages, Path(str(source_path)).name)

    # 标签统一规范化兜底（计划 2026-08-18 Task 3）：pages + extra_pages 在
    # 写盘前统一经过唯一规范化器（tag_namespace.normalize_tags），任何入口
    # （新生成页 / extra_pages 反向关系 / 重试 / 迁移）的 legacy 或非法标签
    # 都无法到达磁盘。每次 mapping / removal / mandatory add 都记录审计
    # 日志（不包含 API Key 或其他凭据）。
    for _page in pages + _extra:
        _raw_tags = list(_page.tags or [])
        _norm = normalize_tags(_raw_tags, source_path=str(source_path))
        if _norm.tags == _raw_tags:
            continue
        _page.tags = _norm.tags
        for _orig, _new in _norm.mapped.items():
            _logger.warning(
                "[commit_ingest] TAG-MAPPED page=%s source=%s %s -> %s",
                _page.id, source_path, _orig, _new,
            )
        for _rem in _norm.removed:
            _logger.warning(
                "[commit_ingest] TAG-REMOVED page=%s source=%s %s",
                _page.id, source_path, _rem,
            )
        for _add in _norm.mandatory_added:
            _logger.warning(
                "[commit_ingest] TAG-MANDATORY page=%s source=%s +%s",
                _page.id, source_path, _add,
            )

    from ..vector.pending import mark_intent, promote_intent
    _publication_pages = pages + _extra
    # A page_writer call cannot see sibling pages that are still buffered in
    # this AtomicContext. Build the complete batch map first so links from a
    # newly-created source page to a newly-created concept are qualified too.
    from ..wiki.features.gbrain_compat import (
        build_target_slugs, materialize_relations, rewrite_wikilinks,
    )
    from ..wiki.storage.page_writer import page_path_for
    _registry = SchemaRegistry.from_project(paths.root)
    _batch_targets = [
        (
            _page.id,
            page_path_for(
                paths, _page.type, _page.id, _registry,
                getattr(_page, "custom_type", "") or "",
            ),
        )
        for _page in _publication_pages
    ]
    _target_slugs = build_target_slugs(paths, _batch_targets)
    for _page in _publication_pages:
        _page.body = materialize_relations(
            rewrite_wikilinks(_page.body, _target_slugs),
            _page.relations,
            _target_slugs,
        )
    # L3: create the vector publication intent before the first Wiki write.
    # Failure is fail-closed so a committed page can never lack a recovery hint.
    mark_intent(paths, _publication_pages)

    with AtomicContext(flush_callback=flush_pending_writes):
        for page in pages:
            write_page(paths, page,
                       expected_content_hash=(expected_page_hashes or {}).get(page.id))
        for page in _extra:
            write_page(paths, page,
                       expected_content_hash=(expected_page_hashes or {}).get(page.id))
        append_to_index(
            paths,
            [(p.id, p.type, p.title) for p in pages],
        )
        log_event(
            paths,
            event=event,
            task_id=task_id,
            detail=f"generated {len(pages)} pages from {Path(str(source_path)).name}",
        )
    # L3: Wiki committed successfully — make the intent explicitly pending.
    # If promotion fails, the intent remains durable and is recoverable on the
    # next reconcile/startup pass.
    try:
        promote_intent(paths, [page.id for page in _publication_pages])
    except Exception:
        _logger.warning("[commit_ingest] vector publication promotion failed (non-fatal)",
                        exc_info=True)

    if kc_bundle_key:
        from src.kc.mainline import index_and_publish_bundle
        await index_and_publish_bundle(
            paths.root,
            bundle_key=kc_bundle_key,
            pages=_publication_pages,
        )

    if triage_result is not None:
        write_triage_result(paths, triage_result)

    # 1.3 O6：未解析引用 → gap 账本（原子写，继承 blocklist/上限/doc-title 过滤）。
    if missing_slugs:
        from ..wiki.features.knowledge_gaps import KnowledgeGapStore
        _store = KnowledgeGapStore(paths.root)
        # raw_hint 用规范化相对路径（raw/sources/...），Phase 4 按此定位 raw。
        _raw_hint = normalize_source_path(str(source_path), paths.root)
        _title_map = {m["slug"]: m.get("title") for m in missing_slugs
                      if m.get("title")}
        # 逐 gap 归因：每个缺失 slug 记录引用它的页面 id（M-3）。
        _refs_map: dict[str, list[str]] = {
            m["slug"]: list(m.get("referenced_by") or []) for m in missing_slugs
        }
        _added = _store.add_many(
            [m["slug"] for m in missing_slugs],
            referenced_by_map=_refs_map,
            title_map=_title_map,
            raw_hint=_raw_hint,
            max_entries=_get_max_stubs_per_ingest(),
        )
        if _added:
            _store.save()
            _logger.info(
                "[run_ingest] recorded %d gap(s) for %s: %s",
                len(_added), Path(str(source_path)).name,
                ", ".join(_added[:10]),
            )


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
    pages, extra_pages, _meta = await generate_ingest(
        paths=paths,
        source_path=source_path,
        source_text=source_text,
        provider=provider,
        folder_context=folder_context,
        task_id=task_id,
    )
    await commit_ingest(
        paths=paths,
        source_path=source_path,
        pages=pages,
        extra_pages=extra_pages,
        task_id=task_id,
        triage_result=_meta.get("triage"),
        missing_slugs=_meta.get("missing_slugs"),
        kc_bundle_key=_meta.get("kc_bundle_key"),
        readiness_audit=_meta.get("readiness_audit"),
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
