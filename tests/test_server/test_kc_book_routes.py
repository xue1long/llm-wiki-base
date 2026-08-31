"""Tests for the Book HTTP routes (book-build runtime wiring, Task 3).

    GET  /api/v1/kc/book/status?project_id=<id>
    POST /api/v1/kc/book/build      {project_id, apply?, out?, title?}

Status codes:
    200  ok — ``planned`` (dry-run), ``committed`` (apply), or ``empty``
    400  request body missing ``project_id``
    404  project could not be resolved
    409  build failed (a chapter could not be compiled/rendered)

``build`` is dry-run by default; ``{"apply": true}`` is required to write.
Project resolution is monkeypatched (these tests target route behaviour,
not the registry).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.routes import kc as kc_routes


# ─── Fixture builders ──────────────────────────────────────────────────


def _claim(object_id: str, *, source_path: str) -> dict:
    return {
        "id": object_id,
        "type": "claim",
        "title": f"claim {object_id}",
        "content": f"content {object_id}",
        "lifecycle": "processing",
        "confidence": 1.0,
        "provenance": {"source_path": source_path, "source_paths": [source_path],
                       "quote": "q", "ingested_at": 0, "ingestor_version": "v1"},
        "created_at": 0,
        "updated_at": 0,
        "ku_id": None,
    }


def _evidence(evidence_id: str, *, supports: list[str]) -> dict:
    return {
        "evidence_id": evidence_id,
        "document_id": "doc_test",
        "block_id": f"block_{evidence_id}",
        "quote": "evidence quote",
        "quote_hash": "0" * 64,
        "supports": list(supports),
        "confidence": 0.0,
        "status": "candidate",
        "evidence_type": "direct_quote",
        "structured_provenance": None,
        "computation_provenance": None,
    }


def _make_project(root: Path, *, publication_version: int = 4) -> Path:
    kc_root = root / ".index" / "kc"
    bundle = kc_root / "bundles" / "bk_a"
    (bundle / "objects").mkdir(parents=True, exist_ok=True)
    (bundle / "evidence").mkdir(parents=True, exist_ok=True)
    (bundle / "manifest.json").write_text(
        json.dumps({"bundle_key": "bk_a", "source_path": "raw/sources/a.md"}),
        encoding="utf-8",
    )
    for claim in (_claim("c1", source_path="raw/sources/a.md"),
                  _claim("c2", source_path="raw/sources/a.md")):
        (bundle / "objects" / f"{claim['id']}.json").write_text(
            json.dumps(claim, ensure_ascii=False), encoding="utf-8")
    (bundle / "evidence" / "ev1.json").write_text(
        json.dumps(_evidence("ev1", supports=["c1"]), ensure_ascii=False), encoding="utf-8")
    (kc_root / "publication_state.json").write_text(
        json.dumps({"current_version": publication_version, "active_batches": []}),
        encoding="utf-8",
    )
    return root


class _FakeCtx:
    def __init__(self, path: Path) -> None:
        self.path = path


def _patch_resolve(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        kc_routes, "resolve_project",
        lambda project_id, by_id_only=True: (_FakeCtx(root), None),
    )


def _patch_resolve_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.project.context import ProjectNotFoundError

    def _boom(project_id, by_id_only=True):
        raise ProjectNotFoundError(f"No project with id/name '{project_id}'.")

    monkeypatch.setattr(kc_routes, "resolve_project", _boom)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """App client with project resolution redirected at a tmp project."""
    root = _make_project(tmp_path / "project")
    _patch_resolve(monkeypatch, root)
    return TestClient(create_app()), root


# ─── GET /book/status ──────────────────────────────────────────────────


def test_status_returns_snapshot_stats(client) -> None:
    app, _root = client
    resp = app.get("/api/v1/kc/book/status", params={"project_id": "p1"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["chapters"] == 1
    assert payload["claims"] == 2
    assert payload["evidence"] == 1
    assert payload["publication_version"] == 4
    assert payload["derived"] is True
    assert payload["empty"] is False


def test_status_lists_chapters(client) -> None:
    app, _root = client
    payload = app.get("/api/v1/kc/book/status", params={"project_id": "p1"}).json()

    assert len(payload["chapter_list"]) == 1
    chapter = payload["chapter_list"][0]
    assert chapter["order"] == 0
    assert chapter["stable_key"].endswith("::principle")
    assert chapter["claims"] == 2


def test_status_on_empty_project_is_200_with_empty_flag(monkeypatch, tmp_path) -> None:
    _patch_resolve(monkeypatch, tmp_path)
    app = TestClient(create_app())

    resp = app.get("/api/v1/kc/book/status", params={"project_id": "p1"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["empty"] is True
    assert payload["chapters"] == 0
    assert "kc_root:missing" in payload["reason_codes"]


def test_status_unknown_project_is_404(monkeypatch, tmp_path) -> None:
    _patch_resolve_404(monkeypatch)
    app = TestClient(create_app())

    resp = app.get("/api/v1/kc/book/status", params={"project_id": "nope"})
    assert resp.status_code == 404


def test_status_requires_project_id(client) -> None:
    app, _root = client
    resp = app.get("/api/v1/kc/book/status")
    assert resp.status_code == 422  # FastAPI: missing required query param


def test_status_does_not_write(client) -> None:
    app, root = client
    before = {p.name for p in root.rglob("*")}
    app.get("/api/v1/kc/book/status", params={"project_id": "p1"})
    assert {p.name for p in root.rglob("*")} == before


# ─── POST /book/build ──────────────────────────────────────────────────


def test_build_is_dry_run_by_default(client) -> None:
    app, root = client
    resp = app.post("/api/v1/kc/book/build", json={"project_id": "p1"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "planned"
    assert payload["apply"] is False
    assert payload["chapter_count"] == 1
    assert payload["output_dir"] is None
    assert not (root / "book").exists(), "dry-run must not write"


def test_build_apply_writes_output(client) -> None:
    app, root = client
    resp = app.post("/api/v1/kc/book/build", json={"project_id": "p1", "apply": True})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "committed"
    assert payload["apply"] is True
    assert Path(payload["output_dir"]) == root / "book"
    assert len(list((root / "book").glob("*.md"))) == 1
    assert len(list((root / "book").glob("*.json"))) == 1


def test_build_honours_custom_out_dir(client) -> None:
    app, root = client
    custom = root / "custom-book"
    resp = app.post("/api/v1/kc/book/build",
                    json={"project_id": "p1", "apply": True, "out": str(custom)})

    assert resp.status_code == 200
    assert resp.json()["status"] == "committed"
    assert custom.is_dir()
    assert not (root / "book").exists()


def test_build_honours_title(client) -> None:
    app, _root = client
    resp = app.post("/api/v1/kc/book/build",
                    json={"project_id": "p1", "apply": True, "title": "小说写作手册"})
    assert resp.json()["title"] == "小说写作手册"


def test_build_requires_project_id(client) -> None:
    app, _root = client
    resp = app.post("/api/v1/kc/book/build", json={})
    assert resp.status_code == 400


def test_build_unknown_project_is_404(monkeypatch, tmp_path) -> None:
    _patch_resolve_404(monkeypatch)
    app = TestClient(create_app())

    resp = app.post("/api/v1/kc/book/build", json={"project_id": "nope"})
    assert resp.status_code == 404


def test_build_empty_project_is_200_empty(monkeypatch, tmp_path) -> None:
    _patch_resolve(monkeypatch, tmp_path)
    app = TestClient(create_app())

    resp = app.post("/api/v1/kc/book/build", json={"project_id": "p1", "apply": True})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "empty"
    assert payload["chapter_count"] == 0
    assert not (tmp_path / "book").exists()


def test_build_failure_is_409(client, monkeypatch) -> None:
    app, _root = client

    class _FailedReport:
        status = "failed"
        book_id = "book_x"
        publication_version = 4
        rebuilt_chapter_ids = ()
        failed_chapter_ids = ("ch_broken",)
        reason_codes = ("integrity_block:gate",)
        rendered_hashes: dict = {}
        not_evaluable = False

    monkeypatch.setattr(kc_routes, "rebuild_book", lambda *a, **kw: _FailedReport())

    resp = app.post("/api/v1/kc/book/build", json={"project_id": "p1", "apply": True})

    assert resp.status_code == 409
    payload = resp.json()
    assert payload["status"] == "failed"
    assert payload["reason_codes"] == ["integrity_block:gate"]
    assert payload["failed_chapter_ids"] == ["ch_broken"]


def test_build_rejects_non_object_body(client) -> None:
    app, _root = client
    resp = app.post("/api/v1/kc/book/build", json=["not", "an", "object"])
    assert resp.status_code == 400
