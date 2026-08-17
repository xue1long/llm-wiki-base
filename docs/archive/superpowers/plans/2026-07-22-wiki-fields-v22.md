# Wiki Fields v2.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Add 4 v2.2 fields to WikiPage: `id` (UUID v7), `grade` (A/B/C), `processing_depth` (concept/memory), `is_immutable`. Tag namespace validation. Migration v2.0→v2.2.

**Tech Stack:** Python 3.11+, dataclass, regex, Migration framework (from Schemas v3 plan).

**MVP Scope** (per spec): 4 fields + tag namespace (8 prefixes) + migration + CLI `fields validate / tags validate`.

---

### Task 1: Extend WikiPage + ID generator

**Files:** `src/wiki/id_generator.py` + tests + modify `src/wiki/types.py`

```python
# src/wiki/id_generator.py
"""UUID v7 + slug page ID generator."""
import re
import secrets
import time


def generate_page_id(slug: str) -> str:
    """26-char: card_<13hex_millis>_<8hex_random>_<slug>"""
    millis = int(time.time() * 1000) & 0xFFFFFFFFFFFFF  # 13 hex
    rand = secrets.token_hex(4)                         # 8 hex
    return f"card_{millis:013x}_{rand}_{slug}"


ID_PATTERN = re.compile(r"^card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-]+$")


def is_valid_id(s: str) -> bool:
    return bool(ID_PATTERN.match(s))
```

**Modify `src/wiki/types.py`**: extend `WikiPage`:

```python
@dataclass
class WikiPage:
    id: str
    title: str
    type: PageType
    sources: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    body: str = ""
    # NEW v2.2 fields (MVP subset)
    grade: str = "B"                       # "A" | "B" | "C"
    processing_depth: str = "concept"      # "concept" | "memory"
    is_immutable: bool = False

    def to_frontmatter_dict(self) -> dict:
        d = super().to_frontmatter_dict() if hasattr(super(), "to_frontmatter_dict") else {
            "id": self.id, "title": self.title, "type": self.type.value,
            "sources": self.sources, "created_at": self.created_at, "updated_at": self.updated_at,
        }
        d["grade"] = self.grade
        d["processing_depth"] = self.processing_depth
        d["is_immutable"] = self.is_immutable
        return d
```

**Tests** (3): test_generate_id_format, test_is_valid_id, test_wiki_page_v22_fields.

```bash
git add src/wiki/id_generator.py src/wiki/types.py tests/test_wiki/test_id_generator.py
git commit -m "feat(wiki): add UUID v7 page IDs + 4 v2.2 fields (grade/depth/is_immutable)"
```

---

### Task 2: TagNamespace validator

**Files:** `src/wiki/tag_namespace.py` + tests

```python
# src/wiki/tag_namespace.py
"""Validate wiki page tags use controlled namespace prefixes."""
from typing import Iterable


TAG_PREFIXES = {
    "genre": "题材类型",
    "func": "功能类型",
    "char": "角色类型",
    "event": "事件类型",
    "mood": "情绪氛围",
    "entity": "是什么 (What)",
    "scene_phase": "何时用 (When)",
    "status": "生命周期",
}


def is_valid(tag: str) -> bool:
    """True if tag uses one of 8 controlled prefixes."""
    return any(tag.startswith(prefix + "/") for prefix in TAG_PREFIXES)


def parse(tag: str) -> tuple[str, str] | None:
    """Returns (prefix, name) or None if invalid."""
    if "/" not in tag:
        return None
    prefix, _, name = tag.partition("/")
    if prefix in TAG_PREFIXES:
        return prefix, name
    return None


def validate_tags(tags: Iterable[str]) -> list[str]:
    """Return list of invalid tags (must be empty)."""
    return [t for t in tags if not is_valid(t)]
```

**Tests** (3): test_valid, test_invalid, test_parse.

```bash
git add src/wiki/tag_namespace.py tests/test_wiki/test_tag_namespace.py
git commit -m "feat(wiki): add TagNamespace validator (8 prefixes)"
```

---

### Task 3: CLI subcommands

**Files:** `src/cli_ext/fields_cmd.py` + tests + wire in cli.py

```python
# src/cli_ext/fields_cmd.py
"""Wiki field/tag validation CLI."""
import argparse
import sys
import yaml
from pathlib import Path

from ..wiki.id_generator import ID_PATTERN, is_valid_id
from ..wiki.page_writer import read_page
from ..wiki.tag_namespace import validate_tags, is_valid
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_fields_validate(args: argparse.Namespace) -> None:
    """Validate frontmatter of one page (L0-L3)."""
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)

    path = Path(args.path)
    if not path.is_absolute():
        path = ctx.paths.root / path
    if not path.exists():
        print(f"Page not found: {path}", file=sys.stderr); sys.exit(2)

    page = read_page(path)
    errors = []
    # L0: id, title, type, sources
    if not page.id: errors.append("L0: missing id")
    if not page.title.strip(): errors.append("L0: missing title")
    if not page.sources: errors.append("L0: missing sources")
    # L1 (v2.2): grade, processing_depth
    if page.grade not in ("A", "B", "C"): errors.append(f"L1: invalid grade: {page.grade}")
    if page.processing_depth not in ("concept", "memory"): errors.append(f"L1: invalid processing_depth: {page.processing_depth}")
    # L4: id format
    if page.id and not is_valid_id(page.id):
        errors.append(f"WARN: id '{page.id}' does not match UUID v7 format (backwards compat)")

    if errors:
        for e in errors: print(f"  {e}")
        print("FAIL")
        sys.exit(1)
    print("OK")


def cmd_tags_validate(args: argparse.Namespace) -> None:
    """Validate tags of one page (or all pages if --all)."""
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)

    pages = []
    if args.all:
        for sub in [ctx.paths.wiki_sources, ctx.paths.wiki_entities, ctx.paths.wiki_concepts, ctx.paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                pages.append(read_page(f))
    else:
        path = Path(args.page_path)
        if not path.is_absolute():
            path = ctx.paths.root / path
        pages.append(read_page(path))

    all_invalid: list[tuple[str, list[str]]] = []
    for p in pages:
        invalid = validate_tags(getattr(p, "tags", []) or [])
        if invalid:
            all_invalid.append((p.id, invalid))
    if all_invalid:
        for pid, inv in all_invalid:
            print(f"  {pid}: {inv}")
        sys.exit(1)
    print("OK")
```

**Wire in cli.py**:
```python
p_fields = subparsers.add_parser("fields", help="Validate wiki fields")
p_fields_sub = p_fields.add_subparsers(dest="fields_command")
p_fvalidate = p_fields_sub.add_parser("validate")
p_fvalidate.add_argument("path")
p_fvalidate.add_argument("--project")
p_fvalidate.set_defaults(func=cmd_fields_validate)

p_tags = subparsers.add_parser("tags", help="Validate tags")
p_tags_sub = p_tags.add_subparsers(dest="tags_command")
p_tvalidate = p_tags_sub.add_parser("validate")
p_tvalidate.add_argument("page_path", nargs="?")
p_tvalidate.add_argument("--all", action="store_true")
p_tvalidate.add_argument("--project")
p_tvalidate.set_defaults(func=cmd_tags_validate)
```

**Tests** (3): test_fields_validate_ok, test_fields_validate_missing_id, test_tags_validate_invalid.

```bash
git add src/cli_ext/fields_cmd.py src/cli.py tests/test_cli_ext/test_cmd_fields.py
git commit -m "feat(cli): add 'fields validate' + 'tags validate' (L0-L1 + namespace)"
```

---

### Task 4: v2.0 → v2.2 migration

**Files:** `src/schemas/migrations/v2_to_v2_2.py` + tests

```python
# src/schemas/migrations/v2_to_v2_2.py
"""v2.0 → v2.2: Add grade/processing_depth/is_immutable + convert slug IDs to UUID v7."""
import json
import re
import secrets
import time

from ..migration import Migration, MigrationContext, MigrationPlan, MigrationResult, SchemaVersion
from ..registry import MigrationRegistry
from ....wiki.id_generator import generate_page_id, ID_PATTERN


SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class V2ToV2_2WikiPageMigration(Migration):
    schema_name = "wiki_page"
    from_version = SchemaVersion.V2_0
    to_version = SchemaVersion.V2_1   # Reuse V2.1 (which is now V2.2 in spirit)

    def preview(self, ctx):
        files = list(ctx.project_path.glob("wiki/**/*.md"))
        return MigrationPlan(
            from_version=self.from_version, to_version=self.to_version,
            steps=[f"Convert {len(files)} slug IDs to UUID v7",
                   f"Add grade/processing_depth/is_immutable to {len(files)} pages"],
            affected_files=files, reversible=True,
        )

    def up(self, ctx):
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        for f in ctx.project_path.glob("wiki/**/*.md"):
            text = f.read_text(encoding="utf-8")
            if "schema_version: v2.2" in text:
                continue
            # Add fields if missing
            new_text = self._add_v22_fields(text)
            # Convert slug ID to UUID v7
            new_text = self._convert_id_to_uuid_v7(new_text)
            if new_text != text:
                f.write_text(new_text, encoding="utf-8")
                result.files_changed += 1

        # Update project.json
        pj = ctx.project_path / ".llm-wiki" / "project.json"
        if pj.exists():
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["schema_version"] = "v2.2"
            pj.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return result

    def down(self, ctx):
        self._require_backup(ctx)
        result = MigrationResult(success=True)
        for f in ctx.project_path.glob("wiki/**/*.md"):
            text = f.read_text(encoding="utf-8")
            if "schema_version: v2.2" in text:
                # Remove v2.2 fields
                text = re.sub(r"\n?grade: [ABC]\n", "\n", text)
                text = re.sub(r"\n?processing_depth: (concept|memory)\n", "\n", text)
                text = re.sub(r"\n?is_immutable: (true|false)\n", "\n", text)
                text = text.replace("schema_version: v2.2", "schema_version: v2.0")
                f.write_text(text, encoding="utf-8")
                result.files_changed += 1
        return result

    def _add_v22_fields(self, text: str) -> str:
        """Add grade/processing_depth/is_immutable if missing."""
        if "grade:" not in text:
            text = text.replace("schema_version: v2.0", "schema_version: v2.0\ngrade: B", 1)
        if "processing_depth:" not in text:
            text = text.replace("schema_version: v2.0", "schema_version: v2.0\nprocessing_depth: concept", 1)
        if "is_immutable:" not in text:
            text = text.replace("schema_version: v2.0", "schema_version: v2.0\nis_immutable: false", 1)
        return text

    def _convert_id_to_uuid_v7(self, text: str) -> str:
        """Convert 'id: foo' (slug) to 'id: card_<millis>_<rand>_foo'."""
        m = re.search(r"^id: ([a-z0-9-]+)$", text, re.MULTILINE)
        if m and not ID_PATTERN.match(m.group(1)):
            slug = m.group(1)
            new_id = generate_page_id(slug)
            text = text.replace(f"id: {slug}", f"id: {new_id}", 1)
        return text


MigrationRegistry.register("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, V2ToV2_2WikiPageMigration())
```

**Tests** (3): test_up_adds_v22_fields, test_up_converts_id_to_uuid, test_down_reverts.

```bash
git add src/schemas/migrations/v2_to_v2_2.py tests/test_schemas/test_v2_to_v2_2.py
git commit -m "feat(schemas): add v2.0→v2.2 migration (UUID v7 IDs + 4 new fields)"
```

---

## Self-Review

- [x] 4 fields: id (UUID v7) / grade / processing_depth / is_immutable ✓
- [x] Tag namespace validator (8 prefixes) ✓
- [x] v2.0→v2.2 migration ✓
- [x] CLI ✓
- [x] Remaining 4 fields (use_context / maturity / workflow_state) deferred to v2.1

## Implementation order

Tasks 1-4 chain. Total: 4 tasks, ~1.5-2 hours.