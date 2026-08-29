"""Read-only aggregate health summary for a wiki project."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from ..wiki.core.paths import WikiPaths
from ..wiki.features.slug_utils import normalize_reconcile_slug
from ..wiki.storage.page_writer import read_page


def build_content_health(paths: WikiPaths) -> dict:
    """Summarize page counts and recent triage failures without modifying data."""
    pages = []
    check_errors = []
    page_ids: set[str] = set()
    targets: set[str] = set()
    inbound: set[str] = set()
    for path in paths.wiki.rglob("*.md") if paths.wiki.exists() else []:
        if path.name in {"index.md", "log.md"}:
            continue
        try:
            page = read_page(path)
            pages.append(page)
            page_ids.add(page.id)
            for relation in page.relations:
                targets.add(relation.target)
            for target in re.findall(r"\[\[([^\]|#]+)", page.body):
                targets.add(target.strip())
        except Exception:
            check_errors.append({"path": str(path), "error": "invalid page"})
            continue

    triage_failures = 0
    triage_log = paths.index / "triage.log"
    if triage_log.exists():
        for line in triage_log.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("action") in {"skip", "source_only"}:
                    triage_failures += 1
            except json.JSONDecodeError:
                continue

    normalized_page_ids = {normalize_reconcile_slug(page_id) for page_id in page_ids}
    normalized_targets = {normalize_reconcile_slug(target) for target in targets}
    inbound = normalized_targets & normalized_page_ids
    return {
        "page_count": len(pages),
        "page_types": dict(Counter(p.type.value for p in pages)),
        "grades": dict(Counter(p.grade for p in pages)),
        "processing_depths": dict(Counter(p.processing_depth for p in pages)),
        "c_grade_count": sum(p.grade == "C" for p in pages),
        "stub_count": sum(p.processing_depth == "stub" for p in pages),
        "orphan_count": sum(
            p.type.value != "source" and p.id not in inbound for p in pages
        ),
        "dangling_link_count": len(normalized_targets - normalized_page_ids),
        "triage_non_process_count": triage_failures,
        "check_errors": check_errors,
    }
