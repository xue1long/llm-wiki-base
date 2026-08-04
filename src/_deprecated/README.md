# Deprecated Modules

This directory contains modules that have been deprecated and are no longer actively maintained.

## orchestrator/

The `orchestrator/` module was the original multi-agent orchestration system. It has been superseded by the newer pipeline architecture in `src/pipeline/`.

### Migration Notes

- The orchestrator's agent-based workflow has been replaced by the stage-based pipeline
- If you need the old orchestrator behavior, import from `src._deprecated.orchestrator`
- Consider migrating to the new `PipelineService` and `Stage` pattern

### Removal Timeline

This module will be removed in a future version after all dependent code has been migrated.
