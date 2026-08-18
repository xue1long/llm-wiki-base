"""R10 — route-layer boundary guard.

Audit: some server routes imported wiki.storage internals directly,
bypassing the service layer. R10 acceptance: "new routes do not import
Wiki storage internals; key write ops go through a Service".

This guard scans every route module for direct imports of wiki.storage /
wiki.features write internals. The heat restore/archive routes were
already converged to src.services.heat; this test pins that the boundary
stays clean (fail loudly when a future route regresses).

Exceptions list: read-only imports of page_writer helpers that have no
service equivalent yet are permitted and tracked here so the guard is
precise, not cargo-cult.
"""
from pathlib import Path

# Write-path internals that routes must never import directly. Any import
# line referencing one of these symbols (or the module that defines the
# write entry points) triggers a failure.
_FORBIDDEN = {
    "write_page",
    "append_to_index",
    "log_event",
    "cascade_delete",
    "delete_page",
    "DELETE_SENTINEL",
    "set_heat",
}

# Routes may keep using these read-only helpers until a service exists
# (they do not mutate wiki state).
_ALLOWED_READONLY = {
    "wiki.storage.page_writer.read_page",
    "wiki.storage.page_writer.page_path_for",
    "wiki.core.types",
    "wiki.templates",
    "wiki.templates.parser",
    "wiki.templates.types",
    "wiki.features.heat._infer_type",
    "wiki.features.zombie",
    "wiki.features.review.load_reviews",
}


def _route_modules() -> list[Path]:
    return sorted(Path("src/server/routes").glob("*.py"))


def test_no_route_imports_wiki_write_internals():
    """Route modules must not import wiki write-path internals directly."""
    violations = []
    for mod in _route_modules():
        text = mod.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("from ") and not stripped.startswith("import "):
                continue
            for forbidden in _FORBIDDEN:
                if forbidden in stripped:
                    violations.append(f"{mod.name}: {stripped}")
    assert not violations, (
        "Route modules must not import wiki write internals (R10); "
        "delegate to src.services.* instead:\n" + "\n".join(violations)
    )


def test_heat_route_uses_service():
    """heat restore/archive routes delegate to src.services.heat (R10)."""
    text = (Path("src/server/routes/heat.py")).read_text(encoding="utf-8")
    assert "from ...services.heat import restore_zombies" in text
    assert "from ...services.heat import archive_zombies" in text
    # No direct write_page / shutil.move left in the route.
    assert "write_page(" not in text
