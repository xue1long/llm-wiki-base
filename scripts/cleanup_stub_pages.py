#!/usr/bin/env python3
"""cleanup_stub_pages.py — Phase 1.1: delete stub/placeholder wiki pages and
repair every reference to them, bidirectionally.

A *stub page* is any page in ``wiki/{sources,entities,concepts,synthesis}/*.md``
whose body contains "占位条目" **or** whose frontmatter has
``processing_depth: stub``. Stubs were auto-created by the pipeline whenever a
slug was referenced (relations target / [[wikilink]]) but no page was produced
for it that run. Deleting them without fixing references would leave broken
links, so this script:

  * builds a reverse reference index over ALL surviving (non-stub) pages, then
    for each stub gathers every reference to it:
      - frontmatter ``relations[].target == stub``
      - body ``[[stub]]`` / ``[[stub|alias]]`` / ``[[stub#section]]``
    which covers BOTH directions:
      - *forward* references (a page cites the stub),
      - *reverse* edges (a real page got an inverse ``referenced_by``-style
        relation added by ``_compute_reverse_relations`` because the stub cited
        *it*). Both show up as ``target == stub`` on another page, so one scan
        handles both; the stub's own outgoing relations die with the file.
  * per stub bucket (reuses ``scripts/audit_placeholder_classify.bucket``):
      - ``source_like``: if a real source page exists whose slug has the SAME
        8-hex tail (deterministic ``md5(path)[:8]`` criterion — NOT loose stem
        matching), repoint the reference to that real slug; else remove it.
      - ``clean``: if a real (non-stub) page with the same id/title exists,
        repoint; else remove the reference.
      - ``raw_or_path`` / ``tag_like`` / ``type_prefix`` / ``entity_suffix``:
        remove the reference.
  * rewrites referring pages surgically: only the ``relations:`` block and the
    matching ``[[...]]`` wikilinks are touched; every other byte (frontmatter,
    body, line endings) is preserved.
  * deletes each stub file with ``git rm`` (falls back to ``os.remove`` when the
    file is not tracked by git).

SAFE BY DEFAULT: without ``--apply`` nothing is written or deleted — only a
full change plan is printed. ``--max N`` stops after N stubs in apply mode.

Stub files themselves are never rewritten (they are deleted anyway) and a
reference between two stubs is left alone (it dies when the second stub is
deleted). Nothing under ``wiki/_backup_placeholder_pages_20260731/`` is ever
scanned or touched (the scan is restricted to the four type directories).

Usage:
    env PYTHONIOENCODING=utf-8 python scripts/cleanup_stub_pages.py [wiki_root]
    env PYTHONIOENCODING=utf-8 python scripts/cleanup_stub_pages.py [wiki_root] --apply [--max N]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

# bucket() lives in the same scripts/ dir; running this file puts scripts/ on
# sys.path, so a plain relative import works.
from audit_placeholder_classify import HEX_TAIL, bucket

# Only these four type directories are ever scanned/rewritten/deleted.
# Directories like wiki/_backup_placeholder_pages_20260731 (a snapshot of the
# very stub pages this script deletes), wiki/_stubs and wiki/_archive are
# deliberately NOT globbed, so their contents are never touched.
WIKI_TYPES = ("sources", "entities", "concepts", "synthesis")

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
STUB_BODY_MARK = "占位条目"

# Priority for choosing a repoint target when several real pages qualify.
TYPE_PRIORITY = {"source": 0, "concept": 1, "synthesis": 2, "entity": 3}
# Type-dir name -> singular page type (fallback when frontmatter type is
# missing/broken, so a source page still counts as "source" for hex-tail match).
_DIR_TYPE = {"sources": "source", "entities": "entity", "concepts": "concept",
             "synthesis": "synthesis"}


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------

class Stub:
    __slots__ = ("path", "id", "title", "bucket")

    def __init__(self, path: Path, id_: str, title: str, bucket_: str):
        self.path = path          # absolute path of the stub file
        self.id = id_             # slug (frontmatter id == file stem)
        self.title = str(title or "")
        self.bucket = bucket_     # from audit_placeholder_classify.bucket

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Stub {self.bucket} {self.id}>"


class Reference:
    """A single reference to a stub, found inside one page."""

    __slots__ = ("page_path", "kind", "value")

    def __init__(self, page_path: Path, kind: str, value):
        self.page_path = page_path  # the referring page
        self.kind = kind            # "relation" | "wikilink"
        self.value = value          # relation dict | wikilink inner text


class WikiIndex:
    """In-memory snapshot of every wiki page + reverse reference index."""

    def __init__(self, wiki_root: Path):
        self.wiki_root = wiki_root
        self.pages: dict[Path, tuple[str, str, str]] = {}   # path -> (raw, nl, text)
        self.stub_paths: set[Path] = set()
        # real page maps (stubs excluded): used to resolve repoint targets
        self.real_by_id: dict[str, list[tuple[Path, str]]] = {}      # id -> [(path,type)]
        self.real_by_title: dict[str, list[tuple[Path, str]]] = {}   # title -> [(path,type)]
        self.source_tails: dict[str, list[str]] = {}                 # hex8 -> [source slug]
        # reverse reference index: target slug -> references from NON-stub pages
        self.refs_by_target: dict[str, list[Reference]] = defaultdict(list)

    def scan(self) -> list[Stub]:
        """Read every page once, build real-page maps and the reverse index."""
        stubs: list[Stub] = []
        for t in WIKI_TYPES:
            d = self.wiki_root / "wiki" / t
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.md")):
                raw, nl, text = _load(p)
                self.pages[p] = (raw, nl, text)
                fm = _frontmatter(text)
                pid = _page_id(p, fm)
                if _is_stub(text, fm):
                    stubs.append(Stub(p, pid, fm.get("title"), bucket(pid)))
                    continue  # stub pages are never referrers we rewrite

                typ = fm.get("type") or _DIR_TYPE[t]
                self.real_by_id.setdefault(pid, []).append((p, typ))
                title = fm.get("title")
                if title:
                    self.real_by_title.setdefault(str(title), []).append((p, typ))
                if typ == "source":
                    m = HEX_TAIL.search(pid)
                    if m:
                        self.source_tails.setdefault(m.group(0)[1:], []).append(pid)

                for r in fm.get("relations") or []:
                    if isinstance(r, dict) and r.get("target"):
                        self.refs_by_target[str(r["target"])].append(Reference(p, "relation", r))
                m = FRONT_RE.match(text)
                body = m.group(2) if m else text
                for tgt in _wikilink_targets(body):
                    self.refs_by_target[tgt].append(Reference(p, "wikilink", tgt))

        self.stub_paths = {s.path for s in stubs}
        return stubs


# ---------------------------------------------------------------------------
# page helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> tuple[str, str, str]:
    """Read preserving newlines. Returns (raw, nl, normalized_text)."""
    raw = path.read_text(encoding="utf-8", newline="")
    nl = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    return raw, nl, text


def _save(path: Path, nl: str, text: str) -> None:
    out = text.replace("\n", nl) if nl == "\r\n" else text
    path.write_text(out, encoding="utf-8", newline="")


def _frontmatter(text: str) -> dict:
    m = FRONT_RE.match(text)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def _page_id(path: Path, fm: dict) -> str:
    return str(fm.get("id") or path.stem)


def _is_stub(text: str, fm: dict) -> bool:
    return STUB_BODY_MARK in text or fm.get("processing_depth") == "stub"


def _wikilink_targets(body: str) -> list[str]:
    return [m.split("|")[0].split("#")[0].strip() for m in WIKILINK_RE.findall(body)]


def find_references(index: WikiIndex, stub: Stub) -> list[Reference]:
    """All references to *stub* from surviving (non-stub) pages.

    ``stub.id`` almost always equals ``stub.path.stem`` (id == filename), so
    the same Reference object is reachable under both keys; dedupe by object
    identity so each relation / wikilink occurrence is reported exactly once.
    """
    keys = (stub.id,) if stub.id == stub.path.stem else (stub.id, stub.path.stem)
    out: list[Reference] = []
    seen: set[tuple] = set()
    for key in keys:
        for r in index.refs_by_target.get(key, []):
            sig = (r.page_path, r.kind, id(r.value))
            if sig not in seen:
                seen.add(sig)
                out.append(r)
    return out


# ---------------------------------------------------------------------------
# repoint resolution
# ---------------------------------------------------------------------------

def resolve_repoint(index: WikiIndex, stub: Stub) -> str | None:
    """Return the real slug to repoint to, or None => remove the reference."""
    if stub.bucket == "source_like":
        m = HEX_TAIL.search(stub.id)
        tail = m.group(0)[1:] if m else None
        if tail and tail in index.source_tails:
            # deterministic: same 8-hex tail == same md5(path)[:8] source page
            return sorted(index.source_tails[tail])[0]
        return None

    if stub.bucket == "clean":
        cands: list[tuple[Path, str]] = []
        seen = set()
        for p, typ in index.real_by_id.get(stub.id, []):
            if p not in seen:
                cands.append((p, typ))
                seen.add(p)
        if stub.title:
            for p, typ in index.real_by_title.get(stub.title, []):
                if p not in seen:
                    cands.append((p, typ))
                    seen.add(p)
        if not cands:
            return None
        cands.sort(key=lambda c: (TYPE_PRIORITY.get(c[1], 9), str(c[0])))
        p, _ = cands[0]
        raw, _nl, text = index.pages[p]
        return _page_id(p, _frontmatter(text))

    # raw_or_path / tag_like / type_prefix / entity_suffix: never repoint
    return None


# ---------------------------------------------------------------------------
# surgical rewrites (preserve everything else byte-for-byte)
# ---------------------------------------------------------------------------

def _relations_block_span(lines: list[str]) -> tuple[int, int] | None:
    """Return (start, end) of the top-level ``relations:`` block.

    start = index of the ``relations:`` line; end = one past the last line of
    the block (list items at column 0 + indented continuation keys).
    """
    start = None
    for i, ln in enumerate(lines):
        if ln == "" or ln.startswith((" ", "\t")):
            continue
        if ln.rstrip().startswith("relations:"):
            start = i
            break
    if start is None:
        return None
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        if ln == "" or ln.startswith((" ", "\t")) or ln.startswith("- "):
            end += 1
        else:
            break
    return start, end


def rewrite_relations_block(fm_text: str, stub: Stub, replacement: str | None) -> tuple[str, int]:
    """Rewrite only the ``relations:`` block of a frontmatter string.

    Relations whose target is the stub are dropped (replacement is None) or
    repointed (replacement is a real slug). Returns (new_text, changed_count).
    If nothing changes, the original string is returned with count 0.
    """
    lines = fm_text.split("\n")
    span = _relations_block_span(lines)
    if span is None:
        return fm_text, 0
    start, end = span
    block_text = "\n".join(lines[start:end])
    try:
        current = yaml.safe_load(block_text) or {}
    except yaml.YAMLError:
        return fm_text, 0  # unparseable -> conservative: leave as-is
    rels = current.get("relations") or []

    stub_keys = {stub.id, stub.path.stem}
    new_rels = []
    n = 0
    for r in rels:
        if isinstance(r, dict) and str(r.get("target")) in stub_keys:
            n += 1
            if replacement is not None:
                nr = dict(r)
                nr["target"] = replacement
                new_rels.append(nr)
            # else: drop the entry
        else:
            new_rels.append(r)
    if n == 0:
        return fm_text, 0

    dumped = yaml.safe_dump(
        {"relations": new_rels},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")
    new_lines = lines[:start] + dumped.split("\n") + lines[end:]
    return "\n".join(new_lines), n


def _rewrite_one_wikilink(m: re.Match, stub: Stub, replacement: str | None) -> str:
    inner = m.group(1)
    target = inner.split("#")[0].strip()
    if target not in {stub.id, stub.path.stem}:
        return m.group(0)
    if replacement is None:
        return ""  # remove the whole [[...]]
    # repoint: keep the alias / section parts, swap only the target
    section = ""
    if "#" in inner:
        section = inner[inner.find("#"):]
    inner_full = m.group(0)[2:-2]  # between [[ and ]]
    alias = ""
    if "|" in inner_full:
        alias = inner_full.split("|", 1)[1]
    return f"[[{replacement}{section}{'|' + alias if alias else ''}]]"


def rewrite_wikilinks(body: str, stub: Stub, replacement: str | None) -> tuple[str, int]:
    """Remove or repoint every [[wikilink]] whose target is the stub."""
    n = 0

    def _sub(m: re.Match) -> str:
        nonlocal n
        res = _rewrite_one_wikilink(m, stub, replacement)
        if res != m.group(0):
            n += 1
        return res

    return WIKILINK_RE.sub(_sub, body), n


def rewrite_page(index: WikiIndex, path: Path, stub: Stub, replacement: str | None) -> int:
    """Apply repoint/remove for *stub* to one referring page. Returns #changes."""
    raw, nl, text = index.pages[path]
    m = FRONT_RE.match(text)
    if not m:
        new_body, n2 = rewrite_wikilinks(text, stub, replacement)
        if n2:
            index.pages[path] = (raw, nl, new_body)
        return n2
    new_fm, n1 = rewrite_relations_block(m.group(1), stub, replacement)
    new_body, n2 = rewrite_wikilinks(m.group(2), stub, replacement)
    if n1 == 0 and n2 == 0:
        return 0
    new_text = f"---\n{new_fm}\n---\n{new_body}"
    index.pages[path] = (raw, nl, new_text)
    return n1 + n2


# ---------------------------------------------------------------------------
# deletion
# ---------------------------------------------------------------------------

def _git_toplevel(wiki_root: Path) -> Path | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(wiki_root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    toplevel = r.stdout.strip()
    return Path(toplevel) if toplevel else None


def delete_stub(wiki_root: Path, stub: Stub) -> str:
    """git rm the stub; fall back to os.remove if untracked. Returns "git"|"os"."""
    toplevel = _git_toplevel(wiki_root)
    if toplevel is not None:
        try:
            r = subprocess.run(
                ["git", "-C", str(toplevel), "rm", "-f", "--quiet", "--", str(stub.path)],
                capture_output=True, text=True, timeout=60,
            )
            if r.returncode == 0:
                return "git"
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        os.remove(stub.path)
    except FileNotFoundError:
        pass
    return "os"


# ---------------------------------------------------------------------------
# plan / CLI
# ---------------------------------------------------------------------------

def _action_label(stub: Stub, replacement: str | None, refs: list[Reference]) -> str:
    if replacement is not None:
        return f"repoint→{replacement}"
    if refs:
        return "remove-ref"
    return "delete"


def build_plan(index: WikiIndex, stubs: list[Stub]) -> list[tuple[Stub, str | None, list[Reference]]]:
    """Compute the full change plan (stub, replacement|None, referrers)."""
    plan = []
    for s in stubs:
        refs = find_references(index, s)
        replacement = resolve_repoint(index, s)
        plan.append((s, replacement, refs))
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description="Cleanup stub/placeholder wiki pages.")
    ap.add_argument("wiki_root", nargs="?", default="knowledge/novel-wiki",
                    help="wiki root (parent of the wiki/ dir). default: knowledge/novel-wiki")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="execute the cleanup (writes + deletes). DEFAULT is dry-run.")
    mode.add_argument("--dry-run", action="store_true",
                      help="print the plan, change nothing (default).")
    ap.add_argument("--max", type=int, default=None,
                    help="stop after N stubs in --apply mode (safety).")
    args = ap.parse_args()

    wiki_root = Path(args.wiki_root).resolve()
    apply_mode = args.apply

    index = WikiIndex(wiki_root)
    stubs = index.scan()
    bucket_counts = Counter(s.bucket for s in stubs)
    # Group the plan by bucket then id for a readable report.
    bucket_order = {"raw_or_path": 0, "tag_like": 1, "type_prefix": 2,
                    "entity_suffix": 3, "source_like": 4, "clean": 5}
    stubs.sort(key=lambda s: (bucket_order.get(s.bucket, 9), s.id))
    plan = build_plan(index, stubs)

    print(f"wiki_root: {wiki_root}")
    print(f"stubs found: {len(stubs)}")
    for b in ("raw_or_path", "tag_like", "type_prefix", "entity_suffix", "source_like", "clean"):
        if bucket_counts.get(b):
            print(f"  {b:<14} {bucket_counts[b]}")
    n_rep = sum(1 for _, repl, _ in plan if repl is not None)
    n_rem = sum(1 for s, repl, refs in plan if repl is None and refs)
    n_del = sum(1 for s, repl, refs in plan if repl is None and not refs)
    print(f"plan: repoint {n_rep} | remove-ref {n_rem} | delete {n_del}")
    print("=" * 78)

    if not apply_mode:
        for s, replacement, refs in plan:
            print(f"STUB {s.id}  [{s.bucket}]  -> {_action_label(s, replacement, refs)}")
            if not refs:
                continue
            for r in refs:
                kind = "rel" if r.kind == "relation" else "wiki"
                where = r.page_path.relative_to(wiki_root)
                print(f"    {kind:<4} {where}")
        print("=" * 78)
        print("DRY-RUN: nothing written. Re-run with --apply to execute (use --max N to limit).")
        return 0

    # --- apply mode ---
    repointed = 0
    removed = 0
    deleted = 0
    processed = 0

    for s, replacement, refs in plan:
        if args.max is not None and processed >= args.max:
            print(f"--max {args.max} reached; stopping.")
            break
        processed += 1

        rewritten: set[Path] = set()
        for r in refs:
            n = rewrite_page(index, r.page_path, s, replacement)
            if n:
                rewritten.add(r.page_path)
                if replacement is not None:
                    repointed += n
                else:
                    removed += n
        for p in rewritten:
            _raw, nl, text = index.pages[p]
            _save(p, nl, text)

        how = delete_stub(wiki_root, s)
        deleted += 1
        print(f"STUB {s.id}  [{s.bucket}]  {_action_label(s, replacement, refs)}  "
              f"(deleted via {how})")

    print("=" * 78)
    print(f"SUMMARY  stubs processed: {processed} / {len(stubs)}")
    print(f"  references repointed: {repointed}")
    print(f"  references removed:   {removed}")
    print(f"  stub pages deleted:   {deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
