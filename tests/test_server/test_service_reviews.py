"""Tests for src.services.reviews — review queue list + resolve."""
from src.services import reviews as reviews_service


def test_list_reviews_empty(monkeypatch, tmp_path):
    """list_reviews returns empty list when no review file exists."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "src.services.reviews.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    result = reviews_service.list_reviews("u")
    assert result == {"status": "open", "count": 0, "reviews": []}


def test_list_reviews_filters_by_status(monkeypatch, tmp_path):
    """status='all' returns everything; status='open' filters."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    # Write a review file with one open and one closed item
    import json
    review_data = {
        "version": 1,
        "items": [
            {"id": "a", "type": "stub", "title": "Open1", "normalized_title": "open1",
             "detail": "", "confidence": 0.5, "search_queries": [],
             "page_path": None, "created_at": 1000, "source_task_id": None,
             "status": "open"},
            {"id": "b", "type": "stub", "title": "Closed1", "normalized_title": "closed1",
             "detail": "", "confidence": 0.5, "search_queries": [],
             "page_path": None, "created_at": 2000, "source_task_id": None,
             "status": "fixed"},
        ],
    }
    (project_dir / ".index").mkdir()
    (project_dir / ".index" / "reviews.json").write_text(
        json.dumps(review_data), encoding="utf-8"
    )

    monkeypatch.setattr(
        "src.services.reviews.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    # status=open should return only the open one
    result = reviews_service.list_reviews("u", status="open")
    assert result["count"] == 1
    assert result["reviews"][0]["id"] == "a"

    # status=all returns both
    result = reviews_service.list_reviews("u", status="all")
    assert result["count"] == 2


def test_list_resolve_review_marks_resolved(monkeypatch, tmp_path):
    """resolve_review moves the item to resolved and sets status=action."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    import json
    review_data = {
        "version": 1,
        "items": [
            {"id": "x", "type": "stub", "title": "T", "normalized_title": "t",
             "detail": "", "confidence": 0.5, "search_queries": [],
             "page_path": None, "created_at": 1000, "source_task_id": None,
             "status": "open"},
        ],
    }
    (project_dir / ".index").mkdir()
    (project_dir / ".index" / "reviews.json").write_text(
        json.dumps(review_data), encoding="utf-8"
    )

    monkeypatch.setattr(
        "src.services.reviews.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )

    reviews_service.resolve_review("u", "x", "merged")

    # The resolved file should now have the item with status='merged'
    resolved_file = project_dir / ".index" / "reviews_resolved.json"
    assert resolved_file.exists()
    data = json.loads(resolved_file.read_text(encoding="utf-8"))
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == "x"
    assert data["items"][0]["status"] == "merged"


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)
