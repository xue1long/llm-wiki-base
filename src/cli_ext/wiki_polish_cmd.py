"""Wiki v2.1 polish CLI: stubs / dedup --auto / lint --cache-ttl."""
import argparse
import asyncio
import sys
from ..wiki.dedup_auto import dedup_auto
from ..wiki.lint_cache import cache_key, get as cache_get, put as cache_put, invalidate_all, DEFAULT_TTL
from ..wiki.stubs import StubMaterializerWorker
from ..wiki.lint import lint_wiki
from ..wiki.page_writer import read_page
from ..wiki.types import PageType
from ..project.context import ProjectNotFoundError
from ..lib.project import resolve_project


def _resolve_ctx(project_arg):
    try:
        return resolve_project(project_arg, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_stubs_list(args):
    _, paths = _resolve_ctx(args.project)
    for f in paths.wiki_stubs.glob("*.md"):
        try:
            s = read_page(f)
            print(f"  {s.id}  {s.title}")
        except (ValueError, KeyError):
            lines = f.read_text(encoding="utf-8").splitlines()
            meta = {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in lines if ":" in line}
            print(f"  {meta.get('id', f.stem)}  {meta.get('title', f.stem)}")


def _provider():
    from ..llm.provider_factory import create_llm_provider
    from ..llm.registry import ProviderRegistry
    providers = ProviderRegistry.load()
    config = providers.get("default") or next(iter(providers.values()), None)
    if not config:
        print("Error: no LLM providers configured", file=sys.stderr)
        sys.exit(2)
    return create_llm_provider(config.name)


def cmd_stubs_promote(args):
    _, paths = _resolve_ctx(args.project)
    materialized = asyncio.run(StubMaterializerWorker(paths, _provider()).run_once())
    print(f"Materialized {len(materialized)} stubs")


def cmd_dedup_auto(args):
    _, paths = _resolve_ctx(args.project)
    result = dedup_auto(paths, _provider(), threshold=args.threshold)
    records = asyncio.run(result) if hasattr(result, "__await__") else result
    print(f"Auto-merged {len(records)} duplicate groups")


def cmd_lint_cache_clear(args):
    _, paths = _resolve_ctx(args.project)
    print(f"Invalidated {invalidate_all(paths.index / 'lint_cache')} cache entries")


def cmd_lint(args):
    ctx, paths = _resolve_ctx(args.project)
    cache_dir = paths.index / "lint_cache"
    ttl = 0 if args.no_cache else (args.cache_ttl if args.cache_ttl is not None else DEFAULT_TTL)
    summaries = [f.read_text(encoding="utf-8")[:200] for dp in ("wiki_sources", "wiki_entities", "wiki_concepts", "wiki_synthesis") for f in getattr(paths, dp).glob("*.md")]
    key = cache_key("2026-07-21-v1", summaries, index_version=1)
    if ttl > 0:
        cached = cache_get(key, cache_dir)
        if cached is not None:
            print(f"Using cached lint result ({len(cached.get('findings', []))} issues)")
            return
    report = lint_wiki(paths, project_id=ctx.id)
    print(f"Found {len(report.issues)} issues")
    for issue in report.issues:
        print(f"  [{issue.severity.value}] {issue.code}: {issue.message}")
    if ttl > 0:
        cache_put(key, [{"code": i.code, "severity": i.severity.value, "message": i.message} for i in report.issues], cache_dir, ttl=ttl)


__all__ = ["cmd_stubs_list", "cmd_stubs_promote", "cmd_dedup_auto", "cmd_lint_cache_clear", "cmd_lint"]
