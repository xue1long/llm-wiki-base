"""Apply novel-wiki dedup decisions (dedup-decisions-20260904.json).

wiki-repair-novel-wiki §7: collapse the 30 duplicate-title groups per the
operator-reviewed decisions. Three action classes, applied one at a time
so each lands as its own commit:

--action supersede   (21 groups, rule card-id-suffix-collision)
    winner stays in sources/ untouched. Each loser: rewrite every
    in-corpus reference loser_id -> winner_id, git mv
    sources/<loser>.md -> _stubs/<loser>.md, retitle distinctly
    (scanner counts _stubs), append a ``superseded_by`` RELATION (V5
    8-key whitelist forbids a bare frontmatter key) to the winner's id.

--action cross-type  (7 groups, rule same-id-different-type)
    a concept and an entity share the same id+title; decision labels it
    "alias" but a flat id->id alias is inexpressible (alias == canonical)
    and the registry has no type dimension. entity twin is a confirmed
    orphan -> git mv entities/<id>.md -> _stubs/<id>.md + distinct
    retitle. NO superseded_by (would self-loop). Abort if any inbound
    ``entities/<id>`` reference is ever found.

--action disambiguate (2 groups, rule manual-review)
    retitle ONLY the source member (id/path unchanged -> all inbound,
    which targets the id, stays intact). Hardcoded map keyed by page id.

Always dry-run by default; --apply performs. Audit JSON written to
knowledge/novel-wiki/.index/quality/ regardless. Encoding discipline:
every file read/written as UTF-8 with newline='' so CRLF/LF survive.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DECISIONS = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality" / "dedup-decisions-20260904.json"
DEFAULT_WIKI = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"
DEFAULT_QUALITY_DIR = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"

# id -> disambiguated title (source members only; ids verified by hand)
DISAMBIGUATE_RETITLE = {
    "入门教程写手境界-fb364b85": "写手境界（入门教程）",
    "方法论侦探小说二十守则-a0c6c278": "侦探小说二十守则（方法论）",
}

TYPE_ITEMS = {"concepts", "sources", "entities", "synthesis", "_stubs"}
_ARCHIVE_TITLE_SUFFIX = "（已归档）"


def _read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def _iter_md(wiki_root: Path):
    """Yield (path, rel) for every page under the type dirs.

    index.md / log.md are deliberately excluded: index rows are edited via
    dedicated row ops, and log.md is an audit trail that must not be
    rewritten by content migrations.
    """
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) >= 2 and rel.parts[0] in TYPE_ITEMS:
            yield md, rel


def _fm_split(text: str) -> tuple[str, str] | None:
    """Return (frontmatter_body, rest) or None when no `---\\n...\\n---`.

    rest starts AFTER the closing delimiter's newline, so a caller can
    rebuild as `"---\\n" + new_body + "\\n---\\n" + rest` exactly.
    """
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    close_end = end + 4  # first char after the closing '---'
    if text[close_end:close_end + 1] == "\n":
        close_end += 1  # consume the newline that follows the delimiter
    return text[4:end], text[close_end:]


def _relation_item_lines(type_: str, target_: str, indent: str) -> list[str]:
    cont = indent + "  "
    return [f"{indent}- type: {type_}", f"{cont}target: {target_}"]


def _append_relation(text: str, type_: str, target_: str) -> str:
    """Append one relation dict to the frontmatter `relations` list.

    Handles `relations: []`, an empty `relations:` key, and an existing
    indented `- item` block. Idempotent on (type, target).
    """
    split = _fm_split(text)
    if split is None:
        return text
    fm, rest = split
    lines = fm.split("\n")

    ridx = None
    for i, ln in enumerate(lines):
        if re.match(r"^relations:\s*$", ln):
            ridx = i
            break
        if re.match(r"^relations:\s*\[\s*\]\s*$", ln):
            lines[i] = "relations:"
            ridx = i
            break
    if ridx is None:
        return text  # no relations key; leave untouched

    # indentation of existing items
    item_re = re.compile(r"^(\s*)- ")
    indent = "  "
    for ln in lines[ridx + 1:]:
        m = item_re.match(ln)
        if m:
            indent = m.group(1)
            break
        if ln and not ln.startswith((" ", "\t")):
            break  # next top-level key reached -> no items

    # idempotent: skip when an item with this (type, target) already exists,
    # in either the canonical (- type then target) or hand-written
    # (target then type) key order.
    cont = indent + "  "
    block_txt = "\n".join(lines[ridx:])
    for order in (
        f"{indent}- type: {type_}\n{cont}target: {target_}",
        f"{indent}- target: {target_}\n{cont}type: {type_}",
    ):
        if order in block_txt:
            return text

    new_items = _relation_item_lines(type_, target_, indent)

    # insertion point: after the relations line if no item block, else
    # after the last non-blank line of the current item block.
    last_non_blank = ridx
    for j in range(ridx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        if ln.startswith((" ", "\t")):
            last_non_blank = j
        else:
            break
    insert_at = last_non_blank
    lines[insert_at + 1:insert_at + 1] = new_items

    return "---\n" + "\n".join(lines) + "\n---\n" + rest


def _set_title(text: str, new_title: str) -> str:
    """Replace the `title:` value in frontmatter."""
    split = _fm_split(text)
    if split is None:
        return text
    fm, rest = split
    out = []
    for ln in fm.split("\n"):
        if ln.startswith("title:"):
            out.append(f"title: {new_title}")
        else:
            out.append(ln)
    return "---\n" + "\n".join(out) + "\n---\n" + rest


def _remove_index_rows(index_text: str, page_id: str, type_dir: str | None = None) -> str:
    """Drop index.md catalog rows for page_id (optionally filtered by type)."""
    type_label = {
        "concepts": "concept", "sources": "source", "entities": "entity", "synthesis": "synthesis",
    }.get(type_dir, "") if type_dir else ""
    keep = []
    for ln in index_text.split("\n"):
        if f"**{page_id}**" in ln:
            if type_label and f"({type_label})" not in ln:
                keep.append(ln)
                continue
            continue  # drop row
        keep.append(ln)
    # join over the split list reproduces the original trailing-newline state
    # exactly — no extra append here.
    return "\n".join(keep)


def _ensure_concept_row(index_text: str, page_id: str, concept_title: str) -> str:
    """Return index text carrying exactly ONE concept catalog row for page_id.

    The catalog is keyed by id, so when an entity twin registered the row
    first, the same-id canonical concept never got its own. Archiving the twin
    must therefore leave the id catalogued as the concept: transform the
    entity row in place, keep an existing concept row, or append a fresh one
    when neither is present.
    """
    lines = index_text.split("\n")
    out: list[str] = []
    has_concept = False
    for ln in lines:
        if f"**{page_id}**" not in ln:
            out.append(ln)
            continue
        if "(concept)" in ln:
            has_concept = True
            out.append(ln)
            continue
        if "(entity)" in ln:
            if has_concept:
                continue  # id already catalogued as concept; drop the twin
            ln = re.sub(r"\(entity\)", "(concept)", ln, count=1)
            ln = re.sub(r"— .*$", "— " + concept_title, ln)
            has_concept = True
            out.append(ln)
            continue
        out.append(ln)
    text = "\n".join(out)
    if not has_concept:
        if not text.endswith("\n"):
            text += "\n"
        text += f"- **{page_id}** (concept) — {concept_title}\n"
    return text


def _rewrite_index_title(index_text: str, page_id: str, new_title: str) -> str:
    """Update the trailing title of the index row for page_id."""
    out = []
    for ln in index_text.split("\n"):
        if f"**{page_id}**" in ln and "— " in ln:
            ln = re.sub(r"— .*$", "— " + new_title, ln)
        out.append(ln)
    return "\n".join(out)


def _scan_inbound(wiki_root: Path, page_id: str, prefix: str | None, exclude_paths: set,
                  boundary: bool = False) -> list[dict]:
    """Count occurrences of a page id as a reference target across the wiki.

    prefix: e.g. 'entities/' matches `[[entities/<id>]]`-style references
    only (to separate a bare id twin from its same-id canonical). When
    prefix is None, every occurrence of the exact id counts.

    boundary: require the id be a COMPLETE segment, not a prefix of a longer
    id. Otherwise `entities/玄幻小说` would false-match the distinct page
    `entities/玄幻小说创作入门指南` (different id, shared CJK prefix). The
    next character after the id must not extend an id (CJK block + [A-Za-z0-9-]).
    """
    hits = []
    if prefix:
        if boundary:
            rx = re.compile(re.escape(prefix) + re.escape(page_id) + r"(?![A-Za-z0-9-一-鿿])")
        else:
            needle = f"{prefix}{page_id}"
    else:
        needle = page_id
    for md, rel in _iter_md(wiki_root):
        if md in exclude_paths:
            continue
        text = _read(md)
        n = len(rx.findall(text)) if boundary else text.count(needle)
        if n:
            hits.append({"file": str(rel), "occurrences": n})
    return hits


def _existing_titles(wiki_root: Path) -> dict[str, list[str]]:
    titles: dict[str, list[str]] = {}
    for md, _rel in _iter_md(wiki_root):
        text = _read(md)
        sp = _fm_split(text)
        if sp is None:
            continue
        fm, _ = sp
        for ln in fm.split("\n"):
            if ln.startswith("title:"):
                t = ln[6:].strip()
                if t:
                    titles.setdefault(t, []).append(str(md.relative_to(wiki_root)))
                break
    return titles


def _act_supersede(wiki_root: Path, decision: dict, apply: bool) -> dict:
    title = decision["title"]
    winner = decision["canonical"]
    losers = decision.get("superseded") or []
    multi = len(losers) > 1
    result = {"group_title": title, "action": "supersede", "winner": winner["id"], "losers": []}

    for i, los in enumerate(losers, 1):
        lid, wpath = los["id"], winner["id"]
        lpath = wiki_root / los["path"]
        winner_path = wiki_root / winner["path"]
        # NB: multi-loser suffix has NO space before the number — an unquoted
        # YAML scalar truncates at " #" (comment start), which would collapse
        # both losers back onto one truncated duplicate title.
        rec = {"loser_id": lid, "rewire": [], "retitle": f"{title}{_ARCHIVE_TITLE_SUFFIX if not multi else f'（已归档·{i}）'}"}
        if not lpath.exists() or not winner_path.exists():
            rec["error"] = "missing loser or winner file"
            result["losers"].append(rec)
            continue
        # 1. inbound rewire loser_id -> winner_id (exclude the loser page —
        #    its own `id:` must stay; index rows are handled separately).
        hits = _scan_inbound(wiki_root, lid, None, exclude_paths={lpath.resolve()})
        rec["rewire"] = hits
        if apply:
            for h in hits:
                p = wiki_root / h["file"]
                _write(p, _read(p).replace(lid, wpath))
        # 2. move + retitle + superseded_by relation
        dst = wiki_root / "_stubs" / f"{lid}.md"
        if apply:
            if not dst.parent.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
            text = _read(lpath)
            text = _set_title(text, rec["retitle"])
            text = _append_relation(text, "superseded_by", wpath)
            _write(lpath, text)
            r = _git(["mv", str(lpath.relative_to(REPO_ROOT)), str(dst.relative_to(REPO_ROOT))])
            if r.returncode != 0:
                rec["error"] = f"git mv failed: {r.stderr.strip()}"
            # 3. drop index row
            ip = wiki_root / "index.md"
            _write(ip, _remove_index_rows(_read(ip), lid, "sources"))
            rec["moved_to"] = str(dst.relative_to(REPO_ROOT))
        else:
            rec["moved_to"] = f"_stubs/{lid}.md"
        result["losers"].append(rec)
    return result


def _act_cross_type(wiki_root: Path, decision: dict, apply: bool) -> dict:
    canon = decision["canonical"]
    twins = decision.get("aliases_to_register") or []
    result = {"group_title": decision["title"], "action": "archive_cross_type", "canonical": canon["id"], "twins": []}
    for t in twins:
        tpath = wiki_root / t["path"]
        rec = {"twin_id": t["id"], "path": t["path"]}
        if t["id"] != canon["id"]:
            rec["error"] = "twin id != canonical id; not archiving"
            result["twins"].append(rec)
            continue
        # cross-type twin must have NO `entities/<id>` inbound (boundary-aware:
        # the bare id here is often a CJK prefix of unrelated longer entity ids)
        inbound = _scan_inbound(wiki_root, t["id"], "entities/", exclude_paths={tpath.resolve()},
                                boundary=True)
        if inbound:
            rec["error"] = "unexpected inbound entities/<id> references; aborting this twin"
            rec["inbound"] = inbound
            result["twins"].append(rec)
            continue
        rec["inbound"] = inbound
        if not tpath.exists():
            rec["error"] = "entity twin file missing"
            result["twins"].append(rec)
            continue
        dst = wiki_root / "_stubs" / f"{t['id']}.md"
        orig_title = decision["title"]
        rec["retitle"] = f"{orig_title}（已归档·实体条目）"
        if apply:
            if not dst.parent.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
            text = _read(tpath)
            text = _set_title(text, rec["retitle"])
            _write(tpath, text)
            r = _git(["mv", str(tpath.relative_to(REPO_ROOT)), str(dst.relative_to(REPO_ROOT))])
            if r.returncode != 0:
                rec["error"] = f"git mv failed: {r.stderr.strip()}"
            ip = wiki_root / "index.md"
            text = _read(ip)
            # drop the twin row but keep the id catalogued as the canonical
            # concept (the entity may hold the sole row for a same-id concept).
            text = _remove_index_rows(text, t["id"], "entities")
            text = _ensure_concept_row(text, t["id"], decision["title"])
            _write(ip, text)
            rec["moved_to"] = str(dst.relative_to(REPO_ROOT))
        else:
            rec["moved_to"] = f"_stubs/{t['id']}.md"
        result["twins"].append(rec)
    return result


def _act_disambiguate(wiki_root: Path, decision: dict, apply: bool) -> dict:
    result = {"group_title": decision["title"], "action": "disambiguate", "retitles": []}
    for pg in decision.get("pages") or []:
        pid, new_title = pg["id"], DISAMBIGUATE_RETITLE.get(pg["id"])
        if not new_title:
            continue
        rec = {"page_id": pid, "path": pg["path"], "old_title": decision["title"], "new_title": new_title}
        p = wiki_root / pg["path"]
        if not p.exists():
            rec["error"] = "page file missing"
            result["retitles"].append(rec)
            continue
        if apply:
            text = _set_title(_read(p), new_title)
            _write(p, text)
            ip = wiki_root / "index.md"
            _write(ip, _rewrite_index_title(_read(ip), pid, new_title))
        result["retitles"].append(rec)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--action", required=True, choices=["supersede", "cross-type", "disambiguate"])
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki).resolve()
    decisions_path = Path(args.decisions).resolve()
    if not wiki_root.is_dir() or not decisions_path.is_file():
        print(f"error: --wiki {wiki_root} or --decisions {decisions_path} missing", file=sys.stderr)
        return 2

    data = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions = data["decisions"]

    action_key = {"supersede": "supersede", "cross-type": "alias", "disambiguate": "disambiguate"}
    sel = [d for d in decisions if d["recommended_action"] == action_key[args.action]]

    # collision guard for disambiguate new titles (live + would-be archived)
    if args.action == "disambiguate" and args.apply:
        titles = _existing_titles(wiki_root)
        for new_t in DISAMBIGUATE_RETITLE.values():
            if new_t in titles:
                print(f"error: new title collides with existing page: {new_t} ({titles[new_t]})", file=sys.stderr)
                return 2

    results = []
    for d in sel:
        if args.action == "supersede":
            results.append(_act_supersede(wiki_root, d, args.apply))
        elif args.action == "cross-type":
            results.append(_act_cross_type(wiki_root, d, args.apply))
        else:
            results.append(_act_disambiguate(wiki_root, d, args.apply))

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": str(wiki_root),
        "action": args.action,
        "applied": args.apply,
        "decisions_source": str(decisions_path),
        "groups": results,
    }
    out = (args.out or DEFAULT_QUALITY_DIR / f"apply-dedup-{args.action}-{datetime.datetime.now():%Y%m%d-%H%M%S}.json").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audit: {out}")
    if not args.apply:
        print("(dry-run; pass --apply to perform)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
