"""batch_gate_check.py — NDG per-batch quality gate CLI (Phase 3).

Runs the full NDG gate (P1–P7 + P4b) against a batch's wiki pages.
All check logic lives in :mod:`src.wiki.features.ndg_gate` so the
CLI and the programmatic API stay in lock-step.

Usage:
    env PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/batch_gate_check.py \\
      <wiki_root> <page1.md> [page2.md ...]

    # Also accepts --raw-header <raw_path>:<header> for P4b UGC detection:
    env PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/batch_gate_check.py \\
      <wiki_root> page.md --raw-header raw/sources/a.txt:"feishu.cn document"

Exit code: 0 = gate passed, 1 = blockers found, 2 = usage error.
"""
from __future__ import annotations

import sys
from pathlib import Path

from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import read_page
from src.wiki.features.ndg_gate import run_ndg_gate, GateReport


def _parse_raw_headers(args: list[str]) -> dict[str, str]:
    """Parse ``--raw-header path:value`` pairs from positional-style args."""
    headers: dict[str, str] = {}
    for a in args:
        if a.startswith("--raw-header="):
            _, val = a.split("=", 1)
            if ":" in val:
                path, header = val.split(":", 1)
                headers[path] = header
    return headers


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])

    # Separate page paths from --raw-header flags
    page_args = [a for a in args if not a.startswith("--")]
    raw_headers = _parse_raw_headers(args)

    if len(page_args) < 2:
        print("usage: batch_gate_check.py <wiki_root> <page1.md> [page2.md ...] "
              "[--raw-header=raw/sources/x.txt:header_text]")
        return 2

    wiki_root = Path(page_args[0])
    page_paths = [wiki_root / p for p in page_args[1:]]
    paths = WikiPaths(wiki_root)

    pages = []
    for p in page_paths:
        if not p.is_file():
            print(f"[gate] MISSING: {p}", file=sys.stderr)
            # Missing file is a blocker
            pages.clear()
            break
        try:
            pages.append(read_page(p))
        except Exception as exc:
            print(f"[gate] UNREADABLE: {p.name}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            pages.clear()
            break

    if not pages:
        return 1  # missing or unreadable file → block

    report = run_ndg_gate(pages, raw_headers=raw_headers or None, paths=paths)

    print(f"[gate] {len(pages)} page(s): "
          f"{'PASS' if report.passed else 'FAIL'} "
          f"({len(report.issues)} issue(s), "
          f"{report.blocker_count} blocker(s))")
    for issue in report.issues:
        tag = "BLOCK" if issue.is_blocker else "WARN"
        pid = issue.page_id or "-"
        print(f"  [{tag}] {issue.code} {pid}: {issue.message}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
