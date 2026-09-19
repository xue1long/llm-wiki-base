# novel-wiki-v2 质量门理由复核

- 结论：拒绝“质量通过”总体合理，但报告存在明显误报/口径混用。
- 真问题：3 个 concept 页没有按实例 v3.0.0 模板输出；其中 `大纲四要素`、`小说大纲写作技巧` 仍是占位正文；`提纲的重要性` 未生成页面且被错误地按 duplicate 降级；source 页摘要为空。
- H2 复核：报告 18 个 broken targets 中，生产 `resolve_wikilink` 可解析 11 个路径型链接（`sources/...`、`concepts/...`）；4 个 `taxonomy-*` 是分类关系，不应要求对应 Wiki 页面；剩余 3 个 `提纲的重要性` 才是真正未解析引用。
- 误报/实现不一致：`processing_depth=source` 是合法 source 页语义，但 lint 的 `VALID_PROCESSING_DEPTHS` 拒绝它；source 页与 concept 页同标题被重复标题扫描器判为重复，未按 page type/派生关系消歧。

### 方案审计整改（2026-09-18）

- 初始修复方案经第一性原理、批判性思维、终局思维、系统思维审计后，补入了 `reconcile → gap ledger → batch gate → KC/Book` 全链路。
- taxonomy 持久化 canonical target 暂定保持 `taxonomy-<slug>` 以兼容现有 ingest/Book/test 契约；输入侧 `taxonomy/<name>` 统一规范化。
- `source` 不加入 LLM processing-depth enum，改为 page type + depth 联合校验。
- 新增内容级 gold assertions、source-only/失败状态矩阵、KC/Wiki/Vector/Book 一致性和二次摄取幂等验收。
- 语义变体不做 fuzzy 自动合并；无法由 candidate title 或既有 alias 证明同一时，进入 `NEEDS_HUMAN_REVIEW`，禁止静默通过。
