"""Stage 7 extraction audit mapping: raw source id → concept page ids."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class AuditLogger:
    """Persist an idempotent JSON mapping for extraction provenance."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, source_id: str, concept_ids: Iterable[str]) -> None:
        data = self.read()
        values = data.setdefault(str(source_id), [])
        for concept_id in concept_ids:
            concept_id = str(concept_id)
            if concept_id not in values:
                values.append(concept_id)
        self._write(data)

    def read(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(source): [str(concept) for concept in concepts]
            for source, concepts in payload.items()
            if isinstance(concepts, list)
        }

    def _write(self, data: dict[str, list[str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
