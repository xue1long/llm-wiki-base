"""
文件快照存储 - 追踪知识库文件 md5 变化
"""
import hashlib
import json
from pathlib import Path
from typing import Optional


class SnapshotStore:
    """JSON 快照存储：文件名 → md5"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

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
