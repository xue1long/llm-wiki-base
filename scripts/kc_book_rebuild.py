from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.kc.contracts.evidence import Evidence
from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.integrity.orchestrator import IntegrityGate
from src.kc.views.book import Book, Chapter, SimpleKnowledgeCoreView, rebuild_book


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


class SnapshotError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SnapshotError(f"snapshot:{name}:expected_object")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SnapshotError(f"snapshot:{name}:expected_list")
    return value


def _require_string_list(value: Any, name: str) -> tuple[str, ...]:
    items = _require_list(value, name)
    if any(not isinstance(item, str) for item in items):
        raise SnapshotError(f"snapshot:{name}:expected_string_list")
    return tuple(items)


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotError(f"snapshot:{name}:expected_int")
    return value


def _load_book(payload: dict[str, Any]) -> Book:
    try:
        return Book.from_dict(payload)
    except Exception as exc:
        field = exc.args[0] if isinstance(exc, KeyError) and exc.args else type(exc).__name__
        raise SnapshotError(f"snapshot:book:{field}") from exc


def _load_chapters(payloads: list[Any]) -> tuple[Chapter, ...]:
    chapters: list[Chapter] = []
    for index, raw in enumerate(payloads):
        chapter_payload = _require_mapping(raw, f"chapters[{index}]")
        try:
            chapters.append(Chapter.from_dict(chapter_payload))
        except Exception as exc:
            field = exc.args[0] if isinstance(exc, KeyError) and exc.args else type(exc).__name__
            raise SnapshotError(f"snapshot:chapters[{index}]:{field}") from exc
    return tuple(chapters)


def _load_knowledge_units(payloads: list[Any]) -> dict[str, KnowledgeUnit]:
    units: dict[str, KnowledgeUnit] = {}
    for index, raw in enumerate(payloads):
        unit_payload = _require_mapping(raw, f"knowledge_units[{index}]")
        try:
            unit = KnowledgeUnit(**unit_payload)
        except Exception as exc:
            raise SnapshotError(f"snapshot:knowledge_units[{index}]:{type(exc).__name__}") from exc
        units[unit.ku_id] = unit
    return units


def _load_evidences(payloads: list[Any]) -> dict[str, Evidence]:
    evidences: dict[str, Evidence] = {}
    for index, raw in enumerate(payloads):
        evidence_payload = _require_mapping(raw, f"evidences[{index}]")
        try:
            evidence = Evidence(**evidence_payload)
        except Exception as exc:
            raise SnapshotError(f"snapshot:evidences[{index}]:{type(exc).__name__}") from exc
        evidences[evidence.evidence_id] = evidence
    return evidences


def _load_ku_evidence_map(payload: Any) -> dict[str, tuple[str, ...]]:
    mapping = _require_mapping(payload, "ku_evidence_map")
    ku_evidence_map: dict[str, tuple[str, ...]] = {}
    for ku_id, evidence_ids in mapping.items():
        if not isinstance(ku_id, str):
            raise SnapshotError("snapshot:ku_evidence_map:expected_string_keys")
        ku_evidence_map[ku_id] = _require_string_list(
            evidence_ids,
            f"ku_evidence_map[{ku_id}]",
        )
    return ku_evidence_map


def load_snapshot(snapshot_path: Path) -> tuple[Book, tuple[Chapter, ...], SimpleKnowledgeCoreView]:
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotError("snapshot:file_not_found") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotError("snapshot:invalid_json") from exc

    root = _require_mapping(payload, "root")
    required_keys = (
        "book",
        "chapters",
        "knowledge_units",
        "evidences",
        "ku_evidence_map",
        "publication_version",
    )
    for key in required_keys:
        if key not in root:
            raise SnapshotError(f"snapshot:missing_{key}")

    book = _load_book(_require_mapping(root["book"], "book"))
    chapters = _load_chapters(_require_list(root["chapters"], "chapters"))
    knowledge_units = _load_knowledge_units(
        _require_list(root["knowledge_units"], "knowledge_units")
    )
    evidences = _load_evidences(_require_list(root["evidences"], "evidences"))
    ku_evidence_map = _load_ku_evidence_map(root["ku_evidence_map"])
    publication_version = _require_int(root["publication_version"], "publication_version")
    core_view = SimpleKnowledgeCoreView(
        kus=knowledge_units,
        evidences=evidences,
        ku_evidence_map=ku_evidence_map,
        publication_version=publication_version,
    )
    return book, chapters, core_view


def _report_to_dict(
    *,
    project_root: Path,
    output_dir: Path,
    apply: bool,
    chapter_id: str | None,
    report: Any,
) -> dict[str, Any]:
    return {
        "status": report.status,
        "book_id": report.book_id,
        "publication_version": report.publication_version,
        "rebuilt_chapter_ids": list(report.rebuilt_chapter_ids),
        "failed_chapter_ids": list(report.failed_chapter_ids),
        "reason_codes": list(report.reason_codes),
        "rendered_hashes": dict(report.rendered_hashes),
        "not_evaluable": report.not_evaluable,
        "project_root": str(project_root),
        "output_dir": str(output_dir),
        "apply": apply,
        "chapter_id": chapter_id,
    }


def _failure_report(
    *,
    project_root: Path,
    output_dir: Path,
    apply: bool,
    chapter_id: str | None,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "book_id": "",
        "publication_version": 0,
        "rebuilt_chapter_ids": [],
        "failed_chapter_ids": [],
        "failed_object_ids": ["snapshot"],
        "reason_codes": [reason_code],
        "rendered_hashes": {},
        "not_evaluable": False,
        "project_root": str(project_root),
        "output_dir": str(output_dir),
        "apply": apply,
        "chapter_id": chapter_id,
    }


def run(project_root: Path, snapshot_path: Path, *, apply: bool, chapter_id: str | None) -> tuple[dict[str, Any], int]:
    output_dir = project_root / "book"
    try:
        book, chapters, core_view = load_snapshot(snapshot_path)
    except SnapshotError as exc:
        return (
            _failure_report(
                project_root=project_root,
                output_dir=output_dir,
                apply=apply,
                chapter_id=chapter_id,
                reason_code=exc.reason_code,
            ),
            1,
        )

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        target_chapter_ids=(chapter_id,) if chapter_id else None,
        output_dir=output_dir,
        apply=apply,
    )
    payload = _report_to_dict(
        project_root=project_root,
        output_dir=output_dir,
        apply=apply,
        chapter_id=chapter_id,
        report=report,
    )
    return payload, 0 if report.status != "failed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Book chapters from a KC snapshot")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--chapter", type=str, default=None)
    args = parser.parse_args()

    report, exit_code = run(
        args.project_root,
        args.snapshot,
        apply=args.apply,
        chapter_id=args.chapter,
    )
    print(json.dumps(report, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
