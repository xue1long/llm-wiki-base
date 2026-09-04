"""Evidence persistent storage (路线 v2.2 §C-1 / G1, spec §3.2).

Layout::

    .index/evidence/<evidence_id>.json

Each file is a JSON dump of the frozen :class:`Evidence` dataclass
(``dataclasses.asdict``). ``read`` reconstructs the dataclass via ``Evidence(**data)``.

This module is intentionally small — the read/write round-trip is the only
contract callers depend on. Persistence is best-effort and synchronous; we do
not aim for atomic durability here (the safe_write buffer in
``src/lib/write_hooks.py`` is the right place for atomic fan-out).
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..contracts.evidence import Evidence


class EvidenceStorage:
    """Persistent storage for Evidence records under ``.index/evidence/``."""

    def __init__(self, evidence_dir: Path):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def write(self, evidence: Evidence) -> Path:
        """Persist ``evidence`` to ``<evidence_dir>/<evidence_id>.json``.

        Returns the resolved path so callers can chain or log it.
        """
        path = self.evidence_dir / f"{evidence.evidence_id}.json"
        path.write_text(
            json.dumps(asdict(evidence), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def read(self, evidence_id: str) -> Evidence | None:
        """Load an Evidence from disk.

        Returns ``None`` (not raises) when the file is missing, so callers can
        treat "unknown id" as a soft signal rather than an exception path.
        """
        path = self.evidence_dir / f"{evidence_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        # JSON lists become Python lists after ``json.loads``; the Evidence
        # dataclass declares ``supports`` as ``tuple[str, ...]``. Convert it
        # back so the dataclass equality comparison succeeds.
        supports = data.get("supports")
        if isinstance(supports, list):
            data["supports"] = tuple(supports)
        return Evidence(**data)

    def list_all(self) -> list[str]:
        """Return every evidence ID present on disk, sorted lexicographically.

        Returns an empty list when the directory does not yet exist — useful
        for first-run probing where callers want a stable answer whether or
        not the project has been initialized.
    """
        if not self.evidence_dir.exists():
            return []
        return sorted(p.stem for p in self.evidence_dir.glob("*.json"))
