## 2026-09-17 novel-wiki 随机文档摄取

- 运行实例以工作区实际路径为准：`knowledge/novel-wiki`；`registry.json` 中的 `D:\\201\\20260910\\llm-wiki-base\\knowledge\\novel-wiki` 已过期，不能直接用于本机写入。
- 在 `raw/sources/**/*.md` 的 1361 个 Markdown 原始文档中随机选取 `raw/sources/01_新手入门/入门教程写作方法.md`，文件大小 4374 bytes，SHA-256 为 `dd695239b1126be145d6b168ba3d0879c595922b67b7b7f118dfe278a4efddee`。
- 使用现有 candidate pipeline 的同步 `run_ingest` 一次完成，task `codex-random-9ffcd8f13c0d`，provider 类型为 `RetryLLMProvider`；结果为 3 页：一个 source 页和两个 concept 页。
- 结果核验：`wiki/sources/入门教程写作方法.md`、`wiki/concepts/yy-小说主角十大绝技与套路分析.md`、`wiki/concepts/yy-小说绝技-王霸之气.md` 均写入，source frontmatter 包含规范化的 `raw/sources/...` 引用，`wiki/log.md` 有 task 记录。
- 过程出现证据 quote fuzzy-mismatch、4 个 unresolved references，以及若干质量门 duplicate-degraded 告警，但 pipeline 最终以 exit code 0 完成；后续若需要严格质量验收，应单独处理这些告警，不要把 exit code 0 等同于零告警。
- V7 终态复核：Collector/Analyzer/Reviewer(软降级)/Promoter/Generator/Writer 均有落盘证据，但 `.index/kc/bundles/0eb1.../manifest.json` 仍为 `status=staged`、`stores.vector=pending`，`.index/kc/publication_state.json` 仍为 `preparing/current_version=0`，3 个页面仍在 `vector_pending.json`；因此该次摄取不是完整 V7 发布完成。
