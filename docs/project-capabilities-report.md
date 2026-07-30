# ruflo-kb 项目功能清单（基于 codebase-memory 图谱）

> 索引方式：`codebase-memory-MCP` 全量索引（`full` 模式），项目名 `llm-wiki`
> 索引规模：**11,051 节点 / 32,652 边**，`skipped_count=0`（无截断，覆盖完整）
> 语言构成：Python 481 文件、Bash 2、TOML 1、JavaScript/HTML/CSS 各 1；另有 1,661 个 `knowledge/*.md` 数据文件被纳入图谱但未标语言
> 说明：图谱中 68 条 `Route` 里有一部分是测试夹具（`does-not-exist`/`proj-1`/`x`/`u`）和字符串字面量，下表只列**真实对外接口**。

---

## 一、这个项目是什么

一个**本地 LLM 知识库 / 自动化 Wiki 生成器**（项目代号 `ruflo-kb`）。核心链路是：

```
原始素材(raw/) → Collector(采集) → Analyzer(分析) → Generator(生成) → wiki/*.md(概念/实体/来源/综述)
                                                                      ↓
                                                          Archive(切块+向量化) → LanceDB(语义库)
                                                                      ↓
                                          支持：语义/关键词检索、对话、知识图谱浏览、WebUI
```

它把零散的素材（txt/md/pdf）自动整理成带 frontmatter、互相 wikilink 的结构化知识笔记，并建立可语义检索的向量库，最终通过 WebUI / API / CLI / MCP 四种方式对外提供服务。

---

## 二、核心能力（按功能域）

### 1. 知识摄取与生成（Ingest Pipeline）
- **流水线**：Collector 采集原始源 → Analyzer 抽取结构 → Generator 用 LLM 生成 wiki 笔记（分 `concepts/entities/sources/synthesis` 四类）。
- **异步任务队列**：`queue` 层负责入队/状态机/熔断（`CircuitBreaker`）保护，避免 LLM 超时雪崩（见 `server.err.log` 中 MiniMax `ReadTimeout` 触发熔断的记录）。
- **批量/运维脚本**（独立入口点）：
  - `scripts/batch_build.py` — 构建 + 批量 archive（切块向量化）
  - `scripts/batch_ingest.py` / `_batch_ingest.py` — 批量摄取
  - `scripts/ingest_novel_wiki_d.py` / `ingest_novel_wiki_manual.py` — 小说类 wiki 摄取
  - `scripts/quality_check_wiki.py` — 质量检查
  - `scripts/migrate_pinyin_to_cjk_aliases.py` / `migrate_slug_aliases.py` — 别名迁移
  - `scripts/sync_wiki_spec.py` / `setup_git_hooks.py` — 规范同步 / git 钩子

### 2. 检索与浏览（Search & Retrieval）
- **混合检索**：`searcher` 层提供语义（LanceDB 向量）+ 关键词混合检索，结果为 300 字符片段。
- **文件浏览**：列出 wiki 文件、读取文件内容、浏览原始源文件。
- **知识图谱**：导出 wiki 的节点/边关系（`wiki/graph`），供图谱视图渲染。

### 3. 对话 / 本地 Agent
- **项目 KB 对话**：基于当前项目知识库问答（非流式，UI 显示「思考中」）。
- **本地 Agent CLI**：`/agent-cli/status` + `/agent-cli/chat` 提供独立的本地智能体会话。

### 4. 知识质量管理
- **Lint**：检查 wiki 页面健康度（断链、schema 合规等）。
- **Schema 校验**：验证页面 frontmatter 是否符合 v2 规范。
- **人工 Review 队列**：`reviews` 端点支持列出与 Patch 修正（人工介入闭环）。

### 5. 多 LLM Provider 管理
- 支持 OpenAI / Anthropic / MiniMax / Ollama / Kimi / DeepSeek / GLM 等厂商接入。
- 能力：注册（add）、列出（list）、设默认（set-default）、连通性测试（test）、删除（remove）。
- 注意：`src/__init__.py` 不自动 `load_dotenv()`，国产 provider 必须在注册时显式带 `--api-key`，否则不会从环境变量取 key。

### 6. WebUI（单页应用，7 个视图）
- **搜索 / 浏览 / 摄取 / 对话 / 图谱 / 状态 / 设置**（对应 `web/app.js` 的视图切换）。
- 静态资源由 FastAPI `StaticFiles` 挂在 `/`（含 `index.html`/`style.css`/`app.js`），`marked` 走 CDN。

### 7. 服务与运维
- **FastAPI 服务**：`/health` 健康检查、`/metrics` 输出 Prometheus 指标。
- **CLI 管理**：见下文。
- **MCP Server**：`src/mcp_server/main.py` 提供 stdio MCP 服务，供外部 Agent 集成调用。

---

## 三、对外 API 端点一览（真实接口）

**项目管理**
| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/projects` | 列出项目 |
| POST | `/projects` | 新建项目 |
| GET | `/projects/current` | 当前项目 |
| GET | `/projects/{id}` | 项目信息 |
| DELETE | `/projects/{id}` | 删除项目 |
| POST | `/projects/{id}/select` | 设为当前项目 |
| GET/POST | `/api/v1/projects` | v1 别名（列表/新建） |

**知识摄取**
| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/projects/{id}/ingest` | 入队摄取原始源（仅排队，HTTP 200） |
| GET | `/projects/{id}/ingest/status/{task_id}` | 单任务状态 |
| GET | `/projects/{id}/ingest/tasks` | 任务列表 |

**检索与浏览**
| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/projects/{id}/search` | 语义/关键词/混合检索 |
| GET | `/projects/{id}/files` | 列出 wiki 文件 |
| GET | `/projects/{id}/files/content` | 读取文件内容 |
| GET | `/projects/{id}/raw-files` | 列出原始源 |
| GET | `/projects/{id}/wiki/graph` | 知识图谱 |

**质量管理**
| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/projects/{id}/lint` | Lint wiki |
| GET | `/projects/{id}/schema` | Schema 校验 |
| GET | `/projects/{id}/reviews` | 列出 Review |
| PATCH | `/projects/{id}/reviews/{review_id}` | 修正 Review |

**对话 / Agent**
| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/projects/{id}/chat` | 项目 KB 对话 |
| GET | `/agent-cli/status` | 本地 Agent 状态 |
| POST | `/agent-cli/chat` | 本地 Agent 对话 |

**LLM Provider**
| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/providers` | 列出 provider |
| POST | `/providers` | 注册 provider |
| DELETE | `/providers/{name}` | 删除 provider |
| POST | `/providers/set-default` | 设默认 |
| POST | `/providers/test` | 连通性测试 |

**系统 / 静态**
| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |
| GET/ANY | `/` | WebUI 静态页 |

> 另有 `/api/v1/agent-cli/*`、`/api/v1/projects/{id}/chat` 等 v1 别名路由，handler 映射到同一逻辑。

---

## 四、命令行（CLI）能做什么

入口：`python -m src.cli`（主函数 346 行 argparse，子命令分组）。已确认命令组：

- **`project`**：`init` / `list` / `info` / `current` / `select` / `import` / `forget` / `rename` / `discover`
- **`schema`**：`list` / `diff` / `upgrade`（schema 迁移）
- **`serve`**：启动 API + WebUI（默认 8765，start.bat 用 19828）
- **`ingest`** / **`search`**：命令行直接摄取与检索
- **`providers`**（来自 `llm_providers_cmd`）：`add` / `list` / `set-default` / `test` / `remove`
- **`fields` / `tags`**（来自 `fields_cmd`）：校验 wiki 字段与受控 tag 命名空间
- **`lint`** / **`reviews`**：质量检查与人工修正
- **`rebuild`**（`cmd_wiki_rebuild_from_raws`）：从 raws 重建 wiki
- **`mcp`**：启动 stdio MCP 服务（`_run_mcp` → `src.mcp_server.main`）

---

## 五、架构分层（来自 Leiden 聚类与 layers 分析）

核心层（`core`，高 fan-in）：
- **`wiki`**（fan-in 481，最高）—— 笔记存储/写入/模板/校验的核心
- **`pipeline`**（fan-in 100）—— 摄取→分析→生成流水线
- **`queue`**（fan-in 153）—— 异步任务队列与熔断
- **`llm`**（fan-in 173）—— 多 provider 抽象与调用
- **`searcher`**（fan-in 38）—— 检索引擎
- **`services` / `project` / `utils`** —— 业务服务、项目管理、通用工具

内部/入口层：`cli`、`mcp_server`、`scripts/*`、各 `docs/superpowers` 工具。

WebUI 聚类（id 166，内聚度 0.99）独立成团：`api` / `escapeHtml` / `renderDropdown` / `renderResults` / `loadReader` 等，对应 `web/` 单页应用。

---

## 六、一句话总结

**ruflo-kb 是一个「把素材自动变成可检索知识库」的本地 LLM 工具**：能摄取并生成结构化 wiki、建向量库做语义检索、提供对话与知识图谱浏览，并通过 WebUI / REST API / CLI / MCP 四种接口对外服务，同时内置任务队列、熔断、lint、schema 校验、人工 review 与多 LLM provider 管理能力。
