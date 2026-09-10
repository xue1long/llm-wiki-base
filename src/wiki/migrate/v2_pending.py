"""Decision helpers for v2 ``_to_recompile`` cards."""
from __future__ import annotations

import copy
import csv
import os
from pathlib import Path
from typing import Iterable, Mapping

import yaml


class PendingPathError(ValueError):
    """A pending-card slug is unsafe for the target tree."""


class PendingCollisionError(FileExistsError):
    """A pending destination already exists."""


def _card_name(path: Path) -> str:
    name = Path(path).name
    if not name:
        raise PendingPathError(f"pending path has no filename: {path}")
    return name


def classify_pending(
    pending_files: Iterable[Path],
    *,
    main_files: Iterable[Path],
) -> dict[str, dict[str, object]]:
    """Classify pending cards, with the main card winning same-name clashes."""
    main_by_name = {_card_name(path): Path(path) for path in main_files}
    report: dict[str, dict[str, object]] = {}
    for path in sorted((Path(item) for item in pending_files), key=lambda p: str(p)):
        name = _card_name(path)
        if name in report:
            previous = report[name]
            previous.setdefault("skipped_paths", []).append(str(path))
            previous["status"] = "collision"
            previous["reason"] = "duplicate pending filename"
            continue
        if name in main_by_name:
            report[name] = {
                "status": "main_wins",
                "reason": "_to_recompile",
                "source_path": str(path),
                "skipped_paths": [str(main_by_name[name])],
            }
        else:
            report[name] = {
                "status": "pending",
                "reason": "_to_recompile",
                "source_path": str(path),
                "skipped_paths": [],
            }
    return report


def _safe_slug(slug: str) -> str:
    if not isinstance(slug, str) or not slug.strip():
        raise PendingPathError("pending slug must be a non-empty string")
    slug = slug.strip()
    if slug.endswith(".md"):
        slug = slug[:-3]
    if (
        not slug
        or slug in {".", ".."}
        or "/" in slug
        or "\\" in slug
        or any(ord(char) < 32 or ord(char) == 127 for char in slug)
        or any(char in slug for char in '<>:"|?*')
        or slug.endswith((".", " "))
    ):
        raise PendingPathError(f"unsafe pending slug: {slug!r}")
    return slug


def _pending_content(frontmatter: Mapping, body: str) -> str:
    rendered = yaml.safe_dump(
        dict(frontmatter), allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    return f"---\n{rendered}---\n\n{body or ''}"


def write_pending_cards(
    cards: Iterable[Mapping],
    *,
    target_root: Path,
) -> list[Path]:
    """Write cards below ``wiki/_pending`` without overwriting files."""
    destination = Path(target_root).resolve(strict=False) / "wiki" / "_pending"
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for card in cards:
        slug = _safe_slug(card.get("slug", ""))
        target = (destination / f"{slug}.md").resolve(strict=False)
        try:
            target.relative_to(destination.resolve(strict=False))
        except ValueError as exc:
            raise PendingPathError(f"pending target escapes target root: {target}") from exc
        if target.exists():
            raise PendingCollisionError(f"pending target already exists: {target}")
        content = _pending_content(card.get("fm", {}), card.get("body", ""))
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with temp.open("x", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, target)
            except FileExistsError as exc:
                raise PendingCollisionError(f"pending target already exists: {target}") from exc
            temp.unlink(missing_ok=True)
        except BaseException:
            temp.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        written.append(target)
    return written


def merge_pending_metadata(main_fm: Mapping, pending_fm: Mapping) -> dict:
    """Append pending-only metadata into main ``_ko_extra``; main wins."""
    merged = copy.deepcopy(dict(main_fm))
    extra = merged.setdefault("_ko_extra", {})
    if not isinstance(extra, dict):
        extra = {"_v2_previous_ko_extra": extra}
        merged["_ko_extra"] = extra
    pending_extra = pending_fm.get("_ko_extra", {})
    if isinstance(pending_extra, Mapping):
        for key, value in pending_extra.items():
            extra.setdefault(key, copy.deepcopy(value))
    for key, value in pending_fm.items():
        if key == "_ko_extra":
            continue
        extra.setdefault(key, copy.deepcopy(value))
    return merged


def write_pending_decisions(
    report: Mapping[str, Mapping],
    *,
    target_root: Path,
    filename: str = "pending_decisions.csv",
) -> Path:
    """Persist the classification ledger as a deterministic CSV report."""
    if Path(filename).name != filename:
        raise PendingPathError("report filename must not contain directories")
    report_dir = Path(target_root).resolve(strict=False) / "migration"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / filename
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["slug", "status", "reason", "source_path", "skipped_paths"],
        )
        writer.writeheader()
        for slug in sorted(report):
            item = report[slug]
            writer.writerow(
                {
                    "slug": slug,
                    "status": item.get("status", ""),
                    "reason": item.get("reason", ""),
                    "source_path": item.get("source_path", ""),
                    "skipped_paths": ";".join(str(p) for p in item.get("skipped_paths", [])),
                }
            )
    return path
