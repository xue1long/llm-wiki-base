"""Run the small author-task evaluation against the writing index."""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

import yaml

from src.llm.embedding_runtime import set_embedding_provider
from src.llm.local_embed import LocalEmbeddingProvider
from src.searcher.hybrid_search import hybrid_search
from src.services.search import _should_abstain
from src.vector.pending import readiness
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import read_page


ACTIONABLE_TAG = "用途/可执行"


def _actionable(paths: WikiPaths, results: list[dict]) -> list[dict]:
    output = []
    for result in results:
        try:
            if ACTIONABLE_TAG in read_page(paths.root / result["path"]).tags:
                output.append(result)
        except Exception:
            continue
    return output


async def run(root: Path, tasks_path: Path, cases_path: Path) -> dict:
    paths = WikiPaths(root)
    provider = LocalEmbeddingProvider()
    set_embedding_provider(provider)
    status = readiness(paths, embedding_model=provider._model_name, actionable_only=True)
    if not status["ready"]:
        return {"status": "blocked", "reason": status["reason"], "vector": status, "tasks": []}

    task_data = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))
    case_data = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in case_data["cases"]}
    results = []
    for task in task_data["tasks"]:
        started = time.perf_counter()
        queries = 0
        adopted = None
        for case_id in task["case_ids"]:
            case = cases[case_id]
            queries += 1
            if _should_abstain(case["query"]):
                continue
            found = _actionable(paths, await hybrid_search(case["query"], top_k=5, paths=paths, mode="hybrid"))
            expected = f"wiki/concepts/{case['expected_page_id']}.md"
            if expected in [row["path"] for row in found]:
                adopted = {
                    "case_id": case_id,
                    "query": case["query"],
                    "page_path": expected,
                    "page_id": case["expected_page_id"],
                    "provenance": case["evidence_sources"],
                    "reason": "Top-5 命中人工批准的可执行页面，满足任务可采用条件。",
                }
                break
        results.append({
            "task_id": task["task_id"],
            "query_count": queries,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "accepted": adopted is not None,
            "adopted_result": adopted,
            "reason": "已找到可采用答案并记录 provenance。" if adopted else "任务案例序列未找到可采用答案。",
        })
    return {"status": "complete", "reason": "writing-actionable-scope", "vector": status, "tasks": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("knowledge/novel-wiki"))
    parser.add_argument("--tasks", type=Path, default=Path("docs/evaluation/writing_author_tasks.yaml"))
    parser.add_argument("--cases", type=Path, default=Path("docs/evaluation/writing_retrieval_cases.yaml"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.project_root.resolve(), args.tasks.resolve(), args.cases.resolve()))
    args.out.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
