# A 吸收 B 优点完善 WebUI —— 实施方案

> 日期：2026-08-10
> A = `D:\5-Project\LLM-Wiki`（当前生产管线方向，已含本会话 T1b/T2/T3/T4/T6/T7/T8/T9 前端增强）
> B = `D:\5-Project\LLM-Wiki-7-31\LLM-Wiki`（Knowledge-OS 研究方向）

## 0. 前置结论（必须先校正的前提）

**B 的 WebUI 并不是全面领先 A。** 经逐文件核对：

- 两边 `web/js/` **文件集完全相同**（13 个：api/app/router/agent-panel + 7 个 views）。
- 仅 **5 个文件**内容不同：`ingest.js`、`search.js`、`settings.js`、`status.js`、`style.css`。
- 逐文件谁领先：

| 文件 | 谁领先 | 说明 |
|---|---|---|
| `search.js` | **A** | A 有 mode 分段选择器（混合/关键词/语义，T3）；B 硬编码 `mode:"hybrid"` |
| `settings.js` | **A** | A 有独立 Embedding 模型配置（T7）；B 把对话模型当 embedding 模型 |
| `status.js` | **A** | A 有队列暂停/恢复按钮 + 审核卡 resolve/reject（T9）；B 无 |
| `ingest.js` + `style.css` | **B** | B 有 ingest 页**实时队列管理面板**；A 只有静态「任务历史」面板 |
| `package.json`/构建系统 | 均无 | B 的 `node_modules`（2730 文件）是孤儿（无 package.json），**不能构建**，无借鉴价值 |

**所以「A 从 B 吸收 WebUI 优点」精确指向一项：把 B 的 ingest 页实时队列面板移植到 A。** 其余「完善 WebUI」应按 A 自身设计文档未落地项推进，不必盯着 B。

---

## 1. 吸收 B 的真实优点（低风险，纯前端，核心一项）

### P1.1 移植 B 的 ingest 页「实时队列管理面板」到 A

**目标**：在摄取页直接实时监控队列（状态徽章 + 统计 + 暂停/恢复 + 实时任务列表 + 10s 自动刷新），与 A 已有的「任务历史」面板并存。

**改动文件**（2 个，不动后端）：
- `web/js/views/ingest.js`
- `web/style.css`

**具体内容**：
1. HTML：在 ingest 页加 `ingest-queue-panel` 块（状态徽章 `queueStatusBadge`、统计 `qPending/qRunning/qFailed`、按钮 `queuePauseBtn/queueResumeBtn/queueRefreshBtn`、任务列表 `queueTaskList`）。直接复用 B 的标记结构。
2. JS 函数（从 B 搬，见 B `ingest.js:111-136`）：
   - `loadQueueStatus()`：拉队列状态、渲染徽章（running/paused）、显隐暂停/恢复按钮、填统计。
   - `toggleQueuePause(doPause)`：触发暂停/恢复。
   - `setInterval(loadQueueStatus, 10000)`：自动刷新（B 用 10s）。
   - 复用 A 已有 `loadTaskHistory()`（GET `/api/v1/projects/{id}/ingest/tasks`）填充任务列表——**A 后端已返回该数据**，无需新增。
3. CSS：把 B `style.css:633-679` 的 `.ingest-queue-panel*` 整段搬入 A 的 `style.css`，变量（`--bg-surface/--border/--radius/--success-light` 等）A 已全部定义，风格天然一致。

**⚠️ 必改坑（B 代码不能直接抄）**：`App.api(path)` 是 `window.location.origin + path`，**不自动加前缀**。
- B 写的是 `App.api("/queue/status")`、`App.api("/queue/pause"|"/queue/resume")` → 会打到 `/queue/...`，而 **A 后端路由是 `/api/v1/queue/status`、`/api/v1/queue/{pause,resume}`** → 直接 404。
- **移植时必须改成** `/api/v1/queue/status`、`/api/v1/queue/pause`、`/api/v1/queue/resume`（与 A 的 `status.js` T9 保持一致）。`/api/v1/projects/{id}/ingest/tasks` 两边路径已一致，不用改。

**后端依赖**：A 后端**已全部具备**，零后端改动——
- `GET /api/v1/queue/status`（返回 `{paused, ...}`）
- `POST /api/v1/queue/pause` / `POST /api/v1/queue/resume`
- `GET /api/v1/projects/{id}/ingest/tasks`

**验证**：
- `node --check web/js/views/ingest.js`（语法）
- 本机 `python -m src.cli serve` 起服务 → 打开 ingest 页：徽章显示「运行中/已暂停」、统计随时间变化、任务列表随摄取自动刷新；点暂停→后端返回成功且徽章变「已暂停」、恢复同理。
- 回归：A 原有「任务历史」面板、`batchIngest` 入队逻辑不受影响。

**工作量**：约 0.5 天，纯前端，可立即执行。

---

## 2. A 自身 WebUI 完善（达成「完善功能」目标，与 B 无关）

这些才是真正补齐 A 短板的项（源自本会话早前「设计文档 Phase2-3 未落地」核查）：

- **P2.1 浏览页 `browse.js` 增强**：左侧标签筛选（受控前缀 `genre/func/char/...`）、笔记 TOC 目录、反向链接面板。后端已有 wiki 笔记 + tags，可直接对接。
- **P2.2 图谱页 `graph.js` 增强**：节点 hover tooltip、滚轮缩放/拖拽、点击实体弹详情卡。A 后端有 novel-wiki 的 concepts/entities 关系数据可用。
- **P2.3 搜索结果体验**：T8 已回填 `tokenHits`（关键词）/ `vectorHits`（语义），前端可展示命中来源徽章 + 命中片段高亮，让用户区分「为什么命中」。
- **P2.4 全局打磨**：响应式布局（移动端/窄屏）、常用快捷键（如 `/` 聚焦搜索、`g` 跳图谱）。设计文档提及未做。
- **P2.5 前端工程化（真正缺口）**：两边都无 `package.json`/构建系统，纯 `<script>` 直引。建议给 A 的 `web/` 加最小 `package.json` + Vite dev server（热更新 + 打包），**不改变现有 vanilla JS 结构**，只加开发体验。低风险，但要确认 `index.html` 引用方式兼容（先验证再切）。

---

## 3. 不可吸收项（诚实边界，勿踩坑）

B 的 Knowledge-OS 前端特性——**溯源 lineage 视图、演化/衰减看板、冲突/主张（conflicts/claims）浏览器、memory 检索 UI**——全部依赖 B 的 `src/knowledge/` 后端内核（graph/evolution/provenance/memory/...）。**A 后端已移除该架构（换成 orchestrator/server/searcher/schemas 生产管线）**，这些能力在 A 中不存在，前端无从对接。

→ 除非先在 A 后端重建对应能力（超范围，建议单独立项），否则**不要**尝试把 B 的 knowledge 相关前端搬过来，搬了也是死界面。本次方案不包含此项。

---

## 4. 优先级与落地顺序

| 优先级 | 项 | 性质 | 后端改动 |
|---|---|---|---|
| **P0（立即）** | P1.1 移植 ingest 实时队列面板 | 吸收 B 唯一真实优点，纯前端低风险 | 无 |
| P1 | P2.1 浏览页增强 / P2.2 图谱增强 | 纯前端 + 已有后端数据 | 无（或极小） |
| P2 | P2.3 搜索命中展示 / P2.4 响应式快捷键 | 纯前端打磨 | 无 |
| P3 | P2.5 前端工程化（Vite） | 工程改进，可选 | 无 |
| 不做 | 第 3 节 Knowledge-OS 前端 | 缺后端，超范围 | 需重建后端 |

---

## 5. 风险与回滚

- P1.1 为**增量追加**（新增面板 + 新增 CSS 段 + 新增两个函数 + 一个定时器），不删改 A 现有 `ingest-history` 逻辑；若出问题，删新增片段即可回滚，不影响已有摄取流程。
- 定时器 `setInterval` 须在视图切换/`App.renderIngest` 重建时清理，避免多处 ingest 视图叠加刷新（B 用了一个脆弱的 `_origRender` hack；**A 移植时建议用 MutationObserver 或视图卸载钩子正确清理**，不要照搬 B 的 hack）。
- 所有新增 API 路径必须带 `/api/v1` 前缀（见 P1.1 坑），上线前用 `node --check` + 实机点测确认。

---

## 附：B 队列面板关键代码位置（移植参照）

- 标记：`B/web/js/views/ingest.js:32-50`（panel HTML）、`:66-74`（事件绑定 + 定时器）
- 函数：`B/web/js/views/ingest.js:111-136`（`loadQueueStatus` / `toggleQueuePause`）、`:138-`（`loadTaskHistory` 任务行渲染 `queue-task-row`）
- 样式：`B/web/style.css:633-679`（`.ingest-queue-panel*`）
- A 同义后端端点：`GET /api/v1/queue/status`、`POST /api/v1/queue/pause|resume`、`GET /api/v1/projects/{id}/ingest/tasks`（A `status.js` T9 已用前两者，`ingest.js` 已用第三者）
