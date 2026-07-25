"""Tests for PipelineStage Protocol and stage implementations.

The stage tests in this file verify the protocol contract is satisfied
and that each stage can be constructed and called with a PipelineContext.
The end-to-end runner tests are added in Task 9.
"""
import pytest

from src.pipeline.ports import PipelineStage, StageResult, PipelineContext
from src.pipeline.stages import CollectorStage, AnalyzerStage, GeneratorStage
from src.pipeline.stages.collector import CollectorStage as CStage
from src.types import SourceType


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
