# CLI/UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Two UX improvements: (1) shell completion via argcomplete (bash + zsh); (2) 1 built-in project template (research only; 2 more deferred to v2.0.1).

**Tech Stack:** Python 3.11+, argcomplete (optional dep), Jinja2 (for templates).

**MVP Scope** (per spec): bash + zsh completion + 1 template (research).

---

### Task 1: Shell completion via argcomplete

**Files:** `src/cli_ext/completions_cmd.py` + tests + wire

```python
# src/cli_ext/completions_cmd.py
"""Shell completion installation."""
import argparse
import os
import sys
from pathlib import Path

from ..project.registry import GlobalRegistryStore


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
    if args.shell == "bash":
        path = COMPLETION_DIR / "ruflo-kb.bash"
        path.write_text(BASH_SCRIPT, encoding="utf-8")
    elif args.shell == "zsh":
        path = COMPLETION_DIR / "_ruflo-kb"
        path.write_text(ZSH_SCRIPT, encoding="utf-8")
    elif args.shell == "fish":
        # MVP: not implemented
        print("Fish completion deferred to v2.0.1")
        return
    print(f"Installed {args.shell} completion: {path}")
    # Print shell rc instructions
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
        print(f"Unknown shell: {args.shell}", file=sys.stderr); sys.exit(2)


def cmd_completions_print_words(args: argparse.Namespace) -> None:
    """Print all subcommand + project names (for completion scripts)."""
    subcommands = [
        "project", "ingest", "search", "status", "pause", "resume", "delete", "review",
        "lint", "export", "import", "dedup", "config", "templates", "llm-providers",
        "stubs", "relations", "tags", "fields", "schema", "research", "quality", "health",
        "atomic", "budget", "metrics", "serve", "serve-stop", "mcp", "chat", "vision",
    ]
    print(" ".join(subcommands), end="")
    # Append project names
    for entry in GlobalRegistryStore.load().projects.values():
        print(f" {entry.name}", end="")
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
```

**Wire in cli.py** (also enable argcomplete at top of main()):

```python
# src/cli.py — at top of main()
import os
if "RUFLO_COMPLETE" not in os.environ:
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

# Add subparser
p_comp = subparsers.add_parser("completions", help="Manage shell completions")
p_comp_sub = p_comp.add_subparsers(dest="completions_action")
p_comp_inst = p_comp_sub.add_parser("install")
p_comp_inst.add_argument("shell", choices=["bash", "zsh", "fish"])
p_comp_inst.set_defaults(func=cmd_completions)
p_comp_show = p_comp_sub.add_parser("show")
p_comp_show.add_argument("shell", choices=["bash", "zsh"])
p_comp_show.set_defaults(func=cmd_completions)
p_comp_pw = p_comp_sub.add_parser("print-words")
p_comp_pw.set_defaults(func=cmd_completions)
```

**Tests** (2): test_completions_install_bash, test_print_words_includes_projects.

```bash
git add src/cli_ext/completions_cmd.py src/cli.py tests/test_cli_ext/test_cmd_completions.py
git commit -m "feat(cli): add 'completions install/show/print-words' (argcomplete + bash/zsh)"
```

---

### Task 2: Project template (research only MVP)

**Files:** `src/templates/__init__.py` + `src/templates/bundled/research/` + `src/cli_ext/templates_cmd.py` + tests

```python
# src/templates/__init__.py
"""Project templates for `project init --template <name>`."""
```

```bash
# Create template files
mkdir -p src/templates/bundled/research/.llm-wiki/skills
```

```markdown
<!-- src/templates/bundled/research/purpose.md -->
# Purpose: Research Wiki

## Goals
- Build a structured knowledge base of academic papers, articles, and research notes
- Enable quick lookup of concepts, methods, and citations

## Key Questions
- What are the foundational concepts in [your field]?
- How do recent papers build on prior work?

## Research Scope
- [Define your field, time range, methodology preferences]

## Evolving Thesis
- [Update this as the wiki grows]
```

```markdown
<!-- src/templates/bundled/research/schema.md -->
# Wiki Schema Routing

## Page Types

| type | directory |
|------|-----------|
| source | wiki/sources |
| entity | wiki/entities |
| concept | wiki/concepts |
| synthesis | wiki/synthesis |

## Conventions
- All wiki pages MUST have frontmatter `id`, `title`, `type`, `sources`, `created_at`, `updated_at`.
- `id` is UUID v7 format (auto-generated if not provided)
- `sources[]` is relative paths to `raw/sources/<task_id>.<ext>`
- `grade: A | B | C` indicates source quality
- `processing_depth: concept | memory` controls depth
```

```markdown
<!-- src/templates/bundled/research/.llm-wiki/skills/literature-review/SKILL.md -->
---
name: literature-review
description: Helps synthesize literature reviews across multiple papers
required_tools: ["wiki.search", "web.search"]
---

You are a literature review assistant. When given a topic:
1. Search the wiki for related concepts
2. For each related concept, find primary sources
3. Synthesize findings into a coherent review with citations
```

```python
# src/templates/loader.py
"""Template loader (bundled + user custom)."""
from dataclasses import dataclass
from pathlib import Path

BUNDLED_DIR = Path(__file__).parent / "bundled"
USER_DIR = Path.home() / ".config" / "ruflo-kb" / "templates"


@dataclass
class Template:
    name: str
    files: dict[str, str]   # relative path → content


def load(name: str) -> Template:
    """Load template by name. Try bundled first, then user dir."""
    # Bundled
    bundled = BUNDLED_DIR / name
    if bundled.is_dir():
        files = {f.relative_to(bundled).as_posix(): f.read_text(encoding="utf-8")
                 for f in bundled.rglob("*") if f.is_file()}
        return Template(name=name, files=files)
    # User
    user = USER_DIR / name
    if user.is_dir():
        files = {f.relative_to(user).as_posix(): f.read_text(encoding="utf-8")
                 for f in user.rglob("*") if f.is_file()}
        return Template(name=name, files=files)
    raise FileNotFoundError(f"Template not found: {name}")


def list_bundled() -> list[str]:
    """List all bundled template names."""
    if not BUNDLED_DIR.exists():
        return []
    return sorted([d.name for d in BUNDLED_DIR.iterdir() if d.is_dir()])
```

```python
# src/cli_ext/templates_cmd.py
"""Templates CLI."""
import argparse
import shutil
import sys
from pathlib import Path

from ..project.context import ProjectContext, ProjectNotFoundError
from ..templates.loader import Template, load, list_bundled


def cmd_templates_list(args: argparse.Namespace) -> None:
    print("Bundled templates:")
    for t in list_bundled():
        print(f"  - {t}")


def cmd_templates_show(args: argparse.Namespace) -> None:
    try:
        t = load(args.name)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
    print(f"Template: {t.name}")
    print("Files:")
    for f in t.files:
        print(f"  - {f}")


def cmd_templates_apply(args: argparse.Namespace) -> None:
    """Apply template to project (after `project init`)."""
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
    try:
        t = load(args.name)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)
    for rel_path, content in t.files.items():
        dest = ctx.paths.root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    print(f"Applied template '{t.name}' to {ctx.paths.root}")
```

**Wire in cli.py**: 3 subcommands (templates list/show/apply). Add `--template <name>` flag to `project init`.

**Tests** (2): test_templates_list, test_templates_apply.

```bash
git add src/templates/ src/cli_ext/templates_cmd.py src/cli.py tests/test_cli_ext/test_cmd_templates.py
git commit -m "feat(cli): add 'templates list/show/apply' (1 bundled: research)"
```

---

## Self-Review

- [x] bash + zsh completion (fish deferred) ✓
- [x] 1 template (research) ✓
- [x] Optional argcomplete dep ✓
- [x] No placeholders
- [x] novels + business templates + fish completion deferred to v2.0.1

## Implementation order

Tasks 1-2 chain. Total: 2 tasks, ~1-1.5 hours.