"""Publication Batch (B-4 commit 1, spec §5.13 + §17 D-21).

spec §5.13 Publication Batch:
    Knowledge Core、检索索引和派生视图只切换完整 published Batch。
    任一依赖失效时先生成包含 invalidation 的新 Batch，再原子切换默认读取水位；
    不得让新 Core 状态与旧索引混合对外可见。

spec §17 D-21:
    Core / 索引 / Wiki / Book / Agent Context 对外使用同一 publication_version。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ObjectVersion:
    """spec §5.13 object_versions 项."""

    object_type: str
    object_id: str
    version: int


@dataclass(frozen=True)
class PublicationBatch:
    """spec §5.13 Publication Batch (5 层视图原子水位)."""

    batch_id: str
    publication_version: int
    object_versions: tuple[ObjectVersion, ...]
    invalidated_object_ids: tuple[str, ...] = ()
    status: str = "preparing"  # preparing | published | withdrawn
    created_at: int = 0
    published_at: int | None = None

    def publish(self) -> "PublicationBatch":
        """原子发布: preparing → published."""
        if self.status != "preparing":
            raise ValueError(f"batch 状态必须为 preparing (实际: {self.status})")
        return PublicationBatch(
            batch_id=self.batch_id,
            publication_version=self.publication_version,
            object_versions=self.object_versions,
            invalidated_object_ids=self.invalidated_object_ids,
            status="published",
            created_at=self.created_at,
            published_at=int(time.time() * 1000),
        )

    def withdraw(self) -> "PublicationBatch":
        """原子撤回: preparing/published → withdrawn."""
        if self.status not in ("preparing", "published"):
            raise ValueError(
                f"batch 状态必须为 preparing/published (实际: {self.status})"
            )
        return PublicationBatch(
            batch_id=self.batch_id,
            publication_version=self.publication_version,
            object_versions=self.object_versions,
            invalidated_object_ids=self.invalidated_object_ids,
            status="withdrawn",
            created_at=self.created_at,
            published_at=self.published_at,
        )


class PublicationGate:
    """5 层视图原子水位管理器 (spec §5.13 + §17 D-21).

    关键特性:
    - publication_version 单调递增
    - 任一依赖失效时先生成包含 invalidation 的新 Batch, 再原子切换默认读取水位
    - 不得让新 Core 状态与旧索引混合对外可见
    """

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or Path(".index") / "publication_state.json"
        self._current_version: int = 0
        self._active_batches: dict[str, PublicationBatch] = {}

    def create_batch(
        self,
        object_versions: list[ObjectVersion],
        invalidated_object_ids: list[str] | None = None,
    ) -> PublicationBatch:
        """创建新 batch (preparing)."""
        version = self._current_version + 1
        batch = PublicationBatch(
            batch_id=f"pub_{version}_{int(time.time() * 1000)}",
            publication_version=version,
            object_versions=tuple(object_versions),
            invalidated_object_ids=tuple(invalidated_object_ids or ()),
            status="preparing",
            created_at=int(time.time() * 1000),
        )
        self._active_batches[batch.batch_id] = batch
        return batch

    def publish_batch(self, batch_id: str) -> PublicationBatch:
        """原子发布 batch + 切换默认读取水位."""
        batch = self._active_batches.get(batch_id)
        if batch is None:
            raise KeyError(f"batch_id 不存在: {batch_id}")

        published = batch.publish()
        self._active_batches[batch_id] = published
        self._current_version = published.publication_version
        return published

    def withdraw_batch(self, batch_id: str) -> PublicationBatch:
        """原子撤回 batch."""
        batch = self._active_batches.get(batch_id)
        if batch is None:
            raise KeyError(f"batch_id 不存在: {batch_id}")

        withdrawn = batch.withdraw()
        self._active_batches[batch_id] = withdrawn
        return withdrawn

    @property
    def current_version(self) -> int:
        """当前默认读取水位 (spec §11.3 旧版本失效确认前不提供默认查询)."""
        return self._current_version

    def get_batch(self, batch_id: str) -> PublicationBatch | None:
        """Return a registered batch for recovery/publish retries."""
        return self._active_batches.get(batch_id)

    def is_current(self, publication_version: int) -> bool:
        """检查对象版本是否在当前默认水位."""
        return publication_version == self._current_version

    def persist(self) -> Path:
        """持久化到 .index/publication_state.json."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "current_version": self._current_version,
            "active_batches": [
                {
                    "batch_id": b.batch_id,
                    "publication_version": b.publication_version,
                    "status": b.status,
                    "object_versions": [
                        {
                            "object_type": v.object_type,
                            "object_id": v.object_id,
                            "version": v.version,
                        }
                        for v in b.object_versions
                    ],
                    "invalidated_object_ids": list(b.invalidated_object_ids),
                    "created_at": b.created_at,
                    "published_at": b.published_at,
                }
                for b in self._active_batches.values()
            ],
        }
        self.state_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return self.state_path

    def load(self) -> "PublicationGate":
        """从 .index/publication_state.json 加载."""
        if not self.state_path.exists():
            return self
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self._current_version = data.get("current_version", 0)
        self._active_batches = {
            b["batch_id"]: PublicationBatch(
                batch_id=b["batch_id"],
                publication_version=b["publication_version"],
                object_versions=tuple(
                    ObjectVersion(v["object_type"], v["object_id"], v["version"])
                    for v in b.get("object_versions", [])
                ),
                invalidated_object_ids=tuple(b.get("invalidated_object_ids", [])),
                status=b.get("status", "preparing"),
                created_at=b.get("created_at", 0),
                published_at=b.get("published_at"),
            )
            for b in data.get("active_batches", [])
        }
        return self
