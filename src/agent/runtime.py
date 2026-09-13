"""Agent runtime — run agent loop, execute tools, generate final answer."""
import json
import logging

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .tools import TOOLS
from .types import AgentConfig, AgentEvent, AgentLoopAction


_logger = logging.getLogger(__name__)

PLANNER_PROMPT = """You are an Agent. Available tools:
{tool_descriptions}

User message: {message}

Previous tool observations:
{observations}

Local wiki search guidance:
- For wiki questions, search using the user's exact distinctive terms first; do not translate or paraphrase them.
- If a search returns result_count 0, stop reformulating searches and finalize with the limitation.
- If a search returns results, read the best page when needed, then finalize. After wiki.read_page, never read the same path again.

Return exactly one JSON object. Do not return markdown, prose, or a second JSON object.
Allowed fields are action, tool, query, path, topK, fields, and answer.
Examples of valid output:
{{"action":"final","answer":"..."}}
{{"action":"tool","tool":"wiki.search","query":"...","topK":5}}
"""


def _planner_observation(tool_name: str, result: dict) -> str:
    """Keep planner context small while retaining the full event result."""
    if not isinstance(result, dict):
        return str(result)[:1000]
    if tool_name in {"wiki.search", "source.search", "graph.search"}:
        results = result.get("results")
        if isinstance(results, list):
            compact_results = []
            for item in results[:5]:
                if not isinstance(item, dict):
                    continue
                compact = {
                    key: item[key]
                    for key in ("id", "path", "title", "type", "source", "source_id", "score")
                    if key in item
                }
                snippet = item.get("snippet") or item.get("chunk_text") or item.get("content")
                if snippet:
                    compact["snippet"] = str(snippet)[:240]
                compact_results.append(compact)
            diagnostics = result.get("diagnostics")
            backend = result.get("backend")
            if not backend and isinstance(diagnostics, dict):
                backend = diagnostics.get("backend")
            return json.dumps({
                "query": result.get("query"),
                "backend": backend,
                "result_count": len(results),
                "results": compact_results,
            }, ensure_ascii=False)
    if tool_name == "wiki.read_page":
        observation = {"next_step": "finalize"}
        observation.update({
            key: result[key]
            for key in ("id", "title", "type", "body", "error")
            if key in result
        })
        return json.dumps(observation, ensure_ascii=False)[:4000]
    return json.dumps(result, ensure_ascii=False)[:1000]


def _action_fingerprint(action: AgentLoopAction) -> str:
    return json.dumps({
        "tool": action.tool,
        "query": action.query,
        "path": action.path,
        "top_k": action.top_k,
    }, ensure_ascii=False, sort_keys=True)


class AgentRuntime:
    def __init__(self, ctx, config: AgentConfig | None = None):
        self.ctx = ctx
        self.config = config or AgentConfig()
        # Resolve LLM provider with a fallback chain — real ProjectContext does
        # not (yet) expose ctx.settings.llm.provider_registry_name, so we try:
        #   1) "default" key in the registry (preferred for tests / explicit config)
        #   2) ctx.settings.llm.provider_registry_name (pre-task-3 chat.py path)
        #   3) first available provider via get_default() (graceful default)
        # Only the "first available" branch was migrated to use ProviderRegistry.get_default();
        # the named lookups stay as explicit ProviderRegistry.get() calls to preserve order.
        providers = ProviderRegistry.load()
        cfg = providers.get("default")
        if cfg is None:
            try:
                config_name = ctx.settings.llm.provider_registry_name
                cfg = ProviderRegistry.get(config_name)
            except AttributeError:
                cfg = ProviderRegistry.get_default()
        self.provider = create_llm_provider(cfg.name, model_override=self.config.model)
        self.tools = TOOLS

    async def run(self, message: str) -> list[AgentEvent]:
        """Run agent loop; yield events; return when final or max_iterations."""
        events: list[AgentEvent] = []
        events.append(AgentEvent.run_started("s-mvp", self.config.model))
        observations: list[str] = []
        parse_failures = 0
        previous_tool_fingerprint: str | None = None
        duplicate_tool_seen = False
        last_tool_result: dict | None = None

        tool_descs = "\n".join(f"- {n}: {t.description}" for n, t in self.tools.items())

        for iteration in range(self.config.max_iterations):
            prompt = PLANNER_PROMPT.format(
                message=message,
                tool_descriptions=tool_descs,
                observations="\n".join(observations) or "(none yet)",
            )
            response = await self.provider.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["final", "tool", "user_input"]},
                        "tool": {"type": "string"},
                        "query": {"type": "string"},
                        "path": {"type": "string"},
                        "topK": {"type": "integer"},
                        "fields": {"type": "array"},
                        "answer": {"type": "string"},
                    },
                    "required": ["action"],
                },
            )
            # LLMResponse.content holds the raw JSON string.
            try:
                raw_json = response.content if isinstance(response.content, str) else str(response.content)
            except Exception as e:
                _logger.warning(f"[agent] could not extract JSON body: {e}")
                parse_failures += 1
                if parse_failures > 1:
                    events.append(AgentEvent(
                        type="agent_planner_protocol_error",
                        iteration=iteration,
                        timestamp=0,
                        payload={"error": str(e), "attempts": parse_failures},
                    ))
                    return events
                observations.append(
                    "[planner protocol error: return exactly one JSON object and no prose or second object]"
                )
                continue
            try:
                action = AgentLoopAction.from_json(raw_json)
            except Exception as e:
                _logger.warning(f"[agent] parse error: {e}")
                parse_failures += 1
                if parse_failures > 1:
                    events.append(AgentEvent(
                        type="agent_planner_protocol_error",
                        iteration=iteration,
                        timestamp=0,
                        payload={"error": str(e), "attempts": parse_failures},
                    ))
                    return events
                observations.append(
                    "[planner protocol error: return exactly one JSON object and no prose or second object]"
                )
                continue
            parse_failures = 0

            if action.action == "final":
                events.append(AgentEvent.final_answer(iteration, action.answer or "Done.", []))
                return events
            elif action.action == "tool":
                tool = self.tools.get(action.tool)
                if not tool:
                    observations.append(f"[unknown tool: {action.tool}]")
                    continue
                fingerprint = _action_fingerprint(action)
                if fingerprint == previous_tool_fingerprint:
                    if action.tool == "wiki.read_page" and last_tool_result and last_tool_result.get("body"):
                        events.append(AgentEvent.final_answer(
                            iteration, str(last_tool_result["body"]), []
                        ))
                        return events
                    if duplicate_tool_seen:
                        events.append(AgentEvent(
                            type="agent_planner_stalled",
                            iteration=iteration,
                            timestamp=0,
                            payload={"tool": action.tool, "reason": "repeated_identical_tool_call"},
                        ))
                        return events
                    duplicate_tool_seen = True
                    observations.append(
                        "[identical tool call already completed; use its result, choose another tool, or finalize]"
                    )
                    continue
                previous_tool_fingerprint = fingerprint
                duplicate_tool_seen = False
                events.append(AgentEvent.tool_started(iteration, action.tool, {"query": action.query}))
                try:
                    # Filter out None-valued kwargs so tools with narrower signatures
                    # (e.g. wiki.read_page only accepts `path`) don't TypeError on
                    # the universal query/top_k/path trio.
                    result = await tool.execute(
                        self.ctx,
                        **{k: v for k, v in {
                            "query": action.query,
                            "path": action.path,
                            "top_k": action.top_k,
                        }.items() if v is not None}
                    )
                except Exception as e:
                    result = {"error": str(e)}
                events.append(AgentEvent.tool_completed(iteration, action.tool, result))
                last_tool_result = result
                _logger.info(
                    "[agent] tool completed tool=%s keys=%s result_count=%s body_length=%s",
                    action.tool,
                    sorted(result) if isinstance(result, dict) else [],
                    len(result.get("results", [])) if isinstance(result, dict) and isinstance(result.get("results"), list) else None,
                    len(result.get("body", "")) if isinstance(result, dict) else None,
                )
                observations.append(_planner_observation(action.tool, result))
            else:
                # user_input: MVP not supported
                observations.append("[user_input not supported in MVP]")
        events.append(AgentEvent(type="max_iterations_reached", iteration=self.config.max_iterations,
                                  timestamp=0, payload={"limit": self.config.max_iterations}))
        return events
