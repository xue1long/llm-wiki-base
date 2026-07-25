"""Tests for PipelineStage Protocol and stage implementations.

The stage tests in this file verify the protocol contract is satisfied
and that each stage can be constructed and called with a PipelineContext.
The end-to-end runner tests are added in Task 9.
"""
import pytest

from src.pipeline.ports import PipelineStage, StageResult, PipelineContext
from src.pipeline.stages import CollectorStage, AnalyzerStage, GeneratorStage
from src.pipeline.stages.collector import CollectorStage as CStage
from src.types import SourceType, TaskStatus


class TestStageProtocolConformance:
    def test_collector_stage_implements_protocol(self):
        assert isinstance(CollectorStage(), PipelineStage)

    def test_analyzer_stage_implements_protocol(self):
        assert isinstance(AnalyzerStage(), PipelineStage)

    def test_generator_stage_implements_protocol(self):
        assert isinstance(GeneratorStage(), PipelineStage)


class TestStageConstruction:
    def test_collector_stage_has_name(self):
        assert CollectorStage().name == "collector"

    def test_analyzer_stage_has_name(self):
        assert AnalyzerStage().name == "analyzer"

    def test_generator_stage_has_name(self):
        assert GeneratorStage().name == "generator"


class TestPipelineContext:
    def test_minimal_construction(self):
        ctx = PipelineContext(
            task_id="t1", source="x", source_type=SourceType.FILE,
        )
        assert ctx.task_id == "t1"
        assert ctx.source == "x"


class FakeStage:
    def __init__(self, name, returns=None, raises=None):
        self.name = name
        self._returns = returns
        self._raises = raises
        self.calls = []

    async def run(self, ctx, prev):
        self.calls.append((ctx.task_id, prev))
        if self._raises:
            raise self._raises
        return StageResult(success=True, payload=self._returns)


class FakeQueue:
    def __init__(self):
        self.status_updates = []
        self.released = []

    def update_status(self, task_id, status, error=None):
        self.status_updates.append((task_id, status, error))

    def release_in_flight(self, task_id):
        self.released.append(task_id)


class TestPipelineRunner:
    async def test_runs_stages_sequentially(self):
        from src.pipeline.runner import PipelineRunner

        stages = [
            FakeStage("a", returns="A"),
            FakeStage("b", returns="B"),
            FakeStage("c", returns="C"),
        ]
        q = FakeQueue()
        runner = PipelineRunner(q)
        ctx = PipelineContext(
            task_id="kb-1", source="x", source_type=SourceType.FILE,
        )
        await runner.run_stages(stages, ctx)

        # Each stage saw the previous one's payload
        assert stages[0].calls == [("kb-1", None)]
        assert stages[1].calls == [("kb-1", StageResult(success=True, payload="A"))]
        assert stages[2].calls == [("kb-1", StageResult(success=True, payload="B"))]

        # On success: APPROVED + in-flight released
        assert q.status_updates == [("kb-1", TaskStatus.APPROVED, None)]
        assert q.released == ["kb-1"]

    async def test_stage_raises_marks_failed(self):
        from src.pipeline.runner import PipelineRunner

        stages = [
            FakeStage("a", returns="A"),
            FakeStage("b", raises=RuntimeError("boom")),
            FakeStage("c", returns="C"),
        ]
        q = FakeQueue()
        runner = PipelineRunner(q)
        ctx = PipelineContext(
            task_id="kb-2", source="x", source_type=SourceType.FILE,
        )
        await runner.run_stages(stages, ctx)

        # Stage 'c' must NOT have run after the exception
        assert stages[2].calls == []
        # FAILED status was recorded + in-flight released
        assert len(q.status_updates) == 1
        task_id, status, error = q.status_updates[0]
        assert task_id == "kb-2"
        assert status == TaskStatus.FAILED
        assert "boom" in (error or "")
        assert q.released == ["kb-2"]

    async def test_stage_returns_failure_marks_failed(self):
        from src.pipeline.runner import PipelineRunner

        class FailStage:
            name = "fail"
            async def run(self, ctx, prev):
                return StageResult(success=False, payload="nope")

        stages = [FailStage()]
        q = FakeQueue()
        runner = PipelineRunner(q)
        ctx = PipelineContext(
            task_id="kb-3", source="x", source_type=SourceType.FILE,
        )
        await runner.run_stages(stages, ctx)

        # success=False should be treated like a raise
        assert len(q.status_updates) == 1
        task_id, status, _ = q.status_updates[0]
        assert (task_id, status) == ("kb-3", TaskStatus.FAILED)
        assert q.released == ["kb-3"]
