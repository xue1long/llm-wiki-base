"""Unit tests for scripts/phase4_batch.py pure helpers.

R0-2 (empty/all-failed batch guard), R1-1 phase4 side (state double-tool
tolerance + status-independent ``completed_files`` read), and R2-2 commit
loop (``_generate_batch`` / ``_commit_all`` — SOURCE-page ownership resume,
POSTCHECK into state, extras reverse-relation commit, ``--skip-files``).
phase4_batch's top-level imports are stdlib-only
(argparse/asyncio/json/logging/sys/time/pathlib); ``src`` imports are
deferred to call time, so importing it here pulls no heavy deps.
"""
import asyncio
import json
from pathlib import Path

import pytest

from scripts.phase4_batch import (
    _batch_completed_files,
    _check_overwrite_protection,
    _commit_all,
    _decide_abort,
    _generate_batch,
    _load_state,
)
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base


def _make_raw(root, raw_rel: str, text: str = "content") -> None:
    p = root / raw_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _source_page(raw_rel: str) -> WikiPage:
    """A SOURCE page whose ``sources`` is exactly the raw_rel (Fix D shape)."""
    stem = Path(raw_rel).stem
    return WikiPage(
        id=f"src-{stem}", title=stem, type=PageType.SOURCE,
        sources=[raw_rel], body="source body", grade="A",
        processing_depth="source",
    )


def _wiki_page(pid: str, sources=None,
               ptype: PageType = PageType.ENTITY,
               body: str = "body", grade: str = "B") -> WikiPage:
    return WikiPage(
        id=pid, title=pid, type=ptype, sources=list(sources or []),
        body=body, grade=grade, processing_depth="concept",
    )


def _make_generate_fake(pages_by_rel, extra_by_rel=None):
    """Return (fake_generate, calls) — records each source_path generated."""
    calls: list[str] = []

    async def fake_generate(paths, source_path, source_text, provider,
                            folder_context="", task_id="test"):
        raw_rel = str(source_path).replace("\\", "/")
        calls.append(raw_rel)
        pages = list(pages_by_rel.get(raw_rel, []))
        extra = list((extra_by_rel or {}).get(raw_rel, []))
        meta = {
            "source_slug": next(
                (p.id for p in pages if p.type == PageType.SOURCE), ""),
        }
        return pages, extra, meta

    return fake_generate, calls


def _make_commit_fake(fail_on=None, write_to_disk=None, root=None):
    """Return (fake_commit, calls).

    ``write_to_disk`` (a WikiPaths) makes the fake persist pages + index so
    POSTCHECK can pass for the files that commit successfully.  ``fail_on``
    matches the project-relative raw_rel (the form ``_commit_all`` derives
    from ``root / raw_rel``)."""
    calls: list[dict] = []
    fail_on = set(fail_on or [])

    async def fake_commit(paths, source_path, pages, extra_pages=None,
                          task_id="test", *, event="ingest", detail=None,
                          log_task_id=None):
        sp = Path(source_path)
        if root is not None:
            try:
                key = sp.relative_to(root).as_posix()
            except ValueError:
                key = str(sp).replace("\\", "/")
        else:
            key = str(sp).replace("\\", "/")
        calls.append({
            "source": key, "event": event,
            "npages": len(pages), "nextra": len(extra_pages or []),
        })
        if key in fail_on:
            raise RuntimeError(f"commit failed for {source_path}")
        if write_to_disk is not None:
            from src.wiki.features.indexer import append_to_index
            from src.wiki.storage.page_writer import write_page
            for p in pages:
                write_page(write_to_disk, p)
            for p in (extra_pages or []):
                write_page(write_to_disk, p)
            append_to_index(
                write_to_disk, [(p.id, p.type, p.title) for p in pages])

    return fake_commit, calls


def _patch_commit_surface(monkeypatch, tmp_path, commit_fake):
    monkeypatch.setattr("src.pipeline.ingest.commit_ingest", commit_fake)
    monkeypatch.setattr(
        "scripts.phase4_batch.BATCH_STATE", tmp_path / "batch_build_state.json")
    monkeypatch.setattr("scripts.phase4_batch.REPORT", tmp_path / "report.txt")


# ---------------------------------------------------------------------------
# R0-2 · _decide_abort — empty/all-failed batch guard (B4)
# ---------------------------------------------------------------------------

def test_decide_abort_all_failed():
    """① ok==0, err>0 → abort (all files failed)."""
    abort, reason = _decide_abort(
        ok=0, err=3, pending=0, resume=False, completed=set(), skip=0)
    assert abort is True
    assert reason


def test_decide_abort_all_missing():
    """② ok==0, err==0, pending>0 → abort (all files missing / empty batch)."""
    abort, reason = _decide_abort(
        ok=0, err=0, pending=5, resume=False, completed=set(), skip=0)
    assert abort is True
    assert reason


def test_decide_abort_already_completed_resume():
    """③ ok==0, pending==0, resume + files⊆completed → no abort ("已完成")."""
    completed = {"raw/a.md", "raw/b.md"}
    abort, reason = _decide_abort(
        ok=0, err=0, pending=0, resume=True, completed=completed, skip=2)
    assert abort is False
    assert reason


def test_decide_abort_mixed_ok():
    """④ anything with ok>0 → no abort."""
    abort, _reason = _decide_abort(
        ok=2, err=1, pending=0, resume=False, completed=set(), skip=0)
    assert abort is False


# ---------------------------------------------------------------------------
# R1-1 · _load_state — corrupt/unreadable state file → {} (B7/D4)
# ---------------------------------------------------------------------------

def test_load_state_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", tmp_path / "nope.json")
    assert _load_state() == {}


def test_load_state_corrupt_json(tmp_path, monkeypatch):
    state_file = tmp_path / "batch_build_state.json"
    state_file.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", state_file)
    assert _load_state() == {}


def test_load_state_directory_raises_oserror(tmp_path, monkeypatch):
    """A directory at BATCH_STATE raises OSError on read_text → {} (not crash)."""
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", tmp_path)
    assert _load_state() == {}


# ---------------------------------------------------------------------------
# R1-1 · _batch_completed_files — status-independent read (F7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["committing", "partial", "committed", "postcheck_failed"])
def test_batch_completed_files_status_agnostic(tmp_path, monkeypatch, status):
    """Any entry carrying completed_files resumes from it, regardless of status."""
    state_file = tmp_path / "batch_build_state.json"
    state_file.write_text(json.dumps({
        "batch_0": {"status": status, "completed_files": ["raw/a.md", "raw/b.md"]},
    }), encoding="utf-8")
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", state_file)
    assert _batch_completed_files("batch_0") == {"raw/a.md", "raw/b.md"}


def test_batch_completed_files_non_dict_entry(tmp_path, monkeypatch):
    """Non-dict entry (e.g. a bare string) → empty set, not a crash."""
    state_file = tmp_path / "batch_build_state.json"
    state_file.write_text(json.dumps({"batch_0": "garbage"}), encoding="utf-8")
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", state_file)
    assert _batch_completed_files("batch_0") == set()


# ---------------------------------------------------------------------------
# R2-2 · _generate_batch — resume skip + --skip-files exclusion
# ---------------------------------------------------------------------------

def test_generate_resume_skips_completed_files(tmp_path, monkeypatch):
    """--resume: already-completed files are not regenerated."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    files = ["raw/sources/f1.md", "raw/sources/f2.md", "raw/sources/f3.md"]
    for f in files:
        _make_raw(root, f)
    pages_by_rel = {f: [_source_page(f)] for f in files}
    gen_fake, gen_calls = _make_generate_fake(pages_by_rel)
    monkeypatch.setattr("src.pipeline.ingest.generate_ingest", gen_fake)
    monkeypatch.setattr("scripts.phase4_batch.REPORT", tmp_path / "report.txt")

    gen = asyncio.run(_generate_batch(
        paths=paths, provider=None, files=files,
        completed_files={"raw/sources/f1.md", "raw/sources/f2.md"},
        skip_files=set(), concurrency=1, batch_no=0, root=root,
    ))
    assert gen["completed_skip_count"] == 2
    assert gen["ok"] == 1
    assert gen_calls == ["raw/sources/f3.md"]


def test_generate_skip_files_excluded(tmp_path, monkeypatch):
    """--skip-files: excluded raw_rel is dropped before generate."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    files = ["raw/sources/f1.md", "raw/sources/f2.md", "raw/sources/f3.md"]
    for f in files:
        _make_raw(root, f)
    pages_by_rel = {f: [_source_page(f)] for f in files}
    gen_fake, gen_calls = _make_generate_fake(pages_by_rel)
    monkeypatch.setattr("src.pipeline.ingest.generate_ingest", gen_fake)
    monkeypatch.setattr("scripts.phase4_batch.REPORT", tmp_path / "report.txt")

    gen = asyncio.run(_generate_batch(
        paths=paths, provider=None, files=files, completed_files=set(),
        skip_files={"raw/sources/f2.md"}, concurrency=1, batch_no=0, root=root,
    ))
    assert gen["skip_count"] == 1
    assert gen["ok"] == 2
    assert gen_calls == ["raw/sources/f1.md", "raw/sources/f3.md"]


# ---------------------------------------------------------------------------
# R2-2 · _commit_all — SOURCE-page ownership + POSTCHECK + extras
# ---------------------------------------------------------------------------

def test_commit_failure_records_completed_and_resume_regenerates(
        tmp_path, monkeypatch):
    """① Commit of the 3rd file throws → state keeps completed_files=[前2];
    --resume regenerates only the remaining file."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    files = ["raw/sources/f1.md", "raw/sources/f2.md", "raw/sources/f3.md"]
    for f in files:
        _make_raw(root, f)
    pages_by_rel = {
        f: [_source_page(f), _wiki_page(f"concept-{Path(f).stem}", sources=[f])]
        for f in files
    }
    gen_fake, gen_calls = _make_generate_fake(pages_by_rel)
    monkeypatch.setattr("src.pipeline.ingest.generate_ingest", gen_fake)
    commit_fake, _ = _make_commit_fake(
        fail_on={"raw/sources/f3.md"}, write_to_disk=paths, root=root)
    _patch_commit_surface(monkeypatch, tmp_path, commit_fake)

    gen1 = asyncio.run(_generate_batch(
        paths=paths, provider=None, files=files, completed_files=set(),
        skip_files=set(), concurrency=1, batch_no=0, root=root,
    ))
    assert gen1["ok"] == 3
    entry1, rc1 = asyncio.run(_commit_all(
        paths=paths, pages=gen1["pages"], extras=gen1["extra"],
        batch_key="batch_0", batch_files=files, root=root, task_id="b0",
    ))
    assert rc1 == 3
    assert entry1["status"] == "postcheck_failed"
    state = json.loads((tmp_path / "batch_build_state.json").read_text(
        encoding="utf-8"))
    assert state["batch_0"]["completed_files"] == [
        "raw/sources/f1.md", "raw/sources/f2.md"]

    completed = _batch_completed_files("batch_0")
    assert completed == {"raw/sources/f1.md", "raw/sources/f2.md"}
    gen_calls.clear()
    gen2 = asyncio.run(_generate_batch(
        paths=paths, provider=None, files=files, completed_files=completed,
        skip_files=set(), concurrency=1, batch_no=0, root=root,
    ))
    assert gen2["ok"] == 1
    assert gen_calls == ["raw/sources/f3.md"]


def test_completed_files_from_source_sources_not_sources0(tmp_path, monkeypatch):
    """② F5: a page whose ``sources[0]`` is an alias (≠ raw) still records
    the correct raw_rel in completed_files (SOURCE-page ownership)."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    files = ["raw/sources/f1.md"]
    _make_raw(root, files[0])
    src_page = WikiPage(
        id="src-f1", title="f1", type=PageType.SOURCE,
        sources=["raw/sources/alias.md", "raw/sources/f1.md"],
        body="source body", grade="A", processing_depth="source",
    )
    concept = _wiki_page("concept-f1", sources=["raw/sources/f1.md"])
    commit_fake, _ = _make_commit_fake(write_to_disk=paths, root=root)
    _patch_commit_surface(monkeypatch, tmp_path, commit_fake)

    entry, rc = asyncio.run(_commit_all(
        paths=paths, pages=[src_page, concept], extras=[],
        batch_key="batch_0", batch_files=files, root=root, task_id="b0",
    ))
    assert rc == 0
    assert entry["completed_files"] == ["raw/sources/f1.md"]


def test_postcheck_missing_pages_exit3_and_resume_fills(tmp_path, monkeypatch):
    """③ F4: POSTCHECK missing page → exit 3 + postcheck_failed state with
    completed_files & missing list; --resume fills only the missing file."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    files = ["raw/sources/f1.md", "raw/sources/f2.md", "raw/sources/f3.md"]
    for f in files:
        _make_raw(root, f)
    pages_by_rel = {
        f: [_source_page(f), _wiki_page(f"concept-{Path(f).stem}", sources=[f])]
        for f in files
    }
    gen_fake, gen_calls = _make_generate_fake(pages_by_rel)
    monkeypatch.setattr("src.pipeline.ingest.generate_ingest", gen_fake)
    commit_fake, _ = _make_commit_fake(
        fail_on={"raw/sources/f2.md"}, write_to_disk=paths, root=root)
    _patch_commit_surface(monkeypatch, tmp_path, commit_fake)

    gen = asyncio.run(_generate_batch(
        paths=paths, provider=None, files=files, completed_files=set(),
        skip_files=set(), concurrency=1, batch_no=0, root=root,
    ))
    entry, rc = asyncio.run(_commit_all(
        paths=paths, pages=gen["pages"], extras=gen["extra"],
        batch_key="batch_0", batch_files=files, root=root, task_id="b0",
    ))
    assert rc == 3
    assert entry["status"] == "postcheck_failed"
    assert set(entry["completed_files"]) == {
        "raw/sources/f1.md", "raw/sources/f3.md"}
    assert set(entry["missing"]) == {"src-f2", "concept-f2"}

    completed = _batch_completed_files("batch_0")
    assert completed == {"raw/sources/f1.md", "raw/sources/f3.md"}
    gen_calls.clear()
    gen2 = asyncio.run(_generate_batch(
        paths=paths, provider=None, files=files, completed_files=completed,
        skip_files=set(), concurrency=1, batch_no=0, root=root,
    ))
    assert gen_calls == ["raw/sources/f2.md"]


def test_extras_committed_with_reverse_relation_event(tmp_path, monkeypatch):
    """④ B9: extras get one independent commit_ingest(event=reverse-relation)."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    files = ["raw/sources/f1.md"]
    _make_raw(root, files[0])
    src_page = _source_page(files[0])
    concept = _wiki_page("concept-f1", sources=[files[0]])
    extra = _wiki_page("extra-x", sources=[files[0]], body="existing body")
    commit_fake, commit_calls = _make_commit_fake(write_to_disk=paths, root=root)
    _patch_commit_surface(monkeypatch, tmp_path, commit_fake)

    entry, rc = asyncio.run(_commit_all(
        paths=paths, pages=[src_page, concept], extras=[extra],
        batch_key="batch_0", batch_files=files, root=root, task_id="b0",
    ))
    assert rc == 0
    assert entry["status"] == "committed"
    last = commit_calls[-1]
    assert last["event"] == "reverse-relation"
    assert last["source"] == "(batch-reconcile)"
    assert last["nextra"] == 1
    assert last["npages"] == 0


# ---------------------------------------------------------------------------
# R2-2 · B6 collision listing
# ---------------------------------------------------------------------------

def test_b6_blocker_lists_collision_page(tmp_path, monkeypatch):
    """⑤ D7/F6: B6 blocker names the colliding page."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    from src.wiki.features.indexer import append_to_index
    from src.wiki.storage.page_writer import write_page
    write_page(paths, _wiki_page("dup", sources=["raw/sources/old.md"]))
    append_to_index(paths, [("dup", PageType.ENTITY, "dup")])

    new_page = _wiki_page("dup", sources=["raw/sources/new.md"])
    blockers = _check_overwrite_protection([new_page], paths, allow_overwrite=False)
    assert len(blockers) == 1
    assert "dup" in blockers[0]


def test_b6_read_failure_logs_warning_and_blocks(tmp_path, monkeypatch, capsys):
    """C3: a non-PageNotFoundError read failure is logged as WARN and treated
    as a blocker — not silently swallowed."""
    root = tmp_path
    paths = ensure_knowledge_base(root)
    from src.wiki.features.indexer import append_to_index
    append_to_index(paths, [("dup", PageType.ENTITY, "dup")])

    def _boom(path):
        raise OSError("disk error")

    monkeypatch.setattr("src.wiki.storage.page_writer.read_page", _boom)
    monkeypatch.setattr("scripts.phase4_batch.REPORT", tmp_path / "report.txt")

    new_page = _wiki_page("dup", sources=["raw/sources/new.md"])
    blockers = _check_overwrite_protection([new_page], paths, allow_overwrite=False)
    assert len(blockers) == 1
    assert "on-disk read failed" in blockers[0]
    assert "dup" in blockers[0]
    out = capsys.readouterr().out
    assert "WARN overwrite check" in out
