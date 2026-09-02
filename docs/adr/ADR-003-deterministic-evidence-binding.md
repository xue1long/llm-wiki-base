# ADR-003：确定性证据绑定与兼容迁移

- 状态：Accepted
- 日期：2026-09-02

## 决策

Analyzer v2 只输出 `evidence_block_ids`。系统在同一摄取任务创建
`EvidenceBlockRegistry`，从 canonical block 确定性生成 quote、hash 和
`evidence_id`。旧 candidate 通过 Legacy Adapter 进入同一绑定边界。

v1 是默认契约；v2 通过 `RUFLO_EVIDENCE_CONTRACT=v2` 显式启用。v2 的
`generator_candidate` 只作为旧 Generator 的兼容输入，不改变 Generator、
Writer 或 Wiki 页面格式。

## 安全与回滚

- 不存在或不可见的 block 只拒绝对应 claim；没有有效 claim 时进入
  `review_required`，禁止发布空 evidence 页面。
- Shadow 使用已经解析的 Analyzer 结果，不再次调用 LLM，不调用 Writer，
  结果写入 `.index/shadow/<task_id>/evidence-contract.json`。
- v2 bundle manifest 写入 `contract_version: "v2"`。
- 回滚只在任务边界切回 v1。未发布 v2 bundle 通过
  `quarantine_incomplete_v2_bundles()` 原子移入 `.index/quarantine/`；已发布
  Wiki 和已发布 bundle 不回写。

## 切换条件

只有在三篇真实写作文档连续两次通过、20 个固定 fixture 无契约失败、Shadow
没有异常下降且 v1 回滚演练通过后，才允许将默认契约切换为 v2。

## 不在本决策内

不重写模板解析器，不新增远程模板中心，不改变 Vector/Writer 架构，
不删除 legacy candidate 字段。
