from pathlib import Path

from src.status_summary import ProjectStatusSummary, SourceStatus
from src.services import status_summary


def test_status_summary_service_returns_project_counts_without_local_paths(monkeypatch):
    root = Path("D:/private/project")
    sources = (
        SourceStatus(
            source_id="source-1",
            source_path="raw/sources/a.md",
            raw_status="ingested",
            kc_status="committed",
            wiki_status="committed",
            book_status="published",
            overall_status="book_compiled",
        ),
        SourceStatus(
            source_id="source-2",
            source_path="raw/sources/b.md",
            raw_status="failed",
            kc_status="not_started",
            wiki_status="not_started",
            book_status="not_started",
            overall_status="failed",
        ),
    )
    summary = ProjectStatusSummary(
        project_root=root,
        database_path=root / ".index" / "lineage" / "state.db",
        status="partial",
        sources=sources,
        pending_wiki_commits=1,
        build_runs=2,
    )
    ctx = type("Context", (), {"id": "p-1", "name": "Demo"})()
    paths = type("Paths", (), {"root": root})()

    monkeypatch.setattr(status_summary, "resolve_project", lambda *_args, **_kwargs: (ctx, paths))
    monkeypatch.setattr(status_summary, "summarize_project", lambda _root: summary)

    result = status_summary.get_status_summary("p-1")

    assert result["project"] == {"id": "p-1", "name": "Demo"}
    assert result["status"] == "partial"
    assert result["counts"]["sources"] == 2
    assert result["counts"]["raw"] == {"ingested": 1, "failed": 1}
    assert result["counts"]["book"] == {"published": 1, "not_started": 1}
    assert result["pending_wiki_commits"] == 1
    assert result["build_runs"] == 2
    assert "project_root" not in result
    assert "database_path" not in result
