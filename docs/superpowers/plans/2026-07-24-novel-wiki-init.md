# 小说创作素材库 — 初始化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `F:\2026-7-21\knowledge\novel-wiki\` 初始化独立项目，摄入 7 份创作资料，构建可检索知识库。

**Architecture:** 独立 project 实例，共用 ruflo-kb 的 src/ 代码。摄入走 HTTP API（`python -m src.cli serve`）异步 pipeline，自动分类到 source/entity/concept/synthesis 四类目录。

**Tech Stack:** Python 3.14, ruflo-kb CLI, LanceDB, HTTP API (FastAPI)

---

## 待摄入文件

| # | 文件 |
|---|---|
| 1 | `raw/sources/必备资料11大纲和细纲.md` |
| 2 | `raw/sources/必备资料11月28号创酷中文网女频现言讲课记录.md` |
| 3 | `raw/sources/必备资料15顺眼谈文章的画面感.md` |
| 4 | `raw/sources/必备资料20个签约条件新人必看2.md` |
| 5 | `raw/sources/必备资料5速度网络文学创作的唯一秘诀.md` |
| 6 | `raw/sources/必备资料8月7日授课记录.md` |
| 7 | `Inbox/Processing/必备资料912怎么写出小说爽点.md` |

---

## Task 1: 初始化项目

**Files:**
- Create: `F:\2026-7-21\knowledge\novel-wiki\` 目录结构
- Modify: 无

**Interfaces:**
- Produces: 新项目 ID（写入 `.llm-wiki/project.json`）

- [ ] **Step 1: 初始化项目**

Run from repo root:
```bash
cd "F:\2026-7-21\agent-knowledge\ruflo-kb"
python -m src.cli project init "F:\2026-7-21\knowledge\novel-wiki"
```

预期输出：创建 `wiki/`, `raw/`, `.llm-wiki/project.json` 等目录结构。

- [ ] **Step 2: 验证项目创建**

```bash
python -m src.cli project list
```

预期：列出 `novel-wiki` 项目及其 ID。

- [ ] **Step 3: 提交**

```bash
git add -A && git commit -m "feat: init novel-wiki project"
```

---

## Task 2: 确认 LLM Provider 配置

**Files:**
- Modify: 无

**Interfaces:**
- Produces: 确认 LLM provider 可用（OpenAI / Anthropic / Ollama）

- [ ] **Step 1: 检查已配置的 provider**

```bash
python -m src.cli llm-providers list
```

预期：列出已配置的 provider 及是否为 default。

- [ ] **Step 2: 如未配置，引导配置**

如无输出或无可用 provider：
```bash
python -m src.cli llm-providers add openai-prov openai --api-key YOUR_KEY
python -m src.cli llm-providers set-default openai-prov
# 或
python -m src.cli llm-providers add anthropic-prov anthropic --api-key YOUR_KEY
python -m src.cli llm-providers set-default anthropic-prov
```

---

## Task 3: 启动 Server

**Files:**
- Modify: 无

**Interfaces:**
- Consumes: LLM provider 已配置
- Produces: 运行中的 HTTP server（默认 8765 端口）

- [ ] **Step 1: 启动 server（后台）**

```bash
python -m src.cli serve --host 127.0.0.1 --port 8765
```

预期：server 启动，无报错。

- [ ] **Step 2: 验证 server 就绪**

```bash
curl http://127.0.0.1:8765/health
```

预期：返回 `{"status":"ok"}` 或类似 JSON。

---

## Task 4: 摄入 7 份创作资料

**Files:**
- Modify: `F:\2026-7-21\knowledge\novel-wiki\` 目录下的 wiki/

**Interfaces:**
- Consumes: project_id, server 运行中
- Produces: wiki 页面生成（source/entity/concept/synthesis）

- [ ] **Step 1: 获取 project_id**

```bash
python -m src.cli project list
```

记下 `novel-wiki` 的 project_id（格式如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）。

- [ ] **Step 2: 摄入 6 份 raw/sources 文件**

对每份文件执行：
```bash
curl -X POST http://127.0.0.1:8765/api/v1/projects/{PROJECT_ID}/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "F:\\2026-7-21\\agent-knowledge\\ruflo-kb\\raw\\sources\\必备资料11大纲和细纲.md"}'
```

共 6 份，逐一执行或写脚本批量执行。

- [ ] **Step 3: 摄入 1 份 Inbox/Processing 文件**

```bash
curl -X POST http://127.0.0.1:8765/api/v1/projects/{PROJECT_ID}/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "F:\\2026-7-21\\agent-knowledge\\ruflo-kb\\Inbox\\Processing\\必备资料912怎么写出小说爽点.md"}'
```

- [ ] **Step 4: 等待处理完成**

每次 POST 返回 `{status, taskId}`，处理是异步的。等待约 10-30 秒后检查结果。

---

## Task 5: 验证分类结果

**Files:**
- Modify: 无（只读验证）

**Interfaces:**
- Consumes: wiki/ 目录内容
- Produces: 验证报告

- [ ] **Step 1: 检查 wiki/index.md**

```bash
cat "F:\2026-7-21\knowledge\novel-wiki\wiki\index.md"
```

预期：列出所有生成的页面，包含 id、type、title。

- [ ] **Step 2: 检查各目录是否有文件**

```bash
ls "F:\2026-7-21\knowledge\novel-wiki\wiki\sources/"
ls "F:\2026-7-21\knowledge\novel-wiki\wiki\entities/"
ls "F:\2026-7-21\knowledge\novel-wiki\wiki\concepts/"
ls "F:\2026-7-21\knowledge\novel-wiki\wiki\synthesis/"
```

预期：sources/ 下有原始文档页面；entities/concepts/synthesis 下有自动生成的分类页面。

- [ ] **Step 3: 提交初始化成果**

```bash
cd "F:\2026-7-21\agent-knowledge\ruflo-kb"
git add -A && git commit -m "feat(novel-wiki): ingest 7 creative writing source materials"
```
