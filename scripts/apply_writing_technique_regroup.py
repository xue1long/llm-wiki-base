"""Apply writing-technique regroup (Task 4) to the active release.

Consolidates the writing-technique chapters (67 `concept-写...` chunks
plus the other `concept-写*` / `synthesis-写*` volumes) into 7-8 named
topical chapters:

  人物塑造与设定 / 情节与节奏 / 开篇与签约 / 套路与爽点 /
  描写与文笔 / 题材与世界观 / 心态与职业 / 平台与读者

Algorithm:
  1. Load `outline.json` -> map every page_id to its owning chapter_id.
  2. Load the Wiki snapshot for page titles.
  3. For each writing-technique chapter, score it against the 8 keyword
     rules using its member pages' titles; assign the whole chapter to
     its best-matching bucket (majority wins; ties -> catch-all bucket).
     Assigning whole chapters keeps content intact — no page is split.
  4. Concatenate the member chapters' bodies into one merged .md per
     bucket (frontmatter stripped, per-source `##` sub-headings added).
  5. Rewrite `outline.json`: drop the old writing-technique volumes and
     add one volume per non-empty bucket, with readable titles.
  6. Rewrite `manifest.json`: drop the old writing-technique .md entries,
     add the merged .md entries, refresh `chapter_count`.
  7. Update `CURRENT.json` with the new manifest sha.

No LLM calls. The original manifest and outline are backed up next to
themselves as `*.bak.regroup` before any write.

Usage:
    python scripts/apply_writing_technique_regroup.py --project novel-wiki --dry-run
    python scripts/apply_writing_technique_regroup.py --project novel-wiki
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv  # noqa: E402

from src.lib.project import resolve_project  # noqa: E402
from src.kc.views.book.wiki.compiler import resolve_active_version  # noqa: E402
from src.kc.views.book.wiki.partition import (  # noqa: E402
    DEFAULT_WRITING_TECHNIQUE_REGROUP,
)
from src.kc.views.book.wiki.scanner import scan_wiki_snapshot  # noqa: E402


WRITE = chr(0x5199)  # 写
WRITE_VOLUME_PREFIXES = ("concept-" + WRITE, "synthesis-" + WRITE)

# Files that live at the release root but are not chapters.
NON_CHAPTER = {"index.md", "glossary.md", "sources-index.md", "preface.md"}


def _read(p: Path) -> bytes:
    return p.read_bytes()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            return text[end + 4:].lstrip("\n")
    return text


def _load_page_owner(outline: list) -> dict[str, str]:
    """page_id -> chapter_id, from the compiled outline."""
    owner: dict[str, str] = {}
    for proposal in outline:
        if not isinstance(proposal, dict):
            continue
        for volume in proposal.get("volumes") or []:
            if not isinstance(volume, dict):
                continue
            for chapter in volume.get("chapters") or []:
                if not isinstance(chapter, dict):
                    continue
                cid = str(chapter.get("chapter_id") or "")
                if not cid:
                    continue
                for pid in chapter.get("page_ids") or []:
                    owner[str(pid)] = cid
    return owner


def _is_writing_technique_volume(volume_id: str) -> bool:
    return volume_id.startswith(WRITE_VOLUME_PREFIXES)


def _bucket_for_chapter(page_titles: list[str], rules: dict) -> str:
    """Pick the bucket with the most keyword hits; ties -> first rule."""
    scores: dict[str, int] = {cid: 0 for cid in rules}
    for title in page_titles:
        for cid, pattern in rules.items():
            if pattern.search(title or ""):
                scores[cid] += 1
    best = max(scores.values()) if scores else 0
    if best == 0:
        return next(iter(rules))
    for cid in rules:  # deterministic: first rule with the max score
        if scores[cid] == best:
            return cid
    return next(iter(rules))


def _apply(release_dir: Path, *, dry_run: bool) -> int:
    manifest_path = release_dir / "manifest.json"
    outline_path = release_dir / "outline.json"
    current_path = release_dir.parent.parent / "CURRENT.json"

    for required in (manifest_path, outline_path):
        if not required.is_file():
            print(f"Error: missing {required}", file=sys.stderr)
            return 1

    manifest = json.loads(_read(manifest_path))
    outline = json.loads(_read(outline_path))
    if not isinstance(outline, list):
        print("Error: outline.json is not a list", file=sys.stderr)
        return 1

    # Reject re-running on an already-regrouped release. Compare against the
    # canonical rule keys from partition.py rather than a hand-typed prefix:
    # hand-typed CJK in this file is error-prone (a missing character makes
    # the guard silently pass and a careless re-run double-merges).
    rule_keys = set(DEFAULT_WRITING_TECHNIQUE_REGROUP.keys())
    existing_volumes = [
        str(v.get("volume_id", ""))
        for p in outline if isinstance(p, dict)
        for v in (p.get("volumes") or []) if isinstance(v, dict)
    ]
    if any(vid in rule_keys for vid in existing_volumes):
        print("Error: release already contains regrouped writing-technique volumes.")
        print("Refusing to re-run. Restore from *.bak.regroup to start over.")
        return 1

    # --- Page titles from the Wiki snapshot -------------------------
    project_root = release_dir.parents[2]
    wiki_root = project_root / "wiki"
    if not wiki_root.is_dir():
        print(f"Error: wiki dir not found: {wiki_root}", file=sys.stderr)
        return 1
    snapshot = scan_wiki_snapshot(wiki_root)
    page_title = {p.page_id: (p.title or "") for p in snapshot.pages}
    print(f"snapshot pages: {len(snapshot.pages)}")

    # --- Which chapters belong to writing-technique volumes ----------
    chapter_pages: dict[str, list[str]] = {}
    chapter_volume: dict[str, str] = {}
    for proposal in outline:
        if not isinstance(proposal, dict):
            continue
        for volume in proposal.get("volumes") or []:
            if not isinstance(volume, dict):
                continue
            vid = str(volume.get("volume_id") or "")
            if not _is_writing_technique_volume(vid):
                continue
            for chapter in volume.get("chapters") or []:
                if not isinstance(chapter, dict):
                    continue
                cid = str(chapter.get("chapter_id") or "")
                if not cid:
                    continue
                chapter_pages[cid] = [str(x) for x in (chapter.get("page_ids") or [])]
                chapter_volume[cid] = vid

    print(f"writing-technique chapters to regroup: {len(chapter_pages)}")

    # --- Assign each chapter to a bucket -----------------------------
    rules = DEFAULT_WRITING_TECHNIQUE_REGROUP
    buckets: dict[str, list[str]] = {}
    for cid, page_ids in chapter_pages.items():
        titles = [page_title.get(pid, "") for pid in page_ids]
        buckets.setdefault(_bucket_for_chapter(titles, rules), []).append(cid)

    # --- Locate the on-disk file for each old chapter ----------------
    # The compiler names chapters `{safe(volume_id)}__{safe(chapter_id)}.md`.
    def _safe(value: str) -> str:
        return "".join(c if c.isalnum() or c in "._-" else "_" for c in value).strip(".") or "unnamed"

    stem_to_file: dict[str, str] = {}
    for p in release_dir.iterdir():
        if p.is_file() and p.suffix == ".md":
            stem_to_file[p.stem] = p.name

    def _file_for_chapter(cid: str) -> str | None:
        vid = chapter_volume.get(cid, "")
        for candidate in (f"{_safe(vid)}__{_safe(cid)}", _safe(cid), cid):
            if candidate in stem_to_file:
                return stem_to_file[candidate]
        return None

    # --- Merge each bucket's chapters into one .md -------------------
    files = dict(manifest.get("files", {}))
    merged_plan: list[tuple[str, str, str, int]] = []  # (new_id, fname, body, n_sources)
    old_files_to_drop: set[str] = set()

    for bucket_id, chapter_ids in sorted(buckets.items()):
        readable = bucket_id.split(chr(0x6280) + chr(0x6cd5) + "-", 1)[-1] or bucket_id
        parts = [f"# {readable}\n",
                 f"\n_本章由写作技法相关内容合并而成，共 {len(chapter_ids)} 个来源章节。_\n"]
        used = 0
        for cid in chapter_ids:
            fname = _file_for_chapter(cid)
            if not fname:
                continue
            body = _strip_frontmatter(_read(release_dir / fname).decode("utf-8", errors="replace"))
            parts.append(f"\n\n## {cid}\n\n{body.strip()}\n")
            old_files_to_drop.add(fname)
            used += 1
        if used == 0:
            continue
        new_id = bucket_id
        new_fname = f"{new_id}.md"
        merged_plan.append((new_id, new_fname, "".join(parts), used))

    print(f"\nbuckets: {len(buckets)}, merged chapters: {len(merged_plan)}")
    for new_id, fname, body, used in merged_plan:
        print(f"  {used:3d} sources -> {fname}  ({len(body.encode('utf-8')):,} bytes)")
    print(f"old chapter files to drop from manifest: {len(old_files_to_drop)}")

    # --- New outline -------------------------------------------------
    new_outline = []
    for proposal in outline:
        if not isinstance(proposal, dict):
            continue
        kept_volumes = [
            v for v in (proposal.get("volumes") or [])
            if isinstance(v, dict) and not _is_writing_technique_volume(str(v.get("volume_id") or ""))
        ]
        new_proposal = dict(proposal)
        new_proposal["volumes"] = kept_volumes
        new_outline.append(new_proposal)

    merged_ids = {new_id for new_id, _, _, _ in merged_plan}
    for new_id, fname, _body, _used in merged_plan:
        readable = new_id.split(chr(0x6280) + chr(0x6cd5) + "-", 1)[-1] or new_id
        page_ids = [pid for cid in buckets[new_id] for pid in chapter_pages.get(cid, [])]
        new_outline[0]["volumes"].append({
            "volume_id": new_id,
            "title": readable,
            "is_fallback": False,
            "chapters": [{
                "chapter_id": new_id,
                "title": readable,
                "page_ids": page_ids,
                "overview_refs": page_ids[:1],
            }],
        })

    # --- New manifest.files ------------------------------------------
    next_files = {k: v for k, v in files.items() if k not in old_files_to_drop}
    for new_id, fname, body, _used in merged_plan:
        next_files[fname] = _sha(body.encode("utf-8"))

    new_chapter_count = sum(
        1 for name in next_files
        if name.endswith(".md") and name not in NON_CHAPTER and not name.startswith(("concept-", "synthesis-"))
    ) + sum(
        1 for name in next_files
        if name.endswith(".md") and merged_ids and any(name == f"{mid}.md" for mid in merged_ids)
    )
    # Simpler + authoritative: count .md entries that are not the known
    # non-chapter artefacts, then subtract the ones we're replacing.
    new_chapter_count = len([
        name for name in next_files
        if name.endswith(".md") and name not in NON_CHAPTER
    ])

    new_manifest = dict(manifest)
    new_manifest["files"] = next_files
    new_manifest["chapter_count"] = new_chapter_count

    # Serialise the outline FIRST: rewriting outline.json changes its sha,
    # so manifest.files["outline.json"] must be refreshed before the
    # manifest itself is hashed (otherwise the integrity check fails).
    new_outline_bytes = json.dumps(
        new_outline, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    next_files["outline.json"] = _sha(new_outline_bytes)

    new_bytes = _manifest_bytes(new_manifest)
    new_sha = _sha(new_bytes)

    version = manifest.get("run_id") or release_dir.name
    current_payload = {"version": version, "manifest_sha256": new_sha}

    print()
    print(f"chapter_count: {manifest.get('chapter_count')} -> {new_chapter_count}")
    print(f"old manifest sha: {_sha(_read(manifest_path))[:16]}...")
    print(f"new manifest sha: {new_sha[:16]}...")

    if dry_run:
        print()
        print("DRY RUN: not modifying disk.")
        return 0

    # --- Write -------------------------------------------------------
    outline_path.with_suffix(".json.bak.regroup").write_bytes(_read(outline_path))
    manifest_path.with_suffix(".json.bak.regroup").write_bytes(_read(manifest_path))

    for new_id, fname, body, _used in merged_plan:
        # write_bytes, not write_text: write_text applies newline translation
        # on Windows (\\n -> \\r\\n), so the on-disk bytes would not match the
        # sha we recorded in manifest.files.
        (release_dir / fname).write_bytes(body.encode("utf-8"))
    outline_path.write_bytes(new_outline_bytes)
    manifest_path.write_bytes(new_bytes)
    current_path.write_text(
        json.dumps(current_payload, ensure_ascii=False) + "\n", encoding="utf-8",
    )

    print(f"wrote {len(merged_plan)} merged chapters")
    print(f"wrote {outline_path}")
    print(f"wrote {manifest_path}")
    print(f"wrote {current_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", required=True, help="Project id or name")
    parser.add_argument("--release", help="Target release id; default = active")
    parser.add_argument("--dry-run", action="store_true")
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

    return _apply(release_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
