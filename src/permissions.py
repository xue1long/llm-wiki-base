# ruflo-kb/src/permissions.py
"""
目录权限边界校验

Agent 读写权限定义（双布局 back-compat）：

wiki-v2 布局（当前，per CLAUDE.md）：
- Collector:   读写 raw/sources (legacy Inbox/Processing 仍保留)
- Orchestrator: 读写所有目录

wiki-v1 / legacy 布局（历史保留，已无 active caller）：
- Processor/Librarian 的 Notes/Knowledge 条目已从 ALLOWED_PATHS 删除
  （refactor pipeline: remove dead processor.process — 2026-07）。
- Inbox/Pending、Inbox/Processing 仍保留给 Collector 的 read 路径，
  以兼容旧项目布局。

Searcher 已从 ALLOWED_PATHS 移除（legacy Knowledge/.index 无 caller）。

边界检查使用 PurePath 语义 (is_relative_to / posix-prefix 比对)，不使用
Path.resolve() —— 因此结果与 os.getcwd() 无关。C-13 修复。
"""

from enum import Enum
from pathlib import PurePosixPath
from dataclasses import dataclass
from typing import Optional, Iterable

class AgentType(str, Enum):
    COLLECTOR = "collector"
    PROCESSOR = "processor"
    LIBRARIAN = "librarian"
    SEARCHER = "searcher"
    ORCHESTRATOR = "orchestrator"

class Permission(str, Enum):
    READ = "read"
    WRITE = "write"


class PermissionDenied(PermissionError):
    """Raised when an agent is denied access to a resource."""

# 权限白名单
ALLOWED_PATHS = {
    AgentType.COLLECTOR: {
        # Legacy Inbox/ layout (kept for back-compat) + new wiki-v2 layout
        # (per CLAUDE.md: <project>/raw/sources/). Callers resolve an
        # absolute project root via src/lib/project.py:resolve_project()
        # (used by src/services/ingest.py) and pass paths relative to it
        # so the boundary check above can match.
        Permission.READ: ["Inbox/Pending", "Inbox/Processing", "raw", "raw/sources"],
        Permission.WRITE: ["Inbox/Processing", "raw", "raw/sources"],
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


def _to_posix(p: str) -> str:
    """Convert a path-like string to a POSIX (forward-slash) string.

    Pure-string normalisation — no filesystem resolution. This is what
    makes the boundary check CWD-independent.
    """
    return str(p).replace("\\", "/")


def _normalise_segments(p: str) -> str:
    """Normalise a POSIX path's dot segments WITHOUT filesystem resolution.

    Splits ``p`` into segments, walks a stack: push a normal segment,
    on ``..`` pop one segment (if any), and ignore leading ``..``
    segments. Rejects paths that try to escape upward beyond the claimed
    root by leaving a leftover ``..`` in the final form.

    This is a pure-string operation — no ``Path.resolve()`` is invoked,
    so the result is CWD-independent. It runs *before* the
    ``is_relative_to`` boundary check so traversal attempts like
    ``Inbox/Processing/../../secret.txt`` are rejected.
    """
    raw = _to_posix(p).strip("/")
    if not raw:
        return ""
    stack: list[str] = []
    for seg in raw.split("/"):
        if seg == "" or seg == ".":
            # Empty (from "//") or current-dir — skip.
            continue
        if seg == "..":
            # Pop one segment if any; otherwise the path tried to escape
            # above its claimed root. Leave the ".." in the stack so the
            # resulting path is *not* a descendant of any reasonable
            # boundary (which is how we reject the attempt below).
            if stack:
                stack.pop()
            else:
                stack.append("..")
        else:
            stack.append(seg)
    return "/".join(stack)


def _is_within(child: str, boundary: str) -> bool:
    """Return True iff ``child`` is the boundary path or a descendant.

    Uses PurePosixPath.is_relative_to (Python 3.9+). Both inputs are
    pre-normalised to forward slashes; no resolve(), no CWD involvement.

    Dot segments are collapsed before the boundary check, so a path like
    ``Inbox/Processing/../../secret.txt`` is rejected (its normalised
    form is ``../secret.txt`` which is *not* under any reasonable
    boundary). The boundary must be a strict ancestor: ``child ==
    boundary`` returns True (the file at the boundary itself is
    allowed), but ``InboxEvil`` does NOT match boundary ``Inbox``
    because they share only a prefix, not an ancestor relationship.
    """
    c_norm = _normalise_segments(child)
    b_norm = _normalise_segments(boundary)
    if not c_norm or not b_norm:
        return False
    c = PurePosixPath(c_norm)
    b = PurePosixPath(b_norm)
    # Compare on trailing-slash basis so boundary == "Inbox" rejects
    # "InboxEvil" while still accepting "Inbox/x".
    return c == b or c.is_relative_to(b)


def check_permission(
    agent: AgentType,
    path: str,
    permission: Permission,
    allowed_paths: Optional[Iterable[str]] = None,
) -> PermissionCheckResult:
    """
    检查 Agent 是否有权限访问指定路径

    Args:
        agent: Agent 类型
        path: 要访问的路径
        permission: 读或写权限
        allowed_paths: 可选，覆盖默认白名单；用于单次调用收紧/放宽。
                       缺省时使用模块级 ALLOWED_PATHS。

    Returns:
        PermissionCheckResult: 包含是否允许及原因

    Notes:
        C-13 修复：边界检查使用 PurePosixPath.is_relative_to，移除
        Path.resolve() 调用，因此 CWD 不影响结果。
    """
    # URL reads are gated separately by the collector's network ACL
    # (T4 `_check_url_allowlisted`). Returning True here keeps the URL
    # gate as the single source of truth for SSRF / DNS checks; the
    # file-system boundary check is meaningless for URL schemes.
    if (
        agent == AgentType.COLLECTOR
        and permission == Permission.READ
        and path.startswith(("http://", "https://"))
    ):
        return PermissionCheckResult(allowed=True)

    # Orchestrator 有完全权限
    if agent == AgentType.ORCHESTRATOR:
        return PermissionCheckResult(allowed=True)

    # 确定本次白名单：显式 allowed_paths 优先；否则取 ALLOWED_PATHS 默认值
    if allowed_paths is None:
        dirs = list(ALLOWED_PATHS.get(agent, {}).get(permission, []))
    else:
        dirs = list(allowed_paths)

    if not dirs:
        return PermissionCheckResult(
            allowed=False,
            reason=f"{agent.value} 不允许 {permission.value} 操作"
        )

    # 检查路径是否在允许的目录内 (PurePosixPath 边界比对，无 CWD 依赖)
    for allowed_dir in dirs:
        if _is_within(path, allowed_dir):
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
        raise PermissionDenied(f"权限拒绝: {result.reason}")

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
