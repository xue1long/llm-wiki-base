# ruflo-kb WebUI 设计优化 — 执行方案

> 基于 [`docs/web-design-proposal.md`](web-design-proposal.md)，按优先级分 4 个阶段执行。
> 每阶段结束后验证全部视图可用再进入下一阶段。

---

## 阶段 0：基础设施（P0，预计 2-3 个 session）

### 0.1 CSS 变量体系重构

**目标**：将 `web/style.css`（598 行）中所有硬编码颜色替换为 CSS 自定义属性，同时预置深色变量。

**步骤**：

1. 在 `style.css` 顶部 `:root` 中定义完整变量集（对应方案 §4.1–4.3）
2. 逐类替换硬编码值 → `var(--xxx)`
   - 先替换背景色（`#f5f6f8` → `var(--bg-app)` 等）
   - 再替换文字色（`#1f2329` → `var(--text-primary)` 等）
   - 再替换边框/阴影/圆角
3. 同步预置 `[data-theme="dark"]` 深色变量（值先设占位，后续 §2.3 补充）
4. 字体层级：新增 `.h1`/`.h2`/`.h3`/`.h4`/`.text-body`/`.text-meta`/`.text-code` 工具类
5. 按钮/输入框 focus ring 统一为 `box-shadow: 0 0 0 3px var(--accent-ring)`

**验证**：
- `grep -nE '#[0-9a-fA-F]{3,6}' web/style.css` 返回 0（无硬编码颜色残留）
- 启动 `python -m src.cli serve`，逐个视图目视检查配色无异常
- 切换 `data-theme="dark"` 确认变量注入生效

**涉及文件**：`web/style.css`

---

### 0.2 JS 分文件

**目标**：将 `web/app.js`（1570 行）拆分为多个 `<script>` 标签，不改逻辑只改加载方式。

**拆分方案**：

```
web/
├── index.html          (更新 <script> 加载顺序)
├── style.css
├── js/
│   ├── api.js           API 封装 (fetch 包装器)
│   ├── router.js         SPA 路由 + state + 公共工具 (normalizeWikiPath, renderMd, parseFrontmatter, setBanner)
│   ├── views/
│   │   ├── search.js    renderSearch
│   │   ├── browse.js    renderBrowse + renderBrowseRaw + 标签筛选逻辑
│   │   ├── ingest.js    renderIngest
│   │   ├── chat.js      renderChat
│   │   ├── graph.js     renderGraph + 力导向布局
│   │   ├── status.js    renderStatus
│   │   └── settings.js  renderSettings
│   ├── agent-panel.js   setupAgentPanel + SSE 流解析
│   └── app.js           初始化入口 (project 检测 → 挂载视图 → showView 默认页)
```

**步骤**：

1. 创建 `web/js/` 目录结构
2. 提取 `api.js`：`api()` 函数 + `API_BASE` 常量
3. 提取 `router.js`：`state` 对象 + `showView()` + `setBanner()` + 公共工具函数
4. 提取各 `views/*.js`：每个文件一个 IIFE，通过 `window.App` namespace 访问共享状态
5. 提取 `agent-panel.js`
6. 重写 `app.js` 为入口：`App.init()` 执行 project 检测、挂载视图、设置默认页
7. 更新 `index.html`：按依赖顺序加载 `<script>` 标签

**Namespace 约定**：
```javascript
// 全局唯一 namespace
window.App = {
  state: { ... },        // 共享状态
  api: { ... },          // API 函数
  router: { ... },       // showView, setBanner, navigate
  views: { ... },        // renderSearch, renderBrowse, ...
  agent: { ... },        // setupAgentPanel, sendAgentMessage
  init() { ... }         // 入口
};
```

**验证**：
- 7 个视图全部正常渲染，无 `ReferenceError`
- Agent 面板 SSE 流正常
- 项目切换正常（project selector → 刷新各视图数据）
- Wikilink 点击跳转正常
- 浏览页 Raw 文件摄取按钮正常

**涉及文件**：`web/index.html`、`web/app.js`（重写）、`web/js/*`（新建 11 个文件）

---

### 0.3 响应式断点占位

**目标**：在 CSS 中预留断点变量和空 media query，避免后续返工。

**步骤**：

1. `:root` 中新增：
   ```css
   --bp-tablet: 1024px;
   --bp-mobile: 768px;
   --sidebar-width: 220px;
   --sidebar-collapsed: 64px;
   --agent-width: 340px;
   --agent-collapsed: 48px;
   ```
2. 在 `style.css` 末尾添加空 media query 骨架：
   ```css
   @media (max-width: 1024px) { /* tablet: P2 实现 */ }
   @media (max-width: 768px)  { /* mobile: P2 实现 */ }
   ```
3. 将布局相关宽度替换为上述变量引用

**验证**：布局行为与替换前完全一致

**涉及文件**：`web/style.css`

---

## 阶段 1：核心交互（P1，预计 4-5 个 session）

### 1.1 布局微调

**目标**：侧栏可折叠 + Agent 面板默认折叠。

**步骤**：

1. 侧栏折叠按钮（`#sidebar` 底部 `◀/▶` 图标），点击切换 `.collapsed` 类
   - 展开：220px，显示图标+文字+项目列表
   - 折叠：64px，仅显示图标，hover 展开临时浮层显示文字
2. Agent 面板默认加 `.collapsed` 类（当前已有折叠逻辑，只改初始状态）
3. 面包屑组件：根据 `state.currentView` 和浏览页当前路径动态渲染顶栏面包屑

**验证**：
- 侧栏折叠/展开动画流畅（`transition: width 0.2s`）
- Agent 默认 48px 折叠态，点击展开到 340px
- 面包屑正确反映当前位置（搜索→`搜索`，浏览→`浏览 > concepts > 画面感`）

**涉及文件**：`web/style.css`、`web/js/router.js`、`web/index.html`

---

### 1.2 后端 API 变更（前置）

> 浏览页标签筛选器和摄取页工作台依赖以下 API 变更，必须先于前端实现。

#### 1.2.1 新建 `GET /api/v1/projects/{id}/tag-index`

**返回格式**：
```json
{
  "namespaces": {
    "genre": {"label": "题材", "tags": [{"name": "玄幻", "count": 12}, ...]},
    "func":  {"label": "功能", "tags": [{"name": "写作技巧", "count": 34}, ...]},
    ...
  }
}
```

**实现**：遍历 wiki 目录下所有 `.md` 文件，解析 frontmatter `tags` 字段，按 namespace 聚合计数。在 `src/server/routes/` 新增 `tags.py` 路由。

#### 1.2.2 扩展 `GET /api/v1/projects/{id}/files`

增加查询参数 `include_tags=true`，返回条目增加 `tags: [...]` 字段。

#### 1.2.3 扩展 `POST /api/v1/projects/{id}/search`

增加可选请求体字段 `type: "concept" | "entity" | "source" | "synthesis"`，后端 `hybrid_search` 支持按 PageType 过滤。

#### 1.2.4 扩展 `GET /api/v1/projects/{id}/raw-files`

返回条目增加 `created_at` 字段（文件创建时间戳）。

**验证**：`pytest tests/test_server/ -v -k tag` 新增测试通过

**涉及文件**：`src/server/routes/tags.py`（新建）、`src/server/routes/files.py`、`src/server/routes/search.py`、`src/services/search.py`、`tests/test_server/test_service_search.py`

---

### 1.3 浏览页：标签筛选器 + 移除 Raw 子标签 + TOC/面包屑/反向链接

**步骤**：

1. **标签筛选器**（前端 `views/browse.js`）
   - 页面加载时调用 `GET /tag-index` 获取标签聚合数据
   - 渲染 namespace 行 chip 列表（默认展开前 4 个 namespace）
   - 实现交互规则（同 namespace OR、跨 namespace AND、客户端即时筛选）
   - 已选 chip 点击 × 移除；点击 tag 所属 namespace 自动展开
   - 文件树节点计数动态更新；无匹配目录自动折叠；无结果时显示空状态提示
2. **移除 Raw 文件子标签页**
   - 删除 `views/browse.js` 中的 `_browseSub` 状态和 `renderBrowseRaw()` 渲染逻辑
   - Raw 文件相关代码迁移到 `views/ingest.js`（见 §1.4）
3. **TOC（目录导航）**
   - 阅读器顶部解析 markdown `##`/`###` 标题，生成锚点链接列表
   - 点击锚点平滑滚动到对应位置
   - 当前阅读位置高亮对应 TOC 条目（`IntersectionObserver`）
4. **面包屑**（已在 §1.1 实现基础组件，此处接入浏览页路径数据）
5. **反向链接**
   - 调用 `GET /files/content` 读取当前页面 frontmatter `relations` 字段
   - 在正文底部渲染"相关笔记"列表，每项可点击跳转
6. **Wikilink 点击**（当前已有实现，验证拆分后正常工作）

**验证**：
- 标签筛选：选 `题材/玄幻` + `情绪/爽文` → 文件树仅显示同时有这两个标签的页面
- 文件树计数实时更新
- "展开更多 ▼"可切换 namespace 行显示
- TOC 锚点跳转正确，滚动时高亮跟随
- 反向链接列表可点击跳转

**涉及文件**：`web/js/views/browse.js`、`web/style.css`

---

### 1.4 摄取页：Raw 文件工作台

**目标**：将 Raw 文件列表从浏览页迁移到摄取页，改造为勾选批量摄取 + 进度面板。

**步骤**：

1. **左侧文件列表**
   - 复用 §1.3 中迁移过来的 `renderBrowseRaw()` 逻辑
   - 改为表格行布局（checkbox + 图标 + 路径 + 日期 + 大小 + 状态）
   - 实现全选/单选/排序（路径/时间/大小/状态）/筛选（文件名输入+状态下拉）
2. **工具栏**
   - 全选（仅未摄取）、提取选中(N)、全部提取
   - "全部提取"采用并发控制：每次 5 个并行 POST，间隔 500ms
3. **右侧进度面板**
   - 复用现有轮询逻辑（每 1.5s 轮询 `GET /ingest/status/{taskId}`）
   - 改为多任务并行展示：总进度条 + 每条独立状态行
   - 失败项显示错误摘要 + 重试按钮
   - "清空已完成"移除成功条目
4. **手动添加路径**（保留当前功能，移至进度面板下方）

**验证**：
- 勾选 3 个文件 → `[提取选中(3)]` → 右侧进度面板出现 3 个任务
- 进度条实时更新，完成后显示 ✅
- 失败项点重试 → 重新入队
- 全部提取"并发控制生效（5 个/批）
- 摄取完成后切换到浏览页，Wiki 树自动出现新文件

**涉及文件**：`web/js/views/ingest.js`、`web/style.css`

---

### 1.5 搜索结果卡重设计

**目标**：搜索结果卡增加类型标签、关键词高亮、统计摘要。

**步骤**：

1. 搜索栏改为 100% 宽，移除 mode 下拉框
2. 新增类型筛选 radio button（全部/概念/实体/来源/综合）
3. 搜索结果卡增加类型标签（concept=蓝/entity=绿/source=橙/synthesis=紫，与图谱配色统一）
4. 内容片段中关键词高亮（前端 `<mark>` 包裹）
5. 统计行格式：`找到 N 条结果（关键词 M，语义 K）`；语义为 0 时灰色低亮
6. 搜索中显示 loading spinner（替换按钮文字为旋转动画）

**验证**：
- 类型筛选切换 → 搜索结果按 PageType 过滤
- 关键词在结果片段中黄色高亮
- 语义结果 0 时灰色显示，不变黄/不变红

**涉及文件**：`web/js/views/search.js`、`web/style.css`

---

### 1.6 全局反馈系统

**目标**：骨架屏 + 空状态 + Toast 通知。

**步骤**：

1. **骨架屏**（纯 CSS）
   - `.skeleton` 类：灰色脉冲动画（`@keyframes shimmer`），圆角 8px
   - 搜索/浏览/摄取/状态页各一个骨架变体（匹配各自卡片布局）
2. **空状态**（纯 HTML + CSS）
   - `.empty-state` 组件：居中的 emoji 图标 + 提示标题 + 副标题文字
   - 每个视图的空状态文案定制（见方案 §5 各视图的空状态描述）
3. **Toast 通知**（JS）
   - `App.toast(message, type)` 函数挂载到全局 namespace
   - 类型：`success`（绿色）/ `error`（红色），右上角滑入，3s 消失
   - 支持手动关闭（× 按钮）
   - `setBanner()` 保留用于页面级持久通知（如"未连接"）

**验证**：
- 页面加载中显示骨架屏而非空白
- 搜索无结果时显示空状态提示
- API 报错时右上角滑入红色 Toast

**涉及文件**：`web/style.css`、`web/js/router.js`

---

## 阶段 2：体验提升（P2，预计 2-3 个 session）

### 2.1 暗色模式

**目标**：基于 P0 预置的 CSS 变量，实现自动/手动暗色模式切换。

**步骤**：

1. 完善 `[data-theme="dark"]` 下各 CSS 变量值（参考 Tailwind dark palette）
2. 顶栏 `🌙` 按钮切换 `data-theme` 属性（`light` / `dark` / `auto`）
3. `auto` 模式：`matchMedia('(prefers-color-scheme: dark)')` 监听系统变化
4. 偏好存入 `localStorage`，下次打开自动恢复

**验证**：
- 切换 dark → 所有视图配色正确（无刺眼白色卡片残留）
- 系统切换暗色 → 自动跟随（auto 模式）
- 刷新页面后偏好保持

**涉及文件**：`web/style.css`、`web/js/router.js`

---

### 2.2 响应式布局（完整实现）

**目标**：基于 P0 断点骨架实现平板/手机适配。

**步骤**：

1. **平板（768–1024px）**：Agent 默认折叠，侧栏收窄到 180px
2. **手机（< 768px）**：
   - 单栏布局，顶栏汉堡 `☰` 按钮控制侧栏抽屉滑入/滑出
   - Agent 面板从底部抽屉滑入（`:fixed bottom-0`，占 60% 屏幕高度）
   - 浏览页左右分栏改为上下堆叠（树在上，阅读器在下）
   - 设置页 Provider 卡片改为单列
   - 搜索栏控件垂直堆叠

**验证**：
- Chrome DevTools 模拟 iPhone 14 / iPad 无布局溢出
- 所有视图可正常操作（不依赖 hover 交互——移动端用 tap 替代）

**涉及文件**：`web/style.css`、`web/index.html`

---

### 2.3 图谱 hover tooltip + zoom 控件

**目标**：为现有力导向图补充两个交互功能。

**步骤**：

1. **hover tooltip**：SVG `<title>` 元素或绝对定位 `<div>`，显示节点标题+类型+关联边数
2. **zoom 控件**：图谱区右下角 `[+] [-] [↺ 重置]` 按钮组，操作 SVG `viewBox` 缩放
3. 确保 zoom 控件与滚轮缩放/拖拽不冲突

**验证**：
- hover 节点显示 tooltip
- zoom +/- 按钮缩放正常，重置按钮恢复默认

**涉及文件**：`web/js/views/graph.js`、`web/style.css`

---

### 2.4 状态页微调

**步骤**：

1. 顶部新增 4 个指标卡汇总行（wiki 页数/原始源/图谱节点/LLM 调用量）
2. 健康条目 `ok` → ✓（绿）、`bad` → ✗（红）
3. 「刷新」按钮旁加 30s 倒计时（`setInterval`，可点击取消）

**验证**：指标卡数值正确，倒计时归零后自动刷新

**涉及文件**：`web/js/views/status.js`、`web/style.css`

---

### 2.5 设置页 Provider 卡片化

**步骤**：

1. Provider 列表改为 CSS Grid 卡片布局（`auto-fit, minmax(320px, 1fr)`）
2. 每张卡片：名称 + 类型标签 + 星标（★/☆ 切换默认）+ Model/URL/Key 信息 + 测试/删除按钮
3. 「+ 添加」按钮 → 模态框（表单含类型单选区 + 字段输入 + API Key 显隐切换）
4. 测试按钮 → 卡片底部 3s 结果横幅
5. 删除按钮 → 二次确认微型弹窗
6. 预设类型选择后自动填充 Base URL

**验证**：
- 点击 ☆ → API 调用 set-default → 星标切换（旧默认变 ☆，新默认变 ★）
- 模态框"取消"关闭不提交，"添加"成功后卡片列表自动刷新
- 测试失败 → 红色横幅显示错误信息

**涉及文件**：`web/js/views/settings.js`、`web/style.css`

---

## 阶段 3：效率增强（P3，预计 1 个 session）

### 3.1 键盘快捷键

**步骤**：

1. `Ctrl+/` → 聚焦搜索输入框并切到搜索页
2. `Ctrl+B` → 切换到浏览页
3. `Esc` → 关闭当前模态框/弹窗/Agent 面板（如果展开）
4. 快捷键提示在页面底部以半透明浮层展示（首次打开时显示 5s，之后按 `?` 查看）

**验证**：各快捷键行为正确，不与浏览器默认快捷键冲突（`Ctrl+B` 在部分浏览器是书签栏，需 `preventDefault`）

**涉及文件**：`web/js/router.js`

---

## 依赖关系图

```
阶段 0 (基础设施，可并行)
├── 0.1 CSS 变量体系 ─────────────────────────────┐
├── 0.2 JS 分文件 ────────────────────────────────┤
└── 0.3 响应式断点占位 ───────────────────────────┤
                                                   │
阶段 1 (核心交互)                                   │
├── 1.1 布局微调 ←── 依赖 0.1, 0.2                │
├── 1.2 后端 API 变更 ←── 独立，无前端依赖         │
├── 1.3 浏览页改造 ←── 依赖 0.2, 1.2.1, 1.2.2     │
├── 1.4 摄取页改造 ←── 依赖 0.2, 1.2.4, 1.3       │
├── 1.5 搜索卡重设计 ←── 依赖 0.2, 1.2.3          │
└── 1.6 全局反馈 ←── 依赖 0.1, 0.2                │
                                                   │
阶段 2 (体验提升)                                   │
├── 2.1 暗色模式 ←── 依赖 0.1                     │
├── 2.2 响应式 ←── 依赖 0.3, 1.1                  │
├── 2.3 图谱增强 ←── 依赖 0.2                     │
├── 2.4 状态页微调 ←── 依赖 0.2                    │
└── 2.5 设置页改造 ←── 依赖 0.2                    │
                                                   │
阶段 3 (效率增强)                                   │
└── 3.1 键盘快捷键 ←── 依赖全部完成                │
```

---

## 每步通用验证清单

```bash
# 启动服务
python -m src.cli serve --host 127.0.0.1 --port 8765

# 浏览器打开 http://127.0.0.1:8765

# 手动检查：
# - [ ] 7 个视图正常渲染
# - [ ] Agent 面板折叠/展开正常
# - [ ] 项目切换正常
# - [ ] 侧栏导航高亮正确
# - [ ] HTTP 500 不出现
# - [ ] 控制台无 JS 报错

# 后端测试：
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -x -q
```

---

## 文件变更总览

| 文件 | 阶段 | 操作 |
|------|------|------|
| `web/style.css` | 0.1, 0.3, 1.x, 2.x | 全量重构 |
| `web/index.html` | 0.2 | 更新 `<script>` 顺序 |
| `web/app.js` | 0.2 | 重写为入口文件 |
| `web/js/api.js` | 0.2 | 新建 |
| `web/js/router.js` | 0.2, 1.1, 1.6, 3.1 | 新建 |
| `web/js/views/search.js` | 0.2, 1.5 | 新建 |
| `web/js/views/browse.js` | 0.2, 1.3 | 新建 |
| `web/js/views/ingest.js` | 0.2, 1.4 | 新建 |
| `web/js/views/chat.js` | 0.2 | 新建（不改逻辑） |
| `web/js/views/graph.js` | 0.2, 2.3 | 新建 |
| `web/js/views/status.js` | 0.2, 2.4 | 新建 |
| `web/js/views/settings.js` | 0.2, 2.5 | 新建 |
| `web/js/agent-panel.js` | 0.2 | 新建（不改逻辑） |
| `src/server/routes/tags.py` | 1.2.1 | 新建 |
| `src/server/routes/files.py` | 1.2.2 | 修改 |
| `src/server/routes/search.py` | 1.2.3 | 修改 |
| `src/services/search.py` | 1.2.3 | 修改 |
| `src/server/app.py` | 1.2.1 | 注册新路由 |
| `tests/test_server/test_tag_index.py` | 1.2.1 | 新建 |
| `tests/test_server/test_service_search.py` | 1.2.3 | 修改 |
