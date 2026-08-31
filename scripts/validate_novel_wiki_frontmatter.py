"""Validation tool (V4 schema): check novel-wiki WikiPage frontmatter against
the strict 8-key template in
`docs/architecture/novel-wiki-fields-template-2026-08-31.md`.

V4 schema (8 keys, strict whitelist):
    id, title, type, relations, tags, sources, created_at, updated_at

Any other top-level key triggers P0 (FAIL).

The script is read-only by default. Use --strict to fail on any P0.

Usage:
    python scripts/validate_novel_wiki_frontmatter.py [--strict] [wiki_root]

    # default wiki_root = ./knowledge/novel-wiki/wiki
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# V4 Schema (8 keys, strict)
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = frozenset({
    "id", "title", "type", "relations", "tags", "sources",
    "created_at", "updated_at",
})
ALLOWED_FIELDS = REQUIRED_FIELDS  # V4: NO extra fields allowed
ALLOWED_TYPES = frozenset({"source", "entity", "concept", "synthesis"})

TYPE_DIRS = {"concepts", "sources", "entities", "synthesis", "_stubs"}
RESERVED_FILES = {"index.md", "log.md"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    path: str
    severity: str  # "P0" | "P1"
    code: str
    message: str


@dataclass
class PageReport:
    findings: list[Finding] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Frontmatter parser (tolerant to malformed delimiters)
# ---------------------------------------------------------------------------
def parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Return ({key: raw_value_string}, fm_body) or None if no frontmatter.

    Handles two cases:
      1. Strict: `^---\\n(.*?)\\n---\\s*\\n`
      2. Malformed (closing `---` glued to previous line):
         scan top-level keys starting from line 1 until first non-key line.
    """
    m = re.match(r"(?s)^---\s*\n(.*?)\n---\s*\n", text)
    if m:
        return _fields_from_block(m.group(1))

    if not text.startswith("---"):
        return None
    body_lines: list[str] = []
    for line in text.splitlines()[1:]:
        if not line.strip():
            if body_lines:
                break
            continue
        if re.match(r"^\s*-\s+", line):
            body_lines.append(line)
            continue
        if re.match(r"^\s*#", line):
            if body_lines:
                break
            continue
        if re.match(r"^[\w_-]+:", line):
            body_lines.append(line)
            continue
        break
    return _fields_from_block("\n".join(body_lines))


def _fields_from_block(body: str) -> tuple[dict[str, str], str]:
    fields: dict[str, str] = {}
    for line in body.splitlines():
        km = re.match(r"^([\w_-]+):\s*(.*)$", line)
        if km:
            fields[km.group(1)] = km.group(2)
    # Normalize empty multiline list/dict values to "<present>"
    for ml in ("relations", "tags", "sources"):
        if ml in fields and not fields[ml].strip():
            fields[ml] = "<present>"
    return fields, body


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def validate_page(md_path: Path, wiki_root: Path) -> PageReport:
    report = PageReport()
    rel = md_path.relative_to(wiki_root)
    if rel.parts[0] not in TYPE_DIRS:
        return report

    text = md_path.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    if parsed is None:
        report.findings.append(Finding(
            path=str(rel), severity="P0", code="V4001",
            message="no frontmatter delimiters (--- ... ---)"
        ))
        return report

    fields, _ = parsed
    page_id = fields.get("id", "")

    # P0: required fields
    for req in REQUIRED_FIELDS:
        if req not in fields or not fields[req].strip():
            report.findings.append(Finding(
                path=str(rel), severity="P0", code="V4010",
                message=f"missing required field: {req}"
            ))

    # P0: id matches filename
    expected_id = md_path.stem
    if page_id and page_id != expected_id:
        report.findings.append(Finding(
            path=str(rel), severity="P0", code="V4011",
            message=f"id mismatch: '{page_id}' != filename '{expected_id}'"
        ))

    # P0: type enum
    ptype = fields.get("type", "")
    if ptype and ptype not in ALLOWED_TYPES:
        report.findings.append(Finding(
            path=str(rel), severity="P0", code="V4012",
            message=f"type '{ptype}' not in {sorted(ALLOWED_TYPES)}"
        ))

    # P0: strict whitelist — any unknown field fails
    for k in fields:
        if k not in ALLOWED_FIELDS:
            report.findings.append(Finding(
                path=str(rel), severity="P0", code="V4020",
                message=f"unknown field '{k}' — V4 strict whitelist: {sorted(ALLOWED_FIELDS)}"
            ))
            report.unknown_fields.append(k)

    return report


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("wiki_root", nargs="?", default="knowledge/novel-wiki/wiki")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any P0 present")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root).resolve()
    if not wiki_root.is_dir():
        print(f"error: not a directory: {wiki_root}", file=sys.stderr)
        return 2

    scanned = 0
    findings_total: list[Finding] = []
    unknown_counter: Counter = Counter()
    for md in sorted(wiki_root.rglob("*.md")):
        if md.name in RESERVED_FILES:
            continue
        scanned += 1
        rep = validate_page(md, wiki_root)
        findings_total.extend(rep.findings)
        unknown_counter.update(rep.unknown_fields)

    by_severity: dict[str, list[Finding]] = {"P0": [], "P1": []}
    for f in findings_total:
        by_severity.setdefault(f.severity, []).append(f)

    print(f"[validate-v4] scanned={scanned} wiki_root={wiki_root}")
    print(f"[validate-v4] P0={len(by_severity['P0'])}")
    print()
    print("=== P0 findings (top 20 by code) ===")
    by_code: Counter = Counter()
    for f in by_severity["P0"]:
        by_code[(f.code, f.message.split("'")[1] if "'" in f.message else f.message)] += 1
    for (code, fname), n in by_code.most_common(20):
        print(f"  {code} '{fname}': {n} pages")

    if by_severity["P0"]:
        print()
        print("=== P0 sample (first 10) ===")
        for f in by_severity["P0"][:10]:
            print(f"  {f.path}: {f.code} {f.message}")

    if unknown_counter:
        print()
        print("=== Unknown fields histogram (fields to be removed during V4 migration) ===")
        for fname, n in unknown_counter.most_common():
            print(f"  {fname:<20} {n:>5} pages")

    if args.strict and by_severity["P0"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())