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


def _content_hash(root: Path) -> str:
    digest = hashlib.sha256()
    allowed = {root / "schema.md", root / "purpose.md", root / "analyzer.prompt.md", root / "generator.prompt.md"}
    allowed.update((root / ".wiki-templates").glob("*.md"))
    for path in sorted(p for p in allowed if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
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
    try:
        schema = schema_path.read_text(encoding="utf-8")
        purpose = purpose_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("Template must contain schema.md and purpose.md") from exc
    if not template_dir.is_dir():
        raise ValueError("Template must contain .wiki-templates directory")

    routes = _schema_routes(schema)
    registry = SchemaRegistry.from_schema_text(schema)
    allowed_types = tuple(sorted(routes))
    if not allowed_types:
        raise ValueError("Template schema declares no Wiki types")
    slot_rules: dict[str, tuple[str, ...]] = {}
    for type_name in allowed_types:
        path = template_dir / f"{type_name}.md"
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

    for path in template_dir.glob("*.md"):
        type_name = path.stem
        if type_name not in routes:
            raise ValueError(f"template type {type_name!r} not declared by schema")

    template_hash = _content_hash(root)
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
