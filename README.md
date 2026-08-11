# ruflo-kb

> 多 Agent 知识库平台 — 摄取 URL / 文件,通过 Collector → Analyzer → Generator 流水线生成结构化的 Wiki 页面,提供 hybrid(semantic + keyword / RRF)搜索。

[![Tests](https://img.shields.io/badge/tests-873%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-proprietary-red)]()

---

## 快速开始

### 1. 安装依赖

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  pip install -e ".[dev]"

# 大件本地 wheel(可选,避免 PyPI 拉取)
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  pip install docs/environment/wheels/pyarrow-25.0.0-cp314-cp314-win_amd64.whl \
                docs/environment/wheels/lancedb-0.27.1-cp39-abi3-win_amd64.whl

# 可选:联网搜索 / 文件监听
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  pip install tavily-python pypinyin
```

完整安装说明见 [`docs/environment/SETUP.md`](docs/environment/SETUP.md)。

### 2. 初始化项目

```bash
python -m src.cli project init ./my-kb
```

这会创建项目目录结构:

```
my-kb/
├── wiki/             # 生成的内容(sources/entities/concepts/synthesis)
├── raw/sources/     # 你放原始文档的地方
├── .llm-wiki/        # 项目配置(chats, settings.json)
└── .index/           # 向量索引(LanceDB)
```

### 3. 配置 LLM provider

```bash
# OpenAI
python -m src.cli llm-providers add openai openai --api-key $OPENAI_API_KEY
python -m src.cli llm-providers set-default openai

# OpenAI 兼容(国产模型如 MiniMax、Kimi、DeepSeek、GLM)
python -m src.cli llm-providers add minimax openai \
    --base-url "$MINIMAX_BASE_URL" --model "$MINIMAX_CHAT_MODEL"
python -m src.cli llm-providers set-default minimax

# 详见 docs/guides/adding-llm-provider.md
```

### 4. 启动 + 摄取

```bash
# 启动 HTTP API server
python -m src.cli serve --host 127.0.0.1 --port 8765

# 摄取文档(MD/PDF/DOCX/XLSX/URL)
PROJECT=$(python -m src.cli project list | awk '/my-kb/{print $1; exit}')
curl -X POST "http://127.0.0.1:8765/api/v1/projects/$PROJECT/ingest" \
  -H "Content-Type: application/json" \
  -d '{"source": "/path/to/document.md"}'
```

处理是异步的 — API 立即返回 `{status, taskId}`,Collector → Analyzer → Generator 在后台运行。

---

## 架构

### Wiki v2 数据模型

Wiki 是核心数据结构(取代旧的 `Notes/<task_id>.md` 布局)。

每页是 `WikiPage`(`src/wiki/core/types.py`),含:

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | str | kebab-case slug 或 UUID v7 |
| `title` | str | 显示标题 |
| `type` | PageType | `source` \| `entity` \| `concept` \| `synthesis` |
| `sources` | list[str] | 原始文件路径(`raw/sources/<file>`) |
| `relations` | list[Relation] | 17 种内置类型 + `x-*` 用户自定义 |
| `grade` | A/B/C | 源质量 |
| `processing_depth` | concept/memory | 处理深度 |
| `heat` | 0–100 | 衰减追踪器 |

完整规范见 [`docs/guides/wiki-spec.md`](docs/guides/wiki-spec.md)。

### 摄取流水线

```
collector:start → Collector → collector:done
  → Analyzer (LLM 抽取 AnalysisResult)
  → Generator (LLM 渲染 WikiPage 列表,遵循模板)
  → atomic: write_page + append_to_index + log_event
```

入口: `src/pipeline/pipeline.py:run_ingest()`。

### Wiki Page Templates (Plan 25)

每种 PageType 有一个**章节模板**,确保生成的页面有统一结构:

```
bundled/
├── concept.md       ## 定义 / ## 主要特点 / ## 例子 / ## 相关概念 / ## 参考来源
├── entity.md        ## 基本信息 / ## 简介 / ## 别名? / ## 相关引用
├── source.md        ## 来源元数据 / ## 摘要 / ## 关键观点 / ## 抽取的概念
└── synthesis.md     ## 对比维度 / ## 综述 / ## 涉及的概念 / ## 对比表 / ## 结论
```

模板格式 — HTML 注释标记 + 章节标题:

```markdown
<!-- wiki-template-version: 1.0.0 -->
<!-- wiki-template-type: concept -->

## 定义

<!-- slot:definition -->

## 别名

<!-- if:has_aliases -->           <!-- 可选段:条件块 -->

<!-- slot:aliases -->

<!-- /if:has_aliases -->

<!-- include:_base.md -->          <!-- 引用同目录片段 -->
```

三级优先级:`<project>/.wiki-templates/` > `~/.config/ruflo-kb/wiki-templates/` > `bundled/`。

管理命令:

```bash
python -m src.cli wiki-templates list          # 列出所有 PageType
python -m src.cli wiki-templates show concept # 查看模板内容
python -m src.cli wiki-templates edit concept # 复制 bundled → user/,打开编辑器
python -m src.cli wiki-templates status        # v3:查看 bundled 是否更新
python -m src.cli wiki-templates diff concept  # v3:对比 user vs bundled
python -m src.cli wiki-templates upgrade concept --if-unmodified  # v3:升级未改过的
```

详细设计: [`docs/superpowers/plans/2026-07-25-wiki-page-templates.md`](docs/superpowers/plans/2026-07-25-wiki-page-templates.md)

---

## CLI 命令

```bash
# 项目管理
python -m src.cli project init <path>          # 创建项目
python -m src.cli project list | current | info | select | import | forget

# LLM providers
python -m src.cli llm-providers list
python -m src.cli llm-providers add <name> <type> --base-url ... --model ...
python -m src.cli llm-providers set-default <name>

# Wiki 页面模板 (Plan 25)
python -m src.cli wiki-templates {list,show,edit,reset,status,diff,upgrade}

# 服务
python -m src.cli serve --host 127.0.0.1 --port 8765
python -m src.cli serve-stop
python -m src.cli serve-status

# 健康检查 / MCP / 深度研究
python -m src.cli health --project <id>
python -m src.cli mcp                # stdio MCP server(8 个 tools)
python -m src.cli research run ...   # 深度研究管线

# 其他
python -m src.cli relations {list,backlinks,neighbors,path,types,add-type}
python -m src.cli fields validate <page> --project <id>
python -m src.cli tags validate [--all] --project <id>
python -m src.cli heat {show,top,cold,decay,zombies,restore,archive}
python -m src.cli stubs {list,promote} --project <id>
python -m src.cli dedup auto [--threshold high] --project <id>
python -m src.cli lint [--cache-ttl N] [--no-cache] --project <id>
python -m src.cli schema {list,diff,upgrade,downgrade,backup}
```

---

## 项目布局

```
ruflo-kb/
├── src/
│   ├── cli.py                     # CLI 入口
│   ├── cli_ext/                   # 子命令模块
│   ├── pipeline/                  # Collector → Analyzer → Generator
│   │   ├── ingest.py              # run_ingest (原子写入)
│   │   ├── analyzer.py            # LLM 抽取
│   │   ├── generator.py           # LLM 渲染(模板注入)
│   │   └── wiki_rules_prompt.py   # 自动生成的 LLM 规则提示
│   ├── wiki/                      # Wiki v2 数据模型
│   │   ├── core/                  # types, paths, page, id_generator
│   │   ├── storage/               # page_writer, ensure, atomic_ctx
│   │   ├── features/              # relations, heat, lint, dedup, etc.
│   │   └── templates/             # Plan 25 模板系统
│   │       ├── types.py
│   │       ├── parser.py
│   │       ├── resolver.py
│   │       ├── state.py
│   │       └── bundled/{source,entity,concept,synthesis}.md
│   ├── server/                    # FastAPI app + lifespan
│   ├── llm/                       # LLM provider registry, OpenAI/MiniMax/etc.
│   ├── vector/                    # LanceDB 集成
│   ├── queue/                     # 异步摄取队列
│   ├── search/                    # hybrid(semantic + keyword / RRF)
│   └── events/                    # event_bus
├── tests/                         # 873 个测试
│   ├── test_wiki/                 # wiki 核心 + 模板测试
│   ├── test_pipeline/             # 流水线测试
│   ├── test_cli_ext/              # CLI 测试
│   └── ...
├── docs/
│   ├── guides/                    # wiki-spec, adding-llm-provider
│   ├── environment/SETUP.md       # 环境配置
│   └── superpowers/plans/         # 已完成的 plan 文档
├── pyproject.toml
└── README.md (this file)
```

---

## 开发

### 运行测试

```bash
# 全部
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib
# → 873 passed in ~60s

# 特定模块
PYTHONPATH=. python -m pytest tests/test_wiki/ -v

# 调试某个失败
PYTHONPATH=. python -m pytest tests/path/to/test.py::test_name -v --tb=long
```

### 关键约束

- **`PYTHONPATH=.` 是必需的**(`-e ".[dev]"` 安装会让 `src/` 可导入,但 pytest 默认不加入)
- **`--import-mode=importlib`** 避免同名 test 文件冲突
- **Windows 上必须剥离代理**(`env -u HTTP_PROXY ...`),否则连接超时

### 迁移规划

代码库正在从 `Novel-Knowledge-Base` 迁移过来。当前活跃 plan:
`docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md`。每个 plan 文件包含 tasks + TDD 工作流。

---

## 许可

Proprietary. 见 `LICENSE`(未包含)。

---

## 进一步阅读

- [`CLAUDE.md`](CLAUDE.md) — Claude 的项目指南
- [`docs/environment/SETUP.md`](docs/environment/SETUP.md) — 环境配置
- [`docs/guides/wiki-spec.md`](docs/guides/wiki-spec.md) — Wiki 规范
- [`docs/guides/adding-llm-provider.md`](docs/guides/adding-llm-provider.md) — 加 LLM provider
- [`docs/superpowers/plans/2026-07-25-wiki-page-templates.md`](docs/superpowers/plans/2026-07-25-wiki-page-templates.md) — 模板系统设计(Plan 25)
- [`docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md`](docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md) — NKB → ruflo-kb 迁移