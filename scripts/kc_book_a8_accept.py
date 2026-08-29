"""Executable Gate A8 acceptance for the Book view and rebuild chain."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.kc.integrity.orchestrator import IntegrityGate
from src.kc.views.book import (
    Book,
    BookChapterRegistry,
    Chapter,
    MappingHint,
    map_ku_to_chapter,
    rebuild_book,
)
from src.kc.views.book.compiler import CompileError, compile_chapter
from src.kc.views.book.outline import create_outline_proposal
from src.kc.views.book.core_view import SimpleKnowledgeCoreView
from src.kc.domain.knowledge_unit import KnowledgeUnit

from kc_book_rebuild import SnapshotError, load_snapshot


def _mapping_check() -> dict[str, Any]:
    path = Path(__file__).parents[1] / "tests" / "fixtures" / "book_mapping.yaml"
    cases = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    matched = 0
    for case in cases:
        spec = case["ku"]
        ku = KnowledgeUnit(
            ku_id=spec["id"], concept_id=spec["concept_id"],
            question=spec.get("question", "What?"), title=spec.get("title", "Title"),
            unit_type=spec["unit_type"],
        )
        chapters = tuple(Chapter(
            id=item["chapter_id"], book_id="gold", stable_key=item["stable_key"],
            title=item.get("title", item["stable_key"]), order=item.get("order", 1),
            source_knowledge_unit_ids=item.get("source_knowledge_unit_ids", []),
        ) for item in case.get("existing_chapters", []))
        hint = MappingHint(stable_key=case["hint_stable_key"]) if case.get("hint_stable_key") else None
        decision = map_ku_to_chapter(ku, BookChapterRegistry(chapters), hint=hint)
        expected = case["expected"]
        matched += decision.chapter_id == expected.get("chapter_id") and decision.stable_key == expected["stable_key"] and decision.reason == expected["reason"]
    total = len(cases)
    return {"passed": bool(total) and matched / total >= .90, "matched": matched, "total": total, "accuracy": matched / total if total else 0.0}


def _check_snapshot(snapshot: Path) -> dict[str, Any]:
    book, chapters, core = load_snapshot(snapshot)
    checks: list[dict[str, Any]] = []
    checks.append({"name": "mapper_accuracy", **_mapping_check()})
    with tempfile.TemporaryDirectory(prefix="kc-a8-") as raw:
        output = Path(raw) / "book"
        report = rebuild_book(book, chapters, core, IntegrityGate(), output_dir=output, apply=True)
        compiled = [compile_chapter(chapter, core, IntegrityGate()) for chapter in chapters]
        unsupported = sum(item.unsupported_fact_count for item in compiled if not isinstance(item, CompileError))
        checks.append({"name": "unsupported_fact_zero", "passed": report.status == "committed" and unsupported == 0, "unsupported_fact_count": unsupported})
        before = (book.outline_version, tuple(book.chapter_ids), tuple(ch.stable_key for ch in chapters))
        proposal = create_outline_proposal(book, trigger_knowledge_unit_ids=("ku-1",), affected_chapter_ids=("ch-1",), migration_mapping={"stable-ch-1": "ch-1"}, rollback_mapping={"ch-1": "stable-ch-1"})
        after = (book.outline_version, tuple(book.chapter_ids), tuple(ch.stable_key for ch in chapters))
        checks.append({"name": "unapproved_outline_is_noop", "passed": proposal.status.value == "proposed" and before == after})
        changed = SimpleKnowledgeCoreView(
            kus=core.kus,
            evidences=core.evidences,
            claims=core.claims,
            ku_evidence_map={**core.ku_evidence_map, "ku-1": ("ev-2",)},
            publication_version=core.current_publication_version(),
        )
        original = rebuild_book(book, chapters, core, IntegrityGate(), output_dir=None, apply=False).rendered_hashes
        altered = rebuild_book(book, chapters, changed, IntegrityGate(), output_dir=None, apply=False).rendered_hashes
        affected = {cid for cid in original if original[cid] != altered.get(cid)}
        checks.append({"name": "ku_change_scopes_hashes", "passed": affected == {"ch-1"}, "affected_chapter_ids": sorted(affected)})
        shutil.rmtree(output)
        rebuilt = rebuild_book(book, chapters, core, IntegrityGate(), output_dir=output, apply=True)
        checks.append({"name": "delete_then_rebuild", "passed": rebuilt.status == "committed" and len(list(output.glob("*.md"))) == len(chapters)})
        checks.append({"name": "structured_hash_stable", "passed": report.rendered_hashes == rebuilt.rendered_hashes})
        metadata_versions = [json.loads(path.read_text(encoding="utf-8"))["publication_version"] for path in output.glob("*.json")]
        markdown_versions = [line.rsplit(": ", 1)[-1] for path in output.glob("*.md") for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("publication_version: ")]
        expected_version = str(core.current_publication_version())
        checks.append({"name": "publication_version_consistent", "passed": report.publication_version == core.current_publication_version() and all(version == core.current_publication_version() for version in metadata_versions) and all(version == expected_version for version in markdown_versions)})
    checks.append({"name": "empty_fixture_not_evaluable", "passed": rebuild_book(Book(id="empty", title="", template_id="default_v1"), (), core, IntegrityGate()).not_evaluable})
    return {"status": "passed" if all(item.get("passed", False) for item in checks) else "failed", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = _check_snapshot(args.fixture)
    except (OSError, SnapshotError, ValueError, KeyError) as exc:
        result = {"status": "failed", "checks": [], "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
