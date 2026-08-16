"""Knowledge-gap ledger — ``.index/knowledge_gaps.json`` (plan 1.3).

Records wikilink/relation targets that the generator referenced but that
could not be resolved (after the single-call in-loop retry). Each entry
carries enough provenance for Phase 4 to act on it:

    {slug, title?, alias?, type?, raw_hint?, referenced_by[], created_at,
     status: open|resolved|suppressed, suppressed_reason?}

Quality guardrails (inherited from the legacy stub machinery — plan 1.3-4):
- blocklist: slugs matching forbidden patterns never enter the ledger
- hard cap: a single ingest may add at most ``max_entries`` gaps
- doc-title variants: slugs ending with a source-page hash are dropped
  (they are source-page lookalikes, not real knowledge gaps)

Status transitions: open → resolved (page created later) / suppressed
(human decision with reason). ``suppressed`` requires a reason (B5
anti-gaming: the final acceptance samples suppressed entries).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...lib.write_hooks import safe_write

_GAP_FILE = "knowledge_gaps.json"
_SCHEMA_VERSION = 1

# Slugs that should never become gap entries (mirrors ingest stub blocklist
# semantics — hallucinated tags/paths/type-prefixed ids; both Chinese
# namespaces and legacy English prefixes).
_BLOCKLIST_RE = re.compile(
    r"^(题材|功能|角色|事件|情绪|实体|场景阶段|状态|素材|可信度)-"
    r"|^(genre|func|char|event|mood|entity|scene_phase|status)-"
    r"|^(source|concept|synthesis|entity)-"
    r"|-entity$"
    r"|raw"
    r"|--"
)
# A trailing ``-<8hex>`` marks a source-page lookalike (doc-title variant).
_DOC_TITLE_HASH_RE = re.compile(r"-[0-9a-f]{8}$")

# Field order for stable serialization.
_FIELDS = ("slug", "title", "alias", "type", "raw_hint",
           "referenced_by", "created_at", "status", "suppressed_reason")


@dataclass
class KnowledgeGap:
    slug: str
    referenced_by: list[str] = field(default_factory=list)
    title: str | None = None
    alias: str | None = None
    type: str | None = None
    raw_hint: str | None = None
    created_at: int = 0
    status: str = "open"  # open | resolved | suppressed
    suppressed_reason: str | None = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _FIELDS if getattr(self, k) is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeGap":
        return cls(**{k: d.get(k) for k in _FIELDS})


def _blocklisted(slug: str) -> bool:
    return bool(_BLOCKLIST_RE.search(slug)) or _DOC_TITLE_HASH_RE.search(slug) is not None


def is_raw_reference_blocklisted(raw: str) -> bool:
    """Check a RAW (pre-normalization) referenced slug against the gap blocklist.

    The reconciliation path normalizes references via ``normalize_reconcile_slug``
    BEFORE storing a gap, which strips type prefixes (``source-补充教程`` →
    ``补充教程``).  Checking only the normalized form would make the
    ``^(source|concept|synthesis|entity)-`` and ``^(题材|角色|…)-`` branches of
    ``_BLOCKLIST_RE`` unreachable.  Call this on the raw wikilink/relation
    target BEFORE normalization so type-prefixed hallucinated references are
    dropped, then store only the clean normalized slug.
    """
    return _blocklisted(raw)


class KnowledgeGapStore:
    """Persistent gap ledger for one project (atomic writes via safe_write)."""

    def __init__(self, project_root: Path | str):
        self._path = Path(project_root) / ".index" / _GAP_FILE
        self._gaps: dict[str, KnowledgeGap] = {}
        self._load()

    # ── persistence ────────────────────────────────────────────────
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for entry in data.get("gaps") or []:
            try:
                gap = KnowledgeGap.from_dict(entry)
            except TypeError:
                continue
            self._gaps[gap.slug] = gap

    def save(self) -> None:
        payload = {
            "version": _SCHEMA_VERSION,
            "gaps": [self._gaps[s].to_dict() for s in sorted(self._gaps)],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        safe_write(str(self._path),
                   json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    # ── queries ────────────────────────────────────────────────────
    def get(self, slug: str) -> KnowledgeGap | None:
        return self._gaps.get(slug)

    def all(self) -> list[KnowledgeGap]:
        return [self._gaps[s] for s in sorted(self._gaps)]

    def count(self, status: str | None = None) -> int:
        if status is None:
            return len(self._gaps)
        return sum(1 for g in self._gaps.values() if g.status == status)

    # ── writes (with quality guardrails) ───────────────────────────
    def add_many(
        self,
        slugs: list[str],
        *,
        referenced_by: str = "",
        max_entries: int = 3,
        now: int | None = None,
        title_map: dict[str, str] | None = None,
        raw_hint: str | None = None,
        referenced_by_map: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """Register unresolved slugs, applying blocklist + cap + dedup.

        Returns the slugs actually added. ``max_entries`` is a per-call
        hard cap (plan 1.3-4 — hallucination floods must not balloon the
        ledger); caller decides the cap per ingest batch.

        ``title_map`` (plan 1.3 O6): slug → display title, stored on the
        gap entry so Phase 4 can promote it with the real title. ``raw_hint``
        is the raw source path that referenced the slug (Phase 4 gap-priority
        batches resolve gaps by ingesting that raw file).

        ``referenced_by_map`` (per-gap attribution): ``{slug: [page_ids]}`` —
        when provided, each entry's ``referenced_by`` is the page that
        referenced it (not a batch-wide comma string). Falls back to
        ``referenced_by`` for slugs absent from the map.
        """
        ts = now if now is not None else int(time.time() * 1000)
        added: list[str] = []
        refs_map = referenced_by_map or {}
        for slug in dict.fromkeys(slugs):  # dedupe, keep order
            if not slug:
                continue
            if _blocklisted(slug):
                continue
            if len(added) >= max_entries:
                break
            page_refs: list[str] = refs_map.get(slug) or (
                [referenced_by] if referenced_by else []
            )
            existing = self._gaps.get(slug)
            if existing:
                for ref in page_refs:
                    if ref and ref not in existing.referenced_by:
                        existing.referenced_by.append(ref)
                if raw_hint and not existing.raw_hint:
                    existing.raw_hint = raw_hint
                continue
            self._gaps[slug] = KnowledgeGap(
                slug=slug,
                referenced_by=page_refs,
                title=(title_map or {}).get(slug),
                raw_hint=raw_hint,
                created_at=ts,
            )
            added.append(slug)
        return added

    def resolve(self, slug: str) -> bool:
        """Mark a gap resolved (page now exists). Idempotent."""
        gap = self._gaps.get(slug)
        if gap is None:
            return False
        gap.status = "resolved"
        return True

    def suppress(self, slug: str, reason: str) -> bool:
        """Suppress a gap with a mandatory reason (B5 anti-gaming)."""
        if not reason:
            return False
        gap = self._gaps.get(slug)
        if gap is None:
            return False
        gap.status = "suppressed"
        gap.suppressed_reason = reason
        return True


# Convenience factory for scripts/tests.
def load_store(project_root: Path | str) -> KnowledgeGapStore:
    return KnowledgeGapStore(project_root)
