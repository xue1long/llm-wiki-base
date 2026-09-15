"""Run a deterministic V7 extraction pilot in dry-run mode.

The pilot is deliberately a dry-run tool.  It reads raw sources, runs
the local Stage 1 / Stage 3 / Stage 4 / Stage 5 components, and writes
only its requested report files; it never calls the Wiki writer or
mutates ``wiki/``.

v3 (plan 2026-09-15) changes:
- All Stage calls are now ``async def`` (Stage 1 / 3 / 4 / 5 are async
  per the new architecture). ``run_pilot`` / ``_extract_one`` are
  async; ``main`` enters via ``asyncio.run(main())``.
- ``classification.doc_type`` is now a plain string (was
  ``DocType.value`` in v2). Output JSON schema unchanged.
- CLI flags unchanged: ``--count``, ``--seed``, ``--root``,
  ``--json-out``, ``--markdown-out``, ``--provider``, ``--sources``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

# Make direct ``python scripts/extract_pilot.py`` execution behave like a
# module invocation from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.pipeline.v7_extract._page_id import _stable_page_id, validate_page_id
from src.pipeline.v7_extract.completeness_checker import check_completeness
from src.pipeline.v7_extract.doc_classifier import classify_doc
from src.pipeline.v7_extract.slot_filler import fill_slots
from src.pipeline.v7_extract.topic_clusterer import cluster_topics

log = logging.getLogger(__name__)


SUPPORTED_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})
DEFAULT_ROOT = Path("knowledge/novel-wiki")
DEFAULT_JSON = Path("docs/superpowers/reports/2026-09-13-extract-pilot.json")
DEFAULT_MARKDOWN = Path("docs/superpowers/reports/2026-09-13-extract-pilot-report.md")

# T1 / H2 加固: cap the per-failure reason string so a noisy LLM trace
# doesn't dominate the pilot's report.
_EXC_REASON_LIMIT = 500


async def run_pilot(
    root: str | Path = DEFAULT_ROOT,
    *,
    count: int = 50,
    seed: int = 42,
    json_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
    llm: Any = None,
    sources: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    """Run the pilot and optionally write JSON / Markdown reports.

    Selection is deterministic for a given ``seed``.  The returned report
    is fully JSON-serializable so callers can add human spot-check
    annotations.

    ``llm`` is the optional ``LLMClient`` injected for Stage 1 / 3 / 4 / 5.
    When ``llm`` is ``None`` the pipeline runs offline-heuristic only —
    but Stage 1 / 3 / 4 / 5 now REQUIRE an LLM, so this branch is
    effectively a no-op (every stage returns ``incomplete`` / empty
    topics). We keep the parameter for backward compatibility.

    ``sources`` is an explicit list of source paths to run. When provided
    it overrides the random selection — used by spot-check pilots that
    need to cover known-failure cases.
    """
    if count < 1:
        raise ValueError("count must be positive")
    root = Path(root)
    if sources is not None:
        selected = _resolve_sources(root, sources)
    else:
        candidates = _source_files(root)
        selected = _select_sources(candidates, count, seed)
    results: list[dict[str, Any]] = []
    for path in selected:
        relative = path.relative_to(root).as_posix()
        results.append(await _extract_one(root, path, relative, llm=llm))

    report = {
        "mode": "dry-run",
        "root": str(root),
        "seed": seed,
        "llm_enabled": llm is not None,
        "sources": [item["source"] for item in results],
        "summary": _summarize(results),
        "spot_check": {
            "status": "pending",
            "accuracy": None,
            "reviewed_sources": [],
        },
        "results": results,
    }
    if json_output is not None:
        _write_report(Path(json_output), _json_text(report))
    if markdown_output is not None:
        _write_report(Path(markdown_output), _markdown_text(report))
    return report


def _resolve_sources(root: Path, sources: Iterable[str | Path]) -> list[Path]:
    """Resolve the explicit source list to Path objects under ``root``.

    Sources that don't exist under ``root`` are silently dropped so the
    pilot still runs on the remaining files.
    """
    selected: list[Path] = []
    for raw in sources:
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            selected.append(path)
    return selected


def _source_files(root: Path) -> list[Path]:
    source_root = root / "raw" / "sources"
    if not source_root.exists():
        return []
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _select_sources(candidates: list[Path], count: int, seed: int) -> list[Path]:
    # A local import keeps the selection implementation obvious and avoids
    # touching global random state used by other scripts.
    import random

    rng = random.Random(seed)
    if len(candidates) <= count:
        return candidates
    return sorted(rng.sample(candidates, count))


async def _extract_one(
    root: Path,
    path: Path,
    relative: str,
    *,
    llm: Any = None,
    page_sink: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        classification = await classify_doc(
            content, filename_hint=path.name, llm=llm,
            project_root=root,
        )
        # v3: Stage 3 is async + P5-decoupled (doc_type is soft hint).
        complete, completeness_reason = await check_completeness(
            content,
            doc_type_hint=classification.doc_type,
            llm=llm,
            project_root=root,
        )
        result: dict[str, Any] = {
            "source": relative,
            "characters": len(content),
            # v3: classification.doc_type is a plain string (was DocType.value in v2)
            "doc_type": classification.doc_type,
            "confidence": classification.confidence,
            "rationale": classification.rationale,
            "complete": complete,
            "completeness_reason": completeness_reason,
            "topics": [],
            "pages": [],
            "error": None,
        }
        if not complete:
            return result

        items = _extract_items(content, relative)
        item_map = {item["id"]: item for item in items}
        # v3: cluster_topics is async; returns [] if LLM missing
        topics = await cluster_topics(
            items, llm=llm, project_root=root,
        )
        for topic in topics:
            topic_text = "\n\n".join(
                item_map[item_id]["text"]
                for item_id in topic.item_ids
                if item_id in item_map
            )
            # v3: fill_slots is async + D7 (returns None on failure)
            page = await fill_slots(
                topic, source_text=topic_text,
                llm=llm, item_texts=item_map, project_root=root,
            )
            if page is None:
                # D7: skip failed topic — record only that it failed
                result["topics"].append({
                    "id": topic.id,
                    "title": topic.title,
                    "item_ids": topic.item_ids,
                    "failed": True,
                })
                continue
            # T1 / H2 加固: page ID is script-owned. Build a stable
            # page ID from the relative source path + topic slug; never
            # trust the LLM-supplied topic id as the page id (cross-document
            # collisions otherwise). The legacy __dict__ injection of
            # topic_id is replaced below via the dedicated ConceptPage
            # attribute, so failures.filter_failed_topics keeps working
            # without poking the dataclass.
            page_id = _stable_page_id(relative, topic.id)
            validate_page_id(page_id)
            page.topic_id = topic.id  # formal field (see ConceptPage)
            result["topics"].append({
                "id": topic.id,
                "title": topic.title,
                "item_ids": topic.item_ids,
            })
            result["pages"].append({
                "id": page_id,
                "title": page.title,
                "type": page.type,
                "source_ids": list(page.sources),
                "filled_slots": list(page.slots),
                "needs_review_slots": list(page.needs_review_slots),
                "has_evidence": page.has_evidence,
            })
            if page_sink is not None:
                page_sink(page)
        return result
    except Exception as exc:
        # T1 / H2 加固: don't dump the full traceback to the operator's
        # console (P2). Record `failure_stage` + truncated reason in the
        # report so spot-check pilots can correlate failures without
        # drowning in stack noise.
        reason = f"{type(exc).__name__}: {exc}"[:_EXC_REASON_LIMIT]
        log.warning(
            "_extract_one failed for %r: %s", relative, reason,
        )
        return {
            "source": relative,
            "characters": 0,
            "doc_type": None,
            "confidence": 0.0,
            "rationale": "",
            "complete": False,
            "completeness_reason": "",
            "topics": [],
            "pages": [],
            "error": reason,
            "failure_stage": "extract_one",
        }


def _extract_items(content: str, relative: str) -> list[dict[str, str]]:
    """Section / list-item based slicing — same algorithm as v2."""
    headings = list(re.finditer(r"(?m)^#{1,3}\s+(.+?)\s*$", content))
    if len(headings) >= 2:
        items = []
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
            text = content[match.start():end].strip()
            items.append({"id": f"{relative}#section-{index + 1}", "text": text})
        return items
    numbered = [line.strip() for line in content.splitlines() if re.match(r"^\d+[.、,，)]\s*\S", line)]
    if len(numbered) >= 3:
        return [
            {"id": f"{relative}#item-{index + 1}", "text": text}
            for index, text in enumerate(numbered)
        ]
    return [{"id": relative, "text": content.strip()}]


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    types = Counter(item["doc_type"] for item in results if item["doc_type"])
    return {
        "selected": len(results),
        "complete": sum(1 for item in results if item["complete"]),
        "incomplete": sum(1 for item in results if item["doc_type"] == "incomplete"),
        "errors": sum(1 for item in results if item["error"]),
        "topics": sum(len(item["topics"]) for item in results),
        "pages": sum(len(item["pages"]) for item in results),
        "doc_types": dict(sorted(types.items())),
    }


def _json_text(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def _markdown_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# V7 Extract Pilot Report",
        "",
        f"- mode: `{report['mode']}`",
        f"- seed: `{report['seed']}`",
        f"- selected: {summary['selected']}",
        f"- complete: {summary['complete']}",
        f"- incomplete: {summary['incomplete']}",
        f"- pages (dry-run): {summary['pages']}",
        "- spot-check: pending",
        "",
        "## Sources",
        "",
        "| Source | Type | Complete | Topics | Pages | Error |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in report["results"]:
        lines.append(
            f"| `{item['source']}` | `{item['doc_type']}` | "
            f"{item['complete']} | {len(item['topics'])} | "
            f"{len(item['pages'])} | {item['error'] or ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V7 extraction pilot in dry-run mode.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--markdown-out", default=str(DEFAULT_MARKDOWN))
    parser.add_argument(
        "--provider",
        default=None,
        help=(
            "Optional name of a configured LLM provider (from "
            "src.llm.registry.ProviderRegistry). When omitted, the pilot "
            "auto-resolves the registry default and falls back to "
            "offline-heuristic only when no provider is configured."
        ),
    )
    parser.add_argument(
        "--sources",
        default=None,
        help=(
            "Path to a JSON file holding an explicit list of source paths "
            "(relative to --root) to run. Overrides random selection."
        ),
    )
    args = parser.parse_args(argv)
    llm = _build_llm(args.provider)
    sources = _load_sources(args.sources)
    report = asyncio.run(run_pilot(
        args.root,
        count=args.count,
        seed=args.seed,
        json_output=args.json_out,
        markdown_output=args.markdown_out,
        llm=llm,
        sources=sources,
    ))
    print(_json_text(report), end="")
    return 0 if report["summary"]["errors"] == 0 else 2


def _load_sources(path: str | None) -> list[str] | None:
    if not path:
        return None
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_llm(provider_name: str | None):
    """Resolve an injected LLMClient. Returns None when no provider was
    requested — keeps the pilot offline-by-default."""
    target = provider_name
    if not target:
        try:
            from src.llm.registry import ProviderRegistry

            cfg = ProviderRegistry.get_default()
            target = cfg.name
        except Exception:
            return None
    try:
        # Lazy import keeps the offline path free of llm provider deps.
        from src.pipeline.v7_extract.llm_client import AnthropicLLMClient

        return AnthropicLLMClient(default_provider_name=target)
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
