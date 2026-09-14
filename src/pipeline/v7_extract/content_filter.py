"""Task 9 content-safety gate for the V7 extraction pipeline."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from ...wiki.storage.reviews_queue import ReviewQueue


class FilterStatus(str, Enum):
    CLEAN = "clean"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class SensitiveMatch:
    category: str
    term: str
    start: int = 0
    end: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "term": self.term,
            "start": self.start,
            "end": self.end,
        }


@dataclass
class FilterResult:
    status: FilterStatus
    matches: list[SensitiveMatch] = field(default_factory=list)
    review_id: str | None = None


DEFAULT_TERMS: dict[str, tuple[str, ...]] = {
    "political": ("政治敏感", "政治审查", "颠覆政权"),
    "pornographic": ("色情", "淫秽", "露骨色情"),
    "plagiarism": ("抄袭", "洗稿", "剽窃"),
}


class ContentFilter:
    """Find configured sensitive markers and optionally enqueue review."""

    def __init__(
        self,
        *,
        terms: Mapping[str, Iterable[str]] | None = None,
        queue: ReviewQueue | None = None,
    ) -> None:
        source = terms or DEFAULT_TERMS
        self.terms = {
            str(category): tuple(str(term) for term in values if str(term))
            for category, values in source.items()
        }
        self.queue = queue

    def scan(self, content: str) -> FilterResult:
        text = str(content or "")
        matches: list[SensitiveMatch] = []
        for category, terms in self.terms.items():
            for term in terms:
                for found in re.finditer(re.escape(term), text, re.IGNORECASE):
                    matches.append(
                        SensitiveMatch(category, found.group(0), found.start(), found.end())
                    )
        matches.sort(key=lambda match: (match.start, match.end, match.category))
        status = FilterStatus.NEEDS_REVIEW if matches else FilterStatus.CLEAN
        return FilterResult(status, matches)

    def check(self, content: str, *, source_id: str, title: str = "") -> FilterResult:
        result = self.scan(content)
        if result.status is FilterStatus.NEEDS_REVIEW and self.queue is not None:
            content_hash = hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()
            if self.queue.status_for(source_id, content_hash) == "accepted":
                return FilterResult(FilterStatus.CLEAN, result.matches)
            result.review_id = self.queue.enqueue(
                source_id,
                title,
                [match.to_dict() for match in result.matches],
                content_hash=content_hash,
            )
        return result
