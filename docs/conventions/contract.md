# 契约规范（Contract Conventions）

> 适用范围：跨模块/跨层接口（`src/kc/contracts/`、服务层 ↔ core/domain、
> CLI ↔ 服务层、HTTP 路由 ↔ 服务层）。
>
> 本规范定稿的目的是**约束跨层 API 的入参、出参、错误、可空性**四项契约，
> 减少"自由发挥"导致的隐式依赖、隐式 None、隐式字段丢失。

## 1. 入参规范

- **`@dataclass` 优先**（**本项目纪律**）：当函数参数 ≥ 3 个或任一参数
  含义需要注释时，**必须**封装为 `@dataclass`（输入对象），禁止散落位置参数。
- **位置参数 ≤ 5 个**：超过 5 个的位置参数**禁止**出现（lint 友好 + 可读性）；
  超长参数列表必须迁移到 `@dataclass`。
- **关键字参数（kw-only）**：从 v2.2 起，**对外契约函数**（`async_*`、`aclose_*`、
  服务层入口、CLI 处理器）使用 `*,` 强制 kw-only。
- **`**kwargs` 禁止**：除内部 helper / 透传场景外，公开函数**禁止**接受 `**kwargs`；
  需要扩展字段时扩展 dataclass。
- **顺序**：必填参数在前 → 可选 dataclass 在后 → kw-only 段。

```python
# ✅ Good
@dataclass
class IngestRequest:
    source: str | dict[str, Any]              # URL 或本地路径
    project_id: str
    provider: str | None = None
    force: bool = False

async def async_enqueue_source(
    *,
    req: IngestRequest,                       # 入参 dataclass
) -> IngestTaskResult: ...

# ❌ Bad
async def async_enqueue_source(
    source, project_id, provider=None, force=False,
    retries=3, timeout=30, priority=0,        # > 5 个位置参数
    **kwargs,                                  # **kwargs 泛滥
): ...
```

## 2. 出参规范

| 场景 | 推荐 | 原因 |
|---|---|---|
| 多个独立同质字段（2-5 个） | **`@dataclass`** | 类型安全 + IDE 友好 |
| **2 个字段且语义成对**（如 `(value, error)`、`(key, node)`） | **`tuple[T1, T2]`** | 解构简洁，不污染类型空间 |
| 透传上游 dict（如 LLM JSON） | **`dict[str, Any]`** + TypedDict（推荐） | 透传语义清晰，避免"伪结构化" |
| 异步流式增量（`yield`） | **`AsyncIterator[T]`** | 类型流清晰 |
| 不定数量同质元素 | **`list[T]`** + Optional 不允许（用空列表表示空集） | 与 `naming.md` §5 一致 |

- **dict 的边界**：公开契约**禁止裸 `dict` 出参**（必须用 TypedDict 或
  dataclass）；内部函数可酌情使用。
- **不返回 None 表示"空集合"**：用空 `list` / 空 `dict` / 默认 dataclass。

```python
# ✅ Good
@dataclass(frozen=True)
class SearchHit:
    page_id: str
    score: float
    snippet: str

@dataclass
class IngestTaskResult:
    status: Literal["queued", "running", "done", "failed"]
    task_id: str
    cached: bool = False                       # 默认值显式

# ❌ Bad
def search(query: str) -> dict: ...            # 公开契约禁裸 dict
def get_recent() -> list | None: ...           # None 不应表示"空集合"
async def stream() -> tuple[list, list]: ...   # 同质字段应 dataclass
```

## 3. 错误规范

- **业务异常以 `*Error` 后缀**（**本项目约定**）：
  - 模块根目录定义 `<Module>Error(Exception)` 基类（便于上层 `except ModuleError`）。
  - 子异常 `class <Specific>Error(<Module>Error): ...`。
  - 例：`EvidenceError` → `EvidenceNotFoundError` / `EvidencePersistenceError`。
- **系统异常用原始**（不重命名/不重新继承）：
  - `ValueError` / `TypeError` / `KeyError` / `FileNotFoundError` / `IOError` /
    `PermissionError` 等 stdlib 异常**直接抛出**，不要包成 `MyValueError`。
  - 第三方包异常（`lancedb.LanceDBError`、`httpx.HTTPError`）也直接透传。
- **不要 `except Exception:` 全捕获**：最小捕获（`except SpecificError:`），
  必要时 `raise ... from e`（ruff 已禁用 `B904`，但本项目纪律**鼓励**
  `raise NewError(...) from e`，仅在 PR 中豁免）。
- **退出码语义**：CLI 顶层 catch `*Error` 后转 `sys.exit(<code>)`，避免 traceback
  噪声（沿用现状）。

```python
# ✅ Good
class StorageError(Exception):
    """Wiki 存储层错误基类。"""

class SchemaVersionMismatchError(StorageError):
    """schema.md 版本与 WikiPage 不兼容。"""

def load_wiki(paths: WikiPaths) -> WikiIndex:
    if not paths.index.exists():
        raise StorageError(f"index 不存在: {paths.index}")
    # ...
    try:
        return _parse_index(raw)
    except KeyError as e:
        raise SchemaVersionMismatchError(paths) from e

# ❌ Bad
class WikiStorageException(Exception): ...     # 后缀非 Error
class StorageError: ...                        # 漏 (Exception)
try:
    ...
except Exception:                              # 全捕获
    pass
raise StorageError("bad")                      # raise ... from e 缺失
```

## 4. 可空性（nullability）

- **`Optional[T]` 显式标注**（**本项目纪律**）：所有可空字段**必须**类型注解为
  `T | None`（PEP 604）或 `Optional[T]`，并提供合理的默认值。
- **禁止 `T | None` 隐式**（不允许通过 `if x is None` 反推字段是否可选）：
  - dataclass 字段用 `field(default=None)` + 类型注解 `T | None`。
  - 函数参数用 `x: T | None = None`。
- **不可空语义约束**：核心 ID（`page_id` / `task_id` / `project_id`）**禁止**
  `Optional`，必须非空字符串；缺失视为数据缺失，抛 `*NotFoundError`。
- **`Optional[list[T]]` vs `list[T]`**：
  - 默认用 `list[T]` + 空列表（无元素时）。
  - 仅在"该字段是否缺失"与"是否为空"是**两种业务状态**时，才用
    `Optional[list[T]]`（如 `references: list[str] | None`，缺失 = 未引用，
    空列表 = 显式空引用）。

```python
# ✅ Good
@dataclass
class KnowledgeObject:
    id: str                                       # 禁止 Optional
    title: str
    evidence_refs: list[str] = field(default_factory=list)        # 空 = 无
    decision_record: dict | None = None            # 缺失 = 未裁决（与空 dict 区分）

async def async_load_page(*, page_id: str) -> WikiPage:
    if not page_id:
        raise ValueError("page_id 不可为空")
    # ...

# ❌ Bad
@dataclass
class KnowledgeObject:
    id: str | None = None                         # 核心 ID 禁 Optional
    evidence_refs: Optional[list[str]]            # 默认场景不该用 Optional
    title: str                                    # 缺默认值（隐式 None）

async def async_load_page(page_id) -> WikiPage:  # 缺类型注解 + 缺 kw-only
    ...
```

## 5. 跨层契约（contracts/）

- **放置位置**：`src/kc/contracts/`（路线 v2.1+ 新增的领域契约层）。
- **每个契约一个文件**：`<entity>_contract.py`（如 `evidence.py`、`mode.py`），
  在 `src/kc/contracts/__init__.py` 中**集中 re-export**。
- **契约内容**：纯 dataclass + 协议（`Protocol`） + 错误类型，不含实现。
- **依赖方向**：`contracts/` **不依赖** `adapters/` / `services/` / `cli/` / `server/`；
  只允许依赖 stdlib + 内部 dataclass（递归依赖通过类型字符串 `if TYPE_CHECKING:`）。

```python
# src/kc/contracts/evidence.py
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.wiki.core import WikiPage

@dataclass(frozen=True)
class EvidenceRef:
    source_id: str
    span_start: int
    span_end: int
    quote: str

class EvidenceStore(Protocol):
    def persist(self, page_id: str, refs: list[EvidenceRef]) -> None: ...
    def retrieve(self, page_id: str) -> list[EvidenceRef]: ...

class EvidenceError(Exception): ...
class EvidenceNotFoundError(EvidenceError): ...
```

## 6. 反例速查

```python
# ❌ 位置参数爆炸
def build_prompt(role, content, model, temperature, max_tokens, stop, top_p): ...

# ❌ 裸 dict 出参
def get_config() -> dict: ...

# ❌ 异常缺 Error 后缀
class WikiStorageException(Exception): ...

# ❌ 隐式可空
async def async_load_page(page_id=None): ...

# ❌ Optional 误用
@dataclass
class Page:
    tags: Optional[list[str]]           # 应当 list[str] = field(default_factory=list)
```

## 7. Lint / 校验

- **ruff**（已配置）：`N803`（参数名小写）、`UP007`（建议 `T | None` 取代 `Optional[T]`）、
  `B904`（`raise ... from e`，本项目豁免但鼓励）等。
- **`mypy` 严格模式**（路线 v2.2+ 逐步开启）：通过类型注解强制 `Optional` 显式。
- **契约测试**：`tests/test_kc/test_contracts_<entity>.py` 验证 `dataclass`
  round-trip / 协议协议实现完整性（每个契约至少 1 个测试）。