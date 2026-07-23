"""
文件快照存储 - 追踪知识库文件 md5 变化
"""
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional


_logger = logging.getLogger(__name__)


class SnapshotStore:
    """JSON 快照存储：文件名 → md5

    Persists via atomic write (tmp + os.replace) and recovers from
    JSONDecodeError / OSError on load by starting with an empty dict.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning(f"[SnapshotStore] snapshot file corrupt ({e}); starting empty")
            self._data = {}
            return
        if not isinstance(data, dict):
            _logger.warning("[SnapshotStore] snapshot root is not a dict; starting empty")
            self._data = {}
            return
        self._data = {str(k): str(v) for k, v in data.items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._save()

    def as_dict(self) -> dict[str, str]:
        return dict(self._data)

    @staticmethod
    def compute_md5(file_path: Path) -> str:
        return hashlib.md5(file_path.read_bytes()).hexdigest()
