"""Deep Research CLI subcommands."""
import argparse
import asyncio
import sys

from ..research.runner import run_deep_research
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_research_run(args: argparse.Namespace) -> None:
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
    result = asyncio.run(run_deep_research(
        ctx, topic=args.topic, from_review_id=args.from_review_id,
        no_ingest=not args.ingest, top_k=args.top_k,
    ))
    print(f"Task: {result['task_id']}")
    print(f"Synthesis: {result['synthesis_path']}")
    print(f"Sources: {len(result['sources'])}")
    if result['ingest_task_ids']:
        print(f"Ingest tasks: {result['ingest_task_ids']}")


def cmd_research_list(args: argparse.Namespace) -> None:
    """List recent research tasks (MVP: no persistence; placeholder)."""
    print("No persistence in MVP. Run `research run` to create new tasks.")


def cmd_research_show(args: argparse.Namespace) -> None:
    """Show synthesis page (MVP: no state lookup; just read file)."""
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
    from ..wiki.storage.page_writer import read_page
    path = ctx.paths.wiki_synthesis / f"{args.task_id}.md"
    if not path.exists():
        print(f"Synthesis not found: {path}", file=sys.stderr); sys.exit(2)
    p = read_page(path)
    print(p.body)


def add_research_subcommands(subparsers) -> None:
    """Register `research {run, list, show}` on the parent parser."""
    p_research = subparsers.add_parser("research", help="Deep Research workflow")
    p_research_sub = p_research.add_subparsers(dest="research_command")

    # research run
    p_run = p_research_sub.add_parser("run", help="Run a deep research task")
    p_run.add_argument("topic", help="Research topic")
    p_run.add_argument("--from-review-id", default=None,
                       help="Pull queries from a wiki review item")
    p_run.add_argument("--ingest", action="store_true",
                       help="Auto-ingest top sources (off by default)")
    p_run.add_argument("--top-k", type=int, default=10,
                       help="Search results per query (default 10)")
    p_run.add_argument("--project", default=None,
                       help="Project UUID or name")
    p_run.set_defaults(func=cmd_research_run)

    # research list
    p_list = p_research_sub.add_parser("list", help="List recent research tasks")
    p_list.set_defaults(func=cmd_research_list)

    # research show
    p_show = p_research_sub.add_parser("show", help="Show a synthesis page")
    p_show.add_argument("task_id", help="Synthesis page id (filename stem)")
    p_show.add_argument("--project", default=None,
                        help="Project UUID or name")
    p_show.set_defaults(func=cmd_research_show)
