# novel-wiki 书系目标方案实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `novel-wiki` 从“单书五卷”调整为“三本主教程 + 一个参考库”，并以连续 10 章样例验证读者阅读链、来源追溯和 LLM 叙事质量。

**Spec:** `docs/superpowers/specs/2026-09-06-novel-wiki-book-series-target.md`

## 全局约束

- `rule_only` 保持默认；旧 release 必须继续可读。
- 页面只允许一个 canonical `book_id`/`chapter_id`；跨书只建关系，不复制正文。
- 主教程才启用叙事 LLM；参考库使用规则版或百科版。
- `--narrative --use-llm --polish` 只生成 draft；只有加 `--apply` 且质量门通过才更新对应书的 `CURRENT.json`。
- 任何失败只影响当前书的 staged release，不能覆盖旧版本或系列 manifest。
- 来源路径仅发送 allowlist 内的相对路径；API key 不得写入日志和产物。

## 任务

### Task 1：建立页面归属基线

**Files:** `src/kc/views/book/wiki/scanner.py`、`partition.py`、新增 `tests/test_kc/test_book_series_partition.py`

- [ ] 统计教程、素材、规则、案例、重复页和无来源页；输出基线报告。
- [ ] 为每个 eligible page_id 生成唯一 canonical `book_id`/`chapter_id` 或参考库归属。
- [ ] 对重复、未知和无法归属页面写入挂账清单，不进入主教程正文。
- [ ] 运行定向测试并提交 `feat(book): 建立书系页面归属基线`。

### Task 2：实现书系 outline 合同

**Files:** `theme_outline.py`、`outline_model.py`、`outline_validate.py`、新增书系 outline 测试

- [ ] 固化三个主教程的 `reader_promise`、卷名、入口条件和出口产物。
- [ ] 校验一本书只能有一个主承诺，章节不能跨书重复归属。
- [ ] 保留旧 outline-v1 的读取兼容，不强制迁移旧规则版。
- [ ] 运行 outline 回归测试并提交 `feat(book): 增加书系卷章纲契约`。

### Task 3：拆分主教程与参考库编译模式

**Files:** `compiler.py`、`encyclopedic_outline.py`、`quality_gate.py`、新增模式测试

- [ ] 主教程输出 `narrative_draft`/`narrative`；参考库输出 `rule_only`/`encyclopedic`。
- [ ] 编译产物写入 `book_id`、`series_id`、模式、读者承诺和出口产物。
- [ ] 验证页面只归属一本书，跨书引用不重复渲染正文。
- [ ] 运行旧版编译回归测试并提交 `feat(book): 支持书系和参考库编译`。

### Task 4：补齐来源和跨书关系

**Files:** `aggregator.py`、`reading_aids.py`、`cross_links.py`、新增 provenance 测试

- [ ] 按书聚合 `chapter_sources`、`unattributed_page_ids` 和来源覆盖率。
- [ ] 生成跨书 `supports`、`required_by`、`contrasts`、`related` 边；namespace 边不计入失败率。
- [ ] 关系目标不存在、章节归属冲突或 unresolved 超阈值时阻断当前书发布。
- [ ] 运行关系回归测试并提交 `feat(book): 支持跨书来源和关系索引`。

### Task 5：先生成连续 10 章样例

**Files:** `src/cli.py`、`src/cli_ext/book_cmd.py`、新增样例报告

- [ ] 只选择 `writing-foundations` 连续 10 章，不把书籍永久限制为 10 章。
- [ ] 执行 preflight、单章 LLM 调用、证据校验和练习检查；失败即回退规则版。
- [ ] 样例写入独立 staging/report，不更新任何 `CURRENT.json`。
- [ ] 人工检查阅读链、标题、来源、示范场景标记和练习可执行性。
- [ ] 提交 `test(book): 完成书系十章样例验收`。

### Task 6：更新 WebUI 书系导航

**Files:** `src/services/files.py`、`src/server/routes/files.py`、`web/js/views/book.js`、`docs/webui-buttons.md`

- [ ] 下拉选择改为显示书系中的三本书和参考库。
- [ ] 左侧显示“书 → 卷 → 章”，中间显示正文，右侧显示模式、来源覆盖、出口产物和跨书关系。
- [ ] 损坏或缺失 sidecar 时显示可定位错误，不能显示空白页。
- [ ] 运行 API/UI smoke test 并提交 `feat(webui): 展示书系层级和跨书关系`。

### Task 7：小批试跑与正式发布门

**Files:** 新增 `docs/reports/2026-09-06-book-series-acceptance.md`

- [ ] 另外两本主教程各运行 3–5 章 pilot，记录 token、延迟、错误、来源覆盖率和关系解析率。
- [ ] 验证每本书独立 staged release、独立回滚和旧版本选择。
- [ ] 全量只做 dry-run；未通过人工读者任务和质量门不得 apply。
- [ ] 把所有失败样例和整改结果写入验收报告。
