"""Tests for the ``book`` CLI subcommand (book-build runtime wiring, Task 2).

Proves that "generate book" is now a reachable runtime path:

    python -m src.cli book build --project <id> [--apply] [--out DIR]
    python -m src.cli book show  --project <id>

Exit-code contract:
    0  planned (dry-run) or committed (--apply)
    1  rebuild failed (a chapter could not be compiled/rendered)
    2  project could not be resolved
    3  nothing to build (project has no KC claims → empty snapshot)

``book build`` is **dry-run by default** — writing requires an explicit
``--apply``. Project resolution is monkeypatched; these tests target command
behaviour, not the registry.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.cli_ext import book_cmd


# ─── Fixture builders ──────────────────────────────────────────────────


def _claim(object_id: str, *, source_path: str) -> dict:
    return {
        "id": object_id,
        "type": "claim",
        "title": f"claim {object_id}",
        "content": f"content {object_id}",
        "lifecycle": "processing",
        "confidence": 1.0,
        "provenance": {
            "source_path": source_path,
            "source_paths": [source_path],
            "quote": "raw quote",
            "ingested_at": 0,
            "ingestor_version": "legacy-text-v1",
        },
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


def _write_bundle(
    kc_root: Path,
    bundle_key: str,
    *,
    source_path: str,
    claims: list[dict],
    evidences: list[dict] | None = None,
) -> None:
    bundle_dir = kc_root / "bundles" / bundle_key
    (bundle_dir / "objects").mkdir(parents=True, exist_ok=True)
    (bundle_dir / "manifest.json").write_text(
        json.dumps({"bundle_key": bundle_key, "source_path": source_path}),
        encoding="utf-8",
    )
    for claim in claims:
        (bundle_dir / "objects" / f"{claim['id']}.json").write_text(
            json.dumps(claim, ensure_ascii=False), encoding="utf-8"
        )
    if evidences is not None:
        (bundle_dir / "evidence").mkdir(parents=True, exist_ok=True)
        for ev in evidences:
            (bundle_dir / "evidence" / f"{ev['evidence_id']}.json").write_text(
                json.dumps(ev, ensure_ascii=False), encoding="utf-8"
            )


def _make_project(root: Path, *, bundles: list[tuple[str, str, list[dict], list[dict] | None]],
                  publication_version: int = 4) -> Path:
    kc_root = root / ".index" / "kc"
    kc_root.mkdir(parents=True, exist_ok=True)
    for key, source_path, claims, evidences in bundles:
        _write_bundle(kc_root, key, source_path=source_path, claims=claims, evidences=evidences)
    (kc_root / "publication_state.json").write_text(
        json.dumps({"current_version": publication_version, "active_batches": []}),
        encoding="utf-8",
    )
    return root


def _two_source_project(root: Path) -> Path:
    return _make_project(
        root,
        bundles=[
            ("bk_a", "raw/sources/a.md",
             [_claim("c1", source_path="raw/sources/a.md"),
              _claim("c2", source_path="raw/sources/a.md")],
             [_evidence("ev1", supports=["c1"])]),
            ("bk_b", "raw/sources/b.md",
             [_claim("c3", source_path="raw/sources/b.md")],
             [_evidence("ev2", supports=["c3"])]),
        ],
    )


class _FakeCtx:
    """Minimal ProjectContext stand-in (the CLI only reads ``ctx.path``)."""

    def __init__(self, path: Path) -> None:
        self.path = path


def _patch_resolve(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        book_cmd,
        "resolve_project",
        lambda project_arg=None, by_id_only=False: (_FakeCtx(root), None),
    )


def _patch_resolve_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.project.context import ProjectNotFoundError

    def _boom(project_arg=None, by_id_only=False):
        raise ProjectNotFoundError(f"No project with id/name '{project_arg}'.")

    monkeypatch.setattr(book_cmd, "resolve_project", _boom)


class _Args:
    """argparse.Namespace stand-in."""

    def __init__(self, **kwargs: Any) -> None:
        self.project: str | None = None
        self.json: bool = False
        self.apply: bool = False
        self.out: str | None = None
        self.title: str | None = None
        self.__dict__.update(kwargs)


# ─── book show ─────────────────────────────────────────────────────────


def test_book_show_reports_chapter_stats(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    exit_code = book_cmd.cmd_book_show(_Args(project="p1"))
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "chapters=2" in out
    assert "claims=3" in out
    assert "evidence=2" in out
    assert "publication_version=4" in out


def test_book_show_lists_chapters(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    book_cmd.cmd_book_show(_Args(project="p1"))
    out = capsys.readouterr().out

    assert "a.md" in out
    assert "b.md" in out


def test_book_show_json_shape(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    exit_code = book_cmd.cmd_book_show(_Args(project="p1", json=True))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["chapters"] == 2
    assert payload["claims"] == 3
    assert payload["evidence"] == 2
    assert payload["publication_version"] == 4
    assert payload["derived"] is True
    assert len(payload["chapter_list"]) == 2
    assert payload["chapter_list"][0]["order"] == 0


def test_book_show_empty_project_exits_3(tmp_path: Path, capsys, monkeypatch) -> None:
    _patch_resolve(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        book_cmd.cmd_book_show(_Args(project="p1"))
    assert exc.value.code == 3
    assert "kc_root:missing" in capsys.readouterr().err


def test_book_show_exits_2_when_project_unresolved(tmp_path: Path, capsys, monkeypatch) -> None:
    _patch_resolve_error(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        book_cmd.cmd_book_show(_Args(project="nope"))
    assert exc.value.code == 2


# ─── book build — dry run (default) ────────────────────────────────────


def test_book_build_dry_run_writes_nothing(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    exit_code = book_cmd.cmd_book_build(_Args(project="p1"))
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "planned" in out
    assert not (root / "book").exists(), "dry-run must not create the output dir"


def test_book_build_dry_run_reports_planned_chapters(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    book_cmd.cmd_book_build(_Args(project="p1"))
    out = capsys.readouterr().out
    assert "planned=2" in out
    assert "failed=0" in out


def test_book_build_json_dry_run(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    exit_code = book_cmd.cmd_book_build(_Args(project="p1", json=True))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "planned"
    assert payload["apply"] is False
    assert payload["rebuilt_chapter_ids"] and len(payload["rebuilt_chapter_ids"]) == 2
    assert payload["output_dir"] is None


def test_book_build_json_reports_default_output_dir(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    book_cmd.cmd_book_build(_Args(project="p1", json=True, apply=True))
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "committed"
    assert payload["apply"] is True
    assert Path(payload["output_dir"]) == root / "book"


# ─── book build — apply (D-3: <project_root>/book) ─────────────────────


def test_book_build_apply_writes_chapter_files(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    exit_code = book_cmd.cmd_book_build(_Args(project="p1", apply=True))
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "committed" in out

    book_dir = root / "book"
    assert book_dir.is_dir()
    md_files = sorted(p.name for p in book_dir.glob("*.md"))
    json_files = sorted(p.name for p in book_dir.glob("*.json"))
    assert len(md_files) == 2
    assert len(json_files) == 2
    for md in md_files:
        assert (book_dir / md).read_text(encoding="utf-8").strip(), f"{md} is empty"


def test_book_build_apply_honours_custom_out_dir(tmp_path: Path, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)
    custom = tmp_path / "custom-out"

    exit_code = book_cmd.cmd_book_build(_Args(project="p1", apply=True, out=str(custom)))

    assert exit_code == 0
    assert custom.is_dir()
    assert len(list(custom.glob("*.md"))) == 2
    assert not (root / "book").exists()


def _strip_generated_at(raw: bytes) -> str:
    """Markdown body minus the per-run audit timestamp line.

    ``markdown._footer`` writes ``generated_at: <unix ms>`` into every
    chapter body, but ``rendered_hash`` is computed BEFORE the footer is
    filled in — so the content fingerprint is stable while the human-readable
    timestamp is not. Idempotency therefore means: identical file set,
    identical metadata, identical body modulo that one audit line.
    """
    return "\n".join(
        line for line in raw.decode("utf-8").splitlines()
        if not line.startswith("generated_at:")
    )


def test_book_build_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Two runs produce the same artifacts — deterministic chapter ids."""
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    book_cmd.cmd_book_build(_Args(project="p1", apply=True))
    first = {p.name: p.read_bytes() for p in (root / "book").glob("*") if p.is_file()}
    book_cmd.cmd_book_build(_Args(project="p1", apply=True))
    second = {p.name: p.read_bytes() for p in (root / "book").glob("*") if p.is_file()}

    # Same file set — chapter ids are content hashes, not uuid4, so repeated
    # builds rewrite the same filenames instead of littering new ones.
    assert set(first) == set(second)
    assert len([n for n in first if n.endswith(".md")]) == 2

    # Metadata is byte-identical (no timestamp in the sidecar JSON).
    for name in first:
        if name.endswith(".json"):
            assert first[name] == second[name], f"{name} metadata drifted"

    # Markdown bodies differ only in the generated_at audit line.
    for name in first:
        if name.endswith(".md"):
            assert _strip_generated_at(first[name]) == _strip_generated_at(second[name]), (
                f"{name} body drifted beyond the audit timestamp"
            )


def test_book_build_rendered_hash_is_stable(tmp_path: Path, monkeypatch) -> None:
    """The content fingerprint must not change across runs (real idempotency)."""
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    book_cmd.cmd_book_build(_Args(project="p1", apply=True))
    first = {
        p.name: json.loads(p.read_text(encoding="utf-8"))["rendered_hash"]
        for p in (root / "book").glob("*.json")
    }
    book_cmd.cmd_book_build(_Args(project="p1", apply=True))
    second = {
        p.name: json.loads(p.read_text(encoding="utf-8"))["rendered_hash"]
        for p in (root / "book").glob("*.json")
    }

    assert first == second
    assert len(set(first.values())) == 2, "each chapter needs a distinct hash"


def test_book_build_metadata_json_contents(tmp_path: Path, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    book_cmd.cmd_book_build(_Args(project="p1", apply=True))

    meta_files = sorted((root / "book").glob("*.json"))
    payload = json.loads(meta_files[0].read_text(encoding="utf-8"))
    assert payload["publication_version"] == 4
    assert payload["stable_key"].endswith("::principle")
    assert payload["rendered_hash"]
    assert payload["sections"]


def test_book_build_apply_respects_title(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    book_cmd.cmd_book_build(_Args(project="p1", apply=True, title="小说写作手册"))
    out = capsys.readouterr().out
    assert "小说写作手册" in out


# ─── book build — failure / empty ──────────────────────────────────────


def test_book_build_empty_project_exits_3(tmp_path: Path, capsys, monkeypatch) -> None:
    _patch_resolve(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        book_cmd.cmd_book_build(_Args(project="p1", apply=True))
    assert exc.value.code == 3
    assert not (tmp_path / "book").exists()


def test_book_build_exits_2_when_project_unresolved(tmp_path: Path, monkeypatch) -> None:
    _patch_resolve_error(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        book_cmd.cmd_book_build(_Args(project="nope"))
    assert exc.value.code == 2


def test_book_build_exits_1_on_rebuild_failure(tmp_path: Path, capsys, monkeypatch) -> None:
    """A failed chapter surfaces as exit 1 with its reason codes."""
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    class _FailedReport:
        status = "failed"
        book_id = "book_x"
        publication_version = 4
        rebuilt_chapter_ids = ()
        failed_chapter_ids = ("ch_broken",)
        reason_codes = ("integrity_block:gate",)
        rendered_hashes: dict = {}
        not_evaluable = False

    monkeypatch.setattr(book_cmd, "rebuild_book", lambda *a, **kw: _FailedReport())

    with pytest.raises(SystemExit) as exc:
        book_cmd.cmd_book_build(_Args(project="p1", apply=True))
    assert exc.value.code == 1
    assert "integrity_block:gate" in capsys.readouterr().err


def test_book_build_failure_json_exit_1(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _two_source_project(tmp_path)
    _patch_resolve(monkeypatch, root)

    class _FailedReport:
        status = "failed"
        book_id = "book_x"
        publication_version = 4
        rebuilt_chapter_ids = ()
        failed_chapter_ids = ("ch_broken",)
        reason_codes = ("evidence_unsupported:block",)
        rendered_hashes: dict = {}
        not_evaluable = False

    monkeypatch.setattr(book_cmd, "rebuild_book", lambda *a, **kw: _FailedReport())

    with pytest.raises(SystemExit) as exc:
        book_cmd.cmd_book_build(_Args(project="p1", apply=True, json=True))
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["reason_codes"] == ["evidence_unsupported:block"]


# ─── Wiring surface ────────────────────────────────────────────────────


def test_build_parser_registers_subcommands() -> None:
    import argparse

    from src.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["book", "build", "--project", "p1", "--apply"])
    assert args.func is book_cmd.cmd_book_build
    assert args.project == "p1"
    assert args.apply is True


def test_show_parser_registers_subcommands() -> None:
    import argparse

    from src.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["book", "show", "--project", "p1"])
    assert args.func is book_cmd.cmd_book_show
    # Writing must be opt-in: --apply is absent from `book show`.
    with pytest.raises(SystemExit):
        parser.parse_args(["book", "show", "--project", "p1", "--apply"])
