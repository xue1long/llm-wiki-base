"""Run the small writing retrieval evaluation without hiding readiness failures."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

from src.searcher.hybrid_search import hybrid_search
from src.vector.pending import readiness
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import read_page


ACTIONABLE_TAG = "用途/可执行"


def _corpus_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "raw" / "sources").rglob("*")) + sorted((root / "wiki").rglob("*.md")):
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _commit() -> str:
    repo = Path(__file__).resolve().parents[1]
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
    ).strip()


def _load_cases(path: Path) -> list[dict]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]
    if len(cases) != 20:
        raise ValueError(f"expected 20 cases, got {len(cases)}")
    if sum(case["kind"] == "positive" for case in cases) != 15:
        raise ValueError("expected 15 positive cases")
    if sum(case["kind"] == "negative" for case in cases) != 5:
        raise ValueError("expected 5 negative cases")
    return cases


def _is_actionable(paths: WikiPaths, result: dict) -> bool:
    path = paths.root / result["path"]
    try:
        return ACTIONABLE_TAG in read_page(path).tags
    except Exception:
        return False


async def _run(root: Path, cases_path: Path, mode: str = "hybrid") -> dict:
    paths = WikiPaths(root)
    cases = _load_cases(cases_path)
    status = readiness(paths) if mode in {"hybrid", "vector"} else {
        "ready": True, "reason": "keyword", "pending": None,
        "failed": None, "embedding_model": None,
    }
    rows = []
    for case in cases:
        # Direct search is retained only as a baseline diagnostic. It bypasses
        # the service ready gate and must not be treated as the writing result.
        direct = await hybrid_search(case["query"], top_k=5, paths=paths, mode=mode)
        direct_actionable = [r for r in direct if _is_actionable(paths, r)]
        writing = [] if not status["ready"] else direct_actionable
        expected = case.get("expected_page_id")
        expected_path = f"wiki/concepts/{expected}.md" if expected else None
        rows.append({
            "id": case["id"],
            "kind": case["kind"],
            "direct_top5": [r["path"] for r in direct],
            "direct_actionable_top5": [r["path"] for r in direct_actionable],
            "writing_top5": [r["path"] for r in writing],
            "expected_path": expected_path,
            "expected_hit": bool(expected_path and expected_path in [r["path"] for r in writing]),
            "abstained": not writing,
        })
    positives = [row for row in rows if row["kind"] == "positive"]
    negatives = [row for row in rows if row["kind"] == "negative"]
    return {
        "mode": mode,
        "commit": _commit(),
        "status": "blocked" if not status["ready"] else "complete",
        "reason": status["reason"],
        "corpus_hash": _corpus_hash(root),
        "vector": status,
        "cases": len(rows),
        "positive_expected_hits": sum(row["expected_hit"] for row in positives),
        "negative_abstains": sum(row["abstained"] for row in negatives),
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("knowledge/novel-wiki"))
    parser.add_argument(
        "--cases", type=Path,
        default=Path("docs/evaluation/writing_retrieval_cases.yaml"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--mode", choices=("hybrid", "keyword", "vector"), default="hybrid")
    args = parser.parse_args()
    result = asyncio.run(_run(args.project_root.resolve(), args.cases.resolve(), args.mode))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
