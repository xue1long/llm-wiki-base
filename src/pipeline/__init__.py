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

def _get_provider(project_id: str | None = None):
    """Resolve the configured default LLM provider (compat shim target).

    When *project_id* is provided, prefer the project-level LLM config
    stored in ``.llm-wiki/project.json`` over the global default.  Falls
    back to OpenAI when the registry is empty / corrupt.
    """
    from ..llm.provider_factory import create_llm_provider
    from ..llm.registry import ProviderRegistry, RegistryCorruptError, ProviderNotFoundError

    # P3: per-project provider override.
    if project_id is not None:
        try:
            from ..project.registry import GlobalRegistryStore
            entry = GlobalRegistryStore.by_id(project_id)
            if entry is not None and entry.path:
                import json
                from pathlib import Path
                proj_json = Path(entry.path) / ".llm-wiki" / "project.json"
                if proj_json.exists():
                    data = json.loads(proj_json.read_text(encoding="utf-8"))
                    proj_provider = data.get("llm_provider")
                    proj_model = data.get("llm_model")
                    if proj_provider:
                        import logging
                        _logger = logging.getLogger(__name__)
                        _logger.info(
                            "[_get_provider] using project-level provider %r"
                            " (model=%r) for %s",
                            proj_provider, proj_model, project_id,
                        )
                        return create_llm_provider(
                            proj_provider, model_override=proj_model,
                        )
        except Exception:
            pass  # Fall through to global default

    try:
        cfg = ProviderRegistry.get_default()
        return create_llm_provider(cfg.name)
    except (RegistryCorruptError, ProviderNotFoundError, ValueError):
        return create_llm_provider("openai")


def _resolve_wiki_paths(project_id: str | None = None):
    """Resolve WikiPaths for the active project (compat shim target).

    When project_id is provided, look up in the global registry and raise
    ValueError if the project is not found — silently falling back to CWD
    writes wiki pages to the wrong directory with no error.

    When project_id is None, fall back to CWD (legacy single-project mode).
    """
    from ..wiki.core.paths import WikiPaths as _WikiPaths
    from ..project.registry import GlobalRegistryStore
    import logging
    _logger = logging.getLogger(__name__)
    if project_id is not None:
        entry = GlobalRegistryStore.by_id(project_id)
        if entry is not None:
            return _WikiPaths(Path(entry.path))
        raise ValueError(
            f"Project {project_id!r} not found in the global registry. "
            f"Check with: python -m src.cli project list"
        )
    return _WikiPaths(Path.cwd())


# --- re-exports for new consumers ---
# ingest.py is loaded here; it does `from src.pipeline import _resolve_wiki_paths, _get_provider`
# which resolves against the package namespace we just populated above.
from .ingest import run_ingest
from .service import (
    PipelineService,
    PipelineContext,
    get_default_pipeline_service,
    _register_event_handlers,
)
from .generator import generate
from .schemas import AnalysisResult, EntityMention


def _register_event_handlers_if_needed() -> None:
    """Bind the collector:start handler to the global EventBus."""
    from .service import _register_event_handlers
    _register_event_handlers()


# Register handlers on import (mirrors old import-time behavior of pipeline.py)
_register_event_handlers_if_needed()


# --- compat shim for old src.pipeline.pipeline imports ---

# Eagerly load the legacy modules so the compat shim can resolve them.
import src.pipeline.collector as _legacy_collector  # noqa: F401
import src.pipeline.analyzer as _legacy_analyzer    # noqa: F401
import src.pipeline.generator as _legacy_generator  # noqa: F401


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
                provider=self._get_provider(project_id=project_id),
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
    "PipelineContext",
    "run_ingest",
    "generate",
    "AnalysisResult",
    "EntityMention",
    "get_default_pipeline_service",
]