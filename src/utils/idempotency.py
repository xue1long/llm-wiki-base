# ruflo-kb/src/utils/idempotency.py
import hashlib
import time
from typing import Optional
from ..types import SourceType

TTL_SECONDS = 7 * 24 * 60 * 60  # 7天

class IdempotencyCache:
    def __init__(self):
        self._cache: dict[str, float] = {}  # task_hash -> timestamp

    def generate_hash(
        self,
        source_type: SourceType,
        identifier: str,
        content_prefix: str = "",
        project_id: str = "",
        round_key: str = "",
        contract_hash: str = "",
    ) -> str:
        """
        生成幂等键
        算法: md5(source_type + identifier + content_prefix + project_id + round_key)
        project_id 为空时对单项目场景向后兼容

        round_key（Phase 4 P4 P0 加固，plan guidance #7）：重建轮次维度。
        全量重摄入时同一 raw 会在多轮重建（reingest:{batch}:{raw}）——
        若不加轮次维度，第二轮重建会被第一轮的 in-memory 哈希判为重复而跳过。
        缺省为空字符串 → 与旧算法完全一致（队列/文件夹路径调用方不受影响）。
        """
        prefix = source_type.value
        data = f"{prefix}:{identifier}:{content_prefix[:1024]}:{project_id}:{round_key}:{contract_hash}"
        return hashlib.md5(data.encode()).hexdigest()

    def check_and_mark(self, task_hash: str) -> bool:
        """
        检查是否重复，返回 True 表示重复（应忽略）
        """
        now = time.time()

        # 清理过期条目
        expired = [h for h, t in self._cache.items() if now - t > TTL_SECONDS]
        for h in expired:
            del self._cache[h]

        if task_hash in self._cache:
            return True  # 重复

        self._cache[task_hash] = now
        return False

    def clear(self) -> None:
        self._cache.clear()

    def remove(self, task_hash: str) -> None:
        """Remove a hash from the cache, e.g. when a task fails and can be retried."""
        self._cache.pop(task_hash, None)

# 全局单例
_idempotency_cache: Optional[IdempotencyCache] = None

def get_idempotency_cache() -> IdempotencyCache:
    global _idempotency_cache
    if _idempotency_cache is None:
        _idempotency_cache = IdempotencyCache()
    return _idempotency_cache

def generate_task_hash(
    source_type: SourceType,
    source: str,
    content_prefix: str = "",
    project_id: str = "",
    round_key: str = "",
    contract_hash: str = "",
) -> str:
    """便捷函数"""
    cache = get_idempotency_cache()
    return cache.generate_hash(source_type, source, content_prefix, project_id,
                               round_key=round_key, contract_hash=contract_hash)

def check_duplicate(task_hash: str) -> bool:
    """检查是否重复提交"""
    cache = get_idempotency_cache()
    return cache.check_and_mark(task_hash)


def remove_hash(task_hash: str) -> None:
    """Remove a hash from the idempotency cache, allowing the task to be re-enqueued."""
    cache = get_idempotency_cache()
    cache.remove(task_hash)
