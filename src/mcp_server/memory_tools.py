"""MCP Memory API tools — 5 new tools for the knowledge OS memory system.

Old tools (ruflo_kb_search, ruflo_kb_read_file, ruflo_kb_files, ruflo_kb_ingest,
ruflo_kb_reviews, ruflo_kb_projects, ruflo_kb_set_project, ruflo_kb_status)
remain available and are marked deprecated.
"""
import json

from mcp.types import Tool, TextContent


# ---------------------------------------------------------------------------
# Module-level state (set by register_memory_tools)
# ---------------------------------------------------------------------------

_memory_retrieval = None
_decision_recorder = None
_provenance_tracker = None
_wiki_paths = None

# Allowed fields for memory_update
_SAFE_UPDATE_FIELDS = {"title", "content", "grade"}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

MEMORY_TOOLS = [
    Tool(
        name="ruflo_kb_memory_search",
        description="Search the knowledge OS memory system (semantic/episodic/decision/procedural)",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "memory_type": {
                    "type": "string",
                    "enum": ["semantic", "episodic", "decision", "procedural"],
                    "description": "Optional memory type filter",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="ruflo_kb_memory_recall",
        description="Recall a specific memory object by ID with full provenance chain",
        inputSchema={
            "type": "object",
            "properties": {
                "object_id": {"type": "string", "description": "Memory object ID to recall"},
            },
            "required": ["object_id"],
        },
    ),
    Tool(
        name="ruflo_kb_memory_explain",
        description="Explain the provenance chain for a knowledge object (where it came from)",
        inputSchema={
            "type": "object",
            "properties": {
                "object_id": {"type": "string", "description": "Object ID to explain provenance for"},
            },
            "required": ["object_id"],
        },
    ),
    Tool(
        name="ruflo_kb_memory_verify",
        description="Verify a knowledge object — check evidence, confidence, and give a verdict",
        inputSchema={
            "type": "object",
            "properties": {
                "object_id": {"type": "string", "description": "Object ID to verify"},
            },
            "required": ["object_id"],
        },
    ),
    Tool(
        name="ruflo_kb_memory_update",
        description="Update safe fields (title, content, grade) of a memory object",
        inputSchema={
            "type": "object",
            "properties": {
                "object_id": {"type": "string", "description": "Object ID to update"},
                "changes": {
                    "type": "object",
                    "description": "Fields to update (title, content, grade only)",
                },
            },
            "required": ["object_id", "changes"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _memory_response_to_dict(mr) -> dict:
    """Serialize a MemoryResponse to a JSON-safe dict."""
    ranked = []
    for r in (mr.ranked_results or []):
        if hasattr(r, "object_id"):
            ranked.append({
                "object_id": r.object_id,
                "title": r.title,
                "content": r.content,
                "score": r.score,
                "source": r.source,
            })
        elif isinstance(r, dict):
            ranked.append(r)
        else:
            ranked.append(str(r))

    return {
        "memory_object": mr.memory_object,
        "provenance_chain": mr.provenance_chain,
        "related_decisions": mr.related_decisions,
        "conflicting_claims": mr.conflicting_claims,
        "ranked_results": ranked,
        "query": mr.query,
        "query_type": mr.query_type,
    }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def _memory_search(arguments: dict) -> list[TextContent]:
    """Handle ruflo_kb_memory_search."""
    query = arguments.get("query", "")
    memory_type = arguments.get("memory_type")

    if _memory_retrieval is None:
        return [TextContent(type="text", text=json.dumps(
            {"error": "Memory retrieval not configured"}, indent=2))]

    response = _memory_retrieval.retrieve(query)
    result = _memory_response_to_dict(response)
    if memory_type:
        result["filter_memory_type"] = memory_type
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def _memory_recall(arguments: dict) -> list[TextContent]:
    """Handle ruflo_kb_memory_recall."""
    object_id = arguments.get("object_id", "")

    if _memory_retrieval is None:
        return [TextContent(type="text", text=json.dumps(
            {"error": "Memory retrieval not configured"}, indent=2))]

    response = _memory_retrieval.recall(object_id)

    if response.memory_object is None:
        return [TextContent(type="text", text=json.dumps(
            {"error": f"Object not found: {object_id}"}, indent=2))]

    result = _memory_response_to_dict(response)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def _memory_explain(arguments: dict) -> list[TextContent]:
    """Handle ruflo_kb_memory_explain."""
    object_id = arguments.get("object_id", "")

    # Try provenance tracker first
    if _provenance_tracker is not None:
        chain = _provenance_tracker.get_provenance_chain(object_id)
        if chain:
            return [TextContent(type="text", text=json.dumps(
                {"object_id": object_id, "provenance": chain}, indent=2))]

    # Fallback to recall's provenance data
    if _memory_retrieval is not None:
        response = _memory_retrieval.recall(object_id)
        if response.provenance_chain:
            return [TextContent(type="text", text=json.dumps(
                {"object_id": object_id, "provenance": response.provenance_chain}, indent=2))]

    return [TextContent(type="text", text=json.dumps(
        {"object_id": object_id, "provenance": None, "error": "No provenance found"}, indent=2))]


async def _memory_verify(arguments: dict) -> list[TextContent]:
    """Handle ruflo_kb_memory_verify."""
    object_id = arguments.get("object_id", "")

    exists = False
    has_evidence = False
    confidence = 0.0
    source_count = 0

    if _memory_retrieval is not None:
        response = _memory_retrieval.recall(object_id)
        if response.memory_object is not None:
            exists = True
            confidence = response.memory_object.get("score", 0.0)
            if response.provenance_chain:
                has_evidence = True
                source_count = 1

    if _provenance_tracker is not None:
        chain = _provenance_tracker.get_provenance_chain(object_id)
        if chain:
            has_evidence = True
            source_count = max(source_count, len(chain.get("derived_objects", [])))

    if exists and has_evidence:
        verdict = "verified"
    elif exists:
        verdict = "uncertain"
    else:
        verdict = "unverified"

    return [TextContent(type="text", text=json.dumps({
        "object_id": object_id,
        "exists": exists,
        "has_evidence": has_evidence,
        "confidence": confidence,
        "source_count": source_count,
        "verdict": verdict,
    }, indent=2))]


async def _memory_update(arguments: dict) -> list[TextContent]:
    """Handle ruflo_kb_memory_update."""
    object_id = arguments.get("object_id", "")
    changes = arguments.get("changes", {})

    # Validate safe fields
    invalid_fields = set(changes.keys()) - _SAFE_UPDATE_FIELDS
    if invalid_fields:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Cannot update restricted fields: {sorted(invalid_fields)}",
            "allowed_fields": sorted(_SAFE_UPDATE_FIELDS),
        }, indent=2))]

    # Try to persist to disk via wiki_paths
    page = _find_and_update_page(object_id, changes)
    if page is not None:
        return [TextContent(type="text", text=json.dumps({
            "object_id": object_id,
            "updated_fields": changes,
            "updated_object": {
                "object_id": object_id,
                "title": page.title,
                "content": page.body,
                "grade": page.grade,
            },
            "status": "updated",
        }, indent=2))]

    # Fallback: check via memory retrieval
    if _memory_retrieval is not None:
        response = _memory_retrieval.recall(object_id)
        if response.memory_object is None:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Object not found: {object_id}",
            }, indent=2))]
        current = dict(response.memory_object)
        current.update({k: v for k, v in changes.items() if k in _SAFE_UPDATE_FIELDS})
        return [TextContent(type="text", text=json.dumps({
            "object_id": object_id,
            "updated_fields": changes,
            "updated_object": current,
            "status": "updated",
            "note": "Memory retrieval active but no wiki_paths configured; update not persisted",
        }, indent=2))]

    return [TextContent(type="text", text=json.dumps({
        "object_id": object_id,
        "updated_fields": changes,
        "status": "updated",
        "note": "Memory retrieval not configured; update recorded but not persisted",
    }, indent=2))]


def _find_and_update_page(object_id: str, changes: dict):
    """Locate the wiki page for *object_id* and apply *changes* in-place.

    Returns the updated WikiPage on success, or None if the page could not
    be found or written.
    """
    if _wiki_paths is None:
        return None
    try:
        from src.wiki.storage.page_writer import read_page, write_page
        from pathlib import Path

        page_file = _locate_page_file(object_id)
        if page_file is None:
            return None

        page = read_page(page_file)
        if "title" in changes:
            page.title = changes["title"]
        if "content" in changes:
            page.body = changes["content"]
        if "grade" in changes:
            page.grade = changes["grade"]
        page.updated_at = int(__import__("time").time() * 1000)
        write_page(_wiki_paths, page)
        return page
    except Exception:
        return None


def _locate_page_file(object_id: str):
    """Find the .md file for *object_id* across all wiki directories."""
    from pathlib import Path
    for dir_attr in ("wiki_sources", "wiki_entities", "wiki_concepts",
                     "wiki_synthesis", "wiki_claims", "wiki_decisions"):
        dir_path = getattr(_wiki_paths, dir_attr, None)
        if dir_path is None:
            continue
        candidate = Path(dir_path) / f"{object_id}.md"
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Handler registry (used by main.py's call_tool dispatcher)
# ---------------------------------------------------------------------------

_memory_handlers = {
    "ruflo_kb_memory_search": _memory_search,
    "ruflo_kb_memory_recall": _memory_recall,
    "ruflo_kb_memory_explain": _memory_explain,
    "ruflo_kb_memory_verify": _memory_verify,
    "ruflo_kb_memory_update": _memory_update,
}


def register_memory_tools(mcp_server, memory_retrieval=None, decision_recorder=None,
                          provenance_tracker=None, wiki_paths=None):
    """Register the 5 memory tools on the MCP server instance.

    Sets module-level state so that the tool handlers can access the
    memory infrastructure.  Also exports ``MEMORY_TOOLS`` and
    ``_memory_handlers`` for ``main.py`` to merge into ``list_tools()``
    and ``call_tool()``.

    Args:
        mcp_server: The ``mcp.server.Server`` instance.
        memory_retrieval: Optional ``MemoryRetrieval`` instance.
        decision_recorder: Optional ``DecisionRecorder`` instance.
        provenance_tracker: Optional ``ProvenanceTracker`` instance.
        wiki_paths: Optional ``WikiPaths`` for persisting memory updates.
    """
    global _memory_retrieval, _decision_recorder, _provenance_tracker, _wiki_paths
    _memory_retrieval = memory_retrieval
    _decision_recorder = decision_recorder
    _provenance_tracker = provenance_tracker
    _wiki_paths = wiki_paths
