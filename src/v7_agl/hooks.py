"""AGL RolloutHooks for V7 Stage5 marker tagging.

Ponytail: AGL's per-rollout-mean loss broadcasts one reward across all
triplets. To keep Stage5 the only signal, the hook tags Stage5 model_request
events so the RolloutAdapter can drop non-Stage5 events before GRPO loss.

Ponytail: agentlightning is an optional dep. The hooks class degrades to a
no-op stub when the package isn't installed (ruflo-kb dev env doesn't need
AGL installed for V7 patch work).
"""
from __future__ import annotations

from typing import Any

try:
    from agentlightning.hooks import RolloutHooks  # type: ignore[import-not-found]
    from agentlightning.schemas import Rollout, RolloutCreate  # type: ignore[import-not-found]
    _AGL_AVAILABLE = True
except ImportError:
    # Stub classes — allow the module to import in environments without AGL
    # installed (ruflo-kb CI doesn't depend on agentlightning).
    RolloutHooks = object  # type: ignore[assignment,misc]
    Rollout = object  # type: ignore[assignment,misc]
    RolloutCreate = object  # type: ignore[assignment,misc]
    _AGL_AVAILABLE = False


class V7AglHook(RolloutHooks):
    """Tag Stage5 model_request events for downstream filtering."""

    AGENT_CLASS = "src.v7_agl.agent.Agent"
    PROMPTKind = "fill_slots"

    def on_enqueue(self, request: RolloutCreate) -> RolloutCreate:
        # Force the agent_class so the local controller spawns our Agent.
        if request.config is None:
            from agentlightning.schemas import RolloutConfig, RolloutLocalConfig

            request.config = RolloutConfig(
                local=RolloutLocalConfig(agent_class=self.AGENT_CLASS)
            )
        elif request.config.local is None:
            from agentlightning.schemas import RolloutLocalConfig

            request.config.local = RolloutLocalConfig(agent_class=self.AGENT_CLASS)
        else:
            request.config.local.agent_class = self.AGENT_CLASS

        # env_map: trainer injects these per-rollout from rollout.input.
        # Ponytail: trainer reads topics.jsonl produced by precompute_topics.
        if request.config.local.env_map is None:
            request.config.local.env_map = {}
        request.config.local.env_map.update({
            "TOPIC_ID": "input.topic_id",
            "TOPIC_TITLE": "input.title",
            "TOPIC_SOURCES": "input.sources",
            "RAW_PATH": "input.raw_path",
            "PROJECT_ID": "input.project_id",
            "AGL_TRAIN_MODEL": "input.model",
        })
        return request

    def on_succeeded(
        self,
        rollout: Rollout,
        events: dict[str, list[Any]],
        store: Any,
    ) -> None:
        """Tag Stage5 model_request events with stage5_marker."""
        for attempt_id, attempt_events in events.items():
            for event in attempt_events:
                if getattr(event, "event_type", None) != "model_request":
                    continue
                data = getattr(event, "data", {}) or {}
                prompt_kind = data.get("request", {}).get("prompt_kind", "")
                if prompt_kind == self.PROMPTKind:
                    store.add_event(
                        rollout.rollout_id,
                        attempt_id,
                        "stage5_marker",
                        {"stage": "stage5"},
                    )