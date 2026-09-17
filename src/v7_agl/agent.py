"""AGL Agent adapter for V7 Stage5 training.

Ponytail: 1 rollout = 1 topic. The AGL local controller spawns this Agent
once per rollout (per topic). The Agent runs V7 fill_slots on the precomputed
topic, writes the page into wiki/_agl/concepts/ (quarantine), and posts a
reward to the Gateway event endpoint.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx


# Force V2 path (AGL trains V2 fill_slots single-call).
os.environ.setdefault("V7_USE_V3", "false")


REQUIRED_SLOTS = (
    "## 定义",
    "## 主要特点",
    "## 适用场景",
    "## 反模式与常见错误",
    "## 证据强度",
    "## 例子",
    "## 相关概念",
    "## 参考来源",
)


class Agent:
    """AGL local controller spawns this once per rollout (= 1 topic)."""

    async def run(self) -> None:
        # AGL-injected env vars
        agl_base_url = os.environ["AGL_OPENAI_BASE_URL"]
        event_url = os.environ["AGL_EVENT_URL"]
        agl_key = os.environ["AGL_KEY"]

        # Trainer-injected env vars (from env_map)
        topic_id = os.environ["TOPIC_ID"]
        topic_title = os.environ["TOPIC_TITLE"]
        topic_sources = json.loads(os.environ.get("TOPIC_SOURCES", "[]"))
        raw_path = os.environ["RAW_PATH"]
        project_id = os.environ["PROJECT_ID"]
        train_model = os.environ.get("AGL_TRAIN_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")

        raw_text = Path(raw_path).read_text(encoding="utf-8", errors="ignore")

        # Import V7 modules lazily so the agent's PYTHONPATH doesn't have
        # to be set up just to import the harness.
        from src.pipeline.v7_extract.llm_client import BaseURLLLMClient
        from src.pipeline.v7_extract.slot_filler import fill_slots
        from src.pipeline.v7_extract.wiki_writer import WikiWriter
        from src.wiki.core.paths import WikiPaths

        # 1) Stage5 — AGL Gateway intercepts this LLM call
        llm = BaseURLLLMClient(
            base_url=agl_base_url,
            api_key=agl_key,
            model=train_model,
        )
        page = await fill_slots(
            topic={"id": topic_id, "title": topic_title, "item_ids": topic_sources},
            source_text=raw_text,
            llm=llm,
        )

        # 2) Stage7 — write to wiki/_agl/concepts/ for quarantine
        paths = WikiPaths(Path(f"knowledge/{project_id}"))
        writer = WikiWriter(paths)
        writer.set_pages_subdir("_agl")

        if page is not None:
            report = writer.commit_and_index([page])
            reward = _score(page, report)
        else:
            reward = 0.0

        # 3) Post reward to Gateway
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                event_url,
                json={
                    "event_type": "reward",
                    "data": {
                        "value": reward,
                        "source": "v7-agl",
                        "reason": (
                            f"topic_id={topic_id} "
                            f"success={page is not None}"
                        ),
                    },
                },
                headers={"Authorization": f"Bearer {agl_key}"},
            )


def _score(page, report) -> float:
    """0.0-1.0 reward: 8-slot completeness + commit success."""
    if page is None or report.written == 0:
        return 0.0
    body = page.body or ""
    present = sum(1 for slot in REQUIRED_SLOTS if slot in body)
    slot_score = present / len(REQUIRED_SLOTS)
    return slot_score