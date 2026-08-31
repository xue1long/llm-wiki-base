"""Write + read wiki pages as markdown with V4 YAML frontmatter.

V4 schema (per ADR-002, novel-wiki-fields-template-2026-08-31.md):
    8 keys only — id, title, type, relations, tags, sources,
                   created_at, updated_at

The on-disk contract between WikiPage and the frontmatter is the 8 V4 keys.
All other fields (grade/processing_depth/heat/workflow_state/_ko_extra/
decision_record/evidence_refs/valid_from/valid_to/custom_type/category/
taxonomy_sub/...) live on the in-memory WikiPage dataclass for code that
needs them, but are NOT written to disk and NOT validated on read.
"""
from pathlib import Path

import yaml

from ...lib.write_hooks import safe_write
from ..core.paths import WikiPaths
from ..core.types import PageType, WikiPage
from ..features.tag_namespace import validate_tag_compliance


_TYPE_TO_DIR: dict[PageType, str] = {
    PageType.SOURCE: "wiki_sources",
    PageType.ENTITY: "wiki_entities",
    PageType.CONCEPT: "wiki_concepts",
    PageType.SYNTHESIS: "wiki_synthesis",
}


class PageNotFoundError(Exception):
    pass


def page_path_for(paths: WikiPaths, type_: PageType, slug: str) -> Path:
    """Return canonical path for (type, slug) using V4 type system.

    V4 has only source/entity/concept/synthesis — no claim/decision/
    procedure/event and no custom_type routing. Stubs use
    ``page_path_for_stub`` instead.
    """
    if type_ not in _TYPE_TO_DIR:
        raise ValueError(
            f"V4: type {type_!r} not in {sorted(_TYPE_TO_DIR.keys())}; "
            "use page_path_for_stub for stubs"
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

    V4 contract: only the 8 V4 keys are written to frontmatter. The
    ``slug`` is NOT injected — V4 derives it from the file path at read
    time. No custom_type / schema_registry / taxonomy_registry checks —
    V4 has none.

    *expected_content_hash* (optional): sha256 of the current on-disk
    content captured at generate time. When provided and the file exists,
    a mismatch raises :class:`WriteConflictError` instead of silently
    overwriting a manual edit / concurrent write (plan Task 0.3).
    """
    # V4: stub pages go to _stubs/ (preserves P7 stub-detection semantics
    # without requiring processing_depth to be serialized).
    if getattr(page, "processing_depth", "") == "stub":
        path = page_path_for_stub(paths, page.id)
    else:
        path = page_path_for(paths, page.type, page.id)
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
        _snapshot_raw(paths, page.id, path)
    else:
        validate_tag_compliance(page.tags)

    from ..features.gbrain_compat import (
        build_target_slugs, materialize_relations, rewrite_wikilinks,
    )
    target_slugs = build_target_slugs(paths, [(page.id, path)])
    page.body = materialize_relations(
        rewrite_wikilinks(page.body, target_slugs), page.relations, target_slugs,
    )
    # V4: WikiPage.to_frontmatter_dict() returns the strict 8-key whitelist.
    # We do NOT inject `slug` — V4 derives it from the file path at read time.
    fm_text = yaml.dump(
        page.to_frontmatter_dict(),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    content = f"---\n{fm_text}---\n\n{page.body}"
    safe_write(path, content)


def read_page(path: Path) -> WikiPage:
    """Parse markdown file → WikiPage. Raises PageNotFoundError if missing.

    V4 read: tolerates legacy fields in the frontmatter (grade/_ko_extra/...)
    so that pages written by older pipeline versions remain accessible.
    Legacy fields populate the in-memory WikiPage dataclass attributes but
    are never re-written to disk by ``write_page``.
    """
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