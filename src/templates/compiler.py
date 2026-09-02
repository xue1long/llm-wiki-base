"""Compile project-materialized scenario-template files into one contract."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..wiki.core.types import PageType
from ..wiki.schema_registry import SchemaRegistry
from ..wiki.templates.parser import parse
from .contract import TemplateContract, TemplateSnapshot, contract_hash, snapshot_for

_ROW_RE = re.compile(r"^\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")
_PROMPT_FILES = {"analyzer.prompt.md", "generator.prompt.md"}


def _content_hash(root: Path, *, schema: str | None = None,
                  purpose: str | None = None,
                  template_sources: dict[str, bytes] | None = None) -> str:
    digest = hashlib.sha256()
    entries: list[tuple[str, bytes]] = []
    entries.append(("schema.md", (schema if schema is not None else
                                   (root / "schema.md").read_text(encoding="utf-8")).encode("utf-8")))
    entries.append(("purpose.md", (purpose if purpose is not None else
                                   (root / "purpose.md").read_text(encoding="utf-8")).encode("utf-8")))
    for name in ("analyzer.prompt.md", "generator.prompt.md"):
        path = root / name
        if path.is_file():
            entries.append((name, path.read_bytes()))
    if template_sources is None:
        template_sources = {
            path.name: path.read_bytes()
            for path in (root / ".wiki-templates").glob("*.md")
            if path.is_file()
        }
    entries.extend((f".wiki-templates/{name}", data)
                   for name, data in template_sources.items())
    for name, data in sorted(entries):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def _schema_routes(schema: str) -> dict[str, str]:
    routes: dict[str, str] = {}
    for line in schema.splitlines():
        match = _ROW_RE.match(line)
        if not match or match.group(1).strip() in {"type", "------"}:
            continue
        name, directory = match.group(1).strip(), match.group(2).strip().replace("\\", "/")
        if directory.startswith("wiki/"):
            directory = directory[5:]
        routes[name] = directory.strip("/")
    return routes


def compile_project_template(
    project_root: Path,
    *,
    template_id: str,
    template_version: str,
    expected_hash: str | None = None,
) -> tuple[TemplateSnapshot, TemplateContract]:
    root = Path(project_root)
    schema_path = root / "schema.md"
    purpose_path = root / "purpose.md"
    template_dir = root / ".wiki-templates"
    bundled_root = Path(__file__).parent / "bundled" / "general"
    bundled_dir = bundled_root / ".wiki-templates"
    try:
        schema = schema_path.read_text(encoding="utf-8")
    except OSError:
        # Projects created before scenario-template binding may not have the
        # optional materialized files yet. Keep their historical behavior by
        # compiling against the shipped general contract until they opt in to
        # an explicit instance template.
        schema = (bundled_root / "schema.md").read_text(encoding="utf-8")
    try:
        purpose = purpose_path.read_text(encoding="utf-8")
    except OSError:
        purpose = (bundled_root / "purpose.md").read_text(encoding="utf-8")

    routes = _schema_routes(schema)
    registry = SchemaRegistry.from_schema_text(schema)
    allowed_types = tuple(sorted(routes))
    if not allowed_types:
        raise ValueError("Template schema declares no Wiki types")
    slot_rules: dict[str, tuple[str, ...]] = {}
    template_sources: dict[str, bytes] = {}
    for type_name in allowed_types:
        path = template_dir / f"{type_name}.md"
        if not path.is_file():
            if template_dir.is_dir():
                raise ValueError(f"missing page template: {type_name}")
            # Legacy/default projects only materialize schema and purpose.
            # Reuse the closest bundled base template for slot validation;
            # custom types retain their schema route and identity.
            fallback_name = type_name if (bundled_dir / f"{type_name}.md").is_file() else "concept"
            path = bundled_dir / f"{fallback_name}.md"
            if not path.is_file():
                raise ValueError(f"missing page template: {type_name}")
        try:
            page_type = PageType(type_name)
        except ValueError:
            if not registry.is_custom(type_name):
                raise ValueError(f"template type not declared: {type_name}")
            page_type = registry.get_base_type(type_name)
        ast = parse(path.read_text(encoding="utf-8"), page_type)
        slot_rules[type_name] = tuple(slot.name for slot in ast.all_slots if not slot.is_optional)
        template_sources[f"{type_name}.md"] = path.read_bytes()

    for path in template_dir.glob("*.md") if template_dir.is_dir() else ():
        type_name = path.stem
        if type_name not in routes:
            raise ValueError(f"template type {type_name!r} not declared by schema")

    template_hash = _content_hash(root, schema=schema, purpose=purpose,
                                   template_sources=template_sources)
    if expected_hash is not None and template_hash != expected_hash:
        raise ValueError(f"template hash mismatch: expected {expected_hash}, got {template_hash}")
    contract = TemplateContract(
        template_id=template_id,
        template_version=template_version,
        template_hash=template_hash,
        allowed_types=allowed_types,
        slot_rules=slot_rules,
        routes=routes,
        purpose=purpose,
        analyzer_instructions=(root / "analyzer.prompt.md").read_text(encoding="utf-8")
        if (root / "analyzer.prompt.md").is_file() else "",
        generator_instructions=(root / "generator.prompt.md").read_text(encoding="utf-8")
        if (root / "generator.prompt.md").is_file() else "",
    )
    snapshot = snapshot_for(root, contract)
    if contract_hash(contract) != snapshot.contract_hash:
        raise AssertionError("contract hash construction is not deterministic")
    return snapshot, contract
