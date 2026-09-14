"""Small persistent queue for content-filter review decisions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


class ReviewQueue:
    """Persist open/accepted/rejected content review items atomically."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def enqueue(
        self,
        source_id: str,
        title: str,
        matches: Iterable[Mapping[str, Any]],
        *,
        content_hash: str = "",
    ) -> str:
        data = self._read()
        match_list = [dict(match) for match in matches]
        identity = f"{source_id}\0{content_hash}\0" + json.dumps(
            match_list, ensure_ascii=False, sort_keys=True
        )
        review_id = "content-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        for item in data:
            if item.get("id") == review_id:
                return review_id
        data.append(
            {
                "id": review_id,
                "source_id": str(source_id),
                "title": str(title),
                "content_hash": str(content_hash),
                "matches": match_list,
                "status": "open",
            }
        )
        self._write(data)
        return review_id

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        items = self._read()
        if status is None:
            return items
        return [item for item in items if item.get("status") == status]

    def resolve(self, review_id: str, decision: str) -> None:
        if decision not in {"accepted", "rejected"}:
            raise ValueError("decision must be accepted or rejected")
        items = self._read()
        for item in items:
            if item.get("id") != review_id:
                continue
            if item.get("status") != "open":
                raise ValueError("review is already resolved")
            item["status"] = decision
            self._write(items)
            return
        raise KeyError(f"review not found: {review_id}")

    def status_for(self, source_id: str, content_hash: str) -> str | None:
        """Return the latest decision for an exact source/content pair."""
        matches = [
            item for item in self._read()
            if item.get("source_id") == str(source_id)
            and item.get("content_hash", "") == str(content_hash)
        ]
        return matches[-1].get("status") if matches else None

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(payload, dict):
            payload = payload.get("items", [])
        return [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
