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
import unicodedata
from pathlib import Path

from ..wiki.core.paths import WikiPaths
from ..wiki.core.types import WikiPage
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
from . import analyzer as _analyzer_module
from . import generator as _generator_module


def _analyze(**kwargs):
    import sys
    return getattr(sys.modules["src.pipeline.pipeline"], "analyze")(**kwargs)


def _generate(**kwargs):
    import sys
    return getattr(sys.modules["src.pipeline.pipeline"], "generate")(**kwargs)

_logger = logging.getLogger(__name__)


# Note: this file used to define _resolve_wiki_paths and _get_provider as
# local helpers. They were moved to src.pipeline.__init__ as the canonical
# location so that the compat-shim mechanism in __init__.py can re-export
# them as class attributes on sys.modules['src.pipeline.pipeline']. Tests
# monkey-patch those attributes; service.py looks them up late through the
# src.pipeline package namespace, which is what propagates the patch.


async def run_ingest(
    paths: WikiPaths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
) -> list[WikiPage]:
    """Run full 2-step pipeline + write pages + update index + log.

    Returns list of generated WikiPage objects.
    """
    # No pre-flight work needed: the 2026-07 cleanup removed the Inbox
    # staging layer. The collector reads ``raw/sources/<file>`` directly
    # and the wiki page's ``sources:`` field references that same
    # project-relative path.
    _ = paths  # keep the parameter for callers

    # Step 1: Analyze
    analysis = await _analyze(
        source_text=source_text,
        source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".pdf",
        existing_wiki_index="",
        folder_context=folder_context,
        provider=provider,
        task_id=task_id,
        source_path=str(source_path),
    )

    # Step 2: Generate
    pages = await _generate(
        paths=paths,
        analysis=analysis,
        existing_wiki_index="",
        provider=provider,
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
        key_facts = list(analysis.key_facts or [])
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
        source_body = render_body(
            template_body=source_tpl.body_markdown,
            slots={
                "source_meta": (
                    f"- 路径: `{source_path}`\n"
                    f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"- 任务 ID: `{task_id}`\n"
                ),
                "summary": (analysis.summary or "(无摘要)").strip() or "(无摘要)",
                "key_points": key_points_value,
                "extracted_concepts": extracted_concepts_value,
            },
            page_type=PageType.SOURCE,
        )
    except FileNotFoundError:
        # Fallback: hardcoded legacy body (matches the previous
        # behaviour pre-template integration).
        source_summary = (analysis.summary or "").strip() or "(无摘要)"
        source_body = (
            f"## 来源\n\n"
            f"- 路径: `{source_path}`\n"
            f"- 摄取时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- 任务 ID: `{task_id}`\n\n"
            f"## 摘要\n\n"
            f"{source_summary}\n\n"
            f"## 抽取的概念\n\n"
            f"本次摄取共生成 **{len(pages)}** 个下游页面"
            f"{('（共 '+ str(len(analysis.suggested_pages)) + ' 个建议页）') if analysis.suggested_pages else ''}。\n"
        )

    source_page = WikiPage(
        id=source_slug,
        title=source_title,
        type=PageType.SOURCE,
        sources=[str(source_path)],
        body=source_body,
        grade="A",                       # source is the raw artefact — full fidelity
        processing_depth="concept",
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
        """Compare raw paths case-/separator-insensitively."""
        return str(s).strip().lower().replace("/", "\\")

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
    else:
        pages.append(source_page)

    # Fix E: scan every relation target across all generated pages
    # and create a stub entity page for any slug that has no matching
    # wiki page. Without this, references like ``[[佛本是道]]`` end up
    # as dangling wikilinks — the wiki graph can't be navigated to the
    # referenced page, the search index doesn't include the entity,
    # and Obsidian / downstream tools show broken links.
    #
    # Strategy:
    #   1. Collect every slug referenced by any ``relations[].target``,
    #      plus the source page slug, plus the analyzer's
    #      ``links_to_existing`` (normalize through slugify so the same
    #      comparison is consistent with how generator named pages).
    #   2. Subtract the slugs that already have a page (either written
    #      this run, or pre-existing on disk).
    #   3. Emit a stub entity page for each remaining slug. Stubs are
    #      marked ``grade=B``, ``processing_depth=concept``, body
    #      explains that the entity was referenced but not described.
    #   4. Future ingests that include this entity in
    #      ``suggested_pages`` will replace the stub (write_page
    #      overwrites by default).
    from ..utils.slugify import slugify as _slugify

    referenced_slugs: set[str] = set()
    for page in pages:
        for rel in (page.relations or []):
            # Relation dataclass field is ``target_id`` (the YAML key is
            # ``target`` after to_dict() — see src/wiki/features/relations.py).
            tgt = getattr(rel, "target_id", None) or getattr(rel, "target", None)
            if tgt:
                referenced_slugs.add(_slugify(tgt) or tgt)
        for src in (page.sources or []):
            # Skip the source path itself — that's not a wiki slug.
            pass
    for link in (analysis.links_to_existing or []):
        referenced_slugs.add(_slugify(link) or link)

    produced_slugs = {p.id for p in pages}
    # Existing wiki pages (across all four type directories).
    from ..wiki.storage.page_writer import page_path_for
    existing_slugs: set[str] = set()
    for pt in PageType:
        try:
            existing_slugs.update(
                p.stem for p in getattr(paths, f"wiki_{pt.value}s").glob("*.md")
            )
        except Exception:
            pass

    missing = referenced_slugs - produced_slugs - existing_slugs
    if missing:
        _logger.info(
            f"[run_ingest] creating {len(missing)} stub entity page(s): "
            f"{sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}"
        )
    for slug in sorted(missing):
        # Best-effort title: humanize the slug (replace hyphens with
        # spaces, title-case ASCII). The slug is already deterministic
        # via pypinyin so this is consistent.
        slug_text = slug.replace("-", " ")
        # If the slug looks like pinyin (mostly lowercase letters), title-case it
        title = (
            slug_text.title()
            if all(c.islower() or c.isdigit() or c.isspace() for c in slug_text)
            else slug_text
        )
        stub_body = (
            f"## 占位条目\n\n"
            f"此页面被其他页面引用(例如 `[[{slug}]]`),但尚未独立撰写。\n\n"
            f"来源摄取: `{source_path}` (task `{task_id}`)。\n\n"
            f"下次摄取如果包含此实体,系统会自动用真实内容替换本占位页。\n"
        )
        pages.append(WikiPage(
            id=slug,
            title=title,
            type=PageType.ENTITY,
            sources=[str(source_path)],
            body=stub_body,
            grade="B",
            processing_depth="concept",
            is_immutable=False,
            created_at=int(_time.time() * 1000),
            updated_at=int(_time.time() * 1000),
        ))

    # Atomic write all pages + index update + log
    with AtomicContext(flush_callback=flush_pending_writes):
        for page in pages:
            write_page(paths, page)
        append_to_index(
            paths,
            [(p.id, p.type, p.title) for p in pages],
        )
        log_event(
            paths,
            event="ingest",
            task_id=task_id,
            detail=f"generated {len(pages)} pages from {source_path.name}",
        )

    return pages
