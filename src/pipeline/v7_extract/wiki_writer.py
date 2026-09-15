"""Stage 7: atomic, retrying, checkpointed Wiki writer.

v3 (plan 2026-09-15) adds three guards on top of the v2 writer:

  A. P4 — pages whose ``topic_id`` is ``__other__`` (Stage 4's sentinel
     bucket for items the LLM forgot to assign) are routed to
     ``report.blocked``, never written.

  B. needs_review — pages with any slot flagged ``needs_review`` are
     blocked. The body is partial / unreliable; we don't auto-publish
     such pages.

  C. has_evidence — pages where no slot has evidence at all are
     blocked. Without evidence the page is just hallucination.

These three guards plus the existing content_filter are the v3 "four
gates" (P3 + P4). WriteReport.blocked records all four categories.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping

import yaml

from .audit_logger import AuditLogger
from .relation_extractor import PageRelation
from .slot_filler import ConceptPage
from .topic_clusterer import OTHER_TOPIC_ID


PageWriter = Callable[[ConceptPage, Path], None]


# P4: pages whose id starts with this prefix are written into the
# review queue, NOT to disk. This is the v3 sentinel — it lets the
# writer refuse the Stage 4 "其他主题" bucket while still letting
# pages flow through the normal pipeline.
_BLOCKED_TOPIC_PREFIX = "__other__"


@dataclass
class WriteReport:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


class WikiWriter:
    """Write V7 concept pages without duplicating work after a restart."""

    def __init__(
        self,
        root: str | Path,
        *,
        page_writer: PageWriter | None = None,
        content_filter: Any = None,
        max_retries: int = 3,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be positive")
        self.root = Path(root)
        self.pages_dir = self.root / "wiki" / "concepts"
        self.index_path = self.root / "wiki" / "index.md"
        self.checkpoint_path = self.root / ".index" / "v7_checkpoint.json"
        self.audit = AuditLogger(self.root / ".index" / "extract_report.json")
        self.page_writer = page_writer or self._write_page_atomically
        self.content_filter = content_filter
        self.max_retries = max_retries

    def commit_and_index(
        self,
        pages: Iterable[ConceptPage],
        relations: Iterable[PageRelation] = (),
    ) -> WriteReport:
        pages = list(pages)
        relation_map = _relations_by_source(relations)
        self._last_relations = relation_map
        checkpoint = self._read_checkpoint()
        completed = checkpoint["completed"]
        report = WriteReport()

        for page in pages:
            # Guard A: P4 — __other__ topic is a sentinel, never write.
            if page.topic_id == OTHER_TOPIC_ID or page.id.startswith(_BLOCKED_TOPIC_PREFIX):
                report.blocked.append(page.id)
                continue

            # Guard B: needs_review — any slot flagged for review blocks.
            if page.needs_review_slots:
                report.blocked.append(page.id)
                continue

            # Guard C: has_evidence — no evidence at all means hallucination.
            if not page.has_evidence:
                report.blocked.append(page.id)
                continue

            # Guard D: content_filter (existing v2).
            if self.content_filter is not None:
                filter_result = self.content_filter.check(
                    page.body,
                    source_id=page.sources[0] if page.sources else page.id,
                    title=page.title,
                )
                if getattr(filter_result.status, "value", filter_result.status) == "needs_review":
                    report.blocked.append(page.id)
                    continue

            path = self._page_path(page.id)
            if page.id in completed and path.exists():
                report.skipped.append(page.id)
                self._audit_page(page)
                continue
            if page.id in completed:
                completed.remove(page.id)
                self._save_checkpoint(completed)

            last_error: Exception | None = None
            for _ in range(self.max_retries):
                try:
                    self.page_writer(page, path)
                    last_error = None
                    break
                except Exception as exc:  # retry boundary intentionally broad
                    last_error = exc
            if last_error is not None:
                report.failed[page.id] = str(last_error)
                continue

            if page.id not in completed:
                completed.append(page.id)
            self._save_checkpoint(completed)
            report.written.append(page.id)
            self._audit_page(page)

        self._append_index(pages, report)
        return report

    def _write_page_atomically(self, page: ConceptPage, path: Path) -> None:
        relations = getattr(self, "_last_relations", {}).get(page.id, [])
        frontmatter = {
            "id": page.id,
            "title": page.title,
            "type": page.type,
            "sources": list(page.sources),
            "relations": [relation.to_dict() for relation in relations],
        }
        content = "---\n" + yaml.safe_dump(
            frontmatter, allow_unicode=True, sort_keys=False
        ) + "---\n\n" + page.body
        self._atomic_write(path, content)

    def _append_index(self, pages: list[ConceptPage], report: WriteReport) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.index_path.read_text(encoding="utf-8") if self.index_path.exists() else "# Wiki Index\n\n"
        existing = set()
        for line in content.splitlines():
            if line.startswith("- **"):
                existing.add(line.split("**", 2)[1])
        for page in pages:
            if page.id not in report.written and page.id not in report.skipped:
                continue
            if page.id in existing:
                continue
            if not content.endswith("\n"):
                content += "\n"
            content += f"- **{page.id}** (concept) — {page.title}\n"
            existing.add(page.id)
        self._atomic_write(self.index_path, content)

    def _audit_page(self, page: ConceptPage) -> None:
        for source_id in page.sources:
            self.audit.record(source_id, [page.id])

    def _read_checkpoint(self) -> dict[str, list[str]]:
        if not self.checkpoint_path.exists():
            return {"completed": []}
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            completed = payload.get("completed", [])
            if isinstance(completed, list):
                return {"completed": list(dict.fromkeys(str(item) for item in completed))}
        except (OSError, ValueError, AttributeError):
            pass
        return {"completed": []}

    def _save_checkpoint(self, completed: list[str]) -> None:
        self._atomic_write(
            self.checkpoint_path,
            json.dumps({"completed": completed}, ensure_ascii=False, indent=2) + "\n",
        )

    def _page_path(self, page_id: str) -> Path:
        if not page_id or Path(page_id).is_absolute() or PureWindowsPath(page_id).is_absolute():
            raise ValueError("page id must be a relative filename")
        if any(char in page_id for char in "/\\") or ".." in page_id:
            raise ValueError("page id must be a single filename")
        path = self.pages_dir / f"{page_id}.md"
        try:
            path.resolve().relative_to(self.pages_dir.resolve())
        except ValueError as exc:
            raise ValueError("page id escapes concept directory") from exc
        return path

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)


def _relations_by_source(relations: Iterable[PageRelation]) -> dict[str, list[PageRelation]]:
    result: dict[str, list[PageRelation]] = {}
    seen: set[tuple[str, str, str]] = set()
    for raw in relations:
        relation = _coerce_relation(raw)
        key = (relation.source_id, relation.target_id, relation.type)
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(relation.source_id, []).append(relation)
    return result


def _coerce_relation(raw: Any) -> PageRelation:
    if isinstance(raw, PageRelation):
        return raw
    if isinstance(raw, Mapping):
        return PageRelation(
            str(raw.get("source_id", raw.get("source", ""))),
            str(raw.get("target_id", raw.get("target", ""))),
            str(raw.get("type", "")),
            float(raw.get("weight", 1.0)),
            str(raw.get("context", "")),
        )
    return PageRelation(
        str(getattr(raw, "source_id", "")),
        str(getattr(raw, "target_id", "")),
        str(getattr(raw, "type", "")),
        float(getattr(raw, "weight", 1.0)),
        str(getattr(raw, "context", "")),
    )
