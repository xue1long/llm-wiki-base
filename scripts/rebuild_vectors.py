"""Build a replacement vector store from the wiki source of truth.

The builder writes only to ``.index/staging/<run_id>`` until the complete
chunk/row count has been verified.  A failed embedding call therefore leaves
the live store untouched and can be resumed with the same run id.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable


@dataclass(frozen=True)
class RebuildResult:
    run_id: str
    dry_run: bool
    page_count: int
    chunk_count: int
    dimension: int
    vector_row_count: int
    replaced: bool
    checkpoint_path: str
    page_manifest_hash: str
    provider_model: str = ""


@dataclass(frozen=True)
class _Page:
    id: str
    body: str
    path: str


def _default_page_loader(root: Path) -> list[_Page]:
    from src.wiki.storage.page_writer import read_page

    pages: list[_Page] = []
    for bucket in ("sources", "entities", "concepts", "synthesis"):
        directory = root / "wiki" / bucket
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md")):
            page = read_page(path)
            pages.append(_Page(page.id, page.body or "", path.relative_to(root).as_posix()))
    return pages


def _page_values(page: Any, root: Path) -> tuple[str, str, str]:
    page_id = str(getattr(page, "id"))
    body = str(getattr(page, "body", "") or "")
    raw_path = getattr(page, "path", "") or ""
    path = Path(str(raw_path))
    if path.is_absolute():
        try:
            raw_path = path.resolve(strict=False).relative_to(root.resolve()).as_posix()
        except ValueError:
            raw_path = path.as_posix()
    else:
        raw_path = path.as_posix()
    return page_id, body, raw_path


def _chunks_for_page(page: Any, root: Path) -> tuple[str, list[str], str]:
    from src.utils.text import chunk_markdown

    page_id, body, path = _page_values(page, root)
    return page_id, chunk_markdown(body.strip()) if body.strip() else [], path


def _manifest_hash(pages: Iterable[Any], root: Path) -> str:
    values = []
    for page in pages:
        page_id, body, path = _page_values(page, root)
        values.append(
            {
                "id": page_id,
                "path": path,
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
        )
    payload = json.dumps(sorted(values, key=lambda item: (item["path"], item["id"])),
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _checkpoint_path(root: Path, run_id: str) -> Path:
    return root / ".index" / "migration" / run_id / "rebuild_progress.json"


def _load_checkpoint(path: Path, run_id: str, manifest_hash: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("run_id", run_id) != run_id:
        raise ValueError("vector checkpoint run id mismatch")
    if data.get("page_manifest_hash") != manifest_hash:
        raise ValueError("vector checkpoint page manifest hash mismatch")
    return data


def _save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _is_retryable(error: BaseException) -> bool:
    status = getattr(error, "status_code", getattr(error, "status", None))
    if isinstance(status, str) and status.isdigit():
        status = int(status)
    if status == 429 or (isinstance(status, int) and 500 <= status <= 599):
        return True
    message = str(error)
    if re.search(r"(?<!\d)429(?!\d)", message):
        return True
    return bool(re.search(r"(?<!\d)5\d\d(?!\d)", message))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _embed_with_retry(
    provider: Any,
    texts: list[str],
    *,
    sleep: Callable[[float], Awaitable[Any] | Any],
    max_retries: int = 5,
) -> list[Any]:
    for attempt in range(max_retries + 1):
        try:
            return list(await _maybe_await(provider.embed(texts)))
        except BaseException as error:
            if not _is_retryable(error) or attempt >= max_retries:
                raise
            await _maybe_await(sleep(float(2**attempt)))
    raise AssertionError("unreachable")


def _embedding_values(results: list[Any]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for result in results:
        vector = getattr(result, "embedding", result)
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        vectors.append([float(value) for value in vector])
    return vectors


def _default_db_factory(path: Path) -> Any:
    import lancedb

    return lancedb.connect(str(path))


def _default_table_factory(db: Any, dimension: int) -> Any:
    try:
        return db.open_table("chunks")
    except Exception:
        from src.vector.store import _build_schema

        return db.create_table("chunks", schema=_build_schema(dimension), exist_ok=True)


def _row_count(table: Any) -> int:
    count = table.count_rows()
    return int(count.result() if hasattr(count, "result") else count)


def _promote(staging_db: Path, live_db: Path, run_id: str) -> None:
    if not staging_db.exists():
        raise RuntimeError(f"staging vector store missing: {staging_db}")
    live_db.parent.mkdir(parents=True, exist_ok=True)
    backup = live_db.with_name(f"{live_db.name}.backup.{run_id}")
    if backup.exists():
        raise FileExistsError(f"promotion backup already exists: {backup}")
    moved_old = False
    try:
        if live_db.exists():
            os.replace(live_db, backup)
            moved_old = True
        os.replace(staging_db, live_db)
    except BaseException:
        if moved_old and not live_db.exists() and backup.exists():
            os.replace(backup, live_db)
        raise


async def rebuild_vectors(
    root: Path,
    *,
    run_id: str | None = None,
    dry_run: bool = False,
    page_loader: Callable[[Path], Iterable[Any]] | None = None,
    provider: Any | None = None,
    db_factory: Callable[[Path], Any] | None = None,
    table_factory: Callable[[Any, int], Any] | None = None,
    sleep: Callable[[float], Awaitable[Any] | Any] = asyncio.sleep,
) -> RebuildResult:
    """Rebuild vectors in staging and promote only after row reconciliation."""
    root = Path(root).resolve(strict=False)
    run_id = run_id or time.strftime("vector-%Y%m%d-%H%M%S")
    loader = page_loader or _default_page_loader
    pages = list(loader(root))
    manifest_hash = _manifest_hash(pages, root)
    checkpoint_path = _checkpoint_path(root, run_id)
    checkpoint = _load_checkpoint(checkpoint_path, run_id, manifest_hash)

    page_chunks = [_chunks_for_page(page, root) for page in pages]
    chunk_count = sum(len(chunks) for _, chunks, _ in page_chunks)
    if dry_run:
        return RebuildResult(
            run_id, True, len(pages), chunk_count, 0, 0, False,
            str(checkpoint_path), manifest_hash,
            str(getattr(provider, "model", "") or ""),
        )
    if provider is None:
        raise RuntimeError("embedding provider is required for vector rebuild")

    staging_root = root / ".index" / "staging" / run_id
    staging_db = staging_root / "lancedb"
    live_db = root / ".index" / "lancedb"
    staging_db.mkdir(parents=True, exist_ok=True)
    db_factory = db_factory or _default_db_factory
    table_factory = table_factory or _default_table_factory

    processed_ids = list(checkpoint.get("processed_page_ids", []))
    processed_set = set(processed_ids)
    processed_pages = int(checkpoint.get("processed_pages", 0))
    dimension = int(checkpoint.get("dimension", 0) or 0)
    db = db_factory(staging_db)
    table = None
    if dimension:
        table = table_factory(db, dimension)

    pending_batches: list[tuple[str, list[str], str]] = []
    for page_id, chunks, path in page_chunks:
        if page_id in processed_set:
            continue
        pending_batches.append((page_id, chunks, path))

    for start in range(0, len(pending_batches), 100):
        batch = pending_batches[start : start + 100]
        texts = [chunk for _, chunks, _ in batch for chunk in chunks]
        vectors = await _embed_with_retry(provider, texts, sleep=sleep) if texts else []
        embeddings = _embedding_values(vectors)
        if len(embeddings) != len(texts):
            raise ValueError(
                f"embedding count mismatch: expected {len(texts)}, got {len(embeddings)}"
            )
        if embeddings:
            batch_dimension = len(embeddings[0])
            if not batch_dimension or any(len(vector) != batch_dimension for vector in embeddings):
                raise ValueError("embedding dimension mismatch within provider response")
            if dimension and dimension != batch_dimension:
                raise ValueError(
                    f"embedding dimension changed during rebuild: {dimension} -> {batch_dimension}"
                )
            dimension = batch_dimension
            if table is None:
                table = table_factory(db, dimension)

        rows = []
        vector_index = 0
        now = int(time.time() * 1000)
        for page_id, chunks, path in batch:
            for index, chunk in enumerate(chunks):
                rows.append({
                    "id": f"{page_id}-chunk-{index}",
                    "task_id": page_id,
                    "content": chunk,
                    "embedding": embeddings[vector_index],
                    "path": path,
                    "updated_at": now,
                })
                vector_index += 1
            processed_ids.append(page_id)
            processed_set.add(page_id)
        if rows:
            table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(rows)
        processed_pages += len(batch)
        _save_checkpoint(
            checkpoint_path,
            {
                "run_id": run_id,
                "page_manifest_hash": manifest_hash,
                "processed_pages": processed_pages,
                "processed_page_ids": processed_ids,
                "dimension": dimension,
                "provider_model": str(getattr(provider, "model", "") or ""),
                "completed": False,
            },
        )

    vector_row_count = _row_count(table) if table is not None else 0
    if vector_row_count != chunk_count:
        raise ValueError(
            f"vector row count mismatch: expected {chunk_count}, got {vector_row_count}"
        )
    _save_checkpoint(
        checkpoint_path,
        {
            "run_id": run_id,
            "page_manifest_hash": manifest_hash,
            "processed_pages": len(pages),
            "processed_page_ids": processed_ids,
            "dimension": dimension,
            "provider_model": str(getattr(provider, "model", "") or ""),
            "completed": True,
        },
    )
    _promote(staging_db, live_db, run_id)
    return RebuildResult(
        run_id, False, len(pages), chunk_count, dimension, vector_row_count, True,
        str(checkpoint_path), manifest_hash,
        str(getattr(provider, "model", "") or ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the project vector store")
    parser.add_argument("root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from src.llm.embedding_runtime import get_embedding_provider

    result = asyncio.run(
        rebuild_vectors(
            args.root,
            run_id=args.run_id,
            dry_run=args.dry_run,
            provider=get_embedding_provider(),
        )
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
