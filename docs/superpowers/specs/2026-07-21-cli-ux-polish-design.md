# CLI/UX Polish Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ b395c52, post-Quality-Gate-v2.1 spec)

## Goal

Two small UX improvements:

1. **Shell completion** — Tab-completion for bash/zsh/fish via `argcomplete`. All subcommands covered. Project names auto-completed from registry. `--project <id>` argument auto-suggests known project names.

2. **Project templates** — Built-in starter templates for `project init --template <name>`: `research`, `novels`, `business`. Each template seeds `purpose.md`, `schema.md`, and optionally `.llm-wiki/skills/` with template-specific content.

## Non-goals

- No PowerShell completion (deferred).
- No remote template marketplace (deferred).
- No template versioning (each template is current version).
- No user-contributed templates in this spec (deferred).

## Architecture

### Shell completion flow

```
User types: ruflo-kb <TAB>
   │
   ▼
argcomplete's _ARGCOMPLETE=1 bash function:
   1. Detects shell (bash/zsh/fish)
   2. Calls `ruflo-kb` with --_ARGCOMPLETE env var
   3. argparse + argcomplete scan registered completers
   4. Print completions to stdout

User types: ruflo-kb project <TAB>
   │
   ▼
argcomplete + custom completer:
   - list subcommands: list/info/select/init/import/forget/rename/discover
   - for 'select <id|name>': read registry, list all known projects
   - for 'forget <id|name>': same as select
   - for 'init <path>': filesystem path completer (argcomplete built-in)

User types: ruflo-kb --project <TAB>
   │
   ▼
Custom completer reads registry, lists all known project IDs + names
```

### Project templates flow

```
python -m src.cli project init <path> --template research
   │
   ▼
ProjectContext.from_path(path, name, template="research")
   │
   ▼
1. ensure_project_id() — generate UUID
2. write .llm-wiki/project.json
3. write .llm-wiki/settings.json
4. TEMPLATE LOADER:
   - copy templates/research/purpose.md → <path>/purpose.md
   - copy templates/research/schema.md → <path>/schema.md
   - copy templates/research/skills/* → <path>/.llm-wiki/skills/
5. Create knowledge base directory structure (Inbox + wiki + .index + Templates)
6. Register project in global registry
```

## Components

### New modules

```
src/cli/completions.py        # argcomplete completer registration + generation
src/templates/__init__.py
src/templates/loader.py       # TemplateLoader (bundled + user custom)
src/templates/bundled/
├── __init__.py
├── research/
│   ├── purpose.md
│   ├── schema.md
│   └── skills/
│       └── literature-review/
│           └── SKILL.md
├── novels/
│   ├── purpose.md
│   ├── schema.md
│   └── skills/
│       └── character-tracker/
│           └── SKILL.md
└── business/
    ├── purpose.md
    ├── schema.md
    └── skills/
        └── market-analysis/
            └── SKILL.md

tests/test_cli/test_completions.py
tests/test_templates/test_loader.py
```

### Modified modules

| Path | Change |
|---|---|
| `pyproject.toml` | Add `argcomplete>=3.0` (optional via `pip install ruflo-kb[completion]`) |
| `src/cli.py` | `argcomplete.autocomplete()` call at top of `main()`; conditional registration if installed |
| `src/cli_ext/project_cmd.py` | `cmd_project_init --template <name>` accepts template flag |
| `src/cli.py` | New `completions` subcommand: `ruflo-kb completions install bash` writes completion script to `~/.config/ruflo-kb/completions/ruflo-kb.bash` |

## Data structures

```python
# src/templates/loader.py
@dataclass
class Template:
    name: str                              # "research" | "novels" | "business"
    description: str
    files: dict[str, str]                  # {"purpose.md": "...", "schema.md": "...", ".llm-wiki/skills/foo/SKILL.md": "..."}
    
    @classmethod
    def load_bundled(cls, name: str) -> "Template":
        """Load from src/templates/bundled/<name>/."""
        ...
    
    @classmethod
    def list_bundled(cls) -> list[str]:
        """List all bundled template names."""
        ...
    
    @classmethod
    def from_user_dir(cls, path: Path) -> "Template":
        """Load user-defined template from ~/.config/ruflo-kb/templates/<name>/."""
        ...

class TemplateLoader:
    BUNDLED_DIR = "<ruflo_kb>/templates/bundled/"
    USER_DIR = "~/.config/ruflo-kb/templates/"
    
    @staticmethod
    def load(name: str) -> Template:
        """Try bundled first, then user dir."""
        ...
    
    @staticmethod
    def list_all() -> list[str]:
        """Bundled + user templates (dedup, user overrides bundled)."""
        ...
```

## CLI surface

```
python -m src.cli project init <path> --template research|novels|business
    # Uses template to seed purpose.md, schema.md, skills

python -m src.cli project init <path>
    # Default: no template (empty purpose.md + minimal schema.md)

python -m src.cli templates list
    # Show bundled + user templates

python -m src.cli templates show <name>
    # Display purpose.md + schema.md + skills for template

python -m src.cli templates add <name> --from <path>
    # Copy template from local path to ~/.config/ruflo-kb/templates/<name>/

python -m src.cli templates remove <name>
    # Remove user template (refuses if name is bundled)

python -m src.cli completions install bash|zsh|fish
    # Write completion script to ~/.config/ruflo-kb/completions/ruflo-kb.<shell>
    # Print instructions to add source line to shell rc

python -m src.cli completions show bash|zsh|fish
    # Print completion script to stdout (user manually eval)
```

## Built-in templates

### research template

```markdown
<!-- purpose.md -->
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
<!-- schema.md -->
<!-- Standard wiki schema -->
```

```markdown
<!-- .llm-wiki/skills/literature-review/SKILL.md -->
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

### novels template

```markdown
<!-- purpose.md -->
# Purpose: Novel Wiki

## Goals
- Track characters, plot threads, settings, and world-building elements
- Maintain continuity across chapters and drafts
- Build a queryable reference for self-editing

## Key Questions
- What are each character's motivations and arcs?
- How does setting influence plot?

## Research Scope
- [Your novel genre, themes, target audience]
```

```markdown
<!-- .llm-wiki/skills/character-tracker/SKILL.md -->
---
name: character-tracker
description: Tracks character details, relationships, and arcs
required_tools: ["wiki.search", "wiki.read_page"]
---

You help maintain character consistency. When asked about a character:
1. Search wiki/entities for character pages
2. List relationships from frontmatter sources[]
3. Summarize current arc
```

### business template

```markdown
<!-- purpose.md -->
# Purpose: Business Wiki

## Goals
- Track competitive intelligence, customer research, market trends
- Build institutional knowledge across the team
- Enable quick reference for sales, product, strategy decisions

## Key Questions
- Who are our top competitors?
- What are current customer pain points?
- What trends are reshaping the market?

## Research Scope
- [Industry, geography, time range]
```

```markdown
<!-- .llm-wiki/skills/market-analysis/SKILL.md -->
---
name: market-analysis
description: Helps synthesize market analysis from research and notes
required_tools: ["wiki.search", "web.search", "deep_research.run"]
---

You help build market analyses. When given a topic:
1. Search wiki for internal notes
2. Optionally run deep_research for external context
3. Synthesize with citation to sources
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Completion install | Shell not detected | Print supported shells + manual setup instructions |
| Completion install | Write fails (no permission) | Print script to stdout as fallback |
| argcomplete not installed | `import argcomplete` fails | Skip completion; print warning once: "Install argcomplete for shell completion: pip install ruflo-kb[completion]" |
| Template load | Template name not found | Error + list available templates |
| Template load | Bundled template file missing | Error + check installation |
| Template load | User template path doesn't exist | Error |
| Template files | Permission denied on write | Rollback partial template copy |
| `templates add` | Source path not a directory | Error |
| `templates remove` | Name is bundled (can't delete) | Error + suggest `templates show` to inspect |
| Tab completion: project name | Project ID not in registry | Don't suggest |

## Backwards compatibility

- `project init <path>` (without `--template`): unchanged behavior (empty purpose.md).
- `argcomplete` is optional dependency; existing CLI works without it.
- Templates are purely additive.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/cli/completions.py` | argcomplete registration; project name completion from registry |
| `src/templates/loader.py` | Bundled template load; user dir override; missing template error |

### Integration tests

```
tests/test_integration/test_template_init.py:
    def test_init_with_research_template():
        # Run `project init /tmp/test --template research`
        # Verify: purpose.md, schema.md, .llm-wiki/skills/literature-review/SKILL.md exist

    def test_init_default_template():
        # Run `project init /tmp/test` (no template)
        # Verify: empty purpose.md exists, no skills

    def test_template_list_includes_bundled_and_user():
        # Add user template to ~/.config/ruflo-kb/templates/foo/
        # Run templates list
        # Verify: both bundled + user listed

tests/test_integration/test_completions.py:
    def test_completion_bash_script_generated():
        # Run `completions show bash`
        # Verify: valid bash completion script on stdout
```

## Implementation order

2 phases:

1. **Templates** — `src/templates/` + 3 bundled templates + `cmd_project_init --template` + tests
2. **Completions** — `argcomplete` integration + `cmd_completions` + tests

## Cost estimation

Total: ~500 lines new code + ~200 lines tests.
- Templates: ~400 lines (3 templates × ~100 lines content + 100 lines loader)
- Completions: ~100 lines

Operational: argcomplete optional; templates bundled (no download needed).

## Open questions / deferred

- PowerShell completion.
- Remote template marketplace / Git-based templates.
- Template inheritance (templates that extend other templates).
- Per-template custom commands or hooks.
- User-defined template validation (schema enforcement).
- Completion caching for project lists (currently re-reads registry on each TAB).