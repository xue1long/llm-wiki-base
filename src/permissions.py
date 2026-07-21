# ruflo-kb/src/permissions.py
"""
目录权限边界校验

Agent 读写权限定义：
- Collector:   只写 Inbox/Processing
- Processor:  读 Inbox/Processing, 只写 Notes
- Librarian:  读 Notes, 只写 Knowledge
- Searcher:   只读 Knowledge 和 .index
- Orchestrator: 读写所有目录
"""

from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

class AgentType(str, Enum):
    COLLECTOR = "collector"
    PROCESSOR = "processor"
    LIBRARIAN = "librarian"
    SEARCHER = "searcher"
    ORCHESTRATOR = "orchestrator"

class Permission(str, Enum):
    READ = "read"
    WRITE = "write"

# 权限白名单
ALLOWED_PATHS = {
    AgentType.COLLECTOR: {
        Permission.READ: ["Inbox/Pending", "Inbox/Processing"],
        Permission.WRITE: ["Inbox/Processing"],
    },
    AgentType.PROCESSOR: {
        Permission.READ: ["Inbox/Processing"],
        Permission.WRITE: ["Notes"],
    },
    AgentType.LIBRARIAN: {
        Permission.READ: ["Notes"],
        Permission.WRITE: ["Knowledge"],
    },
    AgentType.SEARCHER: {
        Permission.READ: ["Knowledge", ".index"],
        Permission.WRITE: [],
    },
    AgentType.ORCHESTRATOR: {
        Permission.READ: ["Inbox", "Notes", "Knowledge"],
        Permission.WRITE: ["Inbox", "Notes", "Knowledge"],
    },
}

@dataclass
class PermissionCheckResult:
    allowed: bool
    reason: Optional[str] = None

def normalize_path(p: str) -> str:
    """标准化路径"""
    return str(Path(p).resolve()).replace("\\", "/")

def check_permission(
    agent: AgentType,
    path: str,
    permission: Permission,
) -> PermissionCheckResult:
    """
    检查 Agent 是否有权限访问指定路径

    Args:
        agent: Agent 类型
        path: 要访问的路径
        permission: 读或写权限

    Returns:
        PermissionCheckResult: 包含是否允许及原因
    """
    path_obj = Path(path)
    path_str = normalize_path(path)

    # Orchestrator 有完全权限
    if agent == AgentType.ORCHESTRATOR:
        return PermissionCheckResult(allowed=True)

    # 获取 Agent 的权限白名单
    allowed_dirs = ALLOWED_PATHS.get(agent, {}).get(permission, [])

    if not allowed_dirs:
        return PermissionCheckResult(
            allowed=False,
            reason=f"{agent.value} 不允许 {permission.value} 操作"
        )

    # 检查路径是否在允许的目录内
    for allowed_dir in allowed_dirs:
        allowed_path = normalize_path(allowed_dir)
        # 检查是否在允许目录内或其子目录
        if path_str.startswith(allowed_path) or path_obj.name == Path(allowed_path).name:
            return PermissionCheckResult(allowed=True)

    return PermissionCheckResult(
        allowed=False,
        reason=f"{agent.value} 不允许 {permission.value} 路径: {path}"
    )

def enforce_permission(
    agent: AgentType,
    path: str,
    permission: Permission,
) -> None:
    """
    强制执行权限检查，不允许时抛出异常
    """
    result = check_permission(agent, path, permission)
    if not result.allowed:
        raise PermissionError(f"权限拒绝: {result.reason}")

class PermissionGuard:
    """权限守卫上下文管理器"""

    def __init__(self, agent: AgentType, permission: Permission):
        self.agent = agent
        self.permission = permission
        self.path: Optional[str] = None

    def __enter__(self) -> "PermissionGuard":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def check(self, path: str) -> None:
        """检查指定路径的权限"""
        self.path = path
        enforce_permission(self.agent, path, self.permission)
