"""Inject editorial files (preface.md + chapter-titles.json) into baseline manifest.

Task 3 of `docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md`
produces `editorial/chapter-titles.json` (friendly titles) and a
`preface.md` skeleton. These land in the release directory but are
NOT registered in baseline manifest's `files` dict — so the
`book_wiki_manifest` service (which feeds the WebUI) does not surface
the preface field and does not use the friendly titles.

This script performs the minimum-cost path-1 inject:
  1. Copy `editorial/chapter-titles.json` -> `<release>/chapter-titles.json`
     (the integrity check `_verified_book_release` rejects subpath
     entries — Path(name).name must equal name — so the file must
     live at the release root, not under `editorial/`).
  2. Compute sha256 for `preface.md` and the copied `chapter-titles.json`.
  3. Add both to `manifest.files`.
  4. Rewrite manifest.json deterministically (sort_keys + sep=(",", ":")).
  5. Update `CURRENT.json` with the new manifest sha.
  6. WebUI /book-wiki should now return preface field + use friendly
     titles from chapter-titles.json.

No LLM calls. No .md body changes.

Reversal:
  Pass --revert to drop the two entries from manifest.files and
  update CURRENT.json. The copied `chapter-titles.json` at release
  root is left in place (it's a copy of `editorial/chapter-titles.json`,
  which remains the source of truth).

Usage:
    python scripts/inject_editorial_to_baseline.py --project novel-wiki
    python scripts/inject_editorial_to_baseline.py --project novel-wiki --dry-run
    python scripts/inject_editorial_to_baseline.py --project novel-wiki --revert
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv  # noqa: E402

from src.lib.project import resolve_project  # noqa: E402
from src.kc.views.book.wiki.compiler import resolve_active_version  # noqa: E402


# (source relative to release_dir, target relative to release_dir, key in
# manifest.files). Both target paths are at the release root because the
# integrity check rejects subpath entries (see _verified_book_release).
ROOT_FILES = (
    # (source, target, manifest_key)
    ("editorial/chapter-titles.json", "chapter-titles.json", "chapter-titles.json"),
    ("preface.md", "preface.md", "preface.md"),
)


def _read(p: Path) -> bytes:
    return p.read_bytes()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def _resolve_files(release_dir: Path, *, revert: bool):
    """Return (entries, missing).

    Each entry is (manifest_key, target_abs_path, sha). When reverting,
    missing is unused.
    """
    entries = []
    missing = []
    for source_rel, target_rel, manifest_key in ROOT_FILES:
        target = release_dir / target_rel
        if revert:
            entries.append((manifest_key, target, ""))
            continue
        if not target.is_file():
            missing.append(target_rel)
            continue
        entries.append((manifest_key, target, _sha(_read(target))))
    return entries, missing


def _inject(release_dir: Path, *, dry_run: bool, revert: bool) -> int:
    manifest_path = release_dir / "manifest.json"
    current_path = release_dir.parent.parent / "CURRENT.json"

    if not manifest_path.is_file():
        print(f"Error: manifest.json not found at {manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(_read(manifest_path))
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        print("Error: manifest.files is not a dict", file=sys.stderr)
        return 1

    entries, missing = _resolve_files(release_dir, revert=revert)

    if revert:
        next_files = dict(files)
        removed = []
        for manifest_key, _target, _sha_str in entries:
            if manifest_key in next_files:
                removed.append(manifest_key)
                del next_files[manifest_key]
        if not removed:
            print("Nothing to revert (no injected entries found).")
            return 0
        print(f"revert: removing {removed}")
    else:
        if missing:
            print(f"Error: missing target files: {missing}", file=sys.stderr)
            print("Hint: run scripts/title_book_chapters.py --project <id> --apply first.", file=sys.stderr)
            return 1

        # Copy editorial/chapter-titles.json -> release_root/chapter-titles.json
        # (idempotent: skip if sha already matches).
        for source_rel, target_rel, _key in ROOT_FILES:
            if source_rel == target_rel:
                continue  # preface.md already at root
            target = release_dir / target_rel
            source = release_dir / source_rel
            if target.is_file() and _sha(_read(target)) == _sha(_read(source)):
                continue
            if not dry_run:
                shutil.copyfile(source, target)
                print(f"copied  {source_rel}  ->  {target_rel}")

        # Validate no sha mismatch with manifest.
        next_files = dict(files)
        mismatches = []
        for manifest_key, target_abs, target_sha in entries:
            existing = next_files.get(manifest_key)
            if existing and existing != target_sha:
                mismatches.append((manifest_key, existing, target_sha))
        if mismatches:
            print("Error: file shas in manifest don't match disk after copy:", file=sys.stderr)
            for key, m_sha, d_sha in mismatches:
                print(f"  {key}: manifest={m_sha[:16]} disk={d_sha[:16]}", file=sys.stderr)
            print("Hint: re-run scripts/title_book_chapters.py --apply first.", file=sys.stderr)
            return 1

        for manifest_key, _target, target_sha in entries:
            next_files[manifest_key] = target_sha

    new_manifest = dict(manifest)
    new_manifest["files"] = next_files
    new_bytes = _manifest_bytes(new_manifest)
    new_sha = _sha(new_bytes)

    version = manifest.get("run_id") or release_dir.name
    current_payload = {"version": version, "manifest_sha256": new_sha}

    if revert:
        action = "revert"
    else:
        action = "inject"
    print(f"{action}: {release_dir.name}")
    print(f"  files count: {len(files)} -> {len(next_files)}")
    print(f"  old manifest sha:  {_sha(_read(manifest_path))[:16]}...")
    print(f"  new manifest sha:  {new_sha[:16]}...")
    print(f"  CURRENT.json new payload:")
    print(f"    {json.dumps(current_payload, ensure_ascii=False)}")

    if dry_run:
        print()
        print("DRY RUN: not modifying disk. Pass without --dry-run to apply.")
        return 0

    manifest_path.write_bytes(new_bytes)
    print(f"wrote {manifest_path}")
    current_path.write_text(
        json.dumps(current_payload, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {current_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", required=True, help="Project id or name")
    parser.add_argument("--release", help="Target release id; default = active")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without modifying disk")
    parser.add_argument("--revert", action="store_true",
                        help="Remove the two injected entries from manifest.files")
    args = parser.parse_args()

    load_dotenv(_REPO / ".env", override=False)
    load_dotenv(Path.cwd() / ".env", override=False)

    ctx, _paths = resolve_project(args.project, by_id_only=True)
    book_dir = ctx.path / "book-wiki"
    if args.release:
        release_dir = book_dir / ".releases" / args.release
    else:
        active = resolve_active_version(book_dir)
        if active is None:
            print("Error: no active release; pass --release <id>", file=sys.stderr)
            return 1
        release_dir = active

    return _inject(release_dir, dry_run=args.dry_run, revert=args.revert)


if __name__ == "__main__":
    raise SystemExit(main())
