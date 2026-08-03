# ruflo-kb 约束文档（Constraints）

> Version: v1.0 | 2026-08-03
> 用途：给开发者 / 接手者的**单一约束入口**，覆盖三类约束——编码规范、禁用技术栈、输出格式要求。
> 权威来源：本文件是对 `CLAUDE.md`、`docs/guides/wiki-spec.md`、`pyproject.toml`、`src/wiki/features/tag_namespace.py` 的提炼；当本文件与上游冲突时，**以 `CLAUDE.md` 等原始文件为准**，并请回提本文件修正。

---

## 0. 文档权威层级

| 层级 | 文件 | 约束性质 |
|------|------|----------|
| 最高 | `CLAUDE.md` | 行为准则 + 工程硬规则（强制） |
| 高 | `docs/guides/wiki-spec.md` | 生成物（Wiki 页面）输出格式（强制） |
| 高 | `pyproject.toml`（`[tool.ruff]` / `[tool.mypy]`） | Lint / 类型 / 测试配置（强制） |
| 中 | `src/wiki/features/tag_namespace.py`（`TAG_PREFIXES` / `TAG_VALUES` / `MANDATORY_PAIRS`） | 受控标签命名空间（强制值域） |
| 本文件 | `docs/CONSTRAINTS.md` | 上述内容的聚合索引 + 禁用清单推导 |

---

## 1. 编码规范（Coding Standards）

### 1.1 行为准则（CLAUDE.md:350-414，强制性）

四大原则，违反即视为不合格代码：

**① 想清楚再写（Think Before Coding）** — `CLAUDE.md:356`
- 不明确假设时**先说出来**，不要默默选一个。
- 多种解读并存时**列出来**，不要静默拍板。
- 有更简单方案时**说出来**，该反驳就反驳。
- 不清楚就停下，点名困惑之处并提问。

**② 极简优先（Simplicity First）** — `CLAUDE.md:366`
- 不做需求之外的功能。
- 不为单次使用写抽象层。
- 不预置未被要求的"灵活性 / 可配置性"。
- 不为不可能发生的场景写错误处理。
- 写了 200 行却能用 50 行写完 → 重写。
- 自检："资深工程师会觉得这过度复杂吗？"是 → 简化。

**③ 外科手术式改动（Surgical Changes）** — `CLAUDE.md:376`
- 只动必须动的；不顺手改相邻的代码 / 注释 / 格式。
- 不重构没坏的东西；匹配现有风格（即便你有不同的写法）。
- 发现无关死代码 → **提一句，但不要删**。
- 自己改动产生的孤儿（未用 import / 变量 / 函数）要清掉；** preexisting 死代码未经要求不删**。
- 验收标准：每一行改动都能直接追溯到用户需求。

**④ 目标驱动执行（Goal-Driven Execution）** — `CLAUDE.md:392`
- 把任务转成可验证目标："加校验"→"先写非法输入的测试，再让它通过"。
- 多步任务先给简要计划：`1. [步骤] → verify: [检查点]`。
- 成功标准要硬；模糊标准（"让它跑起来"）会不断返工。

### 1.2 工程硬规则（散落于 CLAUDE.md，强制）

| 规则 | 定位 | 要求 |
|------|------|------|
| WikiPage 加字段 | `CLAUDE.md:307` | 必须**同时**改 `to_frontmatter_dict()` 和 `from_dict()`，否则往返损坏 |
| 原子写 | `CLAUDE.md:308` | 多步原子操作（级联删 / 导入导出）必须走 `safe_write` + `DELETE_SENTINEL`，不能用 `os.unlink` 直接删 |
| 旧模块路径失效 | `CLAUDE.md:346` | `from src.wiki.ensure import X` 等旧路径**不再别名**；必须用分层路径（`src.wiki.core.paths` / `src.wiki.storage.ensure` / `src.wiki.features.relations` …） |
| 事件处理器注册 | `CLAUDE.md:205` | 处理器在 import 时通过 `event_bus.on(name, handler)` 注册；EventBus 是单例 |
| Embedding provider | `CLAUDE.md:205` 区 | 进程级单例，勿重复构造 |
| Test 目录镜像 | `CLAUDE.md:227` | `tests/test_X/` 镜像 `src/` 一层；新测试目录要从现有 `conftest.py` 复制 |
| TDD 工作流 | `CLAUDE.md:258` | 每 task 先写测试（红）→ 实现（绿）→ 提交 |
| 提交粒度 | `CLAUDE.md:258` | 一个 task 一个 commit；前缀 `feat(scope):` / `fix(scope):` / `chore:` / `refactor:` |

### 1.3 Lint / 类型 / 测试配置（`pyproject.toml`，强制）

> ⚠️ 注意：CLAUDE.md:79 曾写"无 ruff.toml / mypy.ini 配置"，**实际配置写在 `pyproject.toml`** 里（无独立 `.toml/.ini` 文件）。以 pyproject 为准。

- **Ruff**（`[tool.ruff]` `pyproject.toml:36`）：`target-version = "py311"`；选中规则 `F / E / W / B / C4`；忽略 `E501, B904, B905, B028, E402, B007, E741`（多数因历史代码普遍性，待增量启用）。
- **Mypy**（`[tool.mypy]`）：`strict = false`。
- **Pytest**（`[tool.pytest.ini_options]`）：`asyncio_mode = "auto"`（无需逐测试加 `@pytest.mark.asyncio`）。
- 运行：`PYTHONPATH=. pytest --import-mode=importlib`（避免同名测试文件冲突）。
- **配置位置约束**：lint / format / type 配置**只进 `pyproject.toml`**，不另建 `.ruff.toml` / `mypy.ini` / `.flake8`。

### 1.4 禁止的编码反模式

| 反模式 | 约束依据 |
|--------|----------|
| 静默吞异常（silent swallow） | 历史审计已修正 `hybrid_search` 等，必须分类日志 |
| 跨项目数据泄漏 | 向量存储按 project 隔离（CLAUDE.md 清理系列） |
| `os.unlink` 直接删（级联场景） | 必须用 `DELETE_SENTINEL`（CLAUDE.md:308） |
| 旧 `src.wiki.<old>` 导入 | 已无 sys.modules shim，必须 grep 归零 |
| 硬编码提示词里的配对规则 4 处副本 | 技术债务 #11；应配置化到单一来源 |

---

## 2. 禁用 / 受限技术栈（Forbidden / Restricted）

> 项目**没有专门的 `FORBIDDEN.md` 黑名单**。以下"禁用项"是从 CLAUDE.md 的 Simplicity First 准则 + 实际轻依赖中**推导的事实清单**，具有同等约束力。

### 2.1 明确禁止引入

| 禁用方向 | 事实依据 |
|----------|----------|
| 重型 Web 框架（Django / Flask 全家桶 / 全功能 REST 框架） | HTTP 层只用 **FastAPI + uvicorn**，且 `routes/` 是 thin adapter（`CLAUDE.md` 架构描述） |
| 重型前端框架（React / Vue / Angular / Svelte 等） | `web/` 是**纯静态** `index.html + js + style.css`，零构建步骤 |
| 强制关系型数据库 | 默认**零 DB**；Markdown 文件为真相源，LanceDB 为派生向量索引；PostgreSQL 仅是 `storage/` 已预留的**可选**后端 |
| 容器 / 编排 / 外部服务强依赖 | 单机本地优先；纯文件存储（`platformdirs` 取用户目录） |
| 过度抽象 / 为单用场景预置扩展性 | Simplicity First（CLAUDE.md:366） |
| 独立 lint/format/type 配置文件 | 配置只进 `pyproject.toml`（见 §1.3） |
| 重型向量 / ML 框架（torch / transformers 全家桶） | 仅用 `lancedb` + provider SDK，embedding 走 LLM provider |

### 2.2 当前实际依赖（即"允许清单"）

**运行时核心（10 个，来自 `pyproject.toml:5-14`）**：
```
lancedb>=0.4.0      pypdf>=4.0.0        python-docx>=1.0.0
openpyxl>=3.1.0     pyyaml>=6.0          httpx>=0.25.0
platformdirs>=4.0   mcp>=0.1.0          fastapi>=0.100.0
uvicorn>=0.31.0
```

**开发可选（`[dev]`）**：`pytest>=8.0.0`、`pytest-asyncio>=0.23.0`、`ruff>=0.11.0`、`mypy>=1.14.0`。

**新增依赖原则**：保持轻量、单机可装；原生重包（pyarrow / lancedb）走离线安装（见 `SETUP.md`）。

---

## 3. 输出格式要求（Output Format / Wiki Spec）

> 权威文件：`docs/guides/wiki-spec.md`（11KB）。以下为强制要点摘要，生成 Wiki 页面时必须遵守。

### 3.1 页面 ID（`wiki-spec.md`）
- 命名：`kebab-case`（支持 CJK）或 UUID v7。
- 正则：`^(?:card_...|[a-z0-9-一-鿿]+)$`；`max_length = 64`。
- 保留字：`index` / `log`（不可作普通页面 ID）。
- 生成后需通过 `slug` 规范化（禁止大写、下划线、Latin Extended、路径分隔符）。

### 3.2 Frontmatter（`wiki-spec.md`）
- **required**：`id` / `title` / `type`
- **optional**：`sources` / `relations` / `grade` / `processing_depth` / `is_immutable` / `heat` / `tags` / 其他元数据
- 往返一致性：写 / 读必须对称（见 §1.2 加字段规则）。

### 3.3 Body（`wiki-spec.md`）
- 长度：`min 1` / `max 50000` 字符。
- 允许的 Markdown 子集：bold / italic / headings / lists / **wikilinks** `[[slug]]`。
- 中文 slug 规则、禁止字符见规范。

### 3.4 受控标签命名空间（`src/wiki/features/tag_namespace.py`，强制值域）

> ✅ 机制已完整实现：**10 个中文前缀** + `TAG_VALUES` 值域约束 + `MANDATORY_PAIRS` 强制配对。（此前某评估报告误称"无值域约束 / 8 英文前缀"，**以本段为准**——值域早已存在，真实缺口只是"软约束（提示词）未写入强制校验"。）

**前缀（`TAG_PREFIXES`，`tag_namespace.py:15`）**：

| 前缀 | 含义 | 值域约束（`TAG_VALUES`） |
|------|------|--------------------------|
| `题材` | 题材类型 | 现言/古言/玄幻/仙侠/科幻/悬疑/都市/校园/职场/历史/武侠/军事 |
| `功能` | 功能类型 | 教程/方法论/案例/模板/参考/工具/规范/FAQ |
| `角色` | 角色类型 | 自由（None） |
| `事件` | 事件类型 | 自由（None） |
| `情绪` | 情绪氛围 | 甜宠/虐文/爽文/轻松/正剧/热血/治愈/暗黑/悬疑 |
| `实体` | 是什么 (What) | 自由（None） |
| `场景阶段` | 何时用 (When) | 开篇/转折/高潮/结局/铺垫/过渡/冲突/收束 |
| `状态` | 生命周期 | 完结/连载中/弃坑/暂停/大纲/待发布 |
| `素材` | 素材品类 | ugc/official/转载/原创/投稿 |
| `可信度` | 可信度 | book/web/expert/user/ai/unknown/ugc/mixed |

**校验函数**：
- `is_valid_prefix(tag)`（`tag_namespace.py:61`）：检查前缀是否受控。
- `is_valid_value(prefix, value)`（`tag_namespace.py:80`）：检查值在 `TAG_VALUES` 值域内（自由前缀返回 True）。
- `get_mandatory_pairs()`（`tag_namespace.py:88`）：返回必须出现的配对集合。

**强制配对（MANDATORY_PAIRS，`tag_namespace.py:49`）**：当前 `MANDATORY_PAIRS = []` 为空——UGC 强制配对（`素材/ugc` + `可信度/ugc`）目前**硬编码在 analyzer / generator 提示词**里，非配置驱动（技术债务 #11 同源问题）。

**提示词一致性约束**：三处摄取提示词（analyzer / generator / unified）里硬编码的标签指引，应与 `TAG_PREFIXES` 单一来源一致，禁止另行发明前缀或值。

---

## 4. 跨文档引用

| 主题 | 文件 |
|------|------|
| 完整架构 | `docs/ARCHITECTURE.md` |
| 输出格式全规范 | `docs/guides/wiki-spec.md` |
| 标签命名空间实现 | `src/wiki/features/tag_namespace.py` |
| 技术债务清单（含优先级/负责角色） | `docs/TECH_DEBT_CHECKLIST.md` |
| 摄取流程完善方案 | `docs/superpowers/plans/2026-08-02-ingest-pipeline-completion.md` |
| STS 语义分类可行性 | `docs/evaluations/semantic-taxonomy-feasibility.md` |
| 环境 / 依赖安装 | `docs/environment/SETUP.md` |

---

## 5. 已知文档—代码偏差（诚实记录，待修正）

> 本文件整合过程中发现并纠正的历史偏差，列出以便后续统一：

1. **标签前缀数量**：早期评估报告写成"8 个英文前缀" / "10 个中文前缀无值域"——**均错**。实测为 10 个中文前缀且 `TAG_VALUES` 早已实现（§3.4 为正确版本）。
2. **Web UI 存在性**：早期可行性报告称"Web UI 从未启用"——**错**。`web/` 含完整静态前端，README 有 `serve` 启动命令。
3. **Lint 配置位置**：CLAUDE.md 称"无 ruff.toml/mypy.ini"——实际配置在 `pyproject.toml`（§1.3）。
4. **MANDATORY_PAIRS**：文档多处暗示已配置 UGC 强制配对，实际代码为空列表、配对硬编码在提示词。

如发现新的偏差，请直接修正本文件对应章节，并回提上游原始文件。
