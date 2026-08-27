"""Wiki v2.1 polish CLI: stubs / dedup --auto / lint --cache-ttl."""
import asyncio
import sys
from ..services.wiki_analysis import run_dedup_auto, run_stub_promotion, run_lint
from ..wiki.features.lint_cache import cache_key, get as cache_get, put as cache_put, invalidate_all, DEFAULT_TTL
from ..wiki.storage.page_writer import read_page
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
    from ..llm.registry import ProviderNotFoundError, ProviderRegistry
    try:
        config = ProviderRegistry.get_default()
    except ProviderNotFoundError:
        print("Error: no LLM providers configured", file=sys.stderr)
        sys.exit(2)
    return create_llm_provider(config.name)


def cmd_stubs_promote(args):
    _, paths = _resolve_ctx(args.project)
    materialized = run_stub_promotion(paths, _provider())
    print(f"Materialized {len(materialized)} stubs")


def cmd_dedup_auto(args):
    """dedup_auto CLI（H-1 决策：--require-approval 开关）。

    默认 require_approval=False 走既有 merge-auto-high 路径 (0 回归)；
    --require-approval 时走 merge-reviewed 路径 (spec §11.4 #4 强制)，
    创建 pending Approval 而不实际合并。
    """
    _, paths = _resolve_ctx(args.project)
    require_approval = getattr(args, "require_approval", False)

    if require_approval:
        # spec §11.4 #4 强制路径：merge-reviewed
        from src.wiki.features.dedup_auto import dedup_auto_with_approval
        results = dedup_auto_with_approval(
            paths, _provider(), threshold=args.threshold, require_approval=True
        )
        n_approvals = sum(1 for r in results if hasattr(r, "approval_id"))
        print(
            f"Created {n_approvals} pending approvals (require manual review); "
            "no merges executed (spec §11.4 #4)"
        )
        return results

    # H-1 决策：默认走 merge-auto-high legacy（0 回归）
    result = run_dedup_auto(paths, _provider(), threshold=args.threshold)
    records = asyncio.run(result) if hasattr(result, "__await__") else result
    print(f"Auto-merged {len(records)} duplicate groups")
    return records


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
    report = run_lint(paths, project_id=ctx.id)
    print(f"Found {len(report.issues)} issues")
    for issue in report.issues:
        print(f"  [{issue.severity.value}] {issue.code}: {issue.message}")
    if ttl > 0:
        cache_put(key, [{"code": i.code, "severity": i.severity.value, "message": i.message} for i in report.issues], cache_dir, ttl=ttl)


__all__ = ["cmd_stubs_list", "cmd_stubs_promote", "cmd_dedup_auto", "cmd_lint_cache_clear", "cmd_lint"]
