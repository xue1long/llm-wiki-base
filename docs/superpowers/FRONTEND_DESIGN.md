# ruflo-kb 前端设计方案（实现规格书）

> 本文档是**实现规格**，交给 LLM/开发者直接照做即可，无需再去读后端源码。
> 目标：给 ruflo-kb 知识库做一个 Web 前端（搜索 / 浏览 / 摄取 / 知识库对话 / 状态 / **本地 Agent CLI**），
> 纯静态、零构建，由现有 FastAPI 服务同源托管。

---

## 1. 目标与约束

- 用户已有后端：`python -m src.cli serve` 起 FastAPI，基址 `http://127.0.0.1:19828`。
- 当前后端**只吐 JSON**，无前端、无 CORS、无静态托管。
- 目标：做一个单页 Web 应用，实现 6 块功能：**搜索(A)、浏览(B)、摄取(C)、知识库对话(D)、状态(E)、本地 Agent CLI 聊天面板(F，右侧常驻)**。
- 约束：用户不懂前端，方案必须**零构建、零 npm、双击即用**；浏览器打开即见界面。

## 2. 技术选型（已定，不要改）

| 项 | 选择 | 理由 |
|---|---|---|
| 形态 | 单页应用（SPA），左侧导航 + 中间内容区 + **右侧常驻 agent 面板** | 一个页面切视图，agent 面板全局可聊 |
| 逻辑 | 原生 JavaScript（ES2020+），不用框架构建 | 零构建，浏览器直接跑 |
| 样式 | 手写 CSS，**浅色系**（背景白/浅灰，文字深色） | 用户 IDE 为浅色主题 |
| Markdown 渲染 | CDN 引入 marked：`https://cdn.jsdelivr.net/npm/marked/marked.min.js` | 一个 `<script>` 标签即可渲染 `.md` 为 HTML，无构建 |
| 前端服务器 | **不要**，由 FastAPI 同源托管 | 省掉 dev server / 代理 / CORS 麻烦 |
| 本地 Agent | 后端子进程调本机 `claude` CLI（claude code headless 模式） | 浏览器无法直接调本地进程，必须后端中转（见 §4.4 / §12） |
| 依赖 | 除 marked 外**零依赖** | 若用户离线，可改为内联一个极简 md 渲染函数作为兜底（见 §10） |

## 3. 交付物与文件结构

```
E:\2026-7-21\ruflo-kb\
├── web/                            # ← 新建，FastAPI 挂载到 "/"
│   ├── index.html                  # 单页骨架：侧边栏 + 主区容器 + 右侧 agent 面板 + 引入 app.js/style.css/marked
│   ├── app.js                      # 全部逻辑：API 封装 + 视图切换 + 6 块功能的渲染与交互
│   └── style.css                   # 全部样式（浅色系）
└── src/server/
    ├── app.py                      # ← 改：加 CORS + 静态托管 + 注册 agent_cli 路由（见 §4）
    └── routes/
        └── agent_cli.py            # ← 新建：本地 claude CLI 桥接端点（见 §4.4）
```

- `index.html` 约 50 行骨架。
- `app.js` 约 450–650 行。
- `style.css` 约 200–260 行。
- 后端：`app.py` 约 +18 行；新建 `agent_cli.py` 约 +120 行。

## 4. 后端改动

### 4.1 import（src/server/app.py 顶部新增）
- `from fastapi.middleware.cors import CORSMiddleware`
- `from fastapi.staticfiles import StaticFiles`
- `from pathlib import Path`（若未导入）

### 4.2 CORS + 静态托管（在 create_app() 内，所有 router 注册之后）
- 加 CORS：`app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])`
- 静态托管：
  - `WEB_DIR = Path(__file__).resolve().parents[2] / "web"`（`app.py` 在 `src/server/app.py`，`parents[0]=server`、`parents[1]=src`、`parents[2]=项目根`）
  - `if WEB_DIR.is_dir(): app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")`
  - `html=True` 使 `/` 返回 `web/index.html`；API 路由（`/api/...`、`/health`、`/docs`）已先注册，优先命中，**不冲突**。

### 4.3 注册 agent_cli 路由
- 在 app.py 现有 `include_router(...)` 区域，仿照其它路由：`from .routes import agent_cli` 然后 `app.include_router(agent_cli.router, prefix="/api/v1", tags=["agent-cli"])`。
- **务必放在静态 mount 之前**。

### 4.4 新增 `src/server/routes/agent_cli.py`（本地 claude CLI 桥接）

新建一个 APIRouter，提供两个端点。核心：**用 `asyncio.create_subprocess_exec` 异步调本机 `claude`，参数用数组传递，绝不拼 shell 字符串**（见 §12 安全）。

顶部可配置常量：
- `CLAUDE_CMD = "claude"`（claude code 的可执行名；若在 PATH 找不到，status 端点会报不可用）
- `PERMISSION_MODE = "acceptEdits"`（**用户已拍板**：允许 claude 自动修改文件；风险见 §12。想改回只读用 `"plan"`）
- `MAX_TURNS = 8`、`TIMEOUT_S = 180`、`MAX_BUDGET_USD = None`（可设为 `"1.00"` 限花费）
- `EXTRA_ARGS = []`（如 `["--bare"]` 加速，或 `["--allowedTools", "Read,Grep,Glob"]` 进一步限工具）
- `WORKDIR = 项目根路径`（`Path(__file__).resolve().parents[3]`：routes→server→src→根）

**端点 1：`GET /api/v1/agent-cli/status` —— 检测 claude 是否可用**
- 实现：`proc = await asyncio.create_subprocess_exec(CLAUDE_CMD, "--version", stdout=PIPE, stderr=PIPE)`，`await asyncio.wait_for(proc.communicate(), 10)`。
- 成功（returncode==0）→ `{ "available": true, "version": "<stdout 第一行>" }`
- 找不到命令（FileNotFoundError）→ `{ "available": false, "error": "claude CLI 未安装或不在 PATH。请先安装 claude code 并登录。" }`
- 其它失败 → `{ "available": false, "error": "<stderr 或异常>" }`
- **始终 HTTP 200**（用 body 的 available 表达），前端据此显示状态点。

**端点 2：`POST /api/v1/agent-cli/chat` —— 与 claude 对话**
- 请求体（Pydantic）：`{ "message": str, "sessionId": str | None = None }`
- 逻辑：
  1. 组装命令数组：`cmd = [CLAUDE_CMD, "-p", message, "--output-format", "json", "--permission-mode", PERMISSION_MODE, "--max-turns", str(MAX_TURNS)] + EXTRA_ARGS`
  2. 若 `sessionId` 非空：`cmd += ["--resume", sessionId]`（续接上次会话）
  3. 若 `MAX_BUDGET_USD`：`cmd += ["--max-budget-usd", MAX_BUDGET_USD]`
  4. `proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(WORKDIR), stdout=PIPE, stderr=PIPE)`
  5. `out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)`
  6. `returncode == 0`：解析 `json.loads(out)`，取 `result`（助手文本）和 `session_id`（回传前端存下实现多轮）→ 返回 `{ "reply": result, "sessionId": session_id, "usage": <json 里的 usage 或 None> }`
  7. `returncode != 0` → 抛 `HTTPException(502, detail={"error":"agent_cli_failed","message": err.decode(errors="ignore")[:500]})`
  8. `asyncio.TimeoutError` → 先 `proc.kill()`，抛 `HTTPException(504, "claude 响应超时")`
  9. `FileNotFoundError` → 抛 `HTTPException(503, "claude CLI 未安装")`

> ⚠️ claude headless 参数（已核实官方文档）：`-p`/`--print` 非交互；`--output-format json` 返回含 `result`/`session_id`/`usage` 的 JSON；`--resume <id>` 续会话；`--permission-mode plan|acceptEdits|...`；`--max-turns N`；`--bare` 跳过 hooks/CLAUDE.md 加速；`--allowedTools "A,B"` 限工具。**实现时先跑一次 `claude --help` 核对本机版本的参数名**（不同版本可能有差异）。

### 4.5（可选）启动脚本自动开浏览器
在项目根 `start.bat` / `start-full.bat` 末尾加：`start http://127.0.0.1:19828/`

**验收后端改动**：起服务后 `http://127.0.0.1:19828/` 出前端、`/docs` 正常、`GET /api/v1/projects` 正常、`GET /api/v1/agent-cli/status` 返回 JSON（available true/false）。

## 5. API 对接契约（精确；实现者照此调用）

**Base**：全部相对 `window.location.origin`（同源托管，无需写死 host）。

### 5.1 拿项目 ID（**前端第一步必做**）
- `GET /api/v1/projects` → `{ "projects": [ { "id": "<UUID>", "name": "...", "path": "...", "schema_version": "v2.0" } ] }`
- 前端存 `pid = projects[0].id`。**若 `projects` 为空，显示“未找到已注册项目，请先 python -m src.cli project init”。**

> ⚠️ 陷阱：除 `GET /api/v1/projects/{project_id}` 外，**所有** `{project_id}` 端点**只接受 UUID，不接受项目名**（后端 `by_id_only=True`）。务必先取 `id` 再调其他接口。

### 5.2 搜索（A 页）
- `POST /api/v1/projects/{pid}/search`
- body：`{ "query": "词", "topK": 10, "mode": "hybrid" }`
  - `mode` 可取 `"hybrid" | "keyword" | "vector"`，但**后端目前不区分，只是原样回显**（底层都是混合检索）。
  - `includeContent` 字段被后端忽略，**不要依赖它**。
- 响应：`{ "query", "mode", "topK", "tokenHits": 0, "vectorHits": 0, "results": [ { "path", "title", "content", "score", "source" } ] }`
  - `results[].path` 形如 `"wiki/concepts/xxx.md"`（**带 `wiki/` 前缀**）
  - `results[].content` 是**正文前 300 字符截断**
  - `results[].source` 是 `"semantic"` 或 `"keyword"`，用作徽标
  - `tokenHits`/`vectorHits` 恒为 0，可忽略

### 5.3 列页面 / 读单页（B 页，及 A 页点开的全文）
- 列表：`GET /api/v1/projects/{pid}/files?root=wiki&recursive=true&max_files=2000`
  → `{ "files": [ { "path": "wiki/concepts/xxx.md", "isDir": false, "size": 1234 } ], "truncated": false, "totalCount": 42 }`
- 内容：`GET /api/v1/projects/{pid}/files/content?path={p}`
  → `{ "path": "wiki/concepts/xxx.md", "content": "<markdown 全文>", "truncated": false, "size": 1234 }`

> ⚠️ 关键陷阱：list 返回的 `path` 是**相对项目根**（带 `wiki/` 前缀）；而 `files/content` 的 `path` 参数是**相对 wiki 根**（**不带** `wiki/` 前缀）。调 content 前 `p = path.replace(/^wiki\//, "")`，再 `encodeURIComponent(p)`。

### 5.4 摄取（C 页）
- `POST /api/v1/projects/{pid}/ingest`
- body：`{ "source": "https://... 或文件绝对路径", "folderContext": null }`
- 响应：`{ "status": "queued", "taskId": "...", "reason": null }` 或 `{ "status": "ignored", "taskId": null, "reason": "Duplicate" }`

> ⚠️ **异步入队**，200 ≠ 完成（后台跑 Collector→Analyzer→Generator）。提示用户“已入队，稍后到浏览页查看”。
> ⚠️ 文件夹摄取（`source` 传 `{"folder": ...}`）**未接线**，只接受单个 URL 或单个文件路径。

### 5.5 知识库对话（D 页）
- `POST /api/v1/projects/{pid}/chat`
- body：`{ "message": "...", "sessionId": "..." }`（首次 null，响应回 sessionId 后续复用）
  - 其余字段（mode/topK/includeContent/wiki/web/anytxt）后端**忽略**，不用传。
- 响应：`{ "sessionId", "projectId", "message": { "role": "assistant", "content": "..." }, "references": [...], "usage": { "iterations": N, "toolCalls": M } }`
- 错误：`502` = agent 未收敛。**非流式、可能慢**，必须 loading。

### 5.6 状态（E 页）
- `GET /health` → `{ "ok": true, "status": "running", "version": "0.2.0", "agent": { "chat": true, "streaming": false } }`
- `GET /api/v1/projects/{pid}` → `{ "id", "path", "name", "last_opened": <unix毫秒>, "schema_version": "v2.0" }`（此接口 id 或 name 均可）
- `GET /api/v1/projects/{pid}/files?root=wiki` → 用 `totalCount` 显示页面总数
- `GET /api/v1/projects/{pid}/reviews?status=open` → `{ "count", "reviews": [...] }`，显示待审核数
- `GET /api/v1/projects/{pid}/schema` → `{ "project_id", "schema_version", "schemas": [ { "schema", "from", "to" } ] }`

### 5.7 本地 Agent CLI（F 面板，新增）
- 状态：`GET /api/v1/agent-cli/status` → `{ "available": true, "version": "..." }` 或 `{ "available": false, "error": "..." }`（恒 200）
- 对话：`POST /api/v1/agent-cli/chat`
  - body：`{ "message": "...", "sessionId": "..." }`（首次 null；响应回 `sessionId` 后续复用以实现多轮）
  - 响应：`{ "reply": "<claude 的文本回答>", "sessionId": "...", "usage": { ... } | null }`
  - 错误：`503` claude 未安装；`502` claude 运行失败（detail.message 有 stderr）；`504` 超时

> ⚠️ F 面板与 D 页**完全独立**：D 页是项目自带的“知识库 agent”（基于 wiki 检索），F 是调你本机的 claude code（通用助手）。两者 sessionId 各自维护、互不通用。

## 6. 前端架构（app.js 公共逻辑）

1. **API 封装**：一个 `api(path, {method, body})` 函数，内部 `fetch(origin + path)`，统一 JSON 头、解析 JSON、抛可读错误。
2. **启动流程**：页面加载 → `GET /api/v1/projects` 取 `pid` 存模块级 → 渲染侧边栏项目名 → 默认进搜索页；同时 `GET /api/v1/agent-cli/status` 更新右侧面板状态点。
3. **视图切换**：侧边栏 5 个按钮（搜索/浏览/摄取/知识库对话/状态）切换中间主区；右侧 agent 面板**不参与切换、全局常驻**。
4. **错误展示**：API 失败在主区顶部显示红色 banner。
5. **Markdown**：`window.marked ? marked.parse(md) : "<pre>"+md+"</pre>"`。

## 7. 页面设计（布局 + 交互 + 数据流）

**整体三栏布局**：`左侧导航(~200px) │ 中间主内容区(自适应) │ 右侧 agent 面板(~320px，可折叠)`。右侧 F 面板所有页面都可见、常驻。

### A. 搜索页（默认首页）
- 顶部一行 = 输入框 + 模式下拉(hybrid/keyword/vector) + topK 数字框(默认10) + 搜索按钮。回车或点按钮 → 调 §5.2。
- 结果：纵向卡片列表。每卡显示 `title`（加粗）、`source` 徽标（semantic=蓝 / keyword=灰）、`score`（右侧小字）、`content` 摘要、`path`（等宽小字）。
- 点卡片 → 下方展开全文区：用该卡 `path`（剥 `wiki/`）调 §5.3 content，marked 渲染；再点收起。空结果显示“无结果”。

### B. 浏览页
- 主区左右两栏：左 ~280px 页面树，右阅读区。
- 进入即调 §5.3 列表，按 path 第一级子目录分组（sources/concepts/entities/synthesis，index.md/log.md 归“系统”组），每组可折叠，文件按名排序，显示去 `.md` 的文件名。
- 点文件 → 右侧调 content（剥前缀）→ marked 渲染全文。
- 增强（可选）：解析 markdown 顶部 `---...---` frontmatter，在全文上方小字显示 `id/title/type/heat/grade`（极简逐行 `key: value` 解析，不引 YAML 库）。

### C. 摄取页
- 居中卡片 = 说明 + 大输入框（placeholder“贴一个 URL 或文件绝对路径”）+ 摄取按钮 + 结果区。
- 点按钮 → 校验非空 → 调 §5.4，期间置灰。
- 结果：`queued`→绿“已入队 (taskId=…)，后台处理中”；`ignored`→黄“已存在跳过（Duplicate）”；失败→红。底部注明：仅单 URL/单文件，文件夹暂不支持。

### D. 知识库对话页
- 消息列表（用户靠右 / 助手靠左），底部固定输入框 + 发送按钮。模块级 `sessionId`。
- 发送 → 用户消息入列 + “思考中…”占位 → 调 §5.5 → 用 `message.content` 替换 → 下方列 `references`（path/title，可点跳浏览页看全文）+ `usage` 小字。502 → 占位变红。

### E. 状态页
- 卡片网格，并发调 §5.6：
  - 服务健康卡：ok/status/version、agent.chat、agent.streaming
  - 项目卡：name、id、path、schema_version、last_opened（格式化本地时间）
  - 统计卡：wiki 页面总数（totalCount）、待审核数（reviews count）
  - Schema 卡：当前 schema_version + 可用迁移列表
- 顶部“刷新”按钮重拉全部。

### F. 本地 Agent 面板（右侧常驻，新增）
- **布局**：右侧固定栏，宽 ~320px（可点折叠按钮收成 ~40px 竖条）。自上而下：
  - 头部：标题「本地 Agent · Claude Code」+ 状态点（绿=可用 / 灰=未安装，悬停显示 version 或 error）+ 「新会话」按钮 + 折叠按钮。
  - 消息区：滚动列表，用户气泡靠右、助手气泡靠左；助手回复用 marked 渲染（claude 常回 markdown/代码块）。
  - 底部：多行输入框（Enter 发送 / Shift+Enter 换行）+ 发送按钮。
- **状态**：模块级 `agentSessionId`（首条 null，用响应里的 sessionId 续）；「新会话」清空它。
- **交互**：发送 → 用户消息入列 + “Claude 思考中…(可能数十秒)”占位 → 调 §5.7 chat → 用 `reply` 渲染替换占位。
  - `503` → 面板顶部提示“未检测到 claude code，请先安装并登录：`npm install -g @anthropic-ai/claude-code` 后运行 `claude` 登录”。
  - `502/504` → 占位气泡变红显示错误。
- **状态点初始化**：页面加载时调 §5.7 status；不可用则输入框置灰并显示安装指引。

## 8. 样式规范（浅色系）

- 背景：页面 `#f5f6f8`，卡片 `#ffffff`，侧边栏与右侧面板 `#ffffff`（分隔线 `#e3e5e8`）。
- 文字：主 `#1f2329`，次要 `#6b7280`，边框 `#e5e7eb`。
- 强调色：主按钮/链接 `#2563eb`，semantic 徽标 `#2563eb`，keyword 徽标 `#9ca3af`。
- 状态色：成功 `#16a34a`，警告 `#d97706`，错误 `#dc2626`；agent 状态点 绿 `#16a34a` / 灰 `#9ca3af`。
- 聊天气泡：用户 `#2563eb` 底白字靠右；助手 `#f1f3f5` 底深字靠左；代码块 `#f6f8fa` + 等宽字体。
- 圆角 8px，卡片轻阴影 `0 1px 3px rgba(0,0,0,.06)`；path 用等宽字体（`ui-monospace, Consolas, monospace`）。
- 整体简洁、留白充足；不做暗色模式。

## 9. 启动与验证

1. 改完 §4 后端 + 建好 `web/` 三个文件。
2. 起服务：双击 `start-full.bat`（或 `python -m src.cli serve`）。
3. 浏览器开 `http://127.0.0.1:19828/`：
   - [ ] 看到三栏布局（侧边栏 + 主区 + 右侧 agent 面板）
   - [ ] 状态页显示 ok=true、项目信息
   - [ ] 搜索出结果卡片；点结果/浏览页看到 markdown 全文
   - [ ] 摄取页贴 URL 显示“已入队”
   - [ ] 知识库对话页发话有回答
   - [ ] **右侧 agent 面板状态点变绿（已装 claude code），发一句话能收到 claude 回复；未装则显示安装指引**
   - [ ] `http://127.0.0.1:19828/docs` 仍正常

## 10. 已知陷阱清单（实现者必读，逐条对照）

1. **project_id 必须是 UUID**：先 `GET /api/v1/projects` 取 `projects[0].id`；不要用项目名调其他接口。
2. **path 前缀不一致**：list/search 的 path 带 `wiki/`，`files/content` 的 path **不带**。调 content 前 `replace(/^wiki\//, "")`。
3. **search 的 content 只有前 300 字**：摘要直接用；全文要再调 `files/content`。
4. **search 的 `mode`/`includeContent` 后端不生效**：UI 可留但别指望改变行为。
5. **ingest 是异步**：200 ≠ 完成；只支持单 URL/单文件，文件夹未接线。
6. **知识库 chat（D）与本地 agent（F）是两套**：sessionId 各自维护，别混用。
7. **`tokenHits`/`vectorHits` 恒 0**：别当成功能展示。
8. **marked 离线兜底**：`window.marked ? marked.parse(md) : "<pre>"+md+"</pre>"`。
9. **编码**：若改 `.bat` 启动脚本，内容保持 ASCII（避免 cmd 中文乱码）。
10. **不要把前端放进 `src/`**：放项目根 `web/`，与 `parents[2]/web` 对应。
11. **agent-cli 用异步子进程**：FastAPI 是 async，必须 `asyncio.create_subprocess_exec`（别用阻塞的 `subprocess.run`，否则整服务卡住）；且**参数数组传 `message`，绝不 `shell=True` / 不拼字符串**（防命令注入，见 §12）。
12. **claude 慢**：单轮可能数秒~数十秒，前端 loading + 后端 `TIMEOUT_S` 兜底；`--resume` 续会话要存好 `sessionId`。
13. **claude 参数版本差异**：实现时先 `claude --help` 核对本机参数名（不同版本可能有出入），再定 `EXTRA_ARGS`。

## 11. 验收清单（实现完成后逐项核对）

- [ ] `web/index.html`、`web/app.js`、`web/style.css` 三个文件存在
- [ ] `src/server/app.py` 加了 CORSMiddleware + StaticFiles（顺序在 router 之后）+ 注册 agent_cli 路由
- [ ] 新建 `src/server/routes/agent_cli.py`，两个端点可用
- [ ] 浏览器开 `/` 出三栏界面，`/docs` 仍正常，`/api/v1/projects` 返回 JSON
- [ ] 五个主页面 + 右侧 agent 面板均可切换/使用（搜索出结果、浏览看全文、摄取入队、知识库对话有回答、状态有数据、agent 面板能聊）
- [ ] `GET /api/v1/agent-cli/status` 正确反映 claude 是否安装
- [ ] agent-cli 用参数数组调子进程（无 shell=True），绑 127.0.0.1
- [ ] 浅色系，无控制台报错；刷新后仍能自动拿 pid 并工作

## 12. 安全规范（本地 Agent CLI 必看）

把「网页消息 → 本机执行 claude」接通，本质是给本机命令执行开了个 HTTP 入口，必须守住以下底线：

1. **防命令注入**：调子进程用参数数组 `["claude","-p",message,...]`，**绝不** `shell=True`、绝不把用户输入拼进 shell 字符串。message 作为独立 argv 元素，shell 不会解释其中的 `;` `|` `$()` 等。
2. **绑定回环**：服务务必 `--host 127.0.0.1`。**绝不要**为此功能绑 `0.0.0.0`——否则等于把本机 shell 暴露给整个局域网。
3. **权限级别（已由用户拍板 = `acceptEdits`）**：本项目设为 `"acceptEdits"`——claude 可**自动修改文件**，意味着网页输入能间接改你的项目代码。这是用户明确选择的（要更稳妥改回 `"plan"` 只读）。**禁止**用 `"bypassPermissions"`（连执行命令都不拦，风险过大）。
4. **资源兜底**：`--max-turns` 限轮数、可选 `--max-budget-usd` 限花费、子进程 `TIMEOUT_S` 超时强杀，防失控/烧钱。
5. **工作目录限定**：子进程 `cwd` 固定项目根，别暴露其它目录。
6. **认知**：即便 `plan` 模式，claude 也能读你项目文件内容并回显——本地自用没问题，但别把这个服务给不信任的人访问。

---

## 13. 进阶设计（借鉴 open-design，按需选用；一期可不做）

> 参考 `open-design/docs/web-local-agent-chat.md`（一套成熟的 web → daemon → 本地 CLI 方案）。
> 它的核心分层与本方案一致：**Web 不直接碰 LLM/CLI，只跟后端通信，后端 spawn 本地 CLI 子进程并回传**——印证方向正确。
> 但那是 monorepo 重量级方案（Next.js + daemon + contracts），**不照搬**，只按「已采纳 / 可选增强」分层吸收。一期按 §4.4 / §7F 的**非流式**实现即可，本节是后续迭代方向。

### 13.1 已采纳进当前方案的原则
- **分层桥接**：Web → FastAPI(桥) → 本地 CLI 子进程；Web 永不直接调 LLM 或 CLI（同 open-design 的 daemon 唯一出口）。
- **双路径分离**：知识库 chat(`POST /projects/{id}/chat`) 与本地 agent(`POST /agent-cli/chat`) 是两条独立链路（对应 open-design 的 `/api/chat` BYOK 代理 vs `/api/runs` 本地 agent），sessionId 各自维护、互不混用。
- **stderr 默认不展示**，仅子进程非零退出时把尾部并入错误提示。
- **命令注入防护 / 绑回环 / 权限最小化**（见 §12）。

### 13.2 可选增强（按价值排序，后续迭代再加）
1. **SSE 流式输出（最值得做）**：把「一次性等 claude 跑完」改为「逐字流出」。
   - 后端：`cmd` 改用 `--output-format stream-json --verbose`，用 FastAPI `StreamingResponse` 把 claude 的 NDJSON 逐行转成 SSE 帧推送；事件类型可借鉴 open-design：`start / text_delta(可见增量) / thinking_delta(思考) / tool_use(工具调用) / usage(token·cost) / error / end`。
   - 前端：POST 不能用 EventSource，改用 `fetch` + `res.body.getReader()` 按 `\n\n` 切帧、解析 `data:` 增量渲染。
   - 价值：长回答不用干等，体验接近原生 claude。
2. **取消（Cancel）**：给每次对话发一个 `runId`，后端保存子进程句柄；新增 `POST /api/v1/agent-cli/cancel {runId}` → `proc.kill()`。区分两种语义：关闭前端显示（仅 abort 订阅，子进程继续）vs 真正取消（kill 子进程）。
3. **结构化事件渲染**：若做流式，把 `tool_use` / `thinking_delta` / `usage` 渲染成独立 UI 块（工具调用卡片、可折叠的思考区、用量小字），而非纯文本。
4. **多 agent 支持**：把 `CLAUDE_CMD` 抽象成「agent 配置表」（`{name, bin, args模板}`），支持下拉切换 claude / codex / gemini / opencode 等；`GET /agent-cli/status` 逐个探测可用性。
5. **断线重连 / 刷新恢复（较重，最后做）**：持久化 `runId` + `lastEventId`，SSE 带 `?after=<lastEventId>` 续传；刷新后 reattach 同一 run，不重开。
6. **错误码差异化**：识别 claude stderr / 退出码里的鉴权失败、限流等，前端给「请重新登录 claude」「限流，稍后重试」等针对性提示（对应 open-design 的 `AGENT_AUTH_REQUIRED` / `RATE_LIMITED`）。

> 环境前提（用户已确认）：本机 claude code **已安装并已登录**，`GET /agent-cli/status` 应返回 `available: true`。

## 14. 演进路线：借鉴 llm_wiki-main（E:\2026-7-21\llm_wiki-main）

> 来源：对 llm_wiki-main（Tauri 桌面端知识库应用，TS 前端 + Rust 后端）做 codebase-memory 图谱分析后提炼（7453 节点 / 23615 边）。
> 定位差异：它是桌面端（Rust 直接 spawn 本地进程），ruflo-kb 是 FastAPI Web 服务——同样的能力在 ruflo-kb 一律由**后端子进程/后台任务**承担。
> 本节按「对 ruflo-kb 的价值」排序，标注参考实现文件，供后续迭代选用；**不影响一期范围**。

### P0 —— 直接解当前痛点（建议优先做）

**14.1 摄取任务队列（ingest status）**
- 参考：`llm_wiki-main/src/lib/ingest-queue.ts`（`processNext`：串行处理 + 进度状态 + 可取消）。
- ruflo-kb 现状：`POST /ingest` 入队即返回，之后查不到任务进度/成败。
- 做法：后端加内存任务表 `{task_id, status, progress, error}`；新增 `GET /api/v1/projects/{id}/ingest/status/{task_id}`；前端 C 页提交后轮询该端点展示进度条与失败原因。

**14.2 文件监听自动摄取（file watcher）**
- 参考：`src/commands/file-sync.ts::startProjectFileWatcher` + `src/lib/project-file-sync.ts`（监听目录 → 变更入队 → retry/ignore 死信）。
- ruflo-kb 现状：手动投放 `raw/sources/` → 手动 ingest → 手动 archive，三步全靠人。
- 做法：后端用 `watchdog` 盯 `raw/sources/`，新文件落盘自动触发 ingest → archive 管线；失败进死信表，暴露 retry/ignore 端点。与现有 Inbox 三态（Pending/Processing/Error）天然契合。

**14.3 Agent CLI 流式桥接（F 面板升级的直接参考）**
- 参考：`src-tauri/src/commands/claude_cli.rs::claude_cli_spawn`（spawn 子进程）+ `src/lib/claude-cli-transport.ts::streamClaudeCodeCli`（**逐行解析 stream-json 并转发**，含测试 `__tests__/claude-cli-transport.test.ts`）。
- 价值：实现 §13.2 第 1 项（SSE 流式）时，transport 层的 NDJSON 解析/事件分类逻辑可直接对照移植（TS → Python）。

### P1 —— 增强知识库体验

**14.4 Wiki 图谱可视化**
- 参考：`src/lib/wiki-graph.ts::buildWikiGraph`（从 `[[wikilink]]` 建图）+ `src/components/graph/graph-view.tsx`。
- 做法：后端新增 `GET /api/v1/projects/{id}/wiki/graph`（扫 wiki/*.md 解析 wikilink，返回 `{nodes, edges}`）；前端加「图谱」页，用 Canvas/SVG 力导向渲染，可发现 hub 页与孤儿页。

**14.5 Lint 语义健康检查**
- 参考：`llm-wiki.md` 的 Lint 操作（矛盾检测 / 过期论断 / 孤儿页 / 被提及但未建页的概念）。
- 做法：在现有 H2（断链）/H4（ID 格式）之上加一个「LLM lint」端点，定期让 LLM 扫全库产出问题清单，前端 E 页展示。

**14.6 log.md 规范前缀**
- 参考：`llm-wiki.md`：日志条目统一 `## [YYYY-MM-DD] ingest | Title` 前缀，可 `grep "^## \[" log.md | tail -5` 秒查。
- 做法：generator 写 `wiki/log.md` 时固定此前缀格式。零成本，立即可做。

### P2 —— 锦上添花

**14.7 引用面板（citations UI）**
- 参考：`CitedReferencesPanel`（回答下方附来源卡片：标题 + 路径 + 片段，可点击跳转）。
- 做法：D 页 chat 响应若带来源字段，渲染成可点击卡片，点击跳到 B 页对应笔记。

**14.8 project-store 多项目抽象**
- 参考：`src/lib/project-store.ts::getStore`（fan_in 47，统一多项目存储句柄）。
- 做法：ruflo-kb 已有 project registry，多项目并存时可参照其封装；单项目阶段不急。
