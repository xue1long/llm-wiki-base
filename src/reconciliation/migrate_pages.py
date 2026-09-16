"""Migration tool: legacy page -> canonical_id binding (Task 51).

Reads existing wiki/concepts/*.md, identifies pages without
``canonical_id`` in their YAML frontmatter, and proposes a binding
via simple heuristics (alias match, preferred_label substring). The
default mode is **dry-run only** — page frontmatter is read but never
written unless the caller explicitly passes ``dry_run=False``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.reconciliation.canonical_registry import CanonicalRegistry


log = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    scanned_pages: int
    already_migrated: int
    would_migrate: list[tuple[str, str]] = field(default_factory=list)
    unmigrated: list[str] = field(default_factory=list)
    dry_run: bool = True
    applied: bool = False
    errors: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> dict[str, Any] | None:
    """Parse YAML frontmatter between first pair of --- fences. None on failure."""
    if not text.startswith("---"):
        return None
    try:
        _, fm_block, _ = text.split("---", 2)
    except ValueError:
        return None
    try:
        return yaml.safe_load(fm_block) or {}
    except yaml.YAMLError:
        return None


def _suggest_canonical(
    page_id: str,
    page_title: str,
    registry: CanonicalRegistry,
) -> str | None:
    """Simple heuristic: alias match first, then preferred_label substring."""
    # 1. Alias match: treat page_id as alias.
    hit = registry.get_by_alias(page_id)
    if hit is not None:
        return hit.canonical_id
    # 2. Alias match: treat page_title as alias.
    if page_title:
        hit = registry.get_by_alias(page_title)
        if hit is not None:
            return hit.canonical_id
    # 3. preferred_label substring match (case-insensitive).
    if page_title:
        title_lower = page_title.strip().lower()
        if title_lower:
            for canonical_id, concept in registry.load_concepts().items():
                label = (concept.preferred_label or "").strip().lower()
                if label and (label in title_lower or title_lower in label):
                    return canonical_id
    return None


def _atomic_write_text(path: Path, content: str) -> None:
    """tmp + rename write."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _rewrite_frontmatter_with_canonical(
    path: Path, original_text: str, canonical_id: str
) -> bool:
    """Add canonical_id to the page's frontmatter and rewrite the file.

    Returns True if the file was rewritten, False on parse failure.
    """
    if not original_text.startswith("---"):
        return False
    try:
        head, fm_block, body = original_text.split("---", 2)
    except ValueError:
        return False
    try:
        frontmatter = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(frontmatter, dict):
        return False
    frontmatter["canonical_id"] = canonical_id
    # Re-emit frontmatter. Use sort_keys=False to preserve insertion order
    # so other fields' order matches what was already on disk.
    new_fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
    new_text = f"---{new_fm}---{body}"
    try:
        _atomic_write_text(path, new_text)
    except OSError as e:
        log.warning("migrate_pages: rewrite failed for %s: %s", path, e)
        return False
    return True


def analyze_unmigrated_pages(
    project_root: Path | str,
    *,
    registry: CanonicalRegistry | None = None,
) -> MigrationReport:
    """Read all wiki/concepts/*.md and produce a MigrationReport.

    registry is created from project_root if not provided (handy for tests).
    """
    root = Path(project_root)
    pages_dir = root / "wiki" / "concepts"
    reg = registry or CanonicalRegistry(root)

    scanned = 0
    already = 0
    would: list[tuple[str, str]] = []
    unmigrated: list[str] = []

    if not pages_dir.exists():
        return MigrationReport(
            scanned_pages=0, already_migrated=0,
            dry_run=True, applied=False,
        )

    for path in sorted(pages_dir.glob("*.md")):
        scanned += 1
        page_id = path.stem
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            unmigrated.append(page_id)
            continue
        frontmatter = _parse_frontmatter(text)
        if frontmatter is None:
            unmigrated.append(page_id)
            continue
        if "canonical_id" in frontmatter:
            already += 1
            continue
        # Has no canonical_id — try to suggest one.
        title = str(frontmatter.get("title", "") or "")
        suggestion = _suggest_canonical(page_id, title, reg)
        if suggestion:
            would.append((page_id, suggestion))
        else:
            unmigrated.append(page_id)

    return MigrationReport(
        scanned_pages=scanned,
        already_migrated=already,
        would_migrate=would,
        unmigrated=unmigrated,
        dry_run=True,
        applied=False,
    )


def migrate_pages(
    project_root: Path | str,
    *,
    dry_run: bool = True,
    registry: CanonicalRegistry | None = None,
) -> MigrationReport:
    """Analyze + (if not dry_run) write canonical_id back into frontmatter.

    Default is dry_run=True; no files are modified. Pass ``dry_run=False``
    to actually rewrite page files.
    """
    report = analyze_unmigrated_pages(project_root, registry=registry)

    if dry_run:
        return MigrationReport(
            scanned_pages=report.scanned_pages,
            already_migrated=report.already_migrated,
            would_migrate=report.would_migrate,
            unmigrated=report.unmigrated,
            dry_run=True,
            applied=False,
        )

    root = Path(project_root)
    pages_dir = root / "wiki" / "concepts"
    applied_count = 0
    for page_id, canonical_id in report.would_migrate:
        path = pages_dir / f"{page_id}.md"
        if not path.exists():
            report.errors.append(f"page vanished: {page_id}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            report.errors.append(f"read failed for {page_id}: {e}")
            continue
        if _rewrite_frontmatter_with_canonical(path, text, canonical_id):
            applied_count += 1
        else:
            report.errors.append(f"rewrite failed for {page_id}")

    return MigrationReport(
        scanned_pages=report.scanned_pages,
        already_migrated=report.already_migrated,
        would_migrate=report.would_migrate,
        unmigrated=report.unmigrated,
        dry_run=False,
        applied=True,
        errors=report.errors,
    )


__all__ = [
    "MigrationReport",
    "analyze_unmigrated_pages",
    "migrate_pages",
]