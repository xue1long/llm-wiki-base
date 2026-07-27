# ruflo-kb 代码库图谱索引报告

- **生成时间**：2026-07-27 12:14 (GMT+8)
- **索引工具**：codebase-memory MCP · `index_repository` (mode = `full`)
- **项目名**：`D-5-Project-2026-7-27-ruflo-kb`
- **仓库路径**：`D:\5-Project\2026-7-27\ruflo-kb`
- **索引状态**：`indexed` ✅（expected == actual，无截断；skipped_count = 0）

> 说明：计数取自 `get_graph_schema` / `get_architecture`（`codebase-memory` 的 Cypher 聚合不可靠，官方推荐这两个接口作为权威来源）。

---

## 一、总体规模

| 指标 | 数量 |
|---|---|
| 节点总数 (total_nodes) | **5,060** |
| 边总数 (total_edges) | **24,618** |
| 预期节点 / 预期边 | 5,060 / 24,618（全部达成） |
| 排除目录数 | 84（`.git` `.workbuddy` `__pycache__` `.pytest_cache` `.index` 等） |
| 被跳过文件 | 0 |

---

## 二、节点类型分布（按数量降序）

| 节点 Label | 数量 | 占比 |
|---|---:|---:|
| Function | 1,555 | 30.7% |
| Section | 1,159 | 22.9% |
| File | 558 | 11.0% |
| Module | 550 | 10.9% |
| Method | 464 | 9.2% |
| Variable | 374 | 7.4% |
| Class | 245 | 4.8% |
| Folder | 87 | 1.7% |
| Route | 53 | 1.0% |
| Decorator | 13 | 0.3% |
| Branch | 1 | 0.02% |
| Project | 1 | 0.02% |
| **合计** | **5,060** | 100% |

---

## 三、边类型分布（按数量降序）

| 边 Type | 数量 | 说明 |
|---|---:|---|
| DEFINES | 9,760 | 容器定义成员（文件/模块/类→函数等） |
| CALLS | 4,435 | 函数/方法调用（含跨文件 LSP 解析） |
| USAGE | 4,366 | 符号使用 |
| TESTS | 2,214 | 测试与被测目标关联 |
| IMPORTS | 1,394 | 导入关系 |
| WRITES | 715 | 写操作 |
| CONTAINS_FILE | 558 | 文件夹包含文件 |
| DEFINES_METHOD | 459 | 类定义方法 |
| DECORATES | 301 | 装饰器作用 |
| SEMANTICALLY_RELATED | 125 | 语义相关（full 模式额外边） |
| CONTAINS_FOLDER | 83 | 文件夹嵌套 |
| SIMILAR_TO | 73 | 结构相似（Jaccard） |
| FILE_CHANGES_WITH | 31 | 共修改耦合 |
| RAISES | 28 | 抛异常 |
| INHERITS | 25 | 继承 |
| HTTP_CALLS | 23 | HTTP 调用 |
| HANDLES | 18 | 处理器绑定 |
| THROWS | 9 | throw 语句 |
| HAS_BRANCH | 1 | git 分支 |
| **合计** | **24,618** | |

---

## 四、文件覆盖情况

- **已索引 File 节点**：**558** 个
- **按语言分布**：

| 语言 | 文件数 |
|---|---:|
| Python | 459 |
| Bash | 2 |
| TOML | 1 |
| JavaScript | 1 |
| HTML | 1 |
| CSS | 1 |
| **已识别语言小计** | **465** |
| 其余（Markdown / 文档 / 其他非语言文件） | **~93** |

- **覆盖率**：索引器报告 `expected_nodes == nodes` 且 `skipped_count = 0`，即全部可解析文件均被纳入，无遗漏或截断。
- **被排除目录**（84 个，部分因显示截断）：`__pycache__`、`.pytest_cache`、`.git`、`.workbuddy`、`.index`、`.llm-wiki`、`.memory`、`.obsidian`、`.claude` 等——编译产物（`*.pyc`）、依赖、VCS 与本地配置均未计入。

---

## 五、架构快照（辅助信息）

### 语言
Python 459 · Bash 2 · TOML 1 · JS 1 · HTML 1 · CSS 1

### 核心包（按节点数 top）
test_wiki(184) · wiki(154) · test_cli_ext(146) · test_queue(142) · test_llm(133) · cli_ext(128) · test_pipeline(108) · test_server(75) · llm(74) · queue(63) · pipeline(58) · test_searcher(56) · test_lib(51) · schemas(48) · project(41)

### 入口点（entry_points，部分）
- `src/cli.py::main`（CLI 主入口）
- `src/mcp_server/main.py::main`（MCP 服务入口）
- `scripts/batch_build.py::main`、`scripts/batch_ingest.py::main`、`scripts/ingest_novel_wiki_manual.py::main` 等脚本入口

### HTTP 路由（53 条 Route 节点，节选）
- `POST /projects/{project_id}/ingest`、`GET /projects/{project_id}/ingest/status/{task_id}`
- `POST /projects/{project_id}/search`、`POST /projects/{project_id}/chat`
- `GET /projects/{project_id}/wiki/graph`、`GET /health`
- 共 53 条路由被识别（含 `/api/v1/projects` 系列）

### 热点函数（fan_in 最高）
- `builtins.len` (177) · `builtins.list.append` (152) · `src/wiki/storage/ensure.ensure_knowledge_base` (118) · `builtins.print` (103) · `src/wiki/features/lint_cache.get` (74) · `src/wiki/storage/page_writer.write_page` (56) · `builtins.dict.get` (54) · `IdempotencyCache.clear` (27) · `src/wiki/templates/parser.parse` (26)

### 社区聚类（Leiden，节选）
共 12 个高内聚簇，标签多为 `tests`， cohesion 0.44–0.80，核心绑定边皆为 `CALLS`；最大簇 members≈205，典型节点 `str/lower/upsert/ProjectRegistryEntry/by_id`。

---

## 六、结论

- 图谱已完整生成：**5,060 节点 / 24,618 边**，覆盖 **558 个文件**，零跳过、零截断。
- 项目是 Python 为主体的知识库系统（ruflo-kb）：核心域为 `pipeline`（摄取流水线）、`wiki`（笔记存储/检索）、`llm`（模型适配）、`queue`（任务队列）、`searcher`（混合检索）、`schemas`（版本迁移）。
- 测试代码占比很高（tests 相关包与簇占主导），与仓库中 `tests/`（238 个 .py）规模一致。
- 可通过 `query_graph` / `search_graph` / `trace_path` 进一步按符号、调用链、跨文件依赖做精确查询。
