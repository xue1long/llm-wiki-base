# WebUI 功能补齐方案

> 生成日期：2026-08-09 | 基于全量代码分析

---

## 一、现状总览

### 1.1 WebUI 视图与后端 API 覆盖矩阵

| 视图 | 页面 | 已用 API | 未用 API | 覆盖度 |
|------|------|---------|---------|--------|
| 搜索 | `search.js` | `POST /search` | — | 100% |
| 浏览 | `browse.js` | `GET /files`, `GET /files/content`, `GET /tag-index` | — | 100% |
| 摄取 | `ingest.js` | `POST /ingest`, `POST /delete-source`, `GET /raw-files`, `GET /ingest/status`, `GET /quality` | `POST /reingest`, `GET /ingest/tasks` | 70% |
| 对话 | `chat.js` | `POST /chat` | — | 100% |
| 图谱 | `graph.js` | `GET /wiki/graph` | — | 100% |
| 状态 | `status.js` | `GET /health`, `GET /project`, `GET /files`, `GET /raw-files`, `GET /wiki/graph`, `GET /reviews`, `GET /schema`, `GET /lint` | — | 100% (只读) |
| 设置 | `settings.js` | `GET/POST/DELETE /providers`, `POST /providers/test`, `POST /providers/set-default`, `GET /providers/{name}` | — | 100% |

### 1.2 CLI-Only 功能清单

| 模块 | CLI 命令 | 代码行数 | 复杂度 | 说明 |
|------|---------|---------|--------|------|
| **热度衰减** | `heat {show,top,cold,decay,zombies,restore,archive}` | 112行 | 中 | 7个子命令，管理知识生命周期 |
| **关系管理** | `relations {list,backlinks,neighbors,path,types,add-type}` | 110行 | 中 | 5个子命令，查询+管理 |
| **去重** | `dedup auto [--threshold]` | — | 中 | 调用 LLM 的批量操作 |
| **审查项处理** | (通过 API 暴露) | — | 低 | 已有 `PATCH /reviews/{id}`，WebUI 未用 |
| **队列管理** | (通过 API 暴露) | — | 低 | 已有 `POST /queue/pause\|resume`, `GET /queue/status`，WebUI 未用 |
| **重新摄取** | (通过 API 暴露) | — | 低 | 已有 `POST /reingest`，WebUI 未用 |
| **Schema 迁移** | `schema {list,diff,upgrade,downgrade,backup}` | 185行 | 中 | 数据迁移操作 |
| **Wiki 模板管理** | `wiki-templates {list,show,edit,reset,status,diff,upgrade}` | 448行 | 高 | 8个子命令，已有完整服务层 |
| **字段校验** | `fields validate <page>` | 116行 | 低 | 单页校验 |
| **标签校验** | `tags validate [--all]` | — | 低 | 批量校验 |
| **存根管理** | `stubs {list,promote}` | — | 中 | 调用 LLM 的批量操作 |
| **缓存清理** | `cache cleanup [--dry-run]` | 70行 | 低 | 运维操作 |
| **深度研究** | `research run ...` | 74行 | 高 | 多步骤研究管线 |
| **Wiki 润色** | `wiki polish` | 79行 | 中 | 批量润色 |
| **视觉处理** | `vision` | 50行 | 低 | 图片提取字幕 |

---

## 二、分阶段实施计划

### 阶段一：补齐已有 API 的 WebUI 调用（P0 — 优先级最高）

这些功能**后端 API 已经存在**，只需 WebUI 前端代码补上调用。工作量小、见效快。

#### 1.1 队列管理（Queue Controls）

**目标：** 在状态页增加队列暂停/恢复/状态查看功能

**后端现状：** 已有 3 个端点可用
- `POST /queue/pause` → `{"status":"paused","pending":N,"running":N}`
- `POST /queue/resume` → `{"status":"resumed","pending":N,"running":N}`
- `GET /queue/status` → `{"paused":bool,"pending_count":N,"running_count":N}`

**WebUI 改动：** `status.js` 或新增独立队列视图

```
┌─ 状态页 ──────────────────────────────────┐
│  [队列状态: 运行中]  [暂停]  [恢复]         │
│  待处理: 3  |  运行中: 2  |  已完成: 156    │
└──────────────────────────────────────────────┘
```

**文件改动：**
- `web/js/views/status.js` — 增加队列控制面板，+80 行
- `web/style.css` — 队列状态卡片样式，+20 行

#### 1.2 审查项处理（Review Actions）

**目标：** 在状态页或独立视图，支持审查项的批准/驳回/取消操作

**后端现状：** 已有 `PATCH /reviews/{id}`，Body 接受 `{resolved: bool, action: "skip"|"accept"|"reject"}`

**WebUI 改动：** `status.js` 增加交互式审查列表

```
┌─ 审查项列表 ────────────────────────────────────┐
│  □ [类型] 标题                      [批准] [驳回] │
│  □ [schema] 页面"xxx"缺少必填字段    [批准] [驳回] │
│  □ [confidence] 置信度低于阈值      [批准] [驳回] │
│  ──────── 已处理的审查项 ────────                  │
│  ✓ [evidence] 已核实 ✓ 已批准                     │
└──────────────────────────────────────────────────┘
```

**文件改动：**
- `web/js/views/status.js` — 将审查项从只读计数改为可交互列表，+100 行
- `web/style.css` — 审查项卡片样式，+30 行

#### 1.3 重新摄取（Reingest）

**目标：** 在摄取页的行操作中，增加"重新摄取"按钮替代当前的"删除"按钮

**后端现状：** 已有 `POST /reingest`，等效于删除+重新摄取一步完成

**WebUI 改动：** `ingest.js` 已摄取文件行增加"重新摄取"按钮

```
[📝] document.md    2026/08/01  2.3 MB  [重新摄取] [删除] [质]
```

**文件改动：**
- `web/js/views/ingest.js` — 行操作增加重新摄取按钮，+30 行

#### 1.4 任务历史列表（Task History）

**目标：** 在摄取页底部展示历史任务列表

**后端现状：** 已有 `GET /ingest/tasks`，返回按时间倒序的任务列表

**WebUI 改动：** `ingest.js` 进度面板下方增加任务列表

```
┌─ 历史任务 ──────────────────────────────────────┐
│  ✓ 2026-08-09 10:32  document.md  (2.4s)        │
│  ✗ 2026-08-09 10:30  paper.pdf    (error: timeout)│
│  ✓ 2026-08-09 10:28  notes.md     (1.1s)        │
└──────────────────────────────────────────────────┘
```

**文件改动：**
- `web/js/views/ingest.js` — 增加任务历史列表，+50 行

---

### 阶段二：新增 API + WebUI 功能（P1 — 日常知识管理）

这些功能**后端没有 REST API**，需要新建端点 + 前端视图。

#### 2.1 热度衰减管理（Heat）

**目标：** 在状态页或独立视图，展示热度分布，支持手工操作

**后端现状：** CLI 命令 `heat {show,top,cold,decay,zombies,restore,archive}`，底层使用 `HeatTracker` 和 `ZombieDetector`。需要新增 API 端点。

**新增 API 端点：**

| 方法 | 路径 | 功能 | 对应 CLI |
|------|------|------|---------|
| `GET` | `/api/v1/projects/{id}/heat` | 热度分布概览 | `heat show` |
| `GET` | `/api/v1/projects/{id}/heat/top` | 热度最高页面 | `heat top` |
| `GET` | `/api/v1/projects/{id}/heat/cold` | 冷门页面列表 | `heat cold` |
| `POST` | `/api/v1/projects/{id}/heat/decay` | 手动触发衰减 | `heat decay` |
| `GET` | `/api/v1/projects/{id}/heat/zombies` | 僵尸页面列表 | `heat zombies` |
| `POST` | `/api/v1/projects/{id}/heat/zombies/{page_id}/restore` | 恢复僵尸页 | `heat restore` |
| `POST` | `/api/v1/projects/{id}/heat/zombies/{page_id}/archive` | 归档僵尸页 | `heat archive` |

**Service 层：** `src/services/wiki_analysis.py` 已有 `get_heat_tracker` 和 `get_zombie_detector`，可直接复用

**WebUI 视图：**

```
┌─ 热度管理 ──────────────────────────────────────────┐
│  [触发衰减] [自动归档]                                │
│                                                      │
│  热度分布:                                           │
│  ████████████████ 热点 (80-100)  12 页               │
│  ██████████      温点 (40-79)   45 页                │
│  █████            冷点 (1-39)    28 页                │
│  ██               僵尸 (0)        8 页 [查看] [归档]  │
│                                                      │
│  ── 最高热度 Top 5 ──                                │
│  🔥 98  [写作风格]  concepts/writing-style           │
│  🔥 95  [世界观设定]  concepts/world-building         │
│  ...                                                 │
│  ── 僵尸页面 ──                                      │
│  💀 [废弃设定v1]  zombie: 2026-06-01  [恢复] [归档]   │
│  💀 [旧人物表]    zombie: 2026-05-15  [恢复] [归档]   │
└──────────────────────────────────────────────────────┘
```

**新增文件：**
- `src/server/routes/heat.py` — 7 个 API 端点，~80 行
- `web/js/views/heat.js` — 新视图，~200 行

**改动文件：**
- `src/server/app.py` — 注册路由，+2 行
- `web/js/app.js` — 注册新视图，+5 行
- `web/index.html` — 导航按钮，+1 行
- `web/style.css` — 热度卡片样式，+40 行
- `docs/webui-buttons.md` — 更新文档

#### 2.2 关系管理增强（Relations）

**目标：** 在浏览页中增强关系查看和编辑能力

**后端现状：** CLI 有 `relations {list,backlinks,neighbors,path,types,add-type}`，底层 `RelationQuery` 已封装。浏览页目前只从 `relations` frontmatter 被动展示。需要新增 API。

**新增 API 端点：**

| 方法 | 路径 | 功能 | 对应 CLI |
|------|------|------|---------|
| `GET` | `/api/v1/projects/{id}/relations/{page_id}` | 列出页面的关系 | `relations list` |
| `GET` | `/api/v1/projects/{id}/backlinks/{page_id}` | 列出反向链接 | `relations backlinks` |
| `GET` | `/api/v1/projects/{id}/neighbors/{page_id}` | 邻居查询 | `relations neighbors` |
| `GET` | `/api/v1/projects/{id}/relations/path` | 两点间路径 | `relations path` |
| `GET` | `/api/v1/projects/{id}/relation-types` | 列出所有关系类型 | `relations types` |

**WebUI 改动：** 浏览页阅读器右侧增加关系面板

```
┌─ 当前页面 ──────┐  ┌─ 关系面板 ────────────────────┐
│                  │  │  关联 (5)                     │
│  [页面内容]      │  │  → 写作风格 (supports)        │
│                  │  │  → 世界观 (part_of)           │
│                  │  │  ← 人物设定 (referenced_by)   │
│                  │  │                               │
│                  │  │  反向链接 (3)                  │
│                  │  │  ← 剧情大纲                   │
│                  │  │  ← 角色设定                   │
│                  │  │  ← 场景描述                   │
└──────────────────┘  └───────────────────────────────┘
```

**新增文件：**
- `src/server/routes/relations.py` — 5 个端点，~60 行

**改动文件：**
- `src/server/app.py` — 注册路由，+2 行
- `web/js/views/browse.js` — 阅读器右侧增加关系面板，+80 行
- `web/style.css` — 关系面板样式，+30 行

#### 2.3 去重管理（Dedup）

**目标：** 在状态页或独立视图，支持一键去重执行

**后端现状：** CLI 有 `dedup auto`，底层 `dedup_auto()` 调用 LLM 判断。`wiki_analysis.py` 已有 `run_dedup_auto` 包装器。

**新增 API 端点：**

| 方法 | 路径 | 功能 |
|------|------|------|
| `POST` | `/api/v1/projects/{id}/dedup` | 执行自动去重 |
| `GET` | `/api/v1/projects/{id}/dedup/status` | 去重任务状态 |

**WebUI 改动：** 状态页增加去重操作按钮

**新增文件：**
- `src/server/routes/dedup.py` — 2 个端点，~40 行

**改动文件：**
- `src/server/app.py` — 注册路由，+2 行
- `web/js/views/status.js` — 增加去重按钮和结果展示，+40 行

---

### 阶段三：运维工具 WebUI 化（P2 — 高级管理）

#### 3.1 Schema 迁移管理

**目标：** 在状态页增加 Schema 迁移操作界面

**后端现状：** CLI 有 `schema {list,diff,upgrade,downgrade,backup}`，`GET /schema` 只读展示。需要新增操作端点。

**新增 API 端点：**

| 方法 | 路径 | 功能 |
|------|------|------|
| `POST` | `/api/v1/projects/{id}/schema/upgrade` | 升级到下一版本 |
| `POST` | `/api/v1/projects/{id}/schema/downgrade` | 降级到上一版本 |
| `POST` | `/api/v1/projects/{id}/schema/backup` | 手动备份 |

**新增文件：**
- `src/server/routes/schema_ops.py` — 3 个端点，~50 行

**改动文件：**
- `src/server/app.py` — 注册路由
- `web/js/views/status.js` — 增加迁移操作按钮

#### 3.2 Wiki 模板管理

**目标：** 新增模板管理页面，可视化查看/编辑模板

**后端现状：** CLI 有 `wiki-templates {list,show,edit,reset,status,diff,upgrade}`，共 448 行。已有 `templates_cmd.py` 和 `wiki_templates_cmd.py`，功能完整但无 API。

**新增 API 端点：**

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/v1/projects/{id}/templates` | 列出所有模板 |
| `GET` | `/api/v1/projects/{id}/templates/{type}` | 查看模板内容 |
| `POST` | `/api/v1/projects/{id}/templates/{type}` | 编辑模板 |
| `POST` | `/api/v1/projects/{id}/templates/{type}/reset` | 重置为默认 |
| `GET` | `/api/v1/projects/{id}/templates/{type}/diff` | 对比差异 |
| `POST` | `/api/v1/projects/{id}/templates/{type}/upgrade` | 升级模板 |

**新增文件：**
- `src/server/routes/templates.py` — 6 个端点，~80 行
- `web/js/views/templates.js` — 新视图，~250 行

**改动文件：**
- `src/server/app.py` — 注册路由
- `web/js/app.js` — 注册新视图
- `web/index.html` — 导航按钮
- `web/style.css` — 模板编辑器样式

#### 3.3 缓存清理 / 字段校验 / 标签校验 / 存根管理

这些功能可以合并到状态页或对应的视图页面，不独立成页。

| 功能 | 位置 | 形式 |
|------|------|------|
| `cache cleanup` | 状态页 | 按钮 + 结果提示 |
| `fields validate` | 浏览页 | 页面操作菜单 |
| `tags validate` | 浏览页 | 标签栏操作 |
| `stubs {list,promote}` | 状态页 | 列表 + 批量操作 |

---

### 阶段四：大型功能（P3 — 可选扩展）

#### 4.1 深度研究（Research）WebUI

**后端现状：** CLI 有 `research run`，74 行，多步骤研究管线。需要完整的前端进度展示。

**建议：** 独立视图，展示研究步骤、中间结果、最终报告。

#### 4.2 Wiki 润色（Polish）WebUI

**后端现状：** CLI 有 `wiki polish`，79 行，批量 LLM 润色。

**建议：** 状态页或独立视图，批量操作+进度展示。

---

## 三、实施路径图

```
优先级    阶段         工作量    依赖
─────────────────────────────────────────────
P0    阶段一 (补齐API)  ~2天     无
       ├─ 队列管理       0.5天   无
       ├─ 审查项处理     0.5天   无
       ├─ 重新摄取       0.2天   无
       └─ 任务历史       0.3天   无

P1    阶段二 (新增API)  ~4天     依赖阶段一
       ├─ 热度管理       1.5天   新 API + 新视图
       ├─ 关系管理       1天     新 API + 增强浏览页
       └─ 去重管理       0.5天   新 API + 状态页按钮

P2    阶段三 (运维工具)  ~3天     依赖阶段二
       ├─ Schema 迁移    1天     新 API + 状态页增强
       ├─ 模板管理       2天     新 API + 新视图
       └─ 小工具合入     0.5天   分散到各页面

P3    阶段四 (大型功能)  ~4天     可选
       ├─ 深度研究       2天     新视图
       └─ Wiki 润色      1天     新视图/对话框
```

**总计：约 13 天（周末·兼职）或 9 天（全职），按 P0→P1→P2→P3 顺序执行。**

---

## 四、架构原则

### 4.1 服务层优先

所有新功能遵循统一路径：

```
CLI (cli_ext/*.py) → Service Layer (src/services/) → HTTP Route (src/server/routes/) → WebUI (web/js/views/)
```

**不绕过。** CLI 和 WebUI 都调用同一 Service Layer，避免逻辑重复。

### 4.2 路由命名规范

```
GET    /api/v1/projects/{id}/heat          # 列表
POST   /api/v1/projects/{id}/heat/decay    # 操作
GET    /api/v1/projects/{id}/heat/top      # 子查询
```

### 4.3 视图注册规范

新视图需要注册 3 处：
1. `web/index.html` — 导航按钮 `<button data-view="heat">`
2. `web/js/app.js` — 路由映射 `App.showView` 中的 `fn` 对象
3. `web/js/views/` — 新视图文件

### 4.4 文档同步

每次新增/修改 WebUI 功能后，同步更新：
- `docs/webui-buttons.md` — 按钮位置、功能、API 映射
- `docs/web-design-execution-plan.md` — 整体设计变更

---

## 五、推荐启动顺序

### 第一周（P0）：快速见效

```
Day 1: 队列管理   → 状态页增加暂停/恢复按钮
Day 2: 审查项处理  → 状态页审查列表可交互操作
Day 3: 重新摄取    → 摄取页行按钮+任务历史列表
```

### 第二周（P1）：核心管理

```
Day 4-5: 热度管理  → 新 API + 新视图
Day 6:   关系管理  → 新 API + 浏览页增强
Day 7:   去重管理  → 新 API + 状态页按钮
```

### 第三周（P2）：运维工具

```
Day 8-9:   Schema 迁移 → 状态页操作界面
Day 10-11: 模板管理   → 新视图（模板编辑器）
Day 12:    小工具合入 → 缓存/字段/标签/存根
```