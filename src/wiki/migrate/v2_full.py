from __future__ import annotations
import csv, json, shutil, uuid
from io import StringIO
import re
from pathlib import Path

from .v2_manifest import CheckpointItem, build_manifest, save_manifest
from .v2_run_state import RunState, load_run_state, save_run_state, rollback_run, write_checkpoint
from .v2_frontmatter import convert_frontmatter_and_body
from .v2_quarantine import write_quarantine
from .v2_raw import copy_raw_file, sha256_file

_DISK_RESERVE_BYTES = 5 * 1024 * 1024 * 1024


def _write_csv(path, rows, fieldnames):
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _write_reports(staging, manifest):
    fields = ["source_path", "kind", "disposition", "target_path", "size", "sha256", "reason"]
    rows = [{field: getattr(item, field) for field in fields} for item in manifest.items]
    _write_csv(staging / "migration_report.csv", rows, fields)
    warning_rows = [row for row in rows if row["disposition"] not in {"migrated", "metadata-only"}]
    _write_csv(staging / "migration_warnings.csv", warning_rows, fields)
    pending_rows = [row for row in rows if row["disposition"] == "pending"]
    _write_csv(staging / "pending_decisions.csv", pending_rows, fields)


def _verify_source_hashes(source, manifest):
    for item in manifest.items:
        if item.disposition in {"skipped", "support-artifact"}:
            continue
        actual = sha256_file(Path(source) / item.source_path)
        if actual != item.sha256:
            raise ValueError(
                f"source changed after manifest: {item.source_path} "
                f"(expected {item.sha256}, got {actual})"
            )


def _disk_preflight(target, manifest):
    source_bytes = sum(item.size for item in manifest.items if item.disposition not in {"skipped", "support-artifact"})
    free_bytes = shutil.disk_usage(target).free
    required_bytes = source_bytes + _DISK_RESERVE_BYTES
    return {
        "source_bytes": source_bytes,
        "free_bytes": free_bytes,
        "reserve_bytes": _DISK_RESERVE_BYTES,
        "required_bytes": required_bytes,
        "passed": free_bytes >= required_bytes,
    }

def _frontmatter(path):
    text=path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"): return {}, text
    _, rest=text.split("---",1); raw, body=rest.split("---",1)
    try:
        import yaml
        data=yaml.safe_load(raw) or {}
    except Exception:
        data={"_migration_parse_error":"invalid yaml"}
    return data, body.lstrip("\n")

def _dump(data, body):
    import yaml
    return "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip() + "\n---\n\n" + body

def _materialize_gap_stubs(target):
    pattern = re.compile(r"\[\[([^\]|#\r\n]+)(?:\|[^\]]+)?\]\]")
    pages = list((target / "wiki").rglob("*.md"))
    known = {p.stem for p in pages}
    stubs = target / "wiki" / "_stubs"
    created = []
    for page in pages:
        body = page.read_text(encoding="utf-8", errors="replace")
        for raw in pattern.findall(body):
            target_id = raw.strip()
            if not target_id or target_id in known or any(c in target_id for c in "/\\:*?\"<>|"):
                continue
            stub = stubs / f"{target_id}.md"
            if not stub.exists():
                stub.parent.mkdir(parents=True, exist_ok=True)
                stub.write_text(
                    _dump({"id": target_id, "title": target_id, "type": "concept", "sources": [], "relations": [], "tags": [], "_ko_extra": {"knowledge_gap": True}}, "# Knowledge gap\n\nUnresolved v2 wikilink; source text preserved."),
                    encoding="utf-8",
                )
                created.append(stub)
            known.add(target_id)

    gaps = set()
    for page in pages:
        body = page.read_text(encoding="utf-8", errors="replace")
        gaps.update(raw.strip() for raw in pattern.findall(body) if raw.strip() not in known)
    gap_path = target / ".index" / "migration-support" / "wikilink-gaps.json"
    gap_path.parent.mkdir(parents=True, exist_ok=True)
    if not gap_path.exists():
        gap_path.write_text(json.dumps({"targets": sorted(gaps)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        created.append(gap_path)
    return created

def resolve_project(project, cwd=None):
    value=str(project); root=Path(cwd or Path.cwd()).resolve()
    candidates=[root] + [p for base in (root/"knowledge", root) if base.exists() for p in base.iterdir() if p.is_dir()]
    for candidate in candidates:
        meta=candidate/".llm-wiki"/"project.json"
        if meta.exists():
            try:
                if json.loads(meta.read_text(encoding="utf-8")).get("id") == value: return candidate
            except json.JSONDecodeError: pass
    raise ValueError("project UUID not found")

def migrate_v2(project_root, v2_path, *, run_id=None, apply=False, resume=False, rollback=False):
    target=Path(project_root).resolve(); source=Path(v2_path).resolve()
    if not source.is_absolute(): raise ValueError("v2 path must be absolute")
    if not (target/".llm-wiki"/"project.json").exists(): raise ValueError("target project metadata missing")
    project_uuid=json.loads((target/".llm-wiki"/"project.json").read_text(encoding="utf-8"))["id"]
    if rollback:
        return rollback_run(target, run_id or "", dry_run=not apply)
    run_id=run_id or uuid.uuid4().hex
    manifest=build_manifest(source,target,run_id); manifest_path=save_manifest(target,manifest)
    state=load_run_state(target,run_id,manifest.manifest_hash) if resume else RunState(run_id,project_uuid,str(source),manifest.manifest_hash)
    staging=target/".index"/"staging"/run_id; payload=staging/"payload"
    disk = _disk_preflight(target, manifest)
    result={"run_id":run_id,"manifest_hash":manifest.manifest_hash,"manifest_path":str(manifest_path),"counts":manifest.counts,"dry_run":not apply,"staging":str(staging),"disk_preflight":disk}
    _write_reports(staging, manifest)
    if not apply: return result
    if not disk["passed"]:
        raise RuntimeError(
            f"insufficient disk space: need {disk['required_bytes']} bytes, "
            f"have {disk['free_bytes']} bytes"
        )
    staging.mkdir(parents=True, exist_ok=True)
    progress = staging / "migration_progress.jsonl"
    raw_progress = staging / "raw_progress.jsonl"
    save_run_state(target, state)
    promoted_paths = []
    try:
        _verify_source_hashes(source, manifest)
        for item in manifest.items:
            src=source/Path(item.source_path); dst=payload/Path(item.target_path)
            if item.source_path in state.checkpoint and dst.is_file():
                if item.kind in {"source", "raw", "archive", "seed"} and sha256_file(dst) != item.sha256:
                    raise ValueError(f"checkpoint output hash mismatch: {dst}")
                continue
            if item.disposition in {"skipped","support-artifact"}:
                state.checkpoint[item.source_path]=item.disposition
                write_checkpoint(progress, CheckpointItem(run_id, item.source_path, item.kind, "done"))
                save_run_state(target, state)
                continue
            if item.kind in {"source", "raw", "archive", "seed", "metadata"}:
                if item.disposition == "metadata-only":
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                else:
                    copy_raw_file(src, dst, staging_root=staging, expected_sha256=item.sha256)
                state.checkpoint[item.source_path]=item.disposition
                write_checkpoint(progress, CheckpointItem(run_id, item.source_path, item.kind, "done"))
                if item.kind in {"source", "raw", "archive", "seed"}:
                    write_checkpoint(raw_progress, CheckpointItem(run_id, item.source_path, item.kind, "done"))
                save_run_state(target, state)
                continue
            if item.disposition == "quarantined":
                fm,body=_frontmatter(src); write_quarantine(src.stem,fm,body,payload)
                state.checkpoint[item.source_path]=item.disposition
                write_checkpoint(progress, CheckpointItem(run_id, item.source_path, item.kind, "done"))
                save_run_state(target, state)
                continue
            if item.kind == "wiki":
                fm,body=_frontmatter(src); fm,body=convert_frontmatter_and_body(fm,file_stem=src.stem,body=body); dst.parent.mkdir(parents=True,exist_ok=True); dst.write_text(_dump(fm,body),encoding="utf-8")
            state.checkpoint[item.source_path]=item.disposition
            write_checkpoint(progress, CheckpointItem(run_id, item.source_path, item.kind, "done"))
            save_run_state(target, state)
        state.complete_phase("promotion",checkpoint=state.checkpoint,counts=manifest.counts); save_run_state(target,state)
        _verify_source_hashes(source, manifest)
        files = [child for child in payload.rglob("*") if child.is_file()]
        destinations = [(child, target/child.relative_to(payload)) for child in files]
        collisions = [dest for _, dest in destinations if dest.exists()]
        if collisions:
            raise FileExistsError(f"target collision: {collisions[0]}")
        for child, dest in destinations:
            dest.parent.mkdir(parents=True,exist_ok=True)
            child.replace(dest)
            promoted_paths.append(dest.relative_to(target).as_posix())
        created = _materialize_gap_stubs(target)
        promoted_paths.extend(path.relative_to(target).as_posix() for path in created)
        # Keep the audit evidence after the temporary payload is removed.
        record = target / ".index" / "migration" / "runs" / run_id
        record.mkdir(parents=True, exist_ok=True)
        (record / "promoted_paths.json").write_text(json.dumps({"run_id": run_id, "project_uuid": project_uuid, "paths": promoted_paths}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.copyfile(staging / "migration-manifest.json", record / "migration-manifest.json")
        for report in ("migration_report.csv", "migration_warnings.csv", "pending_decisions.csv"):
            shutil.copyfile(staging / report, record / report)
        state.complete_phase("complete",checkpoint=state.checkpoint,counts=manifest.counts)
        save_run_state(target,state)
        shutil.copyfile(staging / "run-state.json", record / "run-state.json")
        shutil.rmtree(staging)
        result["manifest_path"] = str(record / "migration-manifest.json")
        result["run_record_path"] = str(record)
        result["dry_run"]=False; result["promoted"]=True
        return result
    except Exception as exc:
        for relative in reversed(promoted_paths):
            path = target / relative
            if path.is_file():
                path.unlink()
        state.fail(str(exc)); save_run_state(target,state); result["error"]=str(exc); raise
