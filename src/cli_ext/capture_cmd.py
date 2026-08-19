"""CLI: fast capture — write wiki pages without LLM pipeline.

Usage:
    python -m src.cli capture --type article --title "xxx" --content "..."
    python -m src.cli capture --type inspiration --title "idea"
    python -m src.cli capture --type video-transcript --title "xxx" --file transcript.txt
"""
import argparse
import sys
from pathlib import Path


def cmd_capture(args: argparse.Namespace) -> None:
    from ..services.capture import capture_page

    # Read content from mutually exclusive sources
    content = args.content or ""
    if args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        if fpath.stat().st_size > 10 * 1024 * 1024:  # 10MB
            print(f"Error: file too large (>10MB): {args.file}", file=sys.stderr)
            sys.exit(1)
        content = fpath.read_text(encoding="utf-8")
    elif args.stdin:
        import select
        # 5 second timeout for stdin
        if sys.stdin.isatty():
            ready, _, _ = select.select([sys.stdin], [], [], 5.0)
            if not ready:
                print("Error: stdin timeout (no input within 5 seconds)", file=sys.stderr)
                sys.exit(1)
        content = sys.stdin.read()

    # Parse tags
    tags = []
    if args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    # Resolve project
    project = args.project or args.path or "."

    try:
        result = capture_page(
            project_id=project,
            type=args.type,
            title=args.title,
            content=content,
            url=args.url or "",
            tags=tags,
            category=args.category or "",
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    status = result["status"]
    if status == "exists":
        print(f"Page already exists: {result['page_id']}")
        print(f"Path: {result['path']}")
    else:
        skeleton = " (skeleton)" if result["is_skeleton"] else ""
        print(f"Captured {args.type}{skeleton}: {result['page_id']}")
        print(f"Path: {result['path']}")


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'capture' subcommand."""
    p = subparsers.add_parser(
        "capture",
        help="Fast capture: write wiki pages without LLM pipeline",
        description="Create wiki pages directly from articles, video transcripts, or inspiration notes.",
    )
    p.add_argument(
        "--type", required=True,
        choices=["article", "video-transcript", "inspiration"],
        help="Capture sub-type",
    )
    p.add_argument("--title", required=True, help="Page title")
    p.add_argument("--content", help="Page content (direct text)")
    p.add_argument("--file", help="Read content from file")
    p.add_argument("--stdin", action="store_true", help="Read content from stdin")
    p.add_argument("--url", help="Source URL")
    p.add_argument("--tags", help="Comma-separated tags (e.g. '题材/科幻,情绪/燃')")
    p.add_argument("--category", help="Taxonomy category (for strict mode)")
    p.add_argument("--project", help="Project ID or path")
    p.add_argument("--path", help="Project path (alias for --project)")
    p.set_defaults(func=cmd_capture)
