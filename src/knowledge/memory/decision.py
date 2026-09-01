"""Decision recorder — structured decision tracking with outcome follow-up.

Decision data is stored in the WikiPage frontmatter as a top-level
``decision_record`` field (C-0 Commit 2). Legacy pages may still carry the
payload under ``_ko_extra.memory.decision``; reads fall back to that key
when ``decision_record`` is absent.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.knowledge.core.adapter import knowledge_object_to_wiki_page
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from src.lib.write_hooks import safe_write
from src.wiki.core.id_generator import generate_page_id
from src.wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# DecisionRecord — the structured payload stored in WikiPage.decision_record
# (legacy: ``_ko_extra.memory.decision``)
# ---------------------------------------------------------------------------

@dataclass
class DecisionRecord:
    """Structured decision data stored in ``WikiPage.decision_record``.

    For pages written before C-0 Commit 2, the same payload lived under
    ``_ko_extra.memory.decision``; readers fall back to that key.
    """

    context: str           # Background / situation leading to the decision
    alternatives: list[str]  # Other options considered
    rationale: str          # Why this option was chosen
    outcome: str = ""       # What actually happened (filled later)
    actual_impact: str = "" # Real-world impact (filled later)
    decided_at: int = 0     # When the decision was made (unix ms)
    outcome_at: int = 0     # When outcome was recorded (unix ms)

    def to_dict(self) -> dict:
        return {
            "context": self.context,
            "alternatives": list(self.alternatives),
            "rationale": self.rationale,
            "outcome": self.outcome,
            "actual_impact": self.actual_impact,
            "decided_at": self.decided_at,
            "outcome_at": self.outcome_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionRecord":
        return cls(
            context=d.get("context", ""),
            alternatives=list(d.get("alternatives", [])),
            rationale=d.get("rationale", ""),
            outcome=d.get("outcome", ""),
            actual_impact=d.get("actual_impact", ""),
            decided_at=d.get("decided_at", 0),
            outcome_at=d.get("outcome_at", 0),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 40) -> str:
    """Create a valid page-ID slug from arbitrary text.

    The ID pattern for the slug segment is ``[a-z0-9-\\u4e00-\\u9fff]+``.
    """
    slug = re.sub(r"\s+", "-", text.strip().lower())
    slug = re.sub(r"[^a-z0-9\-一-鿿]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "decision"


def _write_decision_page(
    paths: WikiPaths, ko: KnowledgeObject, decision_record: DecisionRecord
) -> str:
    """Convert KO → WikiPage, attach ``decision_record``, write to disk."""
    wp = knowledge_object_to_wiki_page(ko)

    # C-0 Commit 2: decision_record is a top-level WikiPage field. Writing
    # it here keeps ``_ko_extra.memory.decision`` as a back-compat read
    # path only — new pages do not embed it under _ko_extra.
    wp.decision_record = decision_record.to_dict()

    fm = wp.to_frontmatter_dict()
    # Decision pages are a legacy compatibility surface outside the V4
    # eight-key wiki page contract; retain their structured payload here.
    fm["decision_record"] = decision_record.to_dict()

    path = paths.wiki_decisions / f"{wp.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.dump(
        fm, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    content = f"---\n{fm_text}---\n\n{wp.body}"
    safe_write(path, content)

    return ko.id


def _read_decision_raw(path: Path) -> dict | None:
    """Read raw decision record from a decision page file.

    Prefers the top-level ``decision_record`` field written by C-0 Commit 2.
    Falls back to the legacy ``_ko_extra.memory.decision`` location for
    pages written before the migration. Returns ``None`` if neither is
    present.
    """
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    top = fm.get("decision_record")
    if isinstance(top, dict):
        return top
    ko_extra = fm.get("_ko_extra")
    if isinstance(ko_extra, dict):
        memory = ko_extra.get("memory")
        if isinstance(memory, dict):
            legacy = memory.get("decision")
            if isinstance(legacy, dict):
                return legacy
    return None


# ---------------------------------------------------------------------------
# DecisionRecorder
# ---------------------------------------------------------------------------

class DecisionRecorder:
    """Records decisions as KnowledgeObjects with extra memory fields.

    Decision data is stored in the WikiPage frontmatter as a top-level
    ``decision_record`` field (C-0 Commit 2).
    """

    def __init__(self, wiki_paths: WikiPaths) -> None:
        self._paths = wiki_paths

    # ------------------------------------------------------------------
    # record_decision
    # ------------------------------------------------------------------

    def record_decision(
        self,
        question: str,
        decision: str,
        context: str = "",
        alternatives: list[str] | None = None,
        rationale: str = "",
    ) -> str:
        """Create a decision-type KnowledgeObject.

        Args:
            question: The question being decided (becomes title).
            decision: The decision made (becomes body content).
            context: Background context.
            alternatives: Other options considered.
            rationale: Why this option was chosen.

        Returns:
            decision_id: The KnowledgeObject ID.
        """
        now_ms = int(time.time() * 1000)
        slug = _slugify(question)
        page_id = generate_page_id(slug)

        if alternatives is None:
            alternatives = []

        decision_record = DecisionRecord(
            context=context,
            alternatives=alternatives,
            rationale=rationale,
            decided_at=now_ms,
        )

        ko = KnowledgeObject(
            id=page_id,
            type=KnowledgeType.DECISION,
            title=question,
            content=decision,
            lifecycle=LifecycleState.ACTIVE,
            confidence=1.0,
            provenance=Provenance(source_path=""),
            created_at=now_ms,
            updated_at=now_ms,
        )

        _write_decision_page(self._paths, ko, decision_record)
        return page_id

    # ------------------------------------------------------------------
    # update_outcome
    # ------------------------------------------------------------------

    def update_outcome(
        self, decision_id: str, outcome: str, actual_impact: str = ""
    ) -> None:
        """Post-hoc outcome update.

        Reads the existing wiki page, updates
        ``decision_record.outcome`` and ``actual_impact``, writes back.
        Falls back to legacy ``_ko_extra.memory.decision`` for pages written
        before the C-0 Commit 2 migration.
        """
        path = self._paths.wiki_decisions / f"{decision_id}.md"
        decision_data = _read_decision_raw(path)
        if decision_data is None:
            raise FileNotFoundError(f"Decision not found: {decision_id}")

        decision_data["outcome"] = outcome
        decision_data["actual_impact"] = actual_impact
        decision_data["outcome_at"] = int(time.time() * 1000)

        # Rebuild the full page frontmatter
        text = path.read_text(encoding="utf-8")
        end = text.find("\n---", 4)
        body = text[end + 5:].lstrip("\n") if end >= 0 else ""
        try:
            fm = yaml.safe_load(text[4:end]) if end >= 0 else {}
        except yaml.YAMLError:
            fm = {}
        if not isinstance(fm, dict):
            fm = {}
        # C-0 Commit 2: write to top-level decision_record (canonical home).
        fm["decision_record"] = decision_data

        fm_text = yaml.dump(
            fm, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
        content = f"---\n{fm_text}---\n\n{body}"
        safe_write(path, content)

    # ------------------------------------------------------------------
    # get_decision_context
    # ------------------------------------------------------------------

    def get_decision_context(self, decision_id: str) -> dict | None:
        """Retrieve full decision record including evidence + history + outcome.

        Returns ``None`` if ``decision_id`` is not found.
        """
        path = self._paths.wiki_decisions / f"{decision_id}.md"
        text_raw = None
        if path.exists():
            text_raw = path.read_text(encoding="utf-8")
        if text_raw is None or not text_raw.startswith("---\n"):
            return None

        end = text_raw.find("\n---", 4)
        if end < 0:
            return None
        try:
            fm = yaml.safe_load(text_raw[4:end]) or {}
        except yaml.YAMLError:
            return None
        if not isinstance(fm, dict):
            return None

        body = text_raw[end + 5:].lstrip("\n")
        # C-0 Commit 2: prefer top-level decision_record; fall back to the
        # legacy ``_ko_extra.memory.decision`` location for pre-migration pages.
        decision_data = fm.get("decision_record")
        if not isinstance(decision_data, dict):
            ko_extra = fm.get("_ko_extra")
            if isinstance(ko_extra, dict):
                memory = ko_extra.get("memory")
                if isinstance(memory, dict):
                    decision_data = memory.get("decision")
        if not isinstance(decision_data, dict):
            return None

        return {
            "id": decision_id,
            "question": fm.get("title", ""),
            "decision": body,
            "context": decision_data.get("context", ""),
            "alternatives": decision_data.get("alternatives", []),
            "rationale": decision_data.get("rationale", ""),
            "outcome": decision_data.get("outcome", ""),
            "actual_impact": decision_data.get("actual_impact", ""),
        }
