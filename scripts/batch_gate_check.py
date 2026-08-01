"""batch_gate_check.py — Phase 4 #12: per-batch quality gate for re-ingestion.

Checks a batch's NEW/updated wiki pages for gate violations. Phase 4 runs this
after each ≤20-file batch so raw-paste pollution never re-enters the wiki layer
(RAG optimization: the full source text lives in raw/, the wiki body must be
distilled, not a raw echo).

Checks (deterministic, no LLM):
  - LINT-RAW-PASTE: non-SOURCE page whose body has a >300-char run of plain
    text with no blockquote/list/code-fence structure. SOURCE pages are exempt
    (their 正文内容 slot, when present, may legitimately carry content).

Reuses the exact lint logic (`src.wiki.features.lint._long_raw_text_run`,
`_RAW_PASTE_THRESHOLD`) so the gate and `cli lint` never disagree.

Usage (called by the Phase 4 batch runner with the batch's page files):
    env PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/batch_gate_check.py \
      <wiki_root> <page1.md> <page2.md> ...
Exit code: 0 = pass, 1 = violations found (batch must not proceed).

Historic-debt note: only the pages passed to this script are checked. Existing
pages that already carry RAW-PASTE are NOT re-flagged — they are a separate
cleanup backlog (Phase 3.1 lint already lists them).
"""
from __future__ import annotations

import sys
from pathlib import Path

from src.wiki.core.types import PageType
from src.wiki.storage.page_writer import read_page
from src.wiki.features.lint import _long_raw_text_run, _RAW_PASTE_THRESHOLD


def check_page(path: Path) -> list[str]:
    """Return gate violations for one page file (empty list = pass)."""
    try:
        page = read_page(path)
    except Exception as exc:  # unparseable page → treat as a violation
        return [f"UNREADABLE: {path.name}: {type(exc).__name__}: {exc}"]
    out: list[str] = []
    if page.type != PageType.SOURCE:
        run = _long_raw_text_run(page.body)
        if run > _RAW_PASTE_THRESHOLD:
            out.append(
                f"LINT-RAW-PASTE: {page.id} ({run}-char unstructured run in "
                f"body — distill or move verbatim text to raw/)"
            )
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print("usage: batch_gate_check.py <wiki_root> <page1.md> [page2.md ...]")
        return 2
    wiki_root = Path(args[0])
    pages = [Path(wiki_root) / p for p in args[1:]]

    violations: list[str] = []
    for p in pages:
        if not p.is_file():
            violations.append(f"MISSING: {p}")
            continue
        violations.extend(check_page(p))

    print(f"[gate] checked {len(pages)} batch page(s): {len(violations)} violation(s)")
    for v in violations:
        print(f"  {v}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
