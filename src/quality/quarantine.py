"""Quarantine store for rejected wiki pages (MVP: mark + don't write)."""
import json
from dataclasses import dataclass
from pathlib import Path

from .types import Judgment


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
    def put(project_root, task_id: str, page_id: str, content: str, judgment: Judgment) -> Path:
        """Write page to quarantine dir + sidecar judgment JSON.

        ``project_root`` should be the project's root path, e.g. ``ctx.paths.root``.
        """
        quarantine_dir = Path(project_root) / QUARANTINE_DIR / task_id
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        page_path = quarantine_dir / f"{page_id}.md"
        page_path.write_text(content, encoding="utf-8")
        judgment_path = quarantine_dir / f"{page_id}.judgment.json"
        judgment_path.write_text(
            json.dumps(judgment.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
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
