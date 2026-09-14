"""Run a deterministic, write-free V7 extraction pilot.

The pilot is deliberately a dry-run tool.  It reads raw sources, runs the
local Stage 1/3/4/5 components, and writes only its requested report files;
it never calls the Wiki writer or mutates ``wiki/``.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Make direct ``python scripts/extract_pilot.py`` execution behave like a
# module invocation from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.pipeline.v7_extract.completeness_checker import check_completeness
from src.pipeline.v7_extract.doc_classifier import classify_doc
from src.pipeline.v7_extract.slot_filler import fill_slots
from src.pipeline.v7_extract.topic_clusterer import cluster_topics


SUPPORTED_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm"})
DEFAULT_ROOT = Path("knowledge/novel-wiki")
DEFAULT_JSON = Path("docs/superpowers/reports/2026-09-13-extract-pilot.json")
DEFAULT_MARKDOWN = Path("docs/superpowers/reports/2026-09-13-extract-pilot-report.md")


def run_pilot(
    root: str | Path = DEFAULT_ROOT,
    *,
    count: int = 50,
    seed: int = 42,
    json_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
    llm: Any = None,
) -> dict[str, Any]:
    """Run the pilot and optionally write JSON/Markdown reports.

    Selection is deterministic for a given ``seed``.  The returned report is
    fully JSON-serializable so callers can add human spot-check annotations.

    ``llm`` is the optional ``LLMClient`` injected for Stage 1 classification
    fallback, Stage 4 topic clustering, and Stage 5 slot filling. When
    ``llm`` is ``None`` the pipeline runs offline-heuristic only — useful
    for tests / CI. The report records whether LLM was enabled.
    """
    if count < 1:
        raise ValueError("count must be positive")
    root = Path(root)
    candidates = _source_files(root)
    selected = _select_sources(candidates, count, seed)
    results: list[dict[str, Any]] = []
    for path in selected:
        relative = path.relative_to(root).as_posix()
        results.append(_extract_one(root, path, relative, llm=llm))

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


def _extract_one(
    root: Path,
    path: Path,
    relative: str,
    *,
    llm: Any = None,
) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        classification = classify_doc(content, filename_hint=path.name, llm=llm)
        complete, completeness_reason = check_completeness(content, classification.doc_type)
        result: dict[str, Any] = {
            "source": relative,
            "characters": len(content),
            "doc_type": classification.doc_type.value,
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
        topics = cluster_topics(items, llm=llm)
        for topic in topics:
            topic_text = "\n\n".join(
                item_map[item_id]["text"]
                for item_id in topic.item_ids
                if item_id in item_map
            )
            page = fill_slots(
                topic,
                source_text=topic_text,
                llm=llm,
                item_texts=item_map,
            )
            page.id = _stable_page_id(relative, topic.id)
            result["topics"].append(
                {
                    "id": topic.id,
                    "title": topic.title,
                    "item_ids": list(topic.item_ids),
                }
            )
            result["pages"].append(
                {
                    "id": page.id,
                    "title": page.title,
                    "type": page.type,
                    "source_ids": [relative],
                    "filled_slots": list(page.slots),
                    "needs_review_slots": list(page.needs_review_slots),
                    "has_evidence": page.has_evidence,
                }
            )
        return result
    except Exception as exc:  # one bad raw file must not abort the pilot
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
            "error": f"{type(exc).__name__}: {exc}",
        }


def _extract_items(content: str, relative: str) -> list[dict[str, str]]:
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


def _stable_page_id(relative: str, topic_id: str) -> str:
    stem = Path(relative).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "source"
    digest = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:8]
    topic_slug = re.sub(r"[^a-z0-9]+", "-", topic_id.lower()).strip("-") or "topic"
    return f"{stem}-{digest}-{topic_slug}"


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
    import json

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
            "runs offline-heuristic only and never hits the network."
        ),
    )
    args = parser.parse_args(argv)
    llm = _build_llm(args.provider)
    report = run_pilot(
        args.root,
        count=args.count,
        seed=args.seed,
        json_output=args.json_out,
        markdown_output=args.markdown_out,
        llm=llm,
    )
    print(_json_text(report), end="")
    return 0 if report["summary"]["errors"] == 0 else 2


def _build_llm(provider_name: str | None):
    """Resolve an injected LLMClient. Returns None when no provider was
    requested — keeps the pilot offline-by-default."""
    if not provider_name:
        return None
    # Lazy import keeps the offline path free of llm provider deps.
    from src.pipeline.v7_extract.llm_client import AnthropicLLMClient

    return AnthropicLLMClient(default_provider_name=provider_name)


if __name__ == "__main__":
    sys.exit(main())
