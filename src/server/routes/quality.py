# src/server/routes/quality.py
"""Quality report endpoint — returns per-source quality summary.

Designed for the WebUI "质" button: the frontend calls this with
``source_path`` and renders a pass/fail badge + tooltip + modal.

The endpoint aggregates:
1. The most recent :class:`IngestReport` (verdict, warnings, etc.)
2. Open :class:`ReviewItem` entries whose ``source_task_id`` matches
3. Quarantine judgments (from the task's quarantine directory)
4. The wiki source page frontmatter (grade, title, body-level issues)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Query

from ...lib.project import resolve_project
from ...project.context import ProjectNotFoundError
from ...pipeline.ingest_report import IngestReport, REPORTS_DIR
from ...pipeline.quality_gate import _meaningful_length, _has_type_prefix
from ...wiki.features.review import load_reviews

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["quality"])


def _find_latest_report(reports_dir: Path, source_path: str) -> dict | None:
    """Scan ``.index/ingest_reports/`` for the most recent report matching
    *source_path*.

    Returns the deserialised report dict, or ``None`` if no match found.
    """
    if not reports_dir.is_dir():
        return None
    candidates: list[tuple[int, dict]] = []
    for fpath in sorted(reports_dir.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("source_path") == source_path:
            finished = data.get("finished_at", 0) or 0
            candidates.append((finished, data))
    if not candidates:
        return None
    # Most recent first (largest finished_at)
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def _load_review_items_for_task(
    paths,
    task_id: str,
) -> list[dict]:
    """Load open ReviewItems whose ``source_task_id`` matches *task_id*."""
    items = load_reviews(paths)
    return [
        {
            "id": i.id,
            "type": i.type,
            "title": i.title,
            "detail": i.detail,
            "confidence": i.confidence,
            "status": i.status,
        }
        for i in items
        if i.source_task_id == task_id
    ]


def _load_quarantine_summary(
    project_root: Path,
    task_id: str,
) -> list[dict]:
    """Load judgment sidecars from ``.index/quarantine/<task_id>/``."""
    qdir = project_root / ".index" / "quarantine" / task_id
    if not qdir.is_dir():
        return []
    results: list[dict] = []
    for jpath in sorted(qdir.glob("*.judgment.json")):
        try:
            data = json.loads(jpath.read_text(encoding="utf-8"))
            results.append({
                "page_id": jpath.stem.replace(".judgment", ""),
                "verdict": data.get("verdict", ""),
                "total_score": data.get("total_score", 0.0),
                "issues": data.get("issues", []),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return results


def _compute_overall_pass(report: dict | None, review_items: list, quarantine: list) -> bool:
    """Determine if the quality check passed overall.

    Pass if ALL of:
    - report exists (otherwise we can't know → fail)
    - verdict is "validated" (not rejected / needs_human_review / skipped)
    - no open review items for this task
    - no quarantined pages
    """
    if report is None:
        return False
    verdict = report.get("verdict", "")
    if verdict not in ("validated", "succeeded"):
        return False
    if review_items:
        return False
    if quarantine:
        return False
    return True


def _read_wiki_page_frontmatter(paths, source_path: str) -> dict:
    """Read grade + title + body-level issues from the wiki source page for *source_path*."""
    key = source_path.replace("\\", "/")
    grade = "B"
    title = None
    issues: list[str] = []

    if paths.wiki_sources.exists():
        for md_file in paths.wiki_sources.iterdir():
            if not md_file.suffix == ".md" or not md_file.is_file():
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if not text.startswith("---\n"):
                continue
            end = text.find("\n---", 4)
            if end < 0:
                continue
            try:
                fm = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                continue
            sources = fm.get("sources", [])
            if isinstance(sources, list) and key in [str(s).replace("\\", "/") for s in sources]:
                grade = fm.get("grade", "B")
                title = fm.get("title")
                page_id = str(fm.get("id", ""))

                # Body checks (same as _quality_report in files.py)
                body = text
                if text.startswith("---\n"):
                    end2 = text.find("\n---", 4)
                    if end2 >= 0:
                        body = text[end2 + 5:]

                if _has_type_prefix(page_id) or _has_type_prefix(title or ""):
                    issues.append(f"prefix_ghost: {title}")
                if _meaningful_length(body) < 20:
                    issues.append("empty_body")
                break

    return {"grade": grade, "title": title, "issues": issues}


@router.get("/projects/{project_id}/quality")
async def quality_report(
    project_id: str,
    source_path: str = Query(..., description="Project-relative raw source path"),
):
    """Return the quality report for a single ingested source file.

    The frontend calls this when the user clicks the "质" button.
    Returns a JSON object with:

    - ``exists``: whether any report was found
    - ``passed``: overall pass/fail (green/red)
    - ``grade``: wiki page grade (A/B/C)
    - ``title``: wiki page title
    - ``issues``: body-level issues (prefix_ghost, empty_body)
    - ``report``: the IngestReport dict, or ``None``
    - ``review_items``: open ReviewItems for this task
    - ``quarantine``: quarantine judgments for this task
    """
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    reports_dir = paths.root / REPORTS_DIR
    report = _find_latest_report(reports_dir, source_path)

    review_items: list[dict] = []
    quarantine: list[dict] = []
    task_id = report.get("task_id") if report else None

    if task_id:
        review_items = _load_review_items_for_task(paths, task_id)
        quarantine = _load_quarantine_summary(paths.root, task_id)

    passed = _compute_overall_pass(report, review_items, quarantine)
    page = _read_wiki_page_frontmatter(paths, source_path)

    result: dict = {
        "exists": report is not None,
        "passed": passed,
        "grade": page["grade"],
        "title": page["title"],
        "issues": page["issues"],
        "report": report,
        "review_items": review_items,
        "quarantine": quarantine,
    }
    return result