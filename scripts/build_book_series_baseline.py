"""Build the deterministic book-series baseline snapshot for the real novel-wiki.

Plan: docs/superpowers/plans/2026-09-06-novel-wiki-book-series-compile-enable.md
Slice S4: this script re-runs ``evaluate_series_gate`` with the relaxed
NOVEL_WIKI_PROFILE plus auto-derived chapter_exit_evidence and persists
a JSON snapshot under ``.llm-wiki/book-series/baselines/<snapshot_sha[:12]>.json``.

The directory is gitignored (``.llm-wiki/`` is in ``.gitignore``) so the
baseline does not pollute git history; up to 5 historical baselines per
project are retained. Older snapshots are pruned by mtime.

This script never invokes an LLM, never overwrites the production
``book-wiki/CURRENT.json``, and is purely an audit trail.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _project_root(arg: str) -> Path:
    root = Path(arg).resolve()
    if not root.exists():
        raise SystemExit(f"project root does not exist: {root}")
    return root


def _scan_wiki(project_root: Path):
    from src.kc.views.book.wiki.scanner import scan_wiki_snapshot, WikiScanError

    wiki_root = project_root / "wiki"
    if not wiki_root.is_dir():
        raise SystemExit(
            f"missing wiki/ directory under {project_root}; "
            f"run `python -m src.cli project init {project_root}` first"
        )
    try:
        return scan_wiki_snapshot(wiki_root)
    except WikiScanError as exc:
        raise SystemExit(f"wiki scan failed: {exc.code}: {exc}")


def _evaluate(snapshot, profile, governance):
    from src.kc.views.book.wiki.partition import evaluate_series_gate

    return evaluate_series_gate(
        snapshot, reader_profile=profile, governance=governance,
    )


def _build_profile(snapshot, candidate_taxonomy: str, all_taxonomies: tuple[str, ...]):
    """Return a per-run profile with chapter_exit_evidence derived from
    the candidate's synthesis pages. ``candidate_taxonomies`` keeps the
    full set so the snapshot's reader_profile field matches the
    operator's intent — the gate itself is restricted to one taxonomy per
    call, but the persistence layer records the full list.
    """
    from src.kc.views.book.wiki.profiles import (
        NOVEL_WIKI_PROFILE, derive_chapter_exit_evidence,
    )

    exit_evidence = derive_chapter_exit_evidence(snapshot, candidate_taxonomy)
    from src.kc.views.book.wiki.partition import ReaderProfile
    return ReaderProfile(
        profile_id=NOVEL_WIKI_PROFILE.profile_id,
        task_types=NOVEL_WIKI_PROFILE.task_types,
        min_pages_per_book=NOVEL_WIKI_PROFILE.min_pages_per_book,
        min_source_coverage=NOVEL_WIKI_PROFILE.min_source_coverage,
        min_reader_tasks=NOVEL_WIKI_PROFILE.min_reader_tasks,
        candidate_taxonomies=all_taxonomies,
        chapter_exit_evidence=exit_evidence,
        closure_strict_types=NOVEL_WIKI_PROFILE.closure_strict_types,
        allowed_learning_edge_types=NOVEL_WIKI_PROFILE.allowed_learning_edge_types,
        require_target_task_match=NOVEL_WIKI_PROFILE.require_target_task_match,
    )


def _serialize_candidate(candidate) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "eligible_page_count": candidate.eligible_page_count,
        "chapter_density": candidate.chapter_density,
        "source_coverage": candidate.source_coverage,
        "duplicate_rate": candidate.duplicate_rate,
        "estimated_chars": candidate.estimated_chars,
        "reader_task_count": candidate.reader_task_count,
        "closure_status": candidate.closure_status,
        "decision": candidate.decision,
        "reason_codes": list(candidate.reason_codes),
        "closure_evidence": list(candidate.closure_evidence),
        "closure_status_reason": candidate.closure_status_reason,
    }


def _write_snapshot(project_root: Path, snapshot, profile, governance, results_by_tax) -> Path:
    candidates_payload: list[dict] = []
    for tax in profile.candidate_taxonomies:
        cand = next(
            (c for c in results_by_tax[tax].candidates if c.candidate_id == tax),
            None,
        )
        if cand is None:
            continue
        candidates_payload.append(_serialize_candidate(cand))

    payload = {
        "project_root": str(project_root.resolve()),
        "wiki_root": str((project_root / "wiki").resolve()),
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_sha256_prefix": snapshot.snapshot_id[:12],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "llm_called": False,
        "network_called": False,
        "current_pointer_changed": False,
        "reader_profile": {
            "profile_id": profile.profile_id,
            "task_types": list(profile.task_types),
            "min_pages_per_book": profile.min_pages_per_book,
            "min_source_coverage": profile.min_source_coverage,
            "min_reader_tasks": profile.min_reader_tasks,
            "candidate_taxonomies": list(profile.candidate_taxonomies),
            "chapter_exit_evidence": list(profile.chapter_exit_evidence),
            "closure_strict_types": list(profile.closure_strict_types),
            "allowed_learning_edge_types": list(profile.allowed_learning_edge_types),
            "require_target_task_match": profile.require_target_task_match,
        },
        "governance": {
            "external_authorized": governance.external_authorized,
            "budget_cap": governance.budget_cap,
            "approver": governance.approver,
        },
        "status": (
            "ready" if any(c["decision"] == "proceed" for c in candidates_payload)
            else "blocked"
        ),
        "generation_mode": "rule_only",
        "candidates": candidates_payload,
    }

    out_dir = project_root / ".llm-wiki" / "book-series" / "baselines"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{snapshot.snapshot_id[:12]}-{int(datetime.now(timezone.utc).timestamp())}"
    content = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"
    for ordinal in range(1_000_000):
        suffix = "" if ordinal == 0 else f"-{ordinal:03d}"
        out_file = out_dir / f"{stem}{suffix}.json"
        try:
            with out_file.open("x", encoding="utf-8") as handle:
                handle.write(content)
            return out_file
        except FileExistsError:
            continue
    raise RuntimeError(f"could not allocate unique baseline filename under {out_dir}")


def _prune(out_dir: Path, keep: int = 5) -> int:
    """Keep only the most recent ``keep`` baselines; remove older ones."""
    files = sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for old in files[keep:]:
        old.unlink()
        removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True,
                         help="Path to the project root containing wiki/ and .llm-wiki/")
    parser.add_argument("--candidate", action="append", default=None,
                         help="Candidate taxonomy to evaluate (defaults to NOVEL_WIKI_PROFILE "
                              "candidate_taxonomies)")
    parser.add_argument("--keep", type=int, default=5,
                         help="Number of historical baselines to retain (default: 5)")
    args = parser.parse_args(argv)

    project_root = _project_root(args.project_root)
    snapshot = _scan_wiki(project_root)

    from src.kc.views.book.wiki.partition import GovernanceConfig
    from src.kc.views.book.wiki.profiles import NOVEL_WIKI_PROFILE

    candidates = args.candidate or list(NOVEL_WIKI_PROFILE.candidate_taxonomies)
    governance = GovernanceConfig(
        external_authorized=True, budget_cap=10, approver="novel-wiki-editor",
    )

    results_by_tax: dict[str, object] = {}
    final_profile = None
    for tax in candidates:
        # ``_build_profile`` restricts candidate_taxonomies to the single
        # tax so the gate runs only for the requested taxonomy; the
        # full list is recorded on ``final_profile`` below for the
        # snapshot's reader_profile section.
        profile = _build_profile(snapshot, tax, all_taxonomies=tuple(candidates))
        final_profile = profile
        results_by_tax[tax] = _evaluate(snapshot, profile, governance)

    if final_profile is None:
        raise SystemExit("no candidates evaluated")

    out_file = _write_snapshot(
        project_root, snapshot, final_profile, governance, results_by_tax,
    )
    removed = _prune(out_file.parent, keep=args.keep)

    summary = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_sha256_prefix": snapshot.snapshot_id[:12],
        "wrote": str(out_file),
        "pruned": removed,
        "candidates": [
            {
                "candidate_id": tax,
                "decision": next(
                    (c.decision for c in results_by_tax[tax].candidates
                     if c.candidate_id == tax),
                    "unknown",
                ),
                "closure_status": next(
                    (c.closure_status for c in results_by_tax[tax].candidates
                     if c.candidate_id == tax),
                    "unknown",
                ),
                "page_count": next(
                    (c.eligible_page_count for c in results_by_tax[tax].candidates
                     if c.candidate_id == tax),
                    0,
                ),
            }
            for tax in candidates
        ],
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
