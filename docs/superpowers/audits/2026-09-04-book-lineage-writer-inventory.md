# Book Lineage Task 0：生产写入口与基线盘点

日期：2026-09-04

## 状态

**PASSED**

初始收集结果与旧 inventory 的 `3716 tests collected` 不一致；差异已定位为旧 inventory 之后已有的风险整改提交。当前隔离环境全量回归已确认，无未解释失败。

## 工作树基线

| 项目 | 当前证据 |
|---|---|
| 分支 | `main` |
| HEAD | `449e44d0 fix(ci): normalize generated wiki prompt line endings` |
| 既有脏改 | `AGENTS.md`、`CLAUDE.md`、`knowledge/novel-wiki/.index/batch_build_state.json`、`scripts/_batch_report.txt` |
| 本次新增文档 | 本 inventory、Book lineage 计划及审计文档 |
| 测试收集 | `3735 tests collected in 14.19s` |
| 完整测试 | `3735 passed, 45 warnings in 626.87s`；隔离临时环境 |

## 实际写入口核验

| 入口 | 证据 | 当前分类 | 本次动作 |
|---|---|---|---|
| `scripts/batch_build.py` | `phase_ingest()` 调用 `src.pipeline.pipeline.run_ingest`；`phase_archive()` 调用 `archive`；`run()` 持久化 `.index/batch_build_state.json` 和 report | **生产入口**：raw ingest + Wiki archive/state | 后续必须接入 lineage；本次不改 |
| `scripts/batch_commit.py` | `_commit_one_batch()` 消费生成缓存并调用 `_commit_raw()`；更新 `batch_build_state` | **生产入口**：批量 Wiki/KC 提交 | 后续必须接入 lineage；本次不改 |
| `scripts/aggregate_synthesis.py` | `_commit_synthesis()` 直接调用 `write_page()`、`append_to_index()`、`log_event()`、`RelationSync.sync_page()` | **生产入口**：synthesis Wiki 写入 | 后续必须接入 lineage；本次不改 |
| `scripts/phase4_batch.py` | `_commit_all()` 调用 `commit_ingest()`，逐 raw 持久化并执行 postcheck | **兼容/生产候选入口** | 需在 Task 0 后续确认调用方；本次不改 |
| `scripts/batch_generate.py` | `save_cache()` 写生成缓存；文档声明零磁盘 Wiki 写 | **生成/缓存入口，非 Wiki 生产写入** | 不接 Wiki lineage；本次不改 |
| `scripts/accept_batch.py` | 读取页面并更新 `batch_build_state` 状态 | **兼容状态入口** | 后续纳入双状态比对；本次不改 |
| `scripts/ingest_novel_wiki_manual.py` | `ingest_one()` 调用 `run_ingest()`；批量人工入口 | **生产候选入口** | 需确认是否仍被实际使用；本次不改 |

## 已确认的计划关联

- Wiki 写入最终经过 `src/wiki/storage/page_writer.py` 的 `write_page()`。
- 主 pipeline 的落盘提交经过 `src/pipeline/ingest.py:commit_ingest()`。
- Book 物化读取 `.index/kc/bundles/` 和 `publication_state.json`，当前仍需接入冻结 lineage manifest。
- `aggregate_synthesis.py` 的 synthesis 页面是多源关系场景，不能按单 source 设计。
- `batch_build_state.json` 仍是现有兼容状态投影，不能在 lineage 切换前删除。

## 本次未执行项

- 未修改任何生产代码。
- 未修改任何既有脏文件。
- 未创建或迁移 SQLite 状态库。
- 未执行 full test、Book 构建、数据库迁移或真实项目写入。

## 放行条件

- `3735` 与既有 `3716` 的差异已由后续风险整改提交解释。
- 当前全量测试 `3735 passed, 45 warnings`。
- 三项指定脚本的职责已完成初步分类，未修改生产代码。
- Task 0 放行；下一步只能进入本计划 Task 1，仍须遵守定点范围。
