"""Quarantine store for rejected wiki pages (MVP: mark + don't write)."""
import json
from dataclasses import dataclass
from pathlib import Path

from .types import Judgment
from ..lib.atomic_ctx import AtomicContext
from ..lib.write_hooks import flush_pending_writes, safe_write


QUARANTINE_DIR = ".index/quarantine"


@dataclass
class QuarantinedPage:
    page_id: str
    task_id: str
    content: str
    judgment: Judgment
    quarantined_at: int


class QuarantineStore:
    @staticmethod
    def put_candidate(project_root, task_id: str, candidate, reason: str) -> Path:
        """Persist a rejected candidate without publishing it to the wiki."""
        quarantine_dir = Path(project_root) / QUARANTINE_DIR / task_id
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = quarantine_dir / "candidate.json"
        judgment_path = quarantine_dir / "candidate.judgment.json"
        payload = {
            "id": getattr(candidate, "id", ""),
            "source_id": getattr(candidate, "source_id", ""),
            "type": getattr(getattr(candidate, "type", ""), "value", getattr(candidate, "type", "")),
            "title": getattr(candidate, "title", ""),
            "claims": getattr(candidate, "claims", []),
            "confidence": getattr(candidate, "confidence", 0.0),
            "evidence": getattr(candidate, "evidence", []),
            "status": getattr(getattr(candidate, "status", ""), "value", getattr(candidate, "status", "")),
        }
        judgment = {"kind": "candidate_rejected", "reason": reason}

        def _default(value):
            return getattr(value, "value", str(value))

        with AtomicContext(flush_callback=flush_pending_writes):
            safe_write(candidate_path, json.dumps(payload, ensure_ascii=False, default=_default, indent=2))
            safe_write(judgment_path, json.dumps(judgment, ensure_ascii=False, indent=2))
        return candidate_path

    @staticmethod
    def put(project_root, task_id: str, page_id: str, content: str, judgment: Judgment) -> Path:
        """Write page to quarantine dir + sidecar judgment JSON.

        ``project_root`` should be the project's root path, e.g. ``ctx.paths.root``.
        """
        quarantine_dir = Path(project_root) / QUARANTINE_DIR / task_id
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        page_path = quarantine_dir / f"{page_id}.md"
        judgment_path = quarantine_dir / f"{page_id}.judgment.json"
        # Atomic pair: page + judgment sidecar must appear together.
        # Wrap in AtomicContext so a mid-write crash leaves the wiki
        # unchanged rather than torn (page-only or judgment-only).
        with AtomicContext(flush_callback=flush_pending_writes):
            safe_write(page_path, content)
            safe_write(judgment_path, json.dumps(judgment.to_dict(), indent=2, ensure_ascii=False))
        return page_path

    @staticmethod
    def list(project_root, task_id: str | None = None) -> list:
        quarantine_root = Path(project_root) / QUARANTINE_DIR
        if not quarantine_root.exists():
            return []
        if task_id:
            task_dir = quarantine_root / task_id
            if not task_dir.exists():
                return []
            return sorted(task_dir.glob("*.md"))
        return sorted(quarantine_root.rglob("*.md"))
