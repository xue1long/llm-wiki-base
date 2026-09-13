# Task 1：落地书系 manifest 和兼容契约

**目标：** 实现 `series-manifest-v1`、book manifest、状态机、批次一致性和旧版兼容读取，为后续 outline/compiler/UI 提供稳定接口。

**Files:** 新增 `src/kc/views/book/wiki/series_model.py`、`series_validate.py`；按需要修改 `src/services/files.py`、`src/server/routes/files.py`；新增契约测试。

**必须满足：**

- schema_version 固定为 `series-manifest-v1`；必需字段为 `series_id`、`release_id`、`status`、`books`。
- book 字段至少包含 `book_id`、`required`、`status`、`outline_id`、`hard_dependencies`、`soft_dependencies`。
- 状态只允许 `draft -> partial -> ready` 或 `draft/partial -> invalid`；非法跳转 fail-closed。
- series `ready` 只能在同一 release 批次内所有 `required=true` 书均 `ready` 时成立；有失败或缺依赖时只能 `partial/invalid`。
- 校验 series/book manifest、outline、sidecar、正文的 sha256；manifest 自身使用 canonical digest，不能自引用。
- 旧 outline-v1/旧 release 缺少 `series_id` 时按单书兼容读取，禁止猜测其新书归属。
- hard dependency 只在目标书存在且状态为 ready 时满足；空候选不能满足依赖；soft dependency 缺失只记录，不阻断。
- API 若修改，必须保持现有单书响应字段兼容，新增字段可选；不得暴露密钥或绝对路径。

**测试要求：** 先写失败测试，覆盖合法 manifest、非法 schema、非法状态跳转、required/partial/invalid、跨批次拒绝、哈希缺失/错误、hard/soft dependency、空候选依赖、legacy fallback 和 API 兼容。运行 `TEMP/TMP/TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest <new tests> -q`，再跑相关 server/files 和 book 回归测试。

**实现约束：** 只用标准库和现有项目工具；保持模块内部实现私有，仅通过本模块公共 API；不调用远程 LLM；不要删除或重置其他未提交改动。

**报告：** 写入 `.superpowers/sdd/2026-09-06-novel-wiki-book-series-target/task-1-report.md`，包含改动文件、RED/GREEN 命令和结果、接口示例、兼容策略、已知限制。不要派生子代理；完成后提交一个逻辑 commit，只返回状态、commit、测试摘要和 concerns。
