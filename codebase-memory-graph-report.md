# Codebase Memory 图谱索引报告

- **项目名**：`llm-wiki`（手动指定，便于后续查询）
- **索引模式**：`full`（含 similarity / semantic 边）
- **仓库路径**：`C:\Users\HP\OneDrive\240 - 项目\LLM-Wiki`
- **索引状态**：`indexed`，`expected_nodes == nodes`、`skipped_count == 0`（无截断、无跳过）

---

## 1. 图谱规模（节点 / 边）

| 指标 | 数量 |
| --- | --- |
| **总节点数** | **5,329** |
| **总边数** | **25,326** |

---

## 2. 节点类型分布（11 类）

| 节点标签 | 数量 | 说明 |
| --- | --- | --- |
| Function | 1,588 | 函数 |
| Section | 1,278 | 文件分段（按逻辑区块切分） |
| **File** | **596** | 被索引的源文件 |
| Module | 588 | 模块 |
| Method | 470 | 类方法 |
| Variable | 391 | 变量 |
| Class | 249 | 类 |
| Folder | 87 | 目录 |
| Route | 65 | HTTP 路由 |
| Decorator | 15 | 装饰器 |
| Branch | 1 | Git 分支 |
| Project | 1 | 项目根 |

> 校验：1,588+1,278+596+588+470+391+249+87+65+15+1+1 = **5,329** ✓

---

## 3. 边类型分布（19 类）

| 边类型 | 数量 | 说明 |
| --- | --- | --- |
| DEFINES | 10,037 | 文件/类 定义 元素 |
| CALLS | 4,580 | 函数调用 |
| USAGE | 4,463 | 符号使用 |
| TESTS | 2,220 | 测试关系 |
| IMPORTS | 1,407 | 导入 |
| WRITES | 744 | 写操作 |
| CONTAINS_FILE | 596 | 目录包含文件 |
| DEFINES_METHOD | 465 | 类定义方法 |
| DECORATES | 311 | 装饰 |
| SEMANTICALLY_RELATED | 168 | 语义相关（full 模式） |
| CONTAINS_FOLDER | 84 | 目录嵌套 |
| SIMILAR_TO | 75 | 代码相似（full 模式） |
| HANDLES | 52 | 路由处理 |
| FILE_CHANGES_WITH | 31 | 协同变更 |
| HTTP_CALLS | 29 | HTTP 调用 |
| RAISES | 28 | 抛出异常 |
| INHERITS | 25 | 继承 |
| THROWS | 10 | 抛出 |
| HAS_BRANCH | 1 | 分支归属 |

> 校验：以上求和 = **25,326** ✓

---

## 4. 文件覆盖情况

- **已索引文件（File 节点）**：**596 个**，**0 个被跳过**（indexer 自报 `skipped_count=0`）。
- **被排除目录**：**88 个**（索引器自动忽略缓存/元数据/副本目录），主要含：
  - `.git`、`.workbuddy`、`.pytest_cache`、`.claude`（含 git worktrees 副本）、`.index`、`.llm-wiki`、`.memory`、`.obsidian`
  - 全部 `__pycache__`（根 + `tests/*` 下各包）+ 编译产物 `.pyc`
- **语言构成**（已识别代码文件 470 个）：

  | 语言 | 文件数 |
  | --- | --- |
  | Python | 464 |
  | Bash | 2 |
  | TOML | 1 |
  | JavaScript | 1 |
  | HTML | 1 |
  | CSS | 1 |

  > 剩余 **126 个文件**为文档/数据类（Markdown、CSV、TXT、JSON、log、`.whl`、`.bat`/`.sh` 等），未分配编程语言标签但已纳入图谱。

- **扫描到的目录结构**：`src/`（30 个子包）、`tests/`（33 个测试包）、`scripts/`、`docs/`、`knowledge/`、`web/`，以及根级 `CLAUDE.md` / `README.md` / `pyproject.toml` 等。
- **HTTP 路由**：检出 **65 条**（FastAPI 风格），如 `/projects`、`/providers`、`/ingest`、`/search`、`/wiki/graph`、`/lint`、`/schema`、`/agent-cli/*`。
- **入口点**：**12 个** `main` 函数（CLI、MCP server、各 batch 脚本）。
- **Leiden 社区聚类**：**13 个**，几乎全部由 `test_*` 包主导（测试代码构成事实上的最大模块簇）。

### 节点数 Top 包（package fan 指标）

| 包 | 节点数 |
| --- | --- |
| test_wiki | 184 |
| wiki | 155 |
| test_cli_ext | 146 |
| test_queue | 142 |
| test_llm | 133 |
| cli_ext | 128 |
| test_pipeline | 108 |
| test_server | 75 |
| llm | 74 |
| queue | 67 |

---

## 5. 复用提示

- 后续查询本项目图谱，统一用 `project = "llm-wiki"`。
- 可用能力：`get_architecture`（架构/分层/热点）、`search_graph`（BM25 / 正则 / 向量语义检索）、`get_code_snippet`、`trace_path`、`query_graph`。
- 跨仓库：可用 `index_repository` 的 `cross-repo-intelligence` 模式建立 `CROSS_HTTP_CALLS` / `CROSS_ASYNC_CALLS` 边。

> 说明：本会话 Bash / PowerShell 执行环境异常（所有命令均返回空输出 + exit 1），故未在文件系统层面二次核验总数；上述数据均来自索引器与图谱 schema 的自报结果，且 `expected_nodes==nodes`、`skipped_count==0`，可信度高。
