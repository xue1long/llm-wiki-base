"""Fail-closed, deterministic reader for the Wiki-to-Book input snapshot."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from .model import ContentBlock, PageRecord, WikiSnapshot

_ELIGIBLE = {"concepts": "concept", "entities": "entity", "synthesis": "synthesis"}
_EXCLUDED = ("sources", "_stubs", "_archive")
_SKIP_DIRS = {"media"}
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


class WikiScanError(ValueError):
    """A page or the input inventory is unsafe to compile."""

    def __init__(self, message: str, *, code: str = "scan-invalid", path: Path | None = None):
        self.code = code
        self.path = path
        super().__init__(message)


class SnapshotChangedError(WikiScanError):
    def __init__(self, message: str):
        super().__init__(message, code="scan-changed")


class _StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root)
        return True
    except ValueError:
        return False


def _inventory(root: Path) -> list[tuple[Path, str]]:
    if not root.exists() or not root.is_dir():
        raise WikiScanError(f"wiki root does not exist: {root}", code="wiki-root-missing", path=root)
    root = root.resolve()
    found: list[tuple[Path, str]] = []
    for dirname, kind in (*_ELIGIBLE.items(), *[(name, "excluded") for name in _EXCLUDED]):
        base = root / dirname
        if not base.exists():
            continue
        if not _inside(base, root):
            raise WikiScanError(f"symlink escapes wiki root: {base}", code="symlink-escape", path=base)
        pending = [base]
        while pending:
            current = pending.pop()
            try:
                children = sorted(current.iterdir(), key=lambda p: p.name)
            except OSError as exc:
                raise WikiScanError(f"cannot read directory: {current}: {exc}", code="inventory-error", path=current) from exc
            for child in children:
                if child.name.startswith("."):
                    continue
                if child.is_symlink() and not _inside(child, root):
                    raise WikiScanError(f"symlink escapes wiki root: {child}", code="symlink-escape", path=child)
                if child.is_dir():
                    if child.name in _SKIP_DIRS:
                        continue
                    pending.append(child)
                elif child.suffix.lower() == ".md":
                    found.append((child, kind))
    return sorted(found, key=lambda pair: pair[0].resolve(strict=False).relative_to(root).as_posix())


def _parse(path: Path, expected_type: str | None, root: Path) -> tuple[dict[str, Any], str, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise WikiScanError(f"cannot read page: {path}: {exc}", code="read-error", path=path) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WikiScanError(f"invalid UTF-8: {path}", code="invalid-utf8", path=path) from exc
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise WikiScanError(f"missing frontmatter: {path}", code="frontmatter-missing", path=path)
    closing = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---"), None)
    if closing is None:
        raise WikiScanError(f"malformed frontmatter: {path}", code="frontmatter-malformed", path=path)
    fm_text = "".join(lines[1:closing])
    try:
        fm = yaml.load(fm_text, Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise WikiScanError(f"malformed frontmatter: {path}: {exc}", code="frontmatter-malformed", path=path) from exc
    if not isinstance(fm, dict):
        raise WikiScanError(f"frontmatter must be a mapping: {path}", code="frontmatter-invalid", path=path)
    for key in ("id", "title", "type"):
        if not isinstance(fm.get(key), str) or not fm[key].strip():
            raise WikiScanError(f"frontmatter field {key!r} is required: {path}", code="frontmatter-invalid", path=path)
    if expected_type is not None and fm["type"] != expected_type:
        raise WikiScanError(f"frontmatter type does not match directory: {path}", code="frontmatter-invalid", path=path)
    body = "".join(lines[closing + 1:]).lstrip("\r\n")
    if not body.strip():
        raise WikiScanError(f"empty body: {path}", code="empty-body", path=path)
    return fm, body, raw


def _blocks(page_id: str, body: str) -> tuple[ContentBlock, ...]:
    blocks: list[ContentBlock] = []
    heading: str | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        text = "\n".join(lines).strip("\r\n")
        if heading is not None or text.strip():
            blocks.append(ContentBlock(f"{page_id}:{len(blocks)}", page_id, heading, text, len(blocks)))
        lines = []

    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            heading = match.group(2).strip()
        else:
            lines.append(line)
    flush()
    return tuple(blocks)


def _relations(fm: dict[str, Any], path: Path) -> tuple[tuple[str, str], ...]:
    raw = fm.get("relations", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise WikiScanError(f"relations must be a list: {path}", code="frontmatter-invalid", path=path)
    result: list[tuple[str, str]] = []
    for relation in raw:
        if (
            not isinstance(relation, dict)
            or not isinstance(relation.get("type"), str)
            or not relation["type"].strip()
            or not isinstance(relation.get("target"), str)
            or not relation["target"].strip()
        ):
            raise WikiScanError(f"invalid relation: {path}", code="frontmatter-invalid", path=path)
        result.append((relation["type"].strip(), relation["target"].strip()))
    return tuple(result)


def _taxonomy(fm: dict[str, Any], relations: tuple[tuple[str, str], ...]) -> str | None:
    explicit = fm.get("primary_taxonomy") or fm.get("category")
    if explicit:
        return str(explicit).strip() or None
    for kind, target in relations:
        if kind != "taxonomy_of":
            continue
        if target.startswith("taxonomy/"):
            return target.removeprefix("taxonomy/").strip() or None
        if target.startswith("taxonomy-"):
            return target.removeprefix("taxonomy-").strip() or None
    return None


def _sources(fm: dict[str, Any], path: Path) -> tuple[str, ...]:
    raw = fm.get("sources", [])
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        raise WikiScanError(f"sources must be a list of non-empty strings: {path}", code="frontmatter-invalid", path=path)
    return tuple(dict.fromkeys(item.strip() for item in raw))


def _record(path: Path, kind: str, root: Path) -> tuple[PageRecord, bytes] | tuple[str, bytes]:
    expected = None if kind == "excluded" else next(value for dirname, value in _ELIGIBLE.items() if path.resolve().relative_to(root).parts[0] == dirname)
    fm, body, raw = _parse(path, expected, root)
    if kind == "excluded":
        return str(fm["id"]), raw
    page_id = fm["id"].strip()
    blocks = _blocks(page_id, body)
    first = next((block.body.strip() for block in blocks if block.body.strip()), "")
    relations = _relations(fm, path)
    return PageRecord(
        page_id=page_id,
        title=fm["title"].strip(),
        page_type=fm["type"],
        path=path.resolve(strict=False).relative_to(root).as_posix(),
        primary_taxonomy=_taxonomy(fm, relations),
        summary=first[:800],
        content_blocks=blocks,
        relation_targets=relations,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        char_count=len(body),
        token_count=None,
        custom_type=str(fm.get("custom_type", "") or "").strip(),
        sources=_sources(fm, path),
        task_type=str(fm.get("task_type", "") or "").strip() or None,
        sensitivity=str(fm.get("sensitivity", fm.get("classification", "")) or "").strip().lower(),
    ), raw


def scan_wiki_snapshot(wiki_root: Path) -> WikiSnapshot:
    root = wiki_root.resolve()
    first_inventory = _inventory(root)
    pages: list[PageRecord] = []
    excluded: list[str] = []
    seen_ids: dict[str, Path] = {}
    seen_titles: dict[str, Path] = {}
    raw_hashes: dict[str, str] = {}
    for path, kind in first_inventory:
        result, raw = _record(path, kind, root)
        rel = path.resolve(strict=False).relative_to(root).as_posix()
        raw_hashes[rel] = hashlib.sha256(raw).hexdigest()
        if kind == "excluded":
            page_id = result  # type: ignore[assignment]
            if page_id not in excluded:
                excluded.append(page_id)
            continue
        page = result  # type: ignore[assignment]
        if page.page_id in seen_ids:
            raise WikiScanError(f"duplicate page id {page.page_id!r}: {path} and {seen_ids[page.page_id]}", code="duplicate-id", path=path)
        if page.title in seen_titles:
            raise WikiScanError(f"duplicate title {page.title!r}: {path} and {seen_titles[page.title]}", code="duplicate-title", path=path)
        seen_ids[page.page_id] = path
        seen_titles[page.title] = path
        pages.append(page)
    second_inventory = _inventory(root)
    first_paths = [p.resolve(strict=False).relative_to(root).as_posix() for p, _ in first_inventory]
    second_paths = [p.resolve(strict=False).relative_to(root).as_posix() for p, _ in second_inventory]
    if first_paths != second_paths:
        raise SnapshotChangedError("wiki inventory changed during scan")
    for path, _ in second_inventory:
        rel = path.resolve(strict=False).relative_to(root).as_posix()
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise SnapshotChangedError(f"wiki content changed during scan: {rel}") from exc
        if digest != raw_hashes[rel]:
            raise SnapshotChangedError(f"wiki content changed during scan: {rel}")
    snapshot = WikiSnapshot("", str(root), "wiki-v3", tuple(sorted(pages, key=lambda p: p.path)), tuple(sorted(excluded)))
    return WikiSnapshot(snapshot_sha256(snapshot), str(root), snapshot.schema_version, snapshot.pages, snapshot.excluded_sources)


def _canonical_payload(snapshot: WikiSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "pages": [
            {
                "page_id": p.page_id,
                "title": p.title,
                "page_type": p.page_type,
                "path": p.path,
                "primary_taxonomy": p.primary_taxonomy,
                "summary": p.summary,
                "content_blocks": [b.__dict__ for b in p.content_blocks],
                "relation_targets": [list(pair) for pair in p.relation_targets],
                "content_sha256": p.content_sha256,
                "char_count": p.char_count,
                "token_count": p.token_count,
                "custom_type": p.custom_type,
                "sources": list(p.sources),
                "task_type": p.task_type,
            }
            for p in sorted(snapshot.pages, key=lambda page: page.path)
        ],
        "excluded_sources": list(sorted(snapshot.excluded_sources)),
    }


def canonical_snapshot_json(snapshot: WikiSnapshot) -> str:
    return json.dumps(_canonical_payload(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def snapshot_sha256(snapshot: WikiSnapshot) -> str:
    return hashlib.sha256(canonical_snapshot_json(snapshot).encode("utf-8")).hexdigest()


# Baseline API is re-exported here because scanner is the snapshot boundary;
# implementation remains in partition to keep grouping logic together.
from .partition import (  # noqa: E402
    CandidateDecision, GateMetrics, GovernanceConfig, ReaderProfile,
    SeriesGateResult, evaluate_series_gate,
)


__all__ = [
    "WikiScanError", "SnapshotChangedError", "scan_wiki_snapshot",
    "canonical_snapshot_json", "snapshot_sha256", "ReaderProfile",
    "GovernanceConfig", "GateMetrics", "CandidateDecision", "SeriesGateResult",
    "evaluate_series_gate",
]
