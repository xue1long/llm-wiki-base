"""Tests for src/server/routes/quality.py — quality report endpoint."""
from fastapi.testclient import TestClient

from src.server.app import create_app

app = create_app()
client = TestClient(app)


def _register_project(monkeypatch, tmp_path, project_id, project_root):
    """Register a project in the registry AND create its .llm-wiki/project.json."""
    from src.project import paths as project_paths
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    import time, json

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    project_root.mkdir(parents=True, exist_ok=True)
    project_json = project_root / ".llm-wiki" / "project.json"
    project_json.parent.mkdir(parents=True, exist_ok=True)
    project_json.write_text(json.dumps({
        "id": project_id,
        "name": project_id,
        "created_at": 1700000000000,
        "schema_version": "v2.0",
    }, ensure_ascii=False), encoding="utf-8")

    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id=project_id,
        path=str(project_root),
        name=project_id,
        last_opened=int(time.time() * 1000),
        schema_version="v1.0",
    ))


def test_quality_returns_404_for_unknown_project():
    """GET /api/v1/projects/unknown/quality?source_path=foo.md returns 404."""
    r = client.get("/api/v1/projects/unknown/quality", params={"source_path": "raw/sources/foo.md"})
    assert r.status_code == 404


def test_quality_returns_exists_false_when_no_report(tmp_path, monkeypatch):
    """Returns exists=false + passed=false when no ingest report exists."""
    _register_project(monkeypatch, tmp_path, "no-report-proj", tmp_path / "proj")

    r = client.get("/api/v1/projects/no-report-proj/quality", params={"source_path": "raw/sources/foo.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["passed"] is False
    assert body["report"] is None


def test_quality_returns_report_when_exists(tmp_path, monkeypatch):
    """Returns report data when a matching ingest report exists."""
    import json

    proj_root = tmp_path / "proj"
    _register_project(monkeypatch, tmp_path, "report-proj", proj_root)

    # Write a fake ingest report
    reports_dir = proj_root / ".index" / "ingest_reports"
    reports_dir.mkdir(parents=True)
    report = {
        "task_id": "task-001",
        "source_path": "raw/sources/foo.md",
        "started_at": 1700000000000,
        "finished_at": 1700000010000,
        "duration_ms": 10000,
        "pipeline_mode": "candidate",
        "source_bytes": 5000,
        "chunks_count": 3,
        "claims_count": 5,
        "evidence_count": 8,
        "candidate_confidence": 0.85,
        "verdict": "validated",
        "verdict_reason": "",
        "pages_total": 3,
        "pages_by_type": {"source": 1, "entity": 1, "concept": 1},
        "quarantined_count": 0,
        "warnings": [],
    }
    (reports_dir / "task-001.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    r = client.get("/api/v1/projects/report-proj/quality", params={"source_path": "raw/sources/foo.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["passed"] is True
    assert body["report"]["verdict"] == "validated"
    assert body["report"]["task_id"] == "task-001"
    assert body["review_items"] == []
    assert body["quarantine"] == []


def test_quality_fails_on_rejected_verdict(tmp_path, monkeypatch):
    """Returns passed=false when verdict is rejected."""
    import json

    proj_root = tmp_path / "proj2"
    _register_project(monkeypatch, tmp_path, "rejected-proj", proj_root)

    reports_dir = proj_root / ".index" / "ingest_reports"
    reports_dir.mkdir(parents=True)
    report = {
        "task_id": "task-002",
        "source_path": "raw/sources/bad.md",
        "started_at": 1700000000000,
        "finished_at": 1700000010000,
        "duration_ms": 10000,
        "pipeline_mode": "candidate",
        "source_bytes": 1000,
        "chunks_count": 1,
        "claims_count": 0,
        "evidence_count": 0,
        "candidate_confidence": 0.0,
        "verdict": "rejected",
        "verdict_reason": "Low quality content",
        "pages_total": 0,
        "pages_by_type": {},
        "quarantined_count": 0,
        "warnings": ["Low confidence"],
    }
    (reports_dir / "task-002.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    r = client.get("/api/v1/projects/rejected-proj/quality", params={"source_path": "raw/sources/bad.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["passed"] is False
    assert body["report"]["verdict"] == "rejected"


def test_quality_collects_wiki_pages(tmp_path, monkeypatch):
    """Returns pages collected from wiki/* frontmatter referencing the source."""
    import json

    proj_root = tmp_path / "proj3"
    _register_project(monkeypatch, tmp_path, "pages-proj", proj_root)

    # A page in wiki/concepts that references raw/sources/foo.md
    concepts_dir = proj_root / "wiki" / "concepts"
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "narrative-view.md").write_text(
        "---\n"
        "id: page_concept_narrative_view\n"
        "title: 叙述视角\n"
        "type: concept\n"
        "grade: B\n"
        'sources:\n  - "raw/sources/foo.md"\n'
        "---\n"
        "正文内容\n",
        encoding="utf-8",
    )
    # A page in wiki/entities that references a different source — must be excluded
    entities_dir = proj_root / "wiki" / "entities"
    entities_dir.mkdir(parents=True)
    (entities_dir / "other.md").write_text(
        "---\n"
        "id: page_entity_other\n"
        "title: 其他\n"
        "type: entity\n"
        "grade: A\n"
        'sources:\n  - "raw/sources/other.md"\n'
        "---\n",
        encoding="utf-8",
    )

    r = client.get("/api/v1/projects/pages-proj/quality", params={"source_path": "raw/sources/foo.md"})
    assert r.status_code == 200
    body = r.json()
    pages = body["pages"]
    assert len(pages) == 1
    assert pages[0]["type"] == "concept"
    assert pages[0]["page_id"] == "page_concept_narrative_view"
    assert pages[0]["title"] == "叙述视角"
    assert pages[0]["grade"] == "B"