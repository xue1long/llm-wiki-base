# 命名规范（Naming Conventions）

> 适用范围：`src/`、`tests/`、`scripts/` 下所有 Python 源码，以及项目内
> Markdown 文档、CLI 命令、数据库列名（无 ORM，沿用约定）。
>
> 本规范与 `docs/architecture/naming.md`（KC 领域词汇）**互补**：
> - 本文管**代码层标识符**（模块/类/函数/字段/列名）。
> - `docs/architecture/naming.md` 管**业务词汇表**（KO / KU / Evidence / Provenance 等）。

## 1. 模块名（module）

- **单复数规则**：集合/容器含义用复数（`tests/`、`adapters/`），单一职责用单数（`wiki.py`、`schema_registry.py`）。
- **缩写字典**（在项目内允许且大小写**严格**）：
  - 全部大写：`URL`、`URI`、`HTTP`、`JSON`、`HTML`、`XML`、`YAML`、`SQL`、`LLM`、`PDF`、`MD`、`CLI`、`MCP`、`RRF`、`CJK`、`UUID`、`WIKI`、`KO`、`KU`、`KC`、`CID`、`TTL`、`ID`、`API`、`SDK`、`SDK`。
  - 全部小写：`kb`、`ip`、`os`、`io`、`db`、`cwd`、`uri` 仅在变量名（非类名）中允许。
  - **反例**：`Url`、`Http`、`Json`、`Pdf`、`Cli`、`Kc`、`Ko`、`Ku` —— 一律按上述字典纠正。
- **包/模块路径**：snake_case，与文件名一致（`src/wiki/storage/`、`src/wiki/features/`）。

```python
# ✅ Good
from src.wiki.storage import ensure_wiki  # 模块 snake_case
from src.services.ingest import enqueue_source

# ❌ Bad
from src.wiki.storage import EnsureWiki   # 模块名 PascalCase（违反 snake_case）
from src.wiki.storage import ensureURL    # 缩写 URL 没全大写
```

## 2. 文件名（file）

- **snake_case + 后缀**：Python 文件一律 snake_case（`wiki_paths.py`、`kc_compiler.py`）。
- **例外**（沿用现状）：README / LICENSE / AGENTS.md / CLAUDE.md / CONTRIBUTING.md 等社区约定大写文件名。
- **测试文件**：`test_<module>.py` / `test_<package>/test_<file>.py`，镜像 `src/` 一级（详见 `directory.md`）。
- **文档**：kebab-case 推荐（`metric_threshold_change_adr.md`），但 snake_case 也允许。

```python
# 文件: src/kc/contracts/evidence.py
# ✅ Good
class EvidenceRef: ...
class EvidenceNotFoundError(Exception): ...

# ❌ Bad
class evidence_ref: ...            # 应当 PascalCase
class evidenceNotFoundError: ...    # 缩写 NF 不规范
```

## 3. 类名（class）

- **PascalCase**：每个单词首字母大写，不使用下划线。
- **异常类**以 `Error` 结尾（**本项目约定**）：业务异常一律 `<Domain>Error`（如
  `EvidenceNotFoundError`、`SchemaValidationError`、`UnsupportedFileTypeError`）；
  **不**重新继承 `Exception` 后不加 `Error` 后缀。
- **抽象基类**以 `ABC` 显式标注；协议类（`Protocol`）加 `Proto` 后缀（约定俗成）。
- **dataclass** 与类同规则（**不用** dataclass 命名后缀 `DC`/`DTO`/`Bean`）。

```python
# ✅ Good
class WikiPage: ...
class EvidenceNotFoundError(Exception): ...
class StorageBackend(ABC): ...

# ❌ Bad
class wiki_page: ...                       # 应 PascalCase
class EvidenceNotFound(Exception): ...    # 缺 Error 后缀
class StorageBackendDC: ...                # 累赘 DC 后缀
```

## 4. 函数名（function）

- **动词开头**：动作语义清晰（`enqueue_source`、`resolve_project`、`build_index`）。
- **异步加 `async_` 前缀**（**本项目约定**，区别于 stdlib `async` 关键字）：
  - 函数签名 `async def foo()` → 模块内/对外调用一律使用 `await async_foo()`。
  - 同步包装器可保留原名（如 `aclose_all` 是 sync、`async_aclose` 是 async）。
- **返回 bool 的谓词**用 `is_/has_/should_/can_` 前缀（`is_immutable`、`has_evidence`）。
- **私有函数**前缀 `_`（`_resolve_ctx_only`）。

```python
# ✅ Good
async def async_load_index(force: bool = False) -> WikiIndex: ...
def is_zombie(page: WikiPage) -> bool: ...
def _resolve_ctx(proj_arg: str) -> tuple[ProjectContext, WikiPaths]: ...

# ❌ Bad
async def load_index(force=False): ...    # async 函数缺 async_ 前缀（违反本约定）
def Zombie(page): ...                    # 谓词缺 is_/has_ 前缀 + PascalCase 命名
```

## 5. 字段名（field，dataclass / 模型属性）

- **snake_case**：所有 dataclass / pydantic 字段使用 snake_case。
- **禁止引入同义字段**（**本项目纪律**）：同概念**只允许一个字段**；如出现
  `quote` 与 `text` 并存、或 `confidence` 与 `score` 并存，立即合并并写迁移。
- **可选字段**显式 `Optional[T]` 标注默认值；`None` 默认值必须与字段语义一致。
- **私有字段**前缀 `_`（`_ko_extra`）。

```python
# ✅ Good
@dataclass
class KnowledgeCandidate:
    claim_text: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence_score: float = 0.0

# ❌ Bad
@dataclass
class KnowledgeCandidate:
    quote: str                # 与 evidence_text 同义 → 必须合并
    text: str                 # 同义字段
    confidence: float         # 与 confidence_score 同义 → 必须合并
    score: float              # 同义字段
```

## 6. 数据库列名（column）

- **snake_case**（沿用现状；项目无 ORM，使用原生 SQL/JSON 序列化）。
- **主键**统一 `id`（字符串），**外键**`<entity>_id`（如 `page_id`、`source_id`）。
- **时间戳列**统一 Unix 毫秒整数，列名 `<verb>_at`（`created_at` / `updated_at` / `last_used_at`）。
- **布尔列**用 `is_/has_/should_` 前缀（`is_immutable`、`is_zombie`）。

```sql
-- ✅ Good (LanceDB / DuckDB / SQLite 兼容)
CREATE TABLE wiki_page (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    is_immutable BOOLEAN DEFAULT 0,
    created_at INTEGER NOT NULL,   -- unix ms
    last_used_at INTEGER DEFAULT 0
);

-- ❌ Bad
CREATE TABLE wiki_page (
    ID TEXT PRIMARY KEY,           -- 列名应 snake_case
    Title TEXT,                    -- 应 title
    immutable BOOLEAN,             -- 应 is_immutable
    createdAt INTEGER,             -- 应 created_at
);
```

## 7. 反例汇总速查

| 类型 | ✅ 正例 | ❌ 反例 |
|---|---|---|
| 模块 | `wiki_paths.py` | `WikiPaths.py`、`ensureURL.py` |
| 类 | `WikiPage`、`EvidenceError` | `wiki_page`、`EvidenceNotFound` |
| 异常 | `SchemaValidationError` | `SchemaValidation`、`InvalidSchema` |
| 函数（async） | `async def async_load_index()` | `async def load_index()` |
| 谓词 | `is_zombie(page)` | `zombie(page)`、`IsZombie(page)` |
| 字段 | `evidence_refs: list[str]` | `evidence_refs: List[str]`、混用 `quote`/`text` |
| 列名 | `created_at INTEGER` | `createdAt`、`Created_At` |
| 缩写 | `URL`、`HTTP`、`LLM`、`KO` | `Url`、`Http`、`Llm`、`Ko` |

## 8. Lint 可执行性

- **`ruff`**（已在 `pyproject.toml` 配置）：
  - `N801`（类名 PascalCase）、`N802`（函数名 snake_case）、`N803`（参数名 snake_case）、`N806`（变量名小写）、`N815`（`mixedCase` 不出现在类属性）、`N818`（异常以 `Error` 结尾）已可被 `select = ["N"]` 启用；
  - 本约定建议在后续 plan（F-2 / L-2）补全 ruff `select` 列表，但本规范文档**先行定稿**。
- **字段去重**：当前无 lint 规则强制；通过 code review + 模板代码块示例（§5）约束。
- **缩写大小写**：依靠 §1 缩写字典 + review checklist（无现成 ruff 规则）。