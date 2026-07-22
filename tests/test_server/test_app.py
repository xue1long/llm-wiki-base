from src.server.app import create_app


def test_create_app_returns_fastapi():
    app = create_app()
    assert app.title == "ruflo-kb API"
    # Verify all routers mounted
    paths = [r.path for r in app.routes]
    assert "/health" in paths
    assert "/api/v1/projects" in paths