# 项目简介（按模板填写）

> 生成日期：2026-08-03 | 数据来源：实测 `pyproject.toml` / `README.md` / `src/` / `web/`

---

【项目名称】
ruflo-kb（多 Agent 知识库平台 / Knowledge OS），当前版本 v2.0.0

【目标用户】
个人知识工作者、研究者、内容创作者——需要把书籍、网页、文档、UGC 等多源素材整理成结构化 Wiki 的人。
从标签体系（题材/玄幻/都市/仙侠、素材/ugc、可信度/book 等）判断，用户重度用于网络文学/写作素材管理 + 通用知识沉淀。

【核心功能清单（必须区分：刚需 / 可选扩展）】

■ 刚需
1. 多格式摄取（Collector）：PDF / DOCX / XLSX / HTML / MD / TXT / URL
2. LLM 分析与抽取（Analyzer）：生成 summary / facts / entities / concepts + 候选页面
3. 自动生成 Wiki 页面（Generator）：按模板填 slot 输出 Markdown 页面
4. 本地文件存储：Markdown 为真相源（source of truth）
5. 混合检索：向量 + 关键词 + RRF 融合（跑在 LanceDB 上）
6. 受控标签命名空间：10 个中文前缀（题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度）+ 值域约束
7. 质量门控 / 治理：Quality Gate / Dedup / Lint / 热度衰减 / NDG Gate
8. 命令行操作：28 个子命令（python -m src.cli；含 wiki-templates / wiki-cleanup-v1-data / wiki-migrate-source-slugs 等）

■ 可选扩展
1. HTTP API：`` python -m src.cli serve --host 127.0.0.1 --port 8765 ``（FastAPI + uvicorn）
2. Web UI：`` web/ `` 静态前端（index.html + js + style.css），需对接 serve 提供的 API
3. MCP Server：暴露 wiki 工具给外部 Agent（依赖 mcp 包）
4. 知识图谱：`` src/knowledge/graph/ ``（内存图 + JSONL 事件日志 + 周期快照）
5. 多 LLM 后端：OpenAI / Anthropic / Ollama / Minimax（统一 Provider 抽象 + 预算控制）
6. 语义分类系统（STS）/ 自演化闭环：规划中（见 docs/evaluations/semantic-taxonomy-feasibility.md）
7. PostgreSQL 可选后端：storage 层已预留 lazy 钩子（psycopg2 非强制依赖）

【运行平台】Windows / Mac / Linux
说明：Python ≥3.11，CLI 为主；可本地起 Web 与 MCP。当前运行环境为 Windows（IDE 内）。

【技术栈约束】
已实现且轻量，建议沿用：
- 语言：Python ≥3.11
- 向量：LanceDB（≥0.4.0）
- HTTP：FastAPI（≥0.100.0）+ uvicorn（≥0.31.0）
- 协议：mcp（≥0.1.0）
- 文档解析：pypdf / python-docx / openpyxl
- 其他：pyyaml / httpx / platformdirs
无任何重型框架、无强制数据库。如需新增能力，由你推荐成熟稳定方案。

【UI风格】命令行（主） + 网页（web/ 静态前端，可选） + 无桌面 GUI

【数据存储】JSON 文件 / 文件系统（Markdown 真相源 + JSONL 事件日志）+ 向量索引（LanceDB，派生）
默认零数据库；PostgreSQL 为可选后端（storage 已预留 lazy 钩子，psycopg2 非项目依赖）。

【禁止事项：不引入重型框架、不要复杂依赖、优先单机本地运行】
项目已遵守：纯文件存储（真相源为本地 Markdown）、核心依赖仅 10 个包、无容器 / 无强制外部服务。

【交付标准：完整可运行代码、启动说明、依赖清单、简易 README】
均已具备：
- 完整可运行代码：873 tests passed（README 徽标）
- 启动说明：README.md「快速开始」+ CLAUDE.md
- 依赖清单：pyproject.toml（核心 10 包 + dev 4 包）
- 简易 README：README.md + CLAUDE.md 已存在
