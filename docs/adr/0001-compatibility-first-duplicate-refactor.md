# ADR-0001: Compatibility-First Cross-File Duplicate Refactoring

- **Status:** Accepted
- **Date:** 2026-08-12

## Context

The codebase-memory graph found repeated production logic in hashing, vector similarity, document extraction errors, CLI project resolution, and script logging. The graph also found live callers and test-only dependencies, so deleting local implementations immediately would create runtime or test failures.

## Decision

Introduce canonical seams first, migrate callers incrementally, and keep the old names as thin compatibility adapters until call-graph and full-suite verification prove they are unused. Format-specific extraction behavior and CLI return/error contracts remain unchanged.

Canonical locations:

- `src/utils/hashing.py` for file hashing
- `src/utils/similarity.py` for vector similarity
- `src/utils/extract/errors.py` for shared extraction error heuristics
- `src/lib/project.py` for CLI-aware project resolution
- `scripts/_common.py` for script-only logging

## Alternatives rejected

1. **Immediate deletion:** rejected because high-risk functions have live production callers.
2. **One generic mega-utility module:** rejected because it would mix filesystem, domain, CLI, and script concerns and create a shallow interface.
3. **Large-bang migration:** rejected because failures would be difficult to attribute and rollback.

## Consequences

The migration temporarily retains small wrappers and therefore does not minimize line count in the first commit. It improves locality and allows each subdomain to be tested and rolled back independently. A later cleanup task can remove wrappers only after static import and MCP call-graph checks are clean.
