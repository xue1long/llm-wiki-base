"""Single-file / URL ingest dedup (audit PR-2 Task D).

Pre-PR-2 bug: the folder branch of ``enqueue_source`` consulted
``_get_ingested_paths`` (wiki source frontmatter) and skipped
already-ingested files. The single-file / URL branch skipped this
check entirely and went straight to ``enqueue_task``, relying only on
the queue's on-disk task-hash dedup.

Consequences:

* Re-submitting the same URL: the previous task had reached APPROVED,
  was filtered out as "not active", and the queue removed that record
  before enqueuing a fresh task — burning another full LLM run.
* Re-submitting the same file (or its project-relative alias): same
  story, plus every folder batch that included an existing raw file
  burned LLM quota because the branch invariant differed from the
  folder branch.

After PR-2: the single-file / URL branch also runs the wiki-frontmatter
scan. A URL is matched verbatim against the page's ``sources:`` list
(``collector`` records the URL unchanged). A file path is normalised
via the same helper the folder branch uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.services.ingest import (
    enqueue_source,
    _find_source_page_by_url,
)
from src.utils.idempotency import get_idempotency_cache
from src.wiki.core.paths import WikiPaths


@pytest.fixture(autouse=True)
def _clean_state():
    """Clear the idempotency cache between every test."""
    get_idempotency_cache().clear()
    yield
    get_idempotency_cache().clear()


def _setup_project(tmp_path: Path, monkeypatch) -> tuple[str, WikiPaths]:
    """Set up a fully-formed project the ingest service can resolve by id.

    Returns ``(project_id, paths)``. Monkeypatches
    ``GlobalRegistryStore.by_id`` / ``.by_name`` to return a
    tmp_path-anchored entry without touching the real on-disk registry.

    The monkeypatch argument is required — pytest cleans it up at test
    teardown so the patches don't leak across the suite (a previous
    version of this helper used ``patch.object(...).start()`` which
    leaked across tests and broke several unrelated suites that share
    the singleton registry).
    """
    import json
    import time
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry

    project_id = "prj-test"
    project_root = tmp_path
    project_root.mkdir(parents=True, exist_ok=True)

    llm_dir = project_root / ".llm-wiki"
    llm_dir.mkdir(parents=True, exist_ok=True)
    (llm_dir / "project.json").write_text(
        json.dumps(
            {
                "id": project_id,
                "name": "dedup-test",
                "created_at": int(time.time() * 1000),
                "schema_version": "v2.0",
            }
        ),
        encoding="utf-8",
    )

    entry = ProjectRegistryEntry(
        id=project_id,
        name="dedup-test",
        path=str(project_root),
        last_opened=int(time.time() * 1000),
    )

    def fake_by_id(cls, pid):
        return entry if pid == project_id else None

    def fake_by_name(cls, name):
        return entry if name == "dedup-test" else None

    monkeypatch.setattr(GlobalRegistryStore, "by_id", classmethod(fake_by_id))
    monkeypatch.setattr(GlobalRegistryStore, "by_name", classmethod(fake_by_name))

    return project_id, WikiPaths(project_root)


def _mk_page(sources_dir, source_id, raw_paths):
    """Write a minimal source page whose ``sources:`` lists the given paths."""
    sources_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {p}" for p in raw_paths)
    (sources_dir / f"{source_id}.md").write_text(
        f"---\nid: {source_id}\ntitle: 源页\nsources:\n{body}\n---\n\n",
        encoding="utf-8",
    )


def test_url_dedup_short_circuits_on_existing_source_page(tmp_path, monkeypatch):
    """Re-submitting an already-ingested URL must short-circuit at the
    service boundary, not silently re-enqueue."""
    project_id, paths = _setup_project(tmp_path, monkeypatch)
    _mk_page(
        tmp_path / "wiki" / "sources",
        "src-url",
        ["https://example.com/article"],
    )

    # The ingest service should return ignored because the wiki page
    # already references this URL.
    result = enqueue_source(project_id, "https://example.com/article")
    assert result["status"] == "ignored", result
    assert result["reason"] == "AlreadyIngested"
    assert result["taskId"] is None


def test_url_dedup_allows_first_ingest_when_no_page_exists(tmp_path, monkeypatch):
    """A genuinely new URL must still queue (no false-positive dedup)."""
    project_id, _ = _setup_project(tmp_path, monkeypatch)
    # No wiki page references this URL.

    result = enqueue_source(project_id, "https://example.com/never-ingested")
    assert result["status"] == "queued", result
    assert result["reason"] is None
    assert result["taskId"]


def test_url_dedup_does_not_match_other_url(tmp_path, monkeypatch):
    """Each URL is its own identity — a different URL must NOT dedup to the
    page recorded for an unrelated URL."""
    project_id, _ = _setup_project(tmp_path, monkeypatch)
    _mk_page(
        tmp_path / "wiki" / "sources",
        "src-other",
        ["https://example.com/some-other-article"],
    )

    result = enqueue_source(
        project_id, "https://example.com/different-article"
    )
    assert result["status"] == "queued", result


def test_file_dedup_short_circuits_on_existing_source_page(tmp_path, monkeypatch):
    """A re-submitted local file (or its project-relative alias) must
    also short-circuit at the service boundary."""
    project_id, _ = _setup_project(tmp_path, monkeypatch)
    raw_rel = "raw/sources/foo.md"
    _mk_page(
        tmp_path / "wiki" / "sources",
        "src-foo",
        [raw_rel],
    )

    # Also place the raw file so the path normalisation succeeds — the
    # _normalize_absolute_path helper requires the project root to be the
    # common prefix.
    (tmp_path / raw_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / raw_rel).write_text("# raw", encoding="utf-8")

    result = enqueue_source(project_id, raw_rel)
    assert result["status"] == "ignored", result
    assert result["reason"] == "AlreadyIngested"


def test_file_dedup_allows_first_ingest_when_no_page_exists(tmp_path, monkeypatch):
    project_id, _ = _setup_project(tmp_path, monkeypatch)
    raw_rel = "raw/sources/fresh.md"
    (tmp_path / raw_rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / raw_rel).write_text("# raw", encoding="utf-8")

    result = enqueue_source(project_id, raw_rel)
    assert result["status"] == "queued", result


def test_find_source_page_by_url_matches_exact_url(tmp_path):
    """The URL helper should find a page whose ``sources:`` list literally
    contains the URL string."""
    sources_dir = tmp_path / "wiki" / "sources"
    _mk_page(sources_dir, "page-block", ["https://example.com/foo"])
    (sources_dir / "page-flow.md").write_text(
        "---\nid: page-flow\nsources: [https://example.com/bar]\n---\n\n",
        encoding="utf-8",
    )

    assert _find_source_page_by_url(
        sources_dir, "https://example.com/foo"
    ) == "page-block"
    assert _find_source_page_by_url(
        sources_dir, "https://example.com/bar"
    ) == "page-flow"
    assert _find_source_page_by_url(
        sources_dir, "https://example.com/missing"
    ) is None


def test_find_source_page_by_url_rejects_non_url_targets():
    """URL helper must not accidentally match raw paths."""
    from src.services.ingest import _find_source_page_by_url
    assert _find_source_page_by_url(None, "raw/sources/foo.md") is None
    assert _find_source_page_by_url(None, "") is None
    assert _find_source_page_by_url(None, "/etc/passwd") is None
