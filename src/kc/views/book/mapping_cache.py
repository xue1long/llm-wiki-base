"""Versioned, persistent cache for deterministic KU-to-Chapter mappings."""
from __future__ import annotations

import json
import threading
from hashlib import sha256
from pathlib import Path
from typing import Any

from .mapper import BookChapterRegistry, MappingDecision, MappingHint, map_ku_to_chapter


class MappingCache:
    """Small JSON cache whose key includes every mapping input version."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self._load()

    def resolve(
        self,
        ku,
        chapter_registry: BookChapterRegistry,
        *,
        hint: MappingHint | None = None,
        template_hash: str = "",
        prompt_version: str = "",
        model: str = "",
        embedding_model: str = "",
    ) -> MappingDecision:
        with self._lock:
            key = self._key(
                ku, chapter_registry, hint, template_hash,
                prompt_version, model, embedding_model,
            )
            cached = self._entries.get(key)
            if cached is not None:
                try:
                    decision = MappingDecision(**cached)
                except (TypeError, ValueError):
                    self._entries.pop(key, None)
                else:
                    self.hits += 1
                    return decision
            self.misses += 1
            decision = map_ku_to_chapter(ku, chapter_registry, hint=hint)
            self._entries[key] = {
                "chapter_id": decision.chapter_id,
                "stable_key": decision.stable_key,
                "confidence": decision.confidence,
                "reason": decision.reason,
            }
            self._save()
            return decision

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._save()

    def _key(self, ku, registry, hint, *versions: str) -> str:
        payload = {
            "ku": {
                "id": ku.ku_id,
                "concept_id": ku.concept_id,
                "unit_type": ku.unit_type,
            },
            "chapters": [
                {
                    "id": ch.id,
                    "stable_key": ch.stable_key,
                    "source_knowledge_unit_ids": ch.source_knowledge_unit_ids,
                }
                for ch in registry.chapters
            ],
            "hint": hint.stable_key if hint else None,
            "versions": versions,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return sha256(blob).hexdigest()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._entries = {
                    key: value for key, value in raw.items()
                    if isinstance(key, str) and isinstance(value, dict)
                }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._entries = {}

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self._entries, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temp.replace(self.path)


__all__ = ["MappingCache"]
