"""Protocols and shared dataclasses for the pipeline subsystem.

PipelineStage is the unit of work. PipelineRunner (in runner.py) takes
a list of stages and a PipelineContext, drives them sequentially, and
handles status transitions.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..types import SourceType


@dataclass
class PipelineContext:
    """Carries the data needed to drive a pipeline run.

    The `stages` dict is populated as stages run: ctx.stages["collector"]
    = CollectorStageResult, etc. Tests can inspect or override any field.
    """
    task_id: str
    source: str
    source_type: SourceType
    project_id: str | None = None
    # Populated by the runner before stages run:
    paths: Any = None
    provider: Any = None
    model: str = "gpt-4o-mini"
    # Stage outputs:
    collector_result: Any = None
    analysis_result: Any = None
    # Metadata:
    folder_context: str = ""
    source_path: str = ""


@dataclass
class StageResult:
    """Result of running a single PipelineStage."""
    success: bool
    payload: Any = None


@runtime_checkable
class PipelineStage(Protocol):
    """A unit of work in the pipeline.

    `name` is a string identifier used in logs and the wiki page metadata.
    `run` is an async coroutine that takes the PipelineContext (mutated
    in place to carry outputs forward) and the previous stage's result
    (None for the first stage).
    """
    name: str

    async def run(self, ctx: PipelineContext, prev_result: Any) -> StageResult: ...
