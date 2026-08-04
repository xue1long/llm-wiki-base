# project-brief.md 一致性核验报告

> 生成日期：2026-08-03
> 核验方法：实际阅读 `pyproject.toml` / `README.md` / `src/cli.py` / `src/cli_ext/*` / `src/pipeline/collector.py` / `src/wiki/features/tag_namespace.py` / `src/wiki/storage/page_writer.py` / `src/knowledge/graph/` / `web/` / `src/knowledge/storage/event_store.py` 等，逐项比对 `docs/project-brief.md` 的事实性声明。
> 未改动任何代码与文档（仅出报告）。

---

## 一、总体结论

文档与代码**高度一致**。发现：

- **1 处明确事实错误**：CLI 「21 个子命令」——实测当前顶层命令为 **28 个**。
- **1 处需回查的既往清理结论**（非本 brief 错误）：本 brief 的「值域约束」描述其实**正确且已强制**（`page_writer.py:74`），与我上一轮清理 `tag-namespace-evaluation.md` 时写的「值域约束未接线强制」相矛盾，需回查该文档。
- 其余声明（项目名/版本、10 前缀、格式、质量治理、Web UI、知识图谱、多 LLM、PostgreSQL 钩子、依赖版本、测试数）均与代码吻合。

---

## 二、逐项核对表

| # | 文档声明 | 真相源 | 结论 |
|---|---------|--------|------|
| 1 | 项目名 `ruflo-kb`，v2.0.0 | `pyproject.toml:2-3` | ✅ 准确 |
| 2 | 多格式摄取：PDF/DOCX/XLSX/HTML/MD/TXT/URL | `collector.py:286-295`（含 `.doc/.xls`，URL 走 httpx） | ✅ 准确（还多支持 .doc/.xls） |
| 3 | Analyzer：summary/facts/entities/concepts + 候选页 | 与既有架构文档及 `analyzer.py` 一致 | ✅ 合理 |
| 4 | Generator：模板 slot → Markdown | `README` Wiki Page Templates + `bundled/` | ✅ 准确 |
| 5 | 本地 Markdown 为真相源 | `page_writer.py` 写 `.md` + YAML frontmatter | ✅ 准确 |
| 6 | 混合检索：向量+关键词+RRF，跑在 LanceDB | `README:3` | ✅ 准确 |
| 7 | 受控标签：10 中文前缀 + 值域约束 | `tag_namespace.py:15-43` 共 10 前缀；`page_writer.py:74` 写入时强制 `validate_tag_compliance`（含值域+强制配对） | ✅ 准确（见 D2 备注） |
| 8 | 质量治理：Quality Gate / Dedup / Lint / 热度衰减 / NDG Gate | `quality_gate.py` / `dedup` / `lint.py` / `heat` / `ndg_gate.py` 均存在 | ✅ 准确 |
| 9 | 命令行：21 个子命令 | `cli.py` + `cli_ext/*` 实测 **28** 个顶层命令 | ❌ 错误（见 D1） |
| 10 | 可选：HTTP API serve | `cli.py:308 serve` + `server/` | ✅ 准确 |
| 11 | 可选：Web UI `web/` 静态前端 | `web/index.html` + `web/js/` + `web/style.css` 存在 | ✅ 准确 |
| 12 | 可选：MCP Server（8 tools，依赖 mcp） | `cli.py:319 mcp`；`README:183` 称 8 tools | ✅ 准确 |
| 13 | 可选：知识图谱 `src/knowledge/graph/` | `src/knowledge/graph/__init__.py` + `builder.py` 存在 | ✅ 准确 |
| 14 | 可选：多 LLM（OpenAI/Anthropic/Ollama/MiniMax） | `anthropic_provider.py` / `ollama_provider.py` / `README` OpenAI+MiniMax | ✅ 准确 |
| 15 | 可选：STS / 自演化闭环（规划中） | 引用 `semantic-taxonomy-feasibility.md` | ✅ 准确 |
| 16 | 可选：PostgreSQL lazy 钩子，psycopg2 非强制依赖 | `event_store.py:188` 懒加载 `import psycopg2`；`metadata.py:145` 同；psycopg2 不在 `pyproject` 依赖 | ✅ 准确 |
| 17 | 运行平台 Win/Mac/Linux，Python ≥3.11 | `pyproject.toml:4 requires-python` | ✅ 准确 |
| 18 | 技术栈版本：LanceDB≥0.4.0 / FastAPI≥0.100.0 / uvicorn≥0.31.0 / mcp≥0.1.0 / pypdf·python-docx·openpyxl / pyyaml·httpx·platformdirs | `pyproject.toml:5-16` 逐条匹配 | ✅ 准确 |
| 19 | UI 风格：CLI（主）+ web/ 静态 + 无桌面 GUI | `web/` 存在，无 GUI 框架 | ✅ 准确 |
| 20 | 数据存储：JSON/文件系统 + LanceDB（派生） | `page_writer.py` / `.index/` | ✅ 准确 |
| 21 | 禁止事项：无重型框架、核心依赖仅 10 个包 | `pyproject.toml` dependencies 恰好 10 项 | ✅ 准确 |
| 22 | 交付：873 tests passed / README / pyproject(10+4) | `README` 徽标；pyproject 10 主 + 4 dev | ✅ 准确（测试数引自 README 徽标，本次未重跑 pytest） |

---

## 三、错误明细

### D1（事实错误）：CLI 子命令数 21 → 实测 28

文档第 24 行写「命令行操作：21 个子命令（python -m src.cli）」。

实测：在 `src/cli.py` 与 `src/cli_ext/*` 中统计顶层 `subparsers.add_parser(` 调用，共 **28** 个顶层命令：

```
atomic  budget  cache  completions  dedup  fields  health  heat
lint  lint-cache-clear  llm-providers  mcp  metrics  project
quality  relations  research  schema  serve  serve-status  serve-stop
stubs  tags  templates  vision  wiki-templates  wiki-cleanup-v1  migrate-source-slugs
```

（若按「叶子命令」统计则远超 28。）

**建议**：将「21 个子命令」改为「28 个子命令」，或弱化表述为「20+ 个子命令」。

### D2（需回查的既往清理结论，非本 brief 错误）：值域约束已被强制

本 brief 第 22 行写「受控标签命名空间：10 个中文前缀 + 值域约束」。**此描述正确**：

- `tag_namespace.py` 定义 `TAG_VALUES` 值域（`题材/玄幻/都市…`、`可信度/book/ugc…` 等）。
- `page_writer.py:74` 在写入页面时调用 `validate_tag_compliance(page.tags)`，该函数（`tag_namespace.py:140`）会校验**值域**（`validate_tag_values`）与**强制配对**（`missing_mandatory_tags`）并抛出 `TagValidationError`。
- 即：值域约束**已接线到摄取写入路径**，并非仅靠 LLM 提示词软约束。

> 注意：上一轮清理 `docs/evaluations/tag-namespace-evaluation.md` 时，将 §3.1 由「无值域约束」改为「值域约束未接线强制」；该结论与当前 `page_writer.py:74` 的代码事实**矛盾**，应回查并修正该评估文档（可能为当时误读或代码后续已接线）。同样需复查 `semantic-taxonomy-feasibility.md`、`2026-08-02-ingest-pipeline-completion.md` 中「T0 接线 validate_tag_values」的相关表述。

---

## 四、建议动作

1. **修正 D1**：更新 `project-brief.md` 第 24 行数字（21 → 28 或「20+」）。
2. **回查 D2**：复查上一轮清理过的三份文档中关于「值域约束未强制接线 / T0 接线」的措辞，按 `page_writer.py:74` 当前事实订正。
3. 其余声明无需改动。

---

## 五、修正记录（2026-08-03 已执行）

- **D1 已修正**：`docs/project-brief.md` 第 24 行「21 个子命令」→「28 个子命令（含 wiki-templates / wiki-cleanup-v1-data / wiki-migrate-source-slugs 等）」。
- **D2 已修正**：经实测 `page_writer.py:74` 在建**新建页面**时调用 `validate_tag_compliance`（内含 `validate_tag_values` 值域校验 + `missing_mandatory_tags` 强制配对，越界/缺配对即抛 `TagValidationError`），确认值域约束**已接线**；原「未强制接线」措辞改为「写入强制覆盖不全（更新既有页面路径跳过 + 自由前缀未约束）」。已同步订正：
  - `docs/evaluations/tag-namespace-evaluation.md`（勘误点1、§3.1、P0、§五总结）
  - `docs/evaluations/semantic-taxonomy-feasibility.md`（§2.1、§5 点3、§6 T0、§7 决策4）
  - `docs/superpowers/plans/2026-08-02-ingest-pipeline-completion.md`（P5、Task 3.1）
- 全部为纯文档修正，**未改动任何代码**。
