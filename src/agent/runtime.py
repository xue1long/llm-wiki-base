"""Agent runtime — run agent loop, execute tools, generate final answer."""
import asyncio
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

Output strict JSON (no markdown fence):
{{
  "action": "tool" | "final" | "user_input",
  "tool": "<tool_name>",
  "query": "...",        // for wiki.search / source.search / graph.search / web.search
  "path": "...",         // for wiki.read_page
  "topK": 5,
  "fields": [...],       // for user_input
  "answer": "..."        // for final
}}
"""


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

        tool_descs = "\n".join(f"- {n}: {t.description}" for n, t in self.tools.items())

        for iteration in range(self.config.max_iterations):
            prompt = PLANNER_PROMPT.format(
                message=message,
                tool_descriptions=tool_descs,
                observations="\n".join(observations) or "(none yet)",
            )
            response = await self.provider.complete(
                prompt=prompt,
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
            try:
                action = AgentLoopAction.from_json(json.dumps(response))
            except Exception as e:
                _logger.warning(f"[agent] parse error: {e}")
                observations.append(f"[parse error: {e}]")
                continue

            if action.action == "final":
                events.append(AgentEvent.final_answer(iteration, action.answer or "Done.", []))
                return events
            elif action.action == "tool":
                tool = self.tools.get(action.tool)
                if not tool:
                    observations.append(f"[unknown tool: {action.tool}]")
                    continue
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
                observations.append(json.dumps(result, ensure_ascii=False)[:1000])
            else:
                # user_input: MVP not supported
                observations.append("[user_input not supported in MVP]")
        events.append(AgentEvent(type="max_iterations_reached", iteration=self.config.max_iterations,
                                  timestamp=0, payload={"limit": self.config.max_iterations}))
        return events