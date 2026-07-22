"""Atomic + Budgeted CLI subcommands."""
import argparse
import sys

from ..lib.atomic_ctx import is_suspended
from ..lib.write_hooks import get_pending_count
from ..lib.context_budget import estimate_tokens, get_model_context_window


def cmd_atomic_status(args: argparse.Namespace) -> None:
    """Print current AtomicContext + pending writes state."""
    if is_suspended():
        print(f"Status: SUSPENDED (active AtomicContext)")
        print(f"Pending writes: {get_pending_count()}")
    else:
        print("Status: idle (no active AtomicContext)")
        print(f"Pending writes: {get_pending_count()}")


def cmd_budget_estimate(args: argparse.Namespace) -> None:
    """Estimate token count for file contents."""
    from pathlib import Path
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(2)
    text = path.read_text(encoding="utf-8")
    chars = len(text)
    tokens = estimate_tokens(text)
    print(f"File: {path}")
    print(f"Characters: {chars}")
    print(f"Estimated tokens (0.5/char): {tokens}")


def cmd_budget_check(args: argparse.Namespace) -> None:
    """Check if file fits in model's context window."""
    from pathlib import Path
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(2)
    text = path.read_text(encoding="utf-8")
    tokens = estimate_tokens(text)
    window = get_model_context_window(args.model)
    safety_window = int(window * 0.8)   # 80% safety margin

    if tokens <= safety_window:
        print(f"✓ {path.name} ({tokens} tokens) fits in {args.model} ({window} context, {safety_window} safety limit)")
    else:
        print(f"✗ {path.name} ({tokens} tokens) EXCEEDS {args.model} ({window} context, {safety_window} safety limit)")
        print(f"  Will be split into ~{(tokens // safety_window) + 1} chunks")
        sys.exit(1)
