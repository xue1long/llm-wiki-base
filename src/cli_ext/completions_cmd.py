"""Shell completion installation."""
import argparse
import os
import sys
from pathlib import Path


COMPLETION_DIR = Path(os.path.expanduser("~/.config/ruflo-kb/completions"))

BASH_SCRIPT = """# ruflo-kb bash completion
_ruflo_kb_completion() {
    local cur prev words cword
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    words=("${COMP_WORDS[@]:1}")
    cword=$((COMP_CWORD - 1))
    COMPREPLY=($(compgen -W "$(ruflo-kb completions print-words ${words[@]} 2>/dev/null)" -- "$cur"))
}
complete -F _ruflo_kb_completion ruflo-kb
complete -F _ruflo_kb_completion python -m src.cli
"""

ZSH_SCRIPT = """#compdef ruflo-kb
_ruflo_kb() {
    local -a subcommands
    subcommands=($(ruflo-kb completions print-words 2>/dev/null))
    _describe 'command' subcommands
}
compdef _ruflo_kb ruflo-kb
"""


def cmd_completions_install(args: argparse.Namespace) -> None:
    """Install shell completion script."""
    COMPLETION_DIR.mkdir(parents=True, exist_ok=True)
    path = None
    if args.shell == "bash":
        path = COMPLETION_DIR / "ruflo-kb.bash"
        path.write_text(BASH_SCRIPT, encoding="utf-8")
    elif args.shell == "zsh":
        path = COMPLETION_DIR / "_ruflo-kb"
        path.write_text(ZSH_SCRIPT, encoding="utf-8")
    elif args.shell == "fish":
        print("Fish completion deferred to v2.0.1")
        return
    if path is None:
        return
    print(f"Installed {args.shell} completion: {path}")
    if args.shell == "bash":
        print(f"Add to ~/.bashrc: source {path}")
    elif args.shell == "zsh":
        print(f"Add to ~/.zshrc: fpath=({COMPLETION_DIR} $fpath); autoload -U compinit; compinit")


def cmd_completions_show(args: argparse.Namespace) -> None:
    """Print completion script to stdout."""
    if args.shell == "bash":
        sys.stdout.write(BASH_SCRIPT)
    elif args.shell == "zsh":
        sys.stdout.write(ZSH_SCRIPT)
    else:
        print(f"Unknown shell: {args.shell}", file=sys.stderr)
        sys.exit(2)


def cmd_completions_print_words(_args: argparse.Namespace) -> None:
    """Print all subcommand + project names (for completion scripts)."""
    subcommands = [
        "atomic", "budget", "completions", "dedup", "fields", "health", "heat",
        "llm-providers", "lint", "lint-cache-clear", "mcp", "metrics", "project",
        "quality", "relations", "research", "schema", "serve", "serve-status",
        "serve-stop", "stubs", "tags", "templates", "vision",
    ]
    print(" ".join(subcommands), end="")
    try:
        # Lazy import to avoid pulling project module in --help
        from ..project.registry import GlobalRegistryStore
        for entry in GlobalRegistryStore.load().projects.values():
            print(f" {entry.name}", end="")
    except Exception:
        # Registry may be empty, corrupt, or unavailable during completion.
        pass
    print()


def cmd_completions(args: argparse.Namespace) -> None:
    """Top-level `completions` dispatcher."""
    action = args.completions_action
    if action == "install":
        cmd_completions_install(args)
    elif action == "show":
        cmd_completions_show(args)
    elif action == "print-words":
        cmd_completions_print_words(args)
