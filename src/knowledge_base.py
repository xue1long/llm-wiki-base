# ruflo-kb/src/knowledge_base.py
"""
知识库目录结构初始化

目录结构:
knowledge-base/
├── Inbox/           # 入口：原始素材（链接/文件）
│   ├── Pending/     # 待处理文件
│   ├── Processing/  # 处理中文件
│   └── Error/       # 死信目录
├── Notes/           # 结构化加工产物
├── Knowledge/       # 正式知识库
│   └── Archive/     # 低价值/过期内容
├── .index/          # 向量/标签索引
└── Templates/       # 模板
"""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class KnowledgeBasePaths:
    """知识库目录路径"""
    base: Path
    inbox: Path
    inbox_pending: Path
    inbox_processing: Path
    inbox_error: Path
    notes: Path
    knowledge: Path
    knowledge_archive: Path
    index: Path
    templates: Path

    @classmethod
    def default(cls, base_path: Optional[str] = None) -> "KnowledgeBasePaths":
        """创建默认路径配置"""
        if base_path is None:
            base_path = "."
        base = Path(base_path)

        return cls(
            base=base,
            inbox=base / "Inbox",
            inbox_pending=base / "Inbox" / "Pending",
            inbox_processing=base / "Inbox" / "Processing",
            inbox_error=base / "Inbox" / "Error",
            notes=base / "Notes",
            knowledge=base / "Knowledge",
            knowledge_archive=base / "Knowledge" / "Archive",
            index=base / ".index",
            templates=base / "Templates",
        )

def ensure_knowledge_base(base_path: Optional[str] = None) -> KnowledgeBasePaths:
    """
    确保知识库目录结构存在

    Args:
        base_path: 知识库根目录，默认为当前目录

    Returns:
        KnowledgeBasePaths: 目录路径配置
    """
    paths = KnowledgeBasePaths.default(base_path)

    # 创建所有目录
    directories = [
        paths.inbox_pending,
        paths.inbox_processing,
        paths.inbox_error,
        paths.notes,
        paths.knowledge,
        paths.knowledge_archive,
        paths.index,
        paths.templates,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug(f"[KnowledgeBase] Created directory: {directory}")

    logger.info(f"[KnowledgeBase] Initialized at: {paths.base.resolve()}")
    return paths

def get_knowledge_base_paths(base_path: Optional[str] = None) -> KnowledgeBasePaths:
    """获取知识库路径配置（不创建目录）"""
    return KnowledgeBasePaths.default(base_path)

def is_valid_knowledge_base(base_path: str) -> bool:
    """检查目录是否为有效的知识库根目录"""
    paths = KnowledgeBasePaths.default(base_path)

    # 检查必要的目录是否存在
    required_dirs = [
        paths.inbox_pending,
        paths.inbox_processing,
        paths.inbox_error,
        paths.notes,
        paths.knowledge,
    ]

    return all(d.exists() and d.is_dir() for d in required_dirs)
