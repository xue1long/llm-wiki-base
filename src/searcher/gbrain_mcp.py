"""Strict adapter for source-scoped GBrain MCP search results."""
from __future__ import annotations

import math
import json
import os
import subprocess
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping


class GBrainSearchError(ValueError):
    """Remote result cannot be trusted or mapped to the local Wiki."""


@dataclass(frozen=True)
class SearchAdapterResult:
    results: list[dict[str, Any]]
    fallback_reason: str = ""


def build_search_request(query: str, top_k: int) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": query, "limit": top_k}},
    }


def build_mutation_request(tool: str, slug: str, content: str | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {"slug": slug}
    if content is not None:
        arguments["content"] = content
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def run_mcp_search(
    runtime_path: str,
    source_id: str,
    query: str,
    top_k: int,
    *,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Run one source-scoped, read-only stdio search session."""
    env = os.environ.copy()
    env["GBRAIN_SOURCE"] = source_id
    process = subprocess.Popen(
        ["bun", "run", "src/cli.ts", "serve"],
        cwd=runtime_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        shell=False,
    )

    def read_line() -> str:
        assert process.stdout is not None
        return process.stdout.readline()

    def request(payload: dict[str, Any]) -> dict[str, Any]:
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        lines: Queue[str] = Queue()
        threading.Thread(target=lambda: lines.put(read_line()), daemon=True).start()
        try:
            line = lines.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError("gbrain mcp response timeout") from exc
        if not line:
            raise RuntimeError("gbrain mcp closed stdout")
        response = json.loads(line)
        if response.get("error"):
            raise RuntimeError("gbrain mcp tool error")
        return response

    try:
        request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "ruflo-kb", "version": "1"},
                },
            }
        )
        assert process.stdin is not None
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        response = request(build_search_request(query, top_k))
        result = response.get("result", {})
        content = result.get("content", []) if isinstance(result, dict) else []
        if content and isinstance(content[0], dict) and isinstance(content[0].get("text"), str):
            result = json.loads(content[0]["text"])
        if isinstance(result, dict):
            result = result.get("results", [])
        if not isinstance(result, list):
            raise GBrainSearchError("invalid_payload")
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=timeout)


def run_mcp_mutation(
    runtime_path: str,
    source_id: str,
    operation: str,
    slug: str,
    content: str | None = None,
    *,
    timeout: float = 10.0,
) -> Any:
    """Apply one source-scoped GBrain page mutation over stdio MCP."""
    if operation not in {"upsert", "delete", "restore"}:
        raise ValueError(f"unsupported GBrain sync operation: {operation}")
    tool = {"upsert": "put_page", "delete": "delete_page", "restore": "restore_page"}[operation]
    env = os.environ.copy()
    env["GBRAIN_SOURCE"] = source_id
    process = subprocess.Popen(
        ["bun", "run", "src/cli.ts", "serve"],
        cwd=runtime_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        shell=False,
    )

    def request(payload: dict[str, Any]) -> dict[str, Any]:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        lines: Queue[str] = Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        try:
            line = lines.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError("gbrain mcp response timeout") from exc
        if not line:
            raise RuntimeError("gbrain mcp closed stdout")
        response = json.loads(line)
        if response.get("error"):
            raise RuntimeError("gbrain mcp tool error")
        result = response.get("result", {})
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError("gbrain mcp tool error")
        return response

    try:
        request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "ruflo-kb", "version": "1"},
            },
        })
        assert process.stdin is not None
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        response = request(build_mutation_request(tool, slug, content))
        result = response.get("result", {})
        if isinstance(result, dict) and result.get("content"):
            first = result["content"][0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                try:
                    return json.loads(first["text"])
                except json.JSONDecodeError:
                    return first["text"]
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=timeout)


def _error(code: str) -> GBrainSearchError:
    return GBrainSearchError(code)


def _safe_manifest_path(path: Any) -> str:
    if not isinstance(path, str):
        raise _error("path_mapping_failed")
    normalized = path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts or not normalized.startswith("wiki/"):
        raise _error("path_mapping_failed")
    return normalized


def adapt_results(
    remote_results: Any,
    *,
    source_id: str,
    manifest: Mapping[str, Mapping[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not isinstance(remote_results, list):
        raise _error("invalid_payload")
    best: dict[str, dict[str, Any]] = {}
    for item in remote_results:
        if not isinstance(item, Mapping):
            raise _error("invalid_payload")
        required = ("slug", "page_id", "title", "type", "chunk_text", "score", "source_id")
        if any(key not in item for key in required):
            raise _error("invalid_payload")
        if item["source_id"] != source_id:
            raise _error("source_scope_mismatch")
        slug = item["slug"]
        if not isinstance(slug, str) or slug not in manifest:
            raise _error("path_mapping_failed")
        path = _safe_manifest_path(manifest[slug].get("path"))
        try:
            score = float(item["score"])
        except (TypeError, ValueError) as exc:
            raise _error("invalid_payload") from exc
        if not math.isfinite(score):
            raise _error("invalid_payload")
        result = {
            "path": path,
            "title": str(item["title"]),
            "content": str(item["chunk_text"]),
            "score": score,
            "source": "gbrain",
            "type": str(item["type"]),
            "page_id": str(item["page_id"]),
            "source_id": source_id,
        }
        previous = best.get(slug)
        if previous is None or score > previous["score"]:
            best[slug] = result
    return sorted(best.values(), key=lambda item: (-item["score"], item["path"]))[:top_k]


def search_with_fallback(
    remote_search: Callable[[], Any],
    local_search: Callable[[], list[dict[str, Any]]],
    *,
    source_id: str,
    manifest: Mapping[str, Mapping[str, Any]],
    top_k: int,
) -> SearchAdapterResult:
    try:
        results = adapt_results(
            remote_search(), source_id=source_id, manifest=manifest, top_k=top_k
        )
        if not results:
            local = local_search()
            if local:
                return SearchAdapterResult(local, "remote_empty_mismatch")
        return SearchAdapterResult(results)
    except GBrainSearchError as exc:
        return SearchAdapterResult(local_search(), str(exc))
    except Exception:
        return SearchAdapterResult(local_search(), "remote_error")


__all__ = [
    "GBrainSearchError",
    "SearchAdapterResult",
    "adapt_results",
    "build_search_request",
    "build_mutation_request",
    "run_mcp_search",
    "run_mcp_mutation",
    "search_with_fallback",
]
