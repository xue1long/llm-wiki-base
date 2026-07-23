# ruflo-kb/src/inbox/manager.py
import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class InboxManager:
    """
    Inbox 目录管理器
    - Pending/: 待处理文件（Orchestrator 只扫描此目录）
    - Processing/: 处理中文件
    - Error/: 死信目录
    """

    def __init__(self, base_path: str = "Inbox"):
        self.base_path = Path(base_path)
        self.pending_path = self.base_path / "Pending"
        self.processing_path = self.base_path / "Processing"
        self.error_path = self.base_path / "Error"

    def ensure_dirs(self) -> None:
        """确保目录结构存在"""
        self.pending_path.mkdir(parents=True, exist_ok=True)
        self.processing_path.mkdir(parents=True, exist_ok=True)
        self.error_path.mkdir(parents=True, exist_ok=True)

    def move_to_processing(self, file_path: str) -> Path:
        """
        将文件从 Pending 移动到 Processing
        返回新的路径
        """
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        dst = self.processing_path / src.name
        # os.replace is idempotent on dst-exists (overwrites). shutil.move is
        # not portable (on POSIX, it falls back to copy+unlink when the
        # destination exists on a different filesystem, which fails the move).
        os.replace(str(src), str(dst))
        logger.info(f"[Inbox] Moved to Processing: {dst}")
        return dst

    def move_to_error(self, file_path: str, error_log: str) -> Path:
        """
        将文件从 Processing 移动到 Error，并写入 error.log
        """
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        dst = self.error_path / src.name
        os.replace(str(src), str(dst))

        # 写入错误日志（使用完整文件名以避免同名不同扩展名冲突）
        error_file = self.error_path / f"{src.name}.error.log"
        with open(error_file, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Error:\n{error_log}\n")

        logger.warning(f"[Inbox] Moved to Error: {dst}")
        return dst

    def scan_pending(self) -> list[Path]:
        """
        扫描 Pending 目录，返回所有待处理文件
        """
        if not self.pending_path.exists():
            return []

        return [
            f for f in self.pending_path.iterdir()
            if f.is_file() and not f.name.startswith(".")
        ]

# 全局单例
_inbox_manager: Optional[InboxManager] = None

def get_inbox_manager() -> InboxManager:
    global _inbox_manager
    if _inbox_manager is None:
        _inbox_manager = InboxManager()
        _inbox_manager.ensure_dirs()
    return _inbox_manager
