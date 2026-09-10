"""Quarantine handling for invalid v2 cards."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any

from ...lib.write_hooks import safe_write


def is_invalid_card(path_or_name: str | Path) -> bool:
    name = Path(path_or_name).name
    return name.startswith("invalid_") and name.endswith(".md")


def extract_quarantine_metadata(frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {key: value for key, value in frontmatter.items()}
    metadata["reason"] = frontmatter.get("invalid_reason") or frontmatter.get("reason") or "unspecified"
    return metadata


def raw_sha256(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _safe_slug(slug: str) -> str:
    if not isinstance(slug, str) or not slug or slug != slug.strip():
        raise ValueError("invalid quarantine slug")
    if Path(slug).is_absolute() or PureWindowsPath(slug).is_absolute():
        raise ValueError("invalid quarantine slug")
    if (Path(slug).name != slug or "/" in slug or "\\" in slug
            or slug in {".", ".."} or any(c in slug for c in "<>:\"|?*")):
        raise ValueError("invalid quarantine slug")
    if any(ord(c) < 32 or ord(c) == 127 for c in slug):
        raise ValueError("invalid quarantine slug")
    return slug[:-3] if slug.endswith(".md") else slug


def write_quarantine(
    slug: str,
    metadata: Mapping[str, Any],
    body: str,
    target_root: str | Path,
) -> Path:
    """Write an invalid card only under ``.index/quarantine``."""
    safe_slug = _safe_slug(slug)
    root = Path(target_root).resolve()
    qdir = root / ".index" / "quarantine"
    page_path = qdir / f"{safe_slug}.md"
    digest = raw_sha256(body)
    page_metadata = dict(metadata)
    page_metadata.setdefault("reason", page_metadata.get("invalid_reason", "unspecified"))
    page_metadata["raw_sha256"] = digest
    metadata_json = json.dumps(page_metadata, ensure_ascii=False, sort_keys=True, default=str)
    content = f"---\nslug: {safe_slug}\nraw_sha256: {digest}\nmetadata_json: {metadata_json}\n---\n\n{body}"
    safe_write(page_path, content)

    judgment_path = qdir / "judgments.jsonl"
    existing = judgment_path.read_text(encoding="utf-8") if judgment_path.exists() else ""
    judgment = dict(page_metadata)
    judgment["slug"] = safe_slug
    judgment["reason"] = page_metadata.get("reason", "unspecified")
    judgment["raw_sha256"] = digest
    line = json.dumps(judgment, ensure_ascii=False, sort_keys=True, default=str)
    if existing and not existing.endswith("\n"):
        existing += "\n"
    safe_write(judgment_path, existing + line + "\n")
    return page_path
