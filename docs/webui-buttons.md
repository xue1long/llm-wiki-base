# WebUI 按钮功能文档

> 本文档记录了 WebUI 所有页面的按钮位置、功能、后端 API 映射关系。
> **更新 WebUI 功能时，请同步更新本文件。**

---

## 0. 项目选择器

**文件：** [web/js/router.js](../web/js/router.js)

| 按钮 | 位置 | 功能 | 后端 API |
|------|------|------|----------|
| **新建项目 +** | 项目选择器顶部 | 输入项目名称并选择知识库场景模板后创建；默认优先选择 `novel-writing` | `GET /api/v1/scenario-templates` + `POST /api/v1/projects` |

## 1. 摄取页（Ingest）

**文件：** [web/js/views/ingest.js](../web/js/views/ingest.js)

### 1.1 URL 输入区

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **提交摄取** | 行 45 | 提交 URL 或文件路径进行摄取 | `POST /api/v1/projects/{id}/ingest` | 输入框按 Enter 也可触发 |

### 1.2 文件夹文件列表

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **提取选中** | 行 49 | 摄取勾选的文件 | `POST /api/v1/projects/{id}/ingest` (批量) | 禁用状态为 0 个选中 |
| **全部提取** | 行 56 | 摄取当前文件夹所有文件 | `POST /api/v1/projects/{id}/ingest` (批量) | |
| **全选复选框** | 行 63 | 切换全选/取消全选 | — | 纯前端行为 |
| **筛选输入框** | 行 70 | 按文件名过滤文件列表 | — | 纯前端行为 |
| **状态筛选下拉** | 行 71 | 按摄取状态过滤 | — | 纯前端行为 |

### 1.3 文件行操作

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **重新摄取** | 行 166 | 删除编译结果后重新执行完整流水线 | `POST /api/v1/projects/{id}/reingest` | P0 新增；确认后执行，进度轮询 |
| **删除** | 行 167 | 删除此文档已编译的所有 wiki 页面和向量（原始文件保留） | `POST /api/v1/projects/{id}/delete-source` | 级联删除 wiki 页面 + 清理向量 |
| **质** | 行 248/257 | 查看质检报告（modal） | `GET /api/v1/projects/{id}/quality?source_path=...` | 聚合 grade + issue + verdict + review_items + quarantine |

### 1.4 任务列表

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **重试** | 行 252 | 失败任务重新入队 | `POST /api/v1/projects/{id}/ingest` | 只在失败任务行显示 |

### 1.5 历史任务列表（P0 新增）

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **历史任务列表** | 行 38 | 自动加载最近 20 条任务记录 | `GET /api/v1/projects/{id}/ingest/tasks` | 每行显示状态图标、文件名、时间、耗时、错误信息 |

### 1.6 质检模态框

| 按钮 | 位置行号 | 功能 | 说明 |
|------|----------|------|------|
| **× 关闭** | 行 483 | 关闭质检弹窗 | 点击遮罩层也可关闭 |

---

## 2. 搜索页（Search）

**文件：** [web/js/views/search.js](../web/js/views/search.js)

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **搜索** | 行 26 | 执行混合搜索（语义+关键词） | `POST /api/v1/projects/{id}/search` | 输入框按 Enter 也可触发 |
| **搜索模式切换** | 行 31 | 切换搜索模式（语义/关键词/混合） | — | 纯前端逻辑 |

---

## 3. 聊天页（Chat）

**文件：** [web/js/views/chat.js](../web/js/views/chat.js)

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **发送** | 行 25 | 发送聊天消息 | `POST /api/v1/projects/{id}/chat` | 输入框按 Enter 也可触发 |

---

## 4. 图谱页（Graph）

**文件：** [web/js/views/graph.js](../web/js/views/graph.js)

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **+** | 行 39 | 放大知识图谱 | — | 纯前端交互 |
| **−** | 行 40 | 缩小知识图谱 | — | 纯前端交互 |
| **↺** | 行 41 | 重置缩放比例 | — | 纯前端交互 |

---

## 5. 设置页（Settings）

**文件：** [web/js/views/settings.js](../web/js/views/settings.js)

### 5.1 Provider 卡片

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **★ 设为默认** | 行 102 | 将该 provider 设为默认 | `POST /api/v1/providers/set-default` | |
| **测试** | 行 115 | 测试 provider 连接 | `POST /api/v1/providers/test?name=...` | |
| **编辑** | 行 140 | 编辑 provider 配置 | `GET /api/v1/providers/{name}` | 打开编辑模态框 |
| **删除** | 行 154 | 删除 provider | `DELETE /api/v1/providers/{name}` | |

### 5.2 添加 Provider

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **+ 添加** | 行 28 | 打开添加 provider 模态框 | — | |
| **测试**（模态框内） | 行 167 | 添加前测试连接 | `POST /api/v1/providers/test?name=...` | |
| **保存** | 行 275 | 保存新 provider | `POST /api/v1/providers` | |
| **取消** | 行 272 | 关闭模态框 | — | |
| **× 关闭** | 行 271 | 关闭模态框 | — | |

---

## 6. 状态页（Status）

**文件：** [web/js/views/status.js](../web/js/views/status.js)

### 6.1 工具栏

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **刷新** | 行 30 | 手动刷新所有状态面板 | 多个 API 并行调用 | 刷新后自动进入 30 秒轮询 |
| **取消自动刷新** | 行 34 | 停止自动轮询 | — | 刷新后显示 |

### 6.2 摄取队列面板（P0 新增）

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **暂停** | queue 面板 | 暂停摄取队列，运行中的任务完成后停止 | `POST /api/v1/queue/pause` | 暂停状态下禁用 |
| **恢复** | queue 面板 | 恢复摄取队列，继续处理待处理任务 | `POST /api/v1/queue/resume` | 运行状态下禁用 |
| **刷新** | queue 面板 | 刷新队列统计 | `GET /api/v1/queue/status` | 同步刷新所有面板 |

队列面板展示：
- 状态指示灯：绿色=运行中，黄色=已暂停，红色=熔断
- 统计卡片：待处理数 / 运行中数 / 失败数
- Circuit Breaker 状态

### 6.3 审查队列面板（P0 新增）

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **批准** | review 面板 | 接受审查项，标记为已批准 | `PATCH /api/v1/projects/{id}/reviews/{id}` | 点击后该条目消失 |
| **驳回** | review 面板 | 拒绝审查项，标记为已驳回 | `PATCH /api/v1/projects/{id}/reviews/{id}` | 点击后该条目消失 |
| **跳过** | review 面板 | 跳过审查项，不做处理 | `PATCH /api/v1/projects/{id}/reviews/{id}` | 点击后该条目消失 |

审查项列表展示：
- 类型标签（缺页/重复页/不确定声明/待核实）
- 标题 + 详情
- 置信度 + 来源路径 + 创建日期

### 6.4 信息面板（只读）

| 面板 | 后端 API | 说明 |
|------|----------|------|
| 健康检查 | `GET /health` | 服务运行状态 |
| 项目信息 | `GET /api/v1/projects/{id}` | 当前项目元数据 |
| 文件统计 | `GET /api/v1/projects/{id}/files?root=wiki` | wiki 文件数 |
| 原始文件 | `GET /api/v1/projects/{id}/raw-files` | 原始素材文件列表 |
| 知识图谱 | `GET /api/v1/projects/{id}/wiki/graph` | 图谱节点/边统计 |
| 审核队列 | `GET /api/v1/projects/{id}/reviews?status=open` | 待审核条目（交互式列表） |
| 模式版本 | `GET /api/v1/projects/{id}/schema` | 当前 schema 版本 |
| Lint 结果 | `GET /api/v1/projects/{id}/lint` | 代码检查结果 |

---

## 7. 热度页（Heat）

**文件：** [web/js/views/heat.js](../web/js/views/heat.js)

### 7.1 工具栏

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **触发衰减** | 工具栏 | 触发热度衰减，降低长期未访问页面热度 | `POST /api/v1/projects/{id}/heat/decay` | 确认后执行，展示结果 toast |
| **刷新** | 工具栏 | 刷新热度分布/Top/僵尸列表 | `GET /api/v1/projects/{id}/heat` | |

### 7.2 僵尸页操作

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **全选** | 僵尸列表 | 全选/取消全选僵尸页 | — | 纯前端行为 |
| **恢复选中** | 僵尸列表 | 恢复选中僵尸页（heat=100, is_immutable=true） | `POST /api/v1/projects/{id}/heat/zombies/restore` | body: `{page_ids: [...]}` |
| **归档选中** | 僵尸列表 | 归档选中僵尸页到 `_archive/` | `POST /api/v1/projects/{id}/heat/zombies/archive` | 确认后归档，body: `{page_ids: [...]}` |

---

## 8. 模板页（Templates）

**文件：** [web/js/views/templates.js](../web/js/views/templates.js)

| 按钮 | 功能 | 后端 API | 说明 |
|------|------|----------|------|
| **类型标签栏** | 切换模板类型（concept/entity/source/synthesis） | — | 纯前端行为 |
| **编辑/自定义** | 编辑模板内容（prompt 弹窗） | `POST /api/v1/projects/{id}/templates/{type}` | body: `{content: ...}` |
| **重置为默认** | 重置为内置默认模板 | `POST /api/v1/projects/{id}/templates/{type}/reset` | 确认后执行，备份原文件 |
| **对比差异** | 对比自定义与内置模板差异 | `GET /api/v1/projects/{id}/templates/{type}/diff` | 展开 diff 面板 |
| **刷新** | 刷新模板列表 | `GET /api/v1/projects/{id}/templates/{type}` | |

---

## 浏览页（Browse）

| 按钮 | 位置行号 | 功能 | 后端 API | 说明 |
|------|----------|------|----------|------|
| **标签展开更多** | 行 72 | 展开/折叠标签列表 | — | 纯前端交互 |
| **标签过滤** | 行 87 | 按标签筛选文件 | — | 纯前端交互 |
| **文件/目录展开** | 行 198 | 展开/折叠目录树 | — | 纯前端交互 |
| **文件编辑** | 行 257 | 点击文件行打开编辑 | `GET /api/v1/projects/{id}/files/content?path=...` | |

---

## 新增按钮流程

在 WebUI 新增功能按钮时：

1. 在对应视图文件（`web/js/views/*.js`）中添加按钮 DOM
2. 绑定事件监听器，调用 `App.api()` 或 `fetch()`
3. 在 `web/style.css` 中添加按钮样式
4. **同步更新本文档**，添加按钮行

---

## 快速定位对照表

| 想找什么 | 去哪个文件 | 搜索关键词 |
|----------|-----------|-----------|
| 摄取相关按钮 | `ingest.js` | `ingest\|reingest\|quality\|质\|taskHistory` |
| 搜索按钮 | `search.js` | `search\|qBtn\|搜索` |
| 聊天按钮 | `chat.js` | `chat\|chatBtn\|发送` |
| 图谱按钮 | `graph.js` | `graph\|zoom\|图谱` |
| 热度管理 | `heat.js` | `heat\|decay\|zombie\|僵尸\|热度` |
| 模板管理 | `templates.js` | `template\|diff\|reset\|模板` |
| 设置按钮 | `settings.js` | `provider\|settings\|设置\|添加\|删除\|编辑` |
| 状态页面 | `status.js` | `status\|refresh\|刷新\|queue\|review\|审查` |
| 浏览文件 | `browse.js` | `browse\|tag\|浏览\|文件` |
| 后端 API 调用 | `api.js` | `App.api\|fetch` |
| 样式 | `style.css` | 按钮类名 |
