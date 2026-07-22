"""Service layer — business logic between HTTP routes and core domain.

Each module in this package exposes a small set of plain functions that
encapsulate a unit of business logic. HTTP routes call these and map
service exceptions to HTTPException; CLI handlers call these directly
without any HTTP machinery.

Conventions:
  - All functions are sync unless they need to await (then async).
  - Domain exceptions (e.g. PathTraversalError, FileNotFoundError) are
    defined in the service module and mapped to HTTP status codes by
    the route.
  - Services depend on src.lib.* and src.wiki.*, never on src.server.*.
"""
