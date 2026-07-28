"""Public pipeline subsystem API + compat layer.

Re-exports the public names from the new submodules. The legacy
src/pipeline/pipeline.py becomes a thin compat shim. The compat shim MUST
preserve the ability to import `src.pipeline.pipeline._resolve_wiki_paths`
and `src.pipeline.pipeline._get_provider` for the existing
test_pipeline_event_bus_integration.py monkey-patch pattern.

Module-load order matters here: _resolve_wiki_paths and _get_provider are
defined in this __init__.py BEFORE anything imports from .ingest, so that
ingest.py's `from src.pipeline import _resolve_wiki_paths, _get_provider`
resolves even though ingest.py is loaded during the explicit import below.
"""
import sys
from pathlib import Path


# --- compat helpers: defined here so they exist in the package namespace
# before any submodule import that re-imports them via `from src.pipeline import ...`. ---

def _get_provider():
    """Resolve the configured default LLM provider (compat shim target).

    Falls back to OpenAI when the registry is empty / corrupt. Identical to
    src/pipeline/pipeline.py:_get_provider — extracted verbatim.
    """
    from ..llm.provider_factory import create_llm_provider
    from ..llm.registry import ProviderRegistry, RegistryCorruptError, ProviderNotFoundError
    try:
        cfg = ProviderRegistry.get_default()
        return create_llm_provider(cfg.name)
    except (RegistryCorruptError, ProviderNotFoundError, ValueError):
        return create_llm_provider("openai")


def _resolve_wiki_paths(project_id: str | None = None):
    """Resolve WikiPaths for the active project (compat shim target).

    When project_id is provided, look up in the global registry. Otherwise
    fall back to CWD. Identical to src/pipeline/pipeline.py:_resolve_wiki_paths.
    """
    from ..wiki.core.paths import WikiPaths as _WikiPaths
    from ..project.registry import GlobalRegistryStore
    import logging
    _logger = logging.getLogger(__name__)
    if project_id is not None:
        try:
            entry = GlobalRegistryStore.by_id(project_id)
            if entry is not None:
                return _WikiPaths(Path(entry.path))
        except Exception:
            _logger.warning("Failed to resolve project %s; falling back to CWD", project_id, exc_info=True)
    return _WikiPaths(Path.cwd())


# --- re-exports for new consumers ---
# ingest.py is loaded here; it does `from src.pipeline import _resolve_wiki_paths, _get_provider`
# which resolves against the package namespace we just populated above.
from .ingest import run_ingest
from .service import (
    PipelineService,
    get_default_pipeline_service,
    register_stages,
)
from .runner import PipelineRunner
from .stages import AnalyzerStage, CollectorStage, GeneratorStage
from .ports import PipelineContext, StageResult, PipelineStage


def _register_event_handlers_if_needed() -> None:
    """Bind the collector:start handler to the global EventBus."""
    from .service import _register_event_handlers
    _register_event_handlers()


# Register handlers on import (mirrors old import-time behavior of pipeline.py)
_register_event_handlers_if_needed()


# --- compat shim for old src.pipeline.pipeline imports ---

# Also alias the old submodule paths to the new stages/ package, BUT the
# legacy src/pipeline/collector.py / analyzer.py / generator.py still
# exist (deleted in Task 11) and define the canonical `collect`, `analyze`,
# `generate` functions. Eagerly load them so the compat shim can resolve
# those names. (After Task 11 deletes the legacy files, the shim's
# __getattr__ will fall back to ``setdefault``-aliased stages modules,
# which expose PipelineStage classes instead of bare functions — at that
# point external code that calls ``pipeline_mod.collect(...)`` will need
# to be migrated. For now, keep the legacy modules authoritative.)
import src.pipeline.collector as _legacy_collector  # noqa: F401
import src.pipeline.analyzer as _legacy_analyzer    # noqa: F401
import src.pipeline.generator as _legacy_generator  # noqa: F401
from .stages import collector as _collector_module
from .stages import analyzer as _analyzer_module
from .stages import generator as _generator_module
# setdefault only kicks in if no entry exists yet — the imports above
# already populated sys.modules with the legacy modules, so the stages
# aliases never overwrite them.
sys.modules.setdefault("src.pipeline.collector", _collector_module)
sys.modules.setdefault("src.pipeline.analyzer", _analyzer_module)
sys.modules.setdefault("src.pipeline.generator", _generator_module)


class _PipelineCompatShim:
    """Mirrors the symbols that old `src.pipeline.pipeline` exposed.

    The legacy file is replaced by this class registered as a module
    under sys.modules['src.pipeline.pipeline']. Tests that do
    `monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", ...)`
    continue to work because ingest.py looks up the symbol via
    `src.pipeline._resolve_wiki_paths` (the package namespace, which is
    the shim's class attribute after this registration).

    Function attributes are wrapped in ``staticmethod`` so they stay as
    plain functions when accessed via the shim instance (rather than
    becoming bound methods, which would inject ``self`` as the first
    positional argument and break calls like ``run_ingest(paths=...)``).
    """
    run_ingest = staticmethod(run_ingest)
    _resolve_wiki_paths = staticmethod(_resolve_wiki_paths)
    _get_provider = staticmethod(_get_provider)
    Path = Path
    # Expose the old globals (eager-loaded via the legacy module imports
    # above; these class attributes resolve to the same function objects).
    collect = staticmethod(sys.modules["src.pipeline.collector"].collect)
    analyze = staticmethod(sys.modules["src.pipeline.analyzer"].analyze)
    generate = staticmethod(sys.modules["src.pipeline.generator"].generate)
    # Test pattern: tests do ``pipeline_mod._on_collector_done(payload)``
    # to drive the legacy handler directly. This implementation matches
    # the OLD `src/pipeline/pipeline.py:_on_collector_done` verbatim:
    # call run_ingest, mark APPROVED, release in-flight. We can't
    # dispatch through the NEW pipeline service here because that path
    # also re-runs the collector stage, which the legacy tests do not
    # expect (they pass a CollectorDonePayload directly).
    async def _on_collector_done(self, payload):
        import logging
        from ..queue import update_task_status
        from ..queue.service import get_default_queue_service
        from ..types import TaskStatus
        _logger = logging.getLogger("src.pipeline")
        if isinstance(payload, dict):
            task_id = payload["task_id"]
            raw_path_str = payload["raw_path"]
            content = payload["content"]
            project_id = payload.get("project_id")
        else:
            task_id = payload.task_id
            raw_path_str = payload.raw_path
            content = payload.content
            project_id = getattr(payload, "project_id", None)
        try:
            # Look up symbols via the package namespace so monkey-patched
            # values on the shim (``pipeline_mod._resolve_wiki_paths``,
            # ``pipeline_mod._get_provider``, ``pipeline_mod.run_ingest``)
            # propagate — these are the call sites the legacy tests patch.
            paths = self._resolve_wiki_paths(project_id=project_id)
            await self.run_ingest(
                paths=paths,
                source_path=Path(raw_path_str),
                source_text=content,
                provider=self._get_provider(),
                task_id=task_id,
            )
            update_task_status(task_id, TaskStatus.APPROVED)
        except Exception as exc:
            _logger.exception("ingest failed for %s", task_id)
            update_task_status(task_id, TaskStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        finally:
            get_default_queue_service().release_in_flight(task_id)


_pipeline_compat_shim = _PipelineCompatShim()
sys.modules.setdefault("src.pipeline.pipeline", _pipeline_compat_shim)

__all__ = [
    "PipelineService",
    "PipelineRunner",
    "PipelineStage",
    "PipelineContext",
    "StageResult",
    "CollectorStage",
    "AnalyzerStage",
    "GeneratorStage",
    "run_ingest",
    "get_default_pipeline_service",
    "register_stages",
]