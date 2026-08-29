"""Write + read wiki pages as markdown with YAML frontmatter."""
from pathlib import Path

import yaml

from ...lib.write_hooks import safe_write
from ..core.paths import WikiPaths
from ..core.types import PageType, WikiPage
from ..features.tag_namespace import validate_tag_compliance
from ..schema_registry import SchemaRegistry
from ..taxonomy_registry import TaxonomyRegistry


_TYPE_TO_DIR: dict[PageType, str] = {
    PageType.SOURCE: "wiki_sources",
    PageType.ENTITY: "wiki_entities",
    PageType.CONCEPT: "wiki_concepts",
    PageType.SYNTHESIS: "wiki_synthesis",
    PageType.CLAIM: "wiki_claims",
    PageType.DECISION: "wiki_decisions",
    PageType.PROCEDURE: "wiki_concepts",
    PageType.EVENT: "wiki_concepts",
}


class PageNotFoundError(Exception):
    pass


def page_path_for(
    paths: WikiPaths, type_: PageType, slug: str,
    registry: SchemaRegistry | None = None,
    custom_type: str = "",
) -> Path:
    """Return canonical path for (type, slug).

    When *registry* is given and *custom_type* names a schema-declared type,
    the path goes to ``wiki/<custom_dir>/<slug>.md`` instead of the base
    type's directory.
    """
    if registry is not None:
        cdir = registry.get_directory(custom_type or type_.value)
        if cdir:
            return paths.get_custom_dir(cdir) / f"{slug}.md"
    if type_ not in _TYPE_TO_DIR:
        raise ValueError(
            f"Stub pages should use page_path_for_stub instead of {type_}"
        )
    dir_prop = _TYPE_TO_DIR[type_]
    return getattr(paths, dir_prop) / f"{slug}.md"


def page_path_for_stub(paths: WikiPaths, slug: str) -> Path:
    return paths.wiki_stubs / f"{slug}.md"


def _snapshot_raw(paths: WikiPaths, page_id: str, file_path: Path) -> None:
    """Save raw markdown content before overwrite, with retention (max 10)."""
    import json
    import time
    import uuid

    raw = file_path.read_text(encoding="utf-8")
    version_dir = paths.index / "page_versions" / page_id
    version_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    version_path = version_dir / f"{ts}_{uid}.json"
    safe_write(
        version_path,
        json.dumps({"content": raw, "saved_at_ms": ts}, ensure_ascii=False),
    )
    files = sorted(version_dir.glob("*.json"))
    for f in files[:-10]:
        f.unlink()


class WriteConflictError(Exception):
    """Overwrite refused: the on-disk content changed since the write was
    planned (manual edit / concurrent writer). Task 0.3 TOCTOU guard."""


def write_page(paths: WikiPaths, page: WikiPage,
               expected_content_hash: str | None = None) -> None:
    """Write page to disk via safe_write (respects AtomicContext).

    *expected_content_hash* (optional): sha256 of the current on-disk
    content captured at generate time. When provided and the file exists,
    a mismatch raises :class:`WriteConflictError` instead of silently
    overwriting a manual edit / concurrent write (plan Task 0.3).
    """
    import logging
    import os

    custom_type = getattr(page, "custom_type", "") or ""
    taxonomy_errors = TaxonomyRegistry.from_project(paths.root).validate(
        page.category, page.taxonomy_sub
    )
    if taxonomy_errors:
        message = "taxonomy validation failed: " + "; ".join(taxonomy_errors)
        from src.config import settings
        if settings().taxonomy_validation == "strict":
            raise ValueError(message)
        logging.getLogger(__name__).warning(message)
    registry = None
    if custom_type:
        registry = SchemaRegistry.from_project(paths.root)
        if not registry.is_custom(custom_type):
            raise ValueError(
                f"Custom page type {custom_type!r} is not declared in schema.md"
            )
    path = page_path_for(paths, page.type, page.id, registry, custom_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if expected_content_hash is not None:
            import hashlib
            cur = hashlib.sha256(path.read_bytes()).hexdigest()
            if cur != expected_content_hash:
                raise WriteConflictError(
                    f"refusing to overwrite {page.id}: on-disk content "
                    f"changed since generate (TOCTOU); expected "
                    f"{expected_content_hash[:8]}… got {cur[:8]}…"
                )
        # Phase 1.7 (F8): never silently overwrite an immutable page —
        # the pipeline re-ingest guard relies on this (ingest commit skips
        # immutable targets); a direct write must fail loudly too.
        try:
            existing = read_page(path)
            if getattr(existing, "is_immutable", False):
                raise ValueError(
                    f"Refusing to overwrite immutable page: {page.id} "
                    f"(set is_immutable=false to edit)"
                )
        except PageNotFoundError:
            pass
        _snapshot_raw(paths, page.id, path)
    else:
        validate_tag_compliance(page.tags)
    from ..features.gbrain_compat import (
        build_target_slugs, gbrain_slug_for_path, materialize_relations,
        rewrite_wikilinks,
    )
    target_slugs = build_target_slugs(paths, [(page.id, path)])
    page.body = materialize_relations(
        rewrite_wikilinks(page.body, target_slugs), page.relations, target_slugs,
    )
    fm = page.to_frontmatter_dict()
    fm["slug"] = gbrain_slug_for_path(paths, path)
    fm_text = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    content = f"---\n{fm_text}---\n\n{page.body}"
    safe_write(path, content)


def read_page(path: Path) -> WikiPage:
    """Parse markdown file → WikiPage. Raises PageNotFoundError if missing."""
    if not path.exists():
        raise PageNotFoundError(f"Page not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return WikiPage(id=path.stem, title=path.stem, type=PageType.SOURCE, body=text)
    end = text.find("\n---", 4)
    if end < 0:
        return WikiPage(id=path.stem, title=path.stem, type=PageType.SOURCE, body=text)
    fm_text = text[4:end]
    body = text[end + 5:].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    return WikiPage.from_dict(fm, body=body)
