# WebUI 前端设计规格书（设计优先，后端补齐）

> 生成日期：2026-08-09 | 设计驱动开发
> 本文档是**实现规格**，交给 LLM/开发者直接照做即可，无需再去读后端源码。
> 设计原则：先确定前端需要什么，再定义后端 API 提供什么。

---

## 目录

1. [设计规范](#1-设计规范)
2. [P0 - 已有 API 的前端补齐](#2-p0---已有-api-的前端补齐)
3. [P1 - 新 API + 新视图](#3-p1---新-api--新视图)
4. [P2 - 运维工具视图](#4-p2---运维工具视图)
5. [API 契约汇总](#5-api-契约汇总)
6. [实施路线图](#6-实施路线图)

---

## 1. 设计规范

### 1.1 通用组件设计

所有视图的状态处理遵循统一模式：

```
┌ 数据加载状态 ──────────────────────────┐
│ 加载中: skeleton 骨架屏（已存在）         │
│ 空状态: 图标 + 标题 + 描述 + 操作按钮     │
│ 错误状态: 错误信息 + 重试按钮             │
│ 正常: 数据展示 + 交互操作                 │
└──────────────────────────────────────────┘
```

### 1.2 操作按钮规范

| 类型 | 颜色 | 用途 |
|------|------|------|
| `.btn-primary` | 主题色 | 主要操作（添加/提交/执行） |
| `.btn-sm` | 默认 | 次要操作（查看/编辑/测试） |
| `.btn-danger` | 红色 | 危险操作（删除/归档） |
| `.btn-ghost` | 透明 | 边框操作（取消/关闭） |

### 1.3 弹窗/确认框规范

| 操作 | 确认方式 | 文案 |
|------|---------|------|
| 删除源 | `confirm()` | `确认删除「{name}」的编译结果？原始文件保留。` |
| 批量操作 | 弹窗确认 | `确认对 {N} 个页面执行 {action}？` |
| Schema 迁移 | 弹窗+预览 | 先展示 diff，再确认执行 |
| 非破坏性操作 | 直接执行 | 不需要确认 |

### 1.4 导航结构（更新后）

```
搜索 | 浏览 | 摄取 | 对话 | 图谱 | 热度 | 模板 | 状态 | 设置
                                                      ↑新增
```

热度管理放在图谱之后、状态之前，因为它是知识生命周期管理的核心。

---

## 2. P0 - 已有 API 的前端补齐

### 2.1 队列控制面板（Status 视图增强）

**目标：** 在状态页增加队列控制卡片，替换只读统计。

**位置：** `web/js/views/status.js`，在"服务健康"卡片下方

**设计稿：**

```
┌─ 摄取队列 ──────────────────────────────────────────┐
│  [状态] 运行中  [暂停]                               │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ 待处理    │  │ 运行中    │  │ 已完成    │           │
│  │   3       │  │   2       │  │ 156       │           │
│  └──────────┘  └──────────┘  └──────────┘           │
│                                                     │
│  [暂停]  [恢复]  [刷新]                              │
└─────────────────────────────────────────────────────┘
```

**交互逻辑：**

| 操作 | 触发 | 结果 |
|------|------|------|
| 点击"暂停" | `POST /queue/pause` | 按钮禁用，状态改为"已暂停" |
| 点击"恢复" | `POST /queue/resume` | 按钮禁用，状态改为"运行中" |
| 自动刷新 | 每 30s | `GET /queue/status` 更新统计 |
| 暂停状态 | 队列已暂停 | 显示黄色警示背景，暂停按钮不可用 |

**API 调用：**

```javascript
// 加载状态
const qs = await App.api('/api/v1/queue/status');
// qs = { paused: false, pending_count: 3, running_count: 2, completed_count: 156 }

// 暂停
const p = await App.api('/api/v1/queue/pause', { method: 'POST' });
// p = { status: 'paused', pending: 3, running: 2 }

// 恢复
const r = await App.api('/api/v1/queue/resume', { method: 'POST' });
// r = { status: 'resumed', pending: 3, running: 2 }
```

**状态处理：**

| 状态 | 展示 | 操作按钮 |
|------|------|---------|
| 加载中 | skeleton 卡片 | 无 |
| 正常 | 统计卡片 + 操作按钮 | 暂停/恢复/刷新 |
| 已暂停 | 黄色背景 + 统计 | 恢复/刷新（暂停禁用） |
| 错误 | 错误提示 + 重试按钮 | 刷新 |

**文件改动：** +80 行（`status.js`），+20 行（`style.css`）

---

### 2.2 审查项处理面板（Status 视图增强）

**目标：** 将只读的审查计数变为可交互的审查列表，支持批准/驳回。

**位置：** `web/js/views/status.js`，在"统计"卡片下方

**设计稿：**

```
┌─ 审查队列 ────────────────────────────────────────────────┐
│  [全部] [待处理] [已处理]                                   │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ [schema] 页面"xxx" 缺少必填字段 "grade"              │  │
│  │ 详情: 该页面未设置 grade 字段，将使用默认值 "B"        │  │
│  │ 置信度: 0.85  |  来源: xxx.md                         │  │
│  │ [批准] [驳回] [跳过]                                   │  │
│  ├──────────────────────────────────────────────────────┤  │
│  │ [evidence] 页面"yyy" 缺少证据引用                     │  │
│  │ 详情: 声明"角色A是B的儿子" 无来源引用                   │  │
│  │ 置信度: 0.72  |  来源: yyy.md                         │  │
│  │ [批准] [驳回] [跳过]                                   │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ── 已处理 (3) ── (可折叠)                                  │
│  ✓ [schema] xxx.md — 已批准 (2026-08-08)                   │
│  ✗ [evidence] yyy.md — 已驳回 (2026-08-08)                 │
│  → [confidence] zzz.md — 已跳过 (2026-08-07)               │
└────────────────────────────────────────────────────────────┘
```

**交互逻辑：**

| 操作 | 触发 | 结果 |
|------|------|------|
| 点击"批准" | `PATCH /reviews/{id}` body: `{resolved: true, action: "accept"}` | 条目移入"已处理"列表 |
| 点击"驳回" | `PATCH /reviews/{id}` body: `{resolved: true, action: "reject"}` | 条目移入"已处理"列表 |
| 点击"跳过" | `PATCH /reviews/{id}` body: `{resolved: true, action: "skip"}` | 条目移入"已处理"列表 |
| 点击"已处理"条目 | 不需要操作（只读） | 展示处理结果 |
| 筛选切换 | 纯前端过滤 | 显示对应状态列表 |

**状态处理：**

| 状态 | 展示 |
|------|------|
| 加载中 | skeleton 列表 |
| 空（无审查项） | ✅ 图标 + "所有审查项已处理" |
| 空（全部已处理） | 折叠的已处理列表 + 空状态 |
| 错误 | 错误提示 + 重试 |
| 操作中 | 按钮 disabled + 旋转动画 |
| 操作失败 | 按钮恢复 + 错误提示 |

**API 调用：**

```javascript
// 加载审查项
const reviews = await App.api('/api/v1/projects/{id}/reviews?status=open');
// reviews = { status: 'open', count: 2, reviews: [{ id, type, title, detail, confidence, ... }] }

// 处理审查项
await App.api('/api/v1/projects/{id}/reviews/{review_id}', {
  method: 'PATCH',
  body: { resolved: true, action: 'accept' }
});
// 返回: { ok: true }

// 加载已处理的审查项
const resolved = await App.api('/api/v1/projects/{id}/reviews?status=resolved');
// resolved = { status: 'resolved', count: 3, reviews: [...] }
```

**文件改动：** +120 行（`status.js`），+30 行（`style.css`）

---

### 2.3 重新摄取按钮（Ingest 视图增强）

**目标：** 已摄取的文件行增加"重新摄取"按钮，替代"删除后重新摄取"的两步操作。

**位置：** `web/js/views/ingest.js`，已摄取文件行的操作区

**设计稿：**

```
已摄取文件行（当前）:
[📝] document.md  2026/08/01  2.3 MB  [删除] [质]

已摄取文件行（增强后）:
[📝] document.md  2026/08/01  2.3 MB  [重新摄取] [删除] [质]
```

**交互逻辑：**

| 操作 | 触发 | 结果 |
|------|------|------|
| 点击"重新摄取" | `POST /reingest` body: `{source_path}` | 弹出确认框，确认后执行，进度展示与普通摄取相同 |
| 点击"删除" | `POST /delete-source`（不变） | 保持不变 |

**确认框文案：**
```
「{name}」已编译过 wiki 页面，重新摄取将：
1. 删除现有编译结果
2. 重新执行完整流水线

确认继续？
```

**API 调用：**

```javascript
await App.api('/api/v1/projects/{id}/reingest', {
  method: 'POST',
  body: { source_path: 'raw/sources/document.md' }
});
// 返回: { status: 'queued', taskId: 'xxx', cleaned: { deleted_pages: 3, deleted_vectors: 12 } }
```

**状态处理：** 与普通摄取同一进度轮询逻辑（复用 `App.ingestOneRaw` 的 `onProgress` 回调）

**文件改动：** +30 行（`ingest.js`）

---

### 2.4 任务历史列表（Ingest 视图增强）

**目标：** 摄取页批量进度面板下方展示历史任务列表。

**位置：** `web/js/views/ingest.js`，在手动添加路径区域下方

**设计稿：**

```
┌─ 历史任务 ──────────────────────────────────────────────────┐
│  显示最近 20 条任务                                          │
│                                                             │
│  ✓ 2026-08-09 10:32:15  document.md         成功  2.4s      │
│  ✗ 2026-08-09 10:30:22  paper.pdf           失败  超时       │
│  ✓ 2026-08-09 10:28:07  notes.md            成功  1.1s      │
│  ⏳ 2026-08-09 10:25:00  draft.md            运行中  45s     │
│  ✓ 2026-08-09 10:20:33  chapter-01.md       成功  8.7s      │
│                                                             │
│  [刷新]  [只有 20 条，更多在终端查看]                          │
└─────────────────────────────────────────────────────────────┘
```

**交互逻辑：**

| 操作 | 触发 | 结果 |
|------|------|------|
| 页面加载 | `GET /ingest/tasks` | 渲染最近 20 条任务 |
| 点击"刷新" | `GET /ingest/tasks` | 重新加载 |
| 点击失败任务 | 无 | 只读，提示"查看终端日志" |
| 批量摄取完成后 | 自动刷新列表 | 新增完成记录 |

**行状态图标：**

| 图标 | 状态 | 颜色 |
|------|------|------|
| ✓ | succeeded | 绿色 |
| ✗ | failed | 红色 |
| ⏳ | running/queued | 蓝色 |
| ⏭ | ignored | 灰色 |

**API 调用：**

```javascript
const tasks = await App.api('/api/v1/projects/{id}/ingest/tasks');
// tasks = { tasks: [{ task_id, source_path, status, started_at, finished_at, error, ... }] }
```

**文件改动：** +50 行（`ingest.js`），+15 行（`style.css`）

---

## 3. P1 - 新 API + 新视图

### 3.1 热度管理视图（Heat）

**目标：** 独立视图，展示热度分布、热点/冷点/僵尸页面，支持操作。

**位置：** 新文件 `web/js/views/heat.js`，导航按钮在"图谱"和"状态"之间

**设计稿：**

```
┌─ 热度管理 ─────────────────────────────────────────────────┐
│  [触发衰减]  [自动归档僵尸页]  [刷新]                      │
│                                                            │
│  ── 热度分布 ──                                            │
│  🔥 热点 (80-100)  ████████████████  12 页                 │
│  🔆 温点 (40-79)   ██████████        45 页                 │
│  ❄️ 冷点 (1-39)    █████              28 页                 │
│  💀 僵尸 (0)       ██                  8 页                 │
│                                                            │
│  ── 最高热度 Top 10 ──                                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ # 热度 类型  标题                  路径               │  │
│  │ 1  98   concept 写作风格           concepts/writing-  │  │
│  │ 2  95   concept 世界观设定          concepts/world-    │  │
│  │ 3  87   entity  主角-张三          entities/zhang-san  │  │
│  │ ...                                                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ── 僵尸页面 ──                                            │
│  [全选] [恢复选中] [归档选中]                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ ☐ 💀 废弃设定v1     concepts/abandoned-setting 06-01  │  │
│  │ ☐ 💀 旧人物表       entities/old-characters   05-15  │  │
│  │ ☐ 💀 初版大纲       concepts/outline-v1       04-28  │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**需要新增的 API 端点：**

| 方法 | 路径 | 返回 | 对应 CLI |
|------|------|------|---------|
| `GET` | `/api/v1/projects/{id}/heat` | `{pools: {hot: N, warm: N, cold: N, zombie: N}, top: [...], zombies: [...]}` | `heat show` + `heat top` + `heat zombies` |
| `POST` | `/api/v1/projects/{id}/heat/decay` | `{decayed: N, zombies_created: N}` | `heat decay` |
| `POST` | `/api/v1/projects/{id}/heat/zombies/restore` | `{restored: N}` | `heat restore` |
| `POST` | `/api/v1/projects/{id}/heat/zombies/archive` | `{archived: N}` | `heat archive` |

**响应体设计（前端需要什么，后端就返回什么）：**

```javascript
// GET /heat
{
  "pools": {
    "hot": 12, "warm": 45, "cold": 28, "zombie": 8
  },
  "top": [
    { "rank": 1, "heat": 98, "type": "concept", "title": "写作风格", "path": "wiki/concepts/writing-style.md" }
  ],
  "zombies": [
    { "page_id": "abandoned-setting", "title": "废弃设定v1", "path": "wiki/concepts/abandoned-setting.md", "zombie_since": "2026-06-01T00:00:00Z" }
  ]
}

// POST /heat/decay
{ "decayed": 156, "zombies_created": 3 }

// POST /heat/zombies/restore  body: { page_ids: ["id1", "id2"] }
{ "restored": 2 }

// POST /heat/zombies/archive  body: { page_ids: ["id1", "id2"] }
{ "archived": 2 }
```

**交互逻辑：**

| 操作 | 触发 | 结果 |
|------|------|------|
| "触发衰减" | `POST /heat/decay` | 确认后执行，展示结果弹窗 |
| 全选僵尸 | 前端 | 选中所有僵尸页 |
| "恢复选中" | `POST /heat/zombies/restore` | 刷新列表 |
| "归档选中" | `POST /heat/zombies/archive` | 确认后归档，刷新列表 |
| 点击热度行 | 跳转到浏览页 | `App.state.pendingBrowseTarget = path` |

**状态处理：**

| 状态 | 展示 |
|------|------|
| 加载中 | skeleton 分布条 + 列表 |
| 空（无数据） | "尚无热度数据，请先摄取文档" |
| 空（无僵尸） | "无僵尸页面" + 绿色图标 |
| 错误 | 错误提示 + 重试 |
| 操作中 | 按钮 disabled |
| 操作完成 | toast 提示 + 刷新 |

**新增文件：** `src/server/routes/heat.py` (~80行)，`web/js/views/heat.js` (~200行)

**改动文件：** `src/server/app.py` (+2行)，`web/js/app.js` (+5行)，`web/index.html` (+1行)，`web/style.css` (+40行)

---

### 3.2 关系面板增强（Browse 视图增强）

**目标：** 浏览页阅读器右侧增加关系面板，展示关联页面和反向链接。

**位置：** `web/js/views/browse.js`，阅读器右侧新增面板

**设计稿：**

```
┌─ 浏览页（增强后布局） ──────────────────────────────────────┐
│                                                             │
│  ┌─ 目录树 ──┐  ┌─ 阅读器 ────────────────────┐  ┌─ 关系面板 │
│  │ concepts  │  │                            │  │ ──────── │
│  │  写作风格  │  │  # 写作风格                 │  │ 关联 (5)  │
│  │  世界观设定 │  │                            │  │ → 支持    │
│  │  人物设计  │  │  ## 定义                   │  │   写作风格 │
│  │ entities  │  │  ...                       │  │ → 包含    │
│  │  主角     │  │                            │  │   世界观   │
│  │  配角     │  │  ## 主要特点                │  │ ← 引用    │
│  └───────────┘  │  ...                       │  │   主角设定 │
│                 │                            │  │          │
│                 │                            │  │ 反向链接  │
│                 │                            │  │ (3)      │
│                 │                            │  │ ← 剧情大纲│
│                 │                            │  │ ← 角色设定│
│                 │                            │  │ ← 场景描述│
│                 │                            │  │          │
│                 │                            │  │ 操作      │
│                 │                            │  │ [查看关系  │
│                 │                            │  │ 图]       │
│                 └────────────────────────────┘  └──────────┘
```

**需要新增的 API 端点：**

| 方法 | 路径 | 返回 |
|------|------|------|
| `GET` | `/api/v1/projects/{id}/relations/{page_id}` | `{relations: [{target_id, type, weight, context}], backlinks: [{source_id, type, weight}]}` |

**响应体设计：**

```javascript
// GET /relations/{page_id}
{
  "page_id": "writing-style",
  "relations": [
    { "target_id": "world-building", "type": "supports", "weight": 0.9, "context": "写作风格影响世界观" },
    { "target_id": "character-design", "type": "related_to", "weight": 0.7, "context": "" }
  ],
  "backlinks": [
    { "source_id": "plot-outline", "type": "references", "weight": 0.8 },
    { "source_id": "character-setting", "type": "mentions", "weight": 0.5 }
  ]
}
```

**交互逻辑：**

| 操作 | 触发 | 结果 |
|------|------|------|
| 点击关联项 | 跳转到目标页面 | 在阅读器中加载目标页面 |
| 点击反向链接 | 跳转到来源页面 | 在阅读器中加载来源页面 |
| "查看关系图" | 跳转到图谱页 | 高亮当前节点 |
| 加载页面时 | `GET /relations/{page_id}` | 自动加载关系数据 |

**状态处理：**

| 状态 | 展示 |
|------|------|
| 加载中 | skeleton 列表 |
| 空（无关系） | "该页面暂无关联" |
| 空（无反向链接） | "尚无其他页面引用此页" |
| 错误 | 静默失败（不阻塞阅读器） |

**后端注意：** 当前 `src/services/wiki_analysis.py` 已有 `get_relations_for_page` 和 `get_backlinks_for_page`，可直接包装为 REST 端点，无需重写业务逻辑。

**新增文件：** `src/server/routes/relations.py` (~60行)

**改动文件：** `src/server/app.py` (+2行)，`web/js/views/browse.js` (+80行)，`web/style.css` (+30行)

---

### 3.3 去重管理（Status 视图增强）

**目标：** 状态页增加去重操作按钮和结果展示。

**位置：** `web/js/views/status.js`，作为独立操作卡片

**设计稿：**

```
┌─ 去重管理 ────────────────────────────────────────────────┐
│  阈值: [低  ○ 中 ● 高 ○]                                   │
│                                                           │
│  [执行自动去重]                                             │
│                                                           │
│  ── 上次去重结果 ──                                        │
│  执行时间: 2026-08-08 14:30:22                              │
│  发现相似组: 5 组                                          │
│  已合并: 3 组  |  已跳过: 2 组                              │
│                                                           │
│  [查看详情]                                                │
└───────────────────────────────────────────────────────────┘
```

**需要新增的 API 端点：**

| 方法 | 路径 | 返回 |
|------|------|------|
| `POST` | `/api/v1/projects/{id}/dedup` | `{task_id, status, threshold}` |
| `GET` | `/api/v1/projects/{id}/dedup/status` | `{status, results: [{group, merged, skipped}]}` |

**交互逻辑：**

| 操作 | 触发 | 结果 |
|------|------|------|
| 选择阈值 | 前端 | 单选切换 |
| "执行自动去重" | `POST /dedup` | 异步执行，展示进度 |
| "查看详情" | 新建模态框或跳转 | 展示相似组详情 |

**新增文件：** `src/server/routes/dedup.py` (~40行)

**改动文件：** `src/server/app.py` (+2行)，`web/js/views/status.js` (+40行)，`web/style.css` (+15行)

---

## 4. P2 - 运维工具视图

### 4.1 Schema 迁移操作（Status 视图增强）

**位置：** 状态页 Schema 卡片增加操作按钮

**设计稿：**

```
当前: Schema 卡片（增强后）
┌─ Schema ───────────────────────────────────────────────┐
│  当前版本: v2                                           │
│  可用迁移: wiki (v1→v2), knowledge (v1→v2)              │
│                                                         │
│  [升级到 v3]  [降级到 v1]  [创建备份]  [查看差异]        │
└─────────────────────────────────────────────────────────┘
```

**需要新增的 API 端点：**

| 方法 | 路径 | 返回 |
|------|------|------|
| `POST` | `/api/v1/projects/{id}/schema/upgrade` | `{status, from, to, details}` |
| `POST` | `/api/v1/projects/{id}/schema/downgrade` | `{status, from, to, details}` |
| `POST` | `/api/v1/projects/{id}/schema/backup` | `{status, backup_path}` |
| `GET` | `/api/v1/projects/{id}/schema/diff` | `{diff: [...]}` |

**新增文件：** `src/server/routes/schema_ops.py` (~50行)

### 4.2 Wiki 模板管理视图（Templates）

**目标：** 独立视图，可视化查看/编辑/重置模板。

**位置：** 新文件 `web/js/views/templates.js`，导航按钮在"设置"之前

**设计稿：**

```
┌─ 模板管理 ───────────────────────────────────────────────────┐
│  选择模板类型: [concept ▼]  [entity]  [source]  [synthesis]  │
│                                                             │
│  ┌─ 模板预览 ──────────────────────────────────────────────┐ │
│  │  <!-- wiki-template-version: 1.0.0 -->                  │ │
│  │  <!-- wiki-template-type: concept -->                   │ │
│  │                                                         │ │
│  │  ## 定义                                                │ │
│  │  <!-- slot:definition -->                               │ │
│  │                                                         │ │
│  │  ## 别名                                                │ │
│  │  <!-- if:has_aliases -->                                │ │
│  │  <!-- slot:aliases -->                                  │ │
│  │  <!-- /if:has_aliases -->                               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                             │
│  状态: 使用中 (bundled)  [编辑]  [重置为默认]  [对比差异]    │
│  状态: 已自定义 (user)    [编辑]  [重置为默认]  [对比差异]    │
│                                                             │
│  ── 差异对比 ──                                             │
│  - 旧: ## 定义                                               │
│  + 新: ## 核心定义                                           │
│  - <!-- slot:aliases -->                                     │
│  + <!-- slot:别名 -->                                        │
└─────────────────────────────────────────────────────────────┘
```

**需要新增的 API 端点：**

| 方法 | 路径 | 返回 |
|------|------|------|
| `GET` | `/api/v1/projects/{id}/templates` | `{templates: [{type, source, version}]}` |
| `GET` | `/api/v1/projects/{id}/templates/{type}` | `{type, source, content, version}` |
| `POST` | `/api/v1/projects/{id}/templates/{type}` | `{ok, type, source}` |
| `POST` | `/api/v1/projects/{id}/templates/{type}/reset` | `{ok, type}` |
| `GET` | `/api/v1/projects/{id}/templates/{type}/diff` | `{diff: [...]}` |

**新增文件：** `src/server/routes/templates.py` (~80行)，`web/js/views/templates.js` (~250行)

### 4.3 小工具合入

| 功能 | 位置 | 形式 |
|------|------|------|
| 缓存清理 | 状态页 | 按钮 + dry-run 确认 |
| 字段校验 | 浏览页 | 页面操作菜单按钮 |
| 标签校验 | 浏览页 | 标签栏"校验"按钮 |
| 存根管理 | 状态页 | 存根计数 + "生成"按钮 |

---

## 5. API 契约汇总

### 5.1 新增 API 端点一览

| 阶段 | 方法 | 路径 | 文件 |
|------|------|------|------|
| **P1** | `GET` | `/api/v1/projects/{id}/heat` | `heat.py` |
| **P1** | `POST` | `/api/v1/projects/{id}/heat/decay` | `heat.py` |
| **P1** | `POST` | `/api/v1/projects/{id}/heat/zombies/restore` | `heat.py` |
| **P1** | `POST` | `/api/v1/projects/{id}/heat/zombies/archive` | `heat.py` |
| **P1** | `GET` | `/api/v1/projects/{id}/relations/{page_id}` | `relations.py` |
| **P1** | `POST` | `/api/v1/projects/{id}/dedup` | `dedup.py` |
| **P1** | `GET` | `/api/v1/projects/{id}/dedup/status` | `dedup.py` |
| **P2** | `POST` | `/api/v1/projects/{id}/schema/upgrade` | `schema_ops.py` |
| **P2** | `POST` | `/api/v1/projects/{id}/schema/downgrade` | `schema_ops.py` |
| **P2** | `POST` | `/api/v1/projects/{id}/schema/backup` | `schema_ops.py` |
| **P2** | `GET` | `/api/v1/projects/{id}/schema/diff` | `schema_ops.py` |
| **P2** | `GET` | `/api/v1/projects/{id}/templates` | `templates.py` |
| **P2** | `GET` | `/api/v1/projects/{id}/templates/{type}` | `templates.py` |
| **P2** | `POST` | `/api/v1/projects/{id}/templates/{type}` | `templates.py` |
| **P2** | `POST` | `/api/v1/projects/{id}/templates/{type}/reset` | `templates.py` |
| **P2** | `GET` | `/api/v1/projects/{id}/templates/{type}/diff` | `templates.py` |

### 5.2 已有 API（WebUI 新增调用，后端不变）

| 阶段 | 方法 | 路径 | 已有文件 |
|------|------|------|---------|
| **P0** | `POST` | `/queue/pause` | `ingest.py` |
| **P0** | `POST` | `/queue/resume` | `ingest.py` |
| **P0** | `GET` | `/queue/status` | `ingest.py` |
| **P0** | `PATCH` | `/projects/{id}/reviews/{review_id}` | `reviews.py` |
| **P0** | `POST` | `/projects/{id}/reingest` | `ingest.py` |
| **P0** | `GET` | `/projects/{id}/ingest/tasks` | `ingest.py` |
| **P0** | `GET` | `/projects/{id}/reviews?status=resolved` | `reviews.py`（检查参数是否支持） |

---

## 6. 实施路线图

### 6.1 执行顺序

```
第1步: 前端设计定稿（本文档）→ 你确认后开始
                            ↓
第2步: P0 前端实现
       ├─ 队列控制面板    (status.js)    0.5天
       ├─ 审查项交互列表  (status.js)    0.5天
       ├─ 重新摄取按钮    (ingest.js)    0.2天
       └─ 任务历史列表    (ingest.js)    0.3天
                            ↓
第3步: P1 后端 API + 前端
       ├─ 热度管理 ── 后端 (heat.py) + 前端 (heat.js)    1.5天
       ├─ 关系增强 ── 后端 (relations.py) + 前端增强      1天
       └─ 去重管理 ── 后端 (dedup.py) + 前端按钮          0.5天
                            ↓
第4步: P2 运维工具
       ├─ Schema 迁移 ── 后端 (schema_ops.py) + 前端      1天
       └─ 模板管理 ── 后端 (templates.py) + 前端 (templates.js)  2天
```

### 6.2 每个任务的交付物

每个任务交付：
1. **后端 API 端点**（如 `heat.py`）
2. **前端视图文件**（如 `heat.js`）
3. **样式补充**（`style.css`）
4. **导航注册**（`index.html` + `app.js`）
5. **文档同步**（`webui-buttons.md`）

### 6.3 测试策略

| 层次 | 测试方式 |
|------|---------|
| 后端 API | 已有测试框架，新增端点添加对应测试 |
| 前端 | 手动测试（当前无前端测试框架） |
| 集成 | 启动 server → 打开浏览器 → 逐功能验证 |

---

## 下一步

你确认这个设计方向后，我会按以下顺序逐个实现：

1. **P0 前端实现**（已有 API，纯前端改动）
2. **P1 热度管理**（后端 + 前端，优先级最高）
3. **P1 关系增强 + 去重**
4. **P2 运维工具**