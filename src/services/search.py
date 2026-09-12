"""Search service — dispatches to the hybrid (semantic + keyword) searcher.

Extracted from src/server/routes/search.py. Validates the project,
delegates to src.searcher.hybrid_search.hybrid_search, and shapes the
response for the HTTP layer.

The service passes the requested mode to the underlying searcher and blocks
semantic writing search when the project's Wiki/Vector state is not ready.

The service resolves ``WikiPaths`` for the project and passes both the paths
and requested mode to the searcher, so readiness and vector retrieval remain
project-scoped.
"""
from __future__ import annotations

import logging
import re
import asyncio

from ..lib.project import resolve_project
from ..integrations.gbrain.api import load_manifest, load_search_config, load_search_state
from ..integrations.gbrain.state import load_runtime_state
from ..searcher.gbrain_mcp import GBrainSearchError, adapt_results, run_mcp_search
from ..llm.embedding_runtime import get_embedding_provider
from ..searcher.hybrid_search import hybrid_search
from ..vector.pending import readiness as vector_readiness
from ..vector.store import get_table as get_vector_table

logger = logging.getLogger(__name__)


async def search(
    project_id: str,
    query: str,
    top_k: int = 10,
    mode: str = "hybrid",
    page_type: str | None = None,
) -> dict:
    """Search the project's wiki tree and return ranked results.

    Returns a dict ready for the HTTP route:
        {
            "query": str,
            "mode": str,           # passed through to the underlying searcher
            "topK": int,           # echoed for the client
            "tokenHits": 0,        # reserved (not populated by current impl)
            "vectorHits": 0,       # reserved (not populated by current impl)
            "results": list[SearchResult],
        }
    """
    # Validate the project exists; capture WikiPaths for project-scoped
    # vector resolution (audit I3).
    ctx, paths = resolve_project(project_id, by_id_only=True)

    if mode not in {"hybrid", "keyword", "vector"}:
        raise ValueError(f"unsupported search mode: {mode}")
    gbrain = _gbrain_readiness(paths.root)
    gbrain_fallback_reason = ""
    if mode == "hybrid" and page_type is None and gbrain["ready"] and not _should_abstain(query):
        try:
            remote = await asyncio.to_thread(
                run_mcp_search,
                gbrain["runtime_path"],
                gbrain["source_id"],
                query,
                top_k,
            )
            results = adapt_results(
                remote,
                source_id=gbrain["source_id"],
                manifest=load_manifest(paths.root),
                top_k=top_k,
            )
            filtered_remote = _filter_actionable(paths, results)
            if filtered_remote:
                return {
                    "query": query,
                    "mode": mode,
                    "topK": top_k,
                    "tokenHits": 0,
                    "vectorHits": 0,
                    "ready": True,
                    "diagnostics": {
                        "ready": True,
                        "backend": "gbrain",
                        "gbrain_ready": True,
                        "local_vector_ready": None,
                    },
                    "results": filtered_remote,
                }
            gbrain_fallback_reason = "remote_filtered_empty"
        except GBrainSearchError as exc:
            gbrain_fallback_reason = str(exc)
        except Exception:
            gbrain_fallback_reason = "remote_error"
    if mode == "keyword":
        status = {"ready": True, "reason": "keyword"}
    else:
        model = ""
        try:
            provider = get_embedding_provider()
            model = str(getattr(provider, "model", "") or getattr(provider, "_model_name", ""))
        except RuntimeError:
            pass
        status = vector_readiness(paths, embedding_model=model, actionable_only=True)
    if mode != "keyword" and status["ready"]:
        try:
            get_vector_table(paths)
        except Exception:
            logger.warning("Vector table init failed for project %s", project_id, exc_info=True)
            status = {**status, "ready": False, "reason": "unavailable"}
    if gbrain_fallback_reason:
        status = {
            **status,
            "backend": "local",
            "gbrain_ready": True,
            "fallback_reason": str(gbrain_fallback_reason),
        }

    if mode != "keyword" and status["ready"] and _should_abstain(query):
        results = []
        status = {**status, "reason": "unsupported_query"}
    elif mode != "keyword" and not status["ready"]:
        results = []
    else:
        results = await hybrid_search(query, top_k=top_k, paths=paths, mode=mode)
        if mode in {"hybrid", "vector"}:
            results = _filter_actionable(paths, results)

    # Post-filter by PageType if requested (1.2.3).
    if page_type:
        results = _filter_by_page_type(paths, results, page_type)

    return {
        "query": query,
        "mode": mode,
        "topK": top_k,
        "tokenHits": 0,
        "vectorHits": 0,
        "ready": status["ready"] if mode != "keyword" else True,
        "diagnostics": status if mode != "keyword" else {"ready": True, "reason": "keyword"},
        "results": results,
    }


def _gbrain_readiness(root) -> dict[str, object]:
    try:
        config = load_search_config(root)
        state = load_search_state(root)
        runtime = load_runtime_state(root)
        ready = bool(
            config.enabled
            and state.status.value == "ready"
            and runtime.get("status") == "ready"
            and runtime.get("path")
            and state.embedding_coverage >= 1.0
            and state.path_mapping_coverage >= 1.0
        )
        return {
            "ready": ready,
            "source_id": config.source_id,
            "runtime_path": runtime.get("path"),
        }
    except Exception:
        return {"ready": False, "source_id": "", "runtime_path": None}


_UNSUPPORTED_WRITING_QUERY = re.compile(
    r"一定|成功率|实时|今天.*榜单|下周.*打赏|预测.*(?:读者|打赏|金额)|"
    r"没有提供|未提供|保证.*一致|直接指出.*重写"
)


def _should_abstain(query: str) -> bool:
    """Reject prediction, real-time, or missing-context writing requests."""
    return bool(_UNSUPPORTED_WRITING_QUERY.search(query))


def _filter_actionable(paths, results: list) -> list:
    """Keep only human-approved actionable pages for semantic writing search."""
    import yaml
    from pathlib import Path
    from ..utils.path import safe_resolve

    filtered = []
    for result in results:
        raw_path = str(result.get("path", "")).replace("\\", "/")
        if raw_path.startswith("wiki/"):
            raw_path = raw_path[5:]
        candidate = safe_resolve(paths.wiki / Path(raw_path))
        if not candidate.exists() or not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end < 0:
            continue
        try:
            frontmatter = yaml.safe_load(text[4:end]) or {}
        except yaml.YAMLError:
            continue
        if "用途/可执行" in (frontmatter.get("tags") or []):
            filtered.append(result)
    return filtered


def _filter_by_page_type(paths, results: list, page_type: str) -> list:
    """Filter search results to only include pages matching page_type."""
    import yaml
    from pathlib import Path

    from ..utils.path import safe_resolve

    wiki_root = paths.wiki
    filtered = []
    for r in results:
        p = r.get("path", "")
        # Normalize: strip backslashes and "wiki/" prefix
        normalized = Path(p.replace("\\", "/").replace("wiki/", "", 1) if p.replace("\\", "/").startswith("wiki/") else p.replace("\\", "/"))
        candidate = safe_resolve(wiki_root / normalized)
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except Exception:
            continue
        if text.startswith("---\n"):
            end = text.find("\n---", 4)
            if end > 0:
                try:
                    fm = yaml.safe_load(text[4:end]) or {}
                except yaml.YAMLError:
                    continue
                if fm.get("type") == page_type:
                    filtered.append(r)
    return filtered
