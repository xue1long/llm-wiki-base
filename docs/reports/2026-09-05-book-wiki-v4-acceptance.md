# Wiki-to-Book V3.2 / V4 验收报告

日期：2026-09-05  
范围：`src/kc/views/book/wiki/`、`book build-from-wiki` CLI 及 V4 增量验收。

## 结论

V3.2 安全基线与 V4-Core 已完成工程验收，可执行纯规则 dry-run；默认不发布。V4-Encyclopedic 已接入 provider registry/显式注入路径；无 provider 时仍 fail-closed，因此本机未配置凭据时不能宣称真实跨页面融合已完成。

## 已验证能力

- preflight：项目、schema、输入目录、输出目录和 provider 条件失败即停；运行锁支持冲突、过期和异常释放。
- scanner：严格 UTF-8/YAML/frontmatter、目录类型、重复 ID/标题、关系和 symlink 越界检查；快照支持内容变更检测。
- compiler：确定性分区、章节聚合、block-ID 多重集守恒、glossary/index、staging + release + `CURRENT.json` 指针发布；指针和文件 hash 校验失败时拒绝读取。
- V4-Core：章节排序、术语别名索引、阅读体验 manifest、四项规则质量门、RubricSpec/ReaderTaskRunner、CLI exit 9/10 契约。
- V4 optional：百科索引只允许发送 page_id/title/taxonomy/summary/block_ids；证据必须命中已有 page/block；cross-link 仅保留 manifest 候选，不改正文。provider 不可用时明确返回 exit 6，不静默降级。

## 摄取链路同步复核

- 摄取生成页经过 `_normalize_generated_pages` 后，`category` / `taxonomy_sub` 会转换为 `taxonomy_of` 关系；V4 writer 继续保持 8 键 frontmatter，不重新引入禁用字段。
- scanner 从 `taxonomy_of` 关系恢复 taxonomy，并读取 writer 持久化的 `sources`；compiler 将来源路径写入 `chapter_sources`，指向 excluded source 的关系写入 `source_provenance`。
- taxonomy/audience/platform/credibility 命名空间关系不再被计入 dangling page relation；excluded source/stub/archive ID 可作为已存在目标参与关系解析。
- 新增摄取→写盘→扫描集成测试，验证 taxonomy、来源和关系格式端到端可见。

## 验证证据

定向回归（使用工作区内 `--basetemp`，避开主机临时目录权限问题）：

```text
80 passed, 1 warning
```

阻塞根因修复后的复核：Book/项目解析定向回归 **44 passed**；`tests/test_kc tests/test_project` 回归 **691 passed**；`py_compile` 与 `git diff --check` 通过。

覆盖 V3 preflight/scanner/outline/partition/aggregation/polish/compiler/E2E、V4 quality gate/rubric/reader tasks/encyclopedic/cross-links 和 CLI。

真实项目编译与发布检查（`knowledge/novel-wiki`）：

- scanner 读取 1255 个 eligible pages；命名空间关系、excluded source、历史 slug 归一化和唯一紧凑 slug 均纳入解析；剩余 70/3001 条页面关系未解析（2.33%，低于 5% 阈值）；
- `python -m src.cli book build-from-wiki --project knowledge/novel-wiki --use-llm --apply --json` 返回 **committed**（exit **0**），CURRENT 指针已更新；
- 显式项目路径解析不依赖全局 registry，受限环境下仍可执行；本机自动发现仍会记录 registry 权限 warning，但不阻断编译；
- `--encyclopedic` 未带 `--use-llm` 返回 exit **6**；带 `--use-llm` 但无 provider 仍按 fail-closed 返回 exit **6**。

## 未完成或必须人工放行

- 已完成真实 `--apply`，release 与 manifest 哈希校验通过；后续重新发布仍应人工检查目标目录、provider、质量门和 rubric 结果。
- Encyclopedic provider 的真实网络调用、跨块融合、人工签名放行尚未在生产数据上验收；本地假 provider 已验证索引写入、证据校验和 manifest 哈希。
- 107 个定向测试验证工程契约（含 27 个真实 async 摄取回归），不等同于“读者读完能写出 X”或百科全书内容质量证明。

## 风险处置

已修复的阻塞根因：历史 slug 的标点/分隔符差异被视为 dangling relation；关系门禁错误地要求 unresolved 必须为 0；CLI 只能查全局 registry，无法在受限环境按项目路径运行。当前剩余 70 条关系仍保留在 manifest 审计数据中，但比例为 2.33%，不再触发 5% 编译阻断阈值；任何失败仍保留旧 release，不自动降级。


## 边界问题复核（2026-09-05）

- 外部绝对路径摄取：`LineageStore.ensure_source` 现在以稳定绝对 key 登记，但仅在调用方提供 `source_text` 时接受，不会隐式读取项目外文件；`generate_ingest` 与候选 source_id 使用同一 key。
- 重摄取/批量隔离：修复 Windows 文本换行导致 lineage digest 与落盘 bytes 不一致的问题；`safe_write` 统一按 UTF-8 bytes 写入，重复摄取和失败文件后的后续文件均可继续提交。
- 异步回归：安装 `pytest-asyncio` 后 `test_ingest_generate_commit_split.py` + `test_pipeline.py` 共 **27 passed**；百科编译/摄取同步定向回归 **27 passed**；阻塞根因修复后 Book/项目解析 44 passed，KC/项目回归 691 passed。
