"""Scenario templates for new knowledge-base projects."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..lib.write_hooks import safe_write

BUNDLED_DIR = Path(__file__).parent / "bundled"
USER_DIR = Path.home() / ".config" / "ruflo-kb" / "templates"
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_META = "template.json"


@dataclass
class Template:
    name: str
    files: dict[str, str]
    description: str = ""
    icon: str = ""
    extra_dirs: list[str] | None = None
    builtin: bool = False

    @property
    def id(self) -> str:
        return self.name


def _validate_id(name: str) -> str:
    if not _ID_RE.fullmatch(name):
        raise ValueError("Template id must match [a-z][a-z0-9_-]{0,63}")
    return name


def _root(name: str) -> tuple[Path, bool]:
    _validate_id(name)
    bundled = BUNDLED_DIR / name
    if bundled.is_dir():
        return bundled, True
    user = USER_DIR / name
    if user.is_dir():
        return user, False
    raise FileNotFoundError(f"Template not found: {name}")


def _read(root: Path, name: str, builtin: bool) -> Template:
    metadata = {}
    meta_path = root / _META
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid template metadata: {meta_path}: {exc}") from exc
        if not isinstance(metadata, dict):
            raise ValueError(f"Invalid template metadata: {meta_path}")
    files = {
        f.relative_to(root).as_posix(): f.read_text(encoding="utf-8")
        for f in root.rglob("*")
        if f.is_file() and f.name != _META
    }
    if "schema.md" not in files or "purpose.md" not in files:
        raise ValueError(f"Template {name!r} must contain schema.md and purpose.md")
    extra = metadata.get("extra_dirs", [])
    if not isinstance(extra, list) or not all(isinstance(x, str) for x in extra):
        raise ValueError(f"Template {name!r} has invalid extra_dirs")
    return Template(
        name=name,
        files=files,
        description=str(metadata.get("description", "")),
        icon=str(metadata.get("icon", "")),
        extra_dirs=extra,
        builtin=builtin,
    )


def load(name: str) -> Template:
    root, builtin = _root(name)
    return _read(root, name, builtin)


def list_bundled() -> list[str]:
    return sorted(d.name for d in BUNDLED_DIR.iterdir() if d.is_dir()) if BUNDLED_DIR.exists() else []


def list_templates() -> list[Template]:
    names = set(list_bundled())
    if USER_DIR.exists():
        names.update(d.name for d in USER_DIR.iterdir() if d.is_dir())
    result = []
    for name in sorted(names):
        try:
            result.append(load(name))
        except (ValueError, FileNotFoundError):
            continue
    return result


def _safe_relative(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe template path: {relative}")
    target = (root / path).resolve()
    target.relative_to(root.resolve())
    return target


def apply_template(name: str, project_root: Path | str, *, force: bool = False) -> list[Path]:
    template = load(name)
    root = Path(project_root).resolve()
    targets = [_safe_relative(root, rel) for rel in template.files]
    dirs = [_safe_relative(root, rel) for rel in (template.extra_dirs or [])]
    conflicts = [p for p in targets if p.exists()]
    blocked = set(conflicts) if not force else set()
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)
    written = []
    for rel, content in template.files.items():
        target = _safe_relative(root, rel)
        if target in blocked:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        safe_write(target, content)
        written.append(target)
    return written


def create(name: str, *, source: str = "general", description: str = "", icon: str = "") -> Template:
    _validate_id(name)
    if (BUNDLED_DIR / name).exists() or (USER_DIR / name).exists():
        raise FileExistsError(f"Template already exists: {name}")
    source_template = load(source)
    root = USER_DIR / name
    root.mkdir(parents=True, exist_ok=False)
    metadata = {
        "name": name,
        "description": description or f"Custom template based on {source}",
        "icon": icon or source_template.icon,
        "extra_dirs": source_template.extra_dirs or [],
    }
    safe_write(root / _META, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    for rel, content in source_template.files.items():
        target = _safe_relative(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        safe_write(target, content)
    return load(name)


def update_metadata(name: str, *, description: str | None = None, icon: str | None = None) -> Template:
    root, builtin = _root(name)
    if builtin:
        raise PermissionError("Bundled templates are read-only")
    template = load(name)
    metadata = {"name": name, "description": template.description, "icon": template.icon, "extra_dirs": template.extra_dirs or []}
    if description is not None:
        metadata["description"] = description
    if icon is not None:
        metadata["icon"] = icon
    safe_write(root / _META, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return load(name)


def update_content(name: str, files: dict[str, str], *, extra_dirs: list[str] | None = None) -> Template:
    root, builtin = _root(name)
    if builtin:
        raise PermissionError("Bundled templates are read-only")
    template = load(name)
    allowed = {"schema.md", "purpose.md", "taxonomy.md"} | {
        f for f in template.files if f.startswith(".wiki-templates/")
    }
    if set(files) - allowed:
        raise ValueError("Only schema.md, purpose.md, taxonomy.md and .wiki-templates/*.md may be edited")
    for rel, content in files.items():
        if not isinstance(content, str):
            raise ValueError(f"Template content must be text: {rel}")
        target = _safe_relative(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        safe_write(target, content)
    if extra_dirs is not None:
        if not all(isinstance(x, str) for x in extra_dirs):
            raise ValueError("extra_dirs must be a list of strings")
        metadata = {"name": name, "description": template.description, "icon": template.icon, "extra_dirs": extra_dirs}
        safe_write(root / _META, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return load(name)


def delete(name: str) -> None:
    root, builtin = _root(name)
    if builtin:
        raise PermissionError("Bundled templates are read-only")
    import shutil
    shutil.rmtree(root)
