from src.server.app import create_app


def _all_paths(app):
    """Recursively collect paths from app and included routers."""
    paths = []
    for r in app.routes:
        orig = getattr(r, "original_router", None)
        if orig is not None:
            paths.extend(_all_paths(orig))
            continue
        p = getattr(r, "path", None)
        if p:
            paths.append(p)
    return paths


def test_create_app_returns_fastapi():
    app = create_app()
    assert app.title == "ruflo-kb API"
    # Verify all routers mounted
    paths = _all_paths(app)
    assert "/health" in paths
    assert "/api/v1/projects" in paths