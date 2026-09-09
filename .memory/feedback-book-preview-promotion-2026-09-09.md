# Book preview → promotion 实施记录（2026-09-09）

## 结论

Book 发布链路已支持 `preview` 后使用 `--apply --apply-from <release_id>`
直接提升同一候选版本，不重新调用 provider。人工可读性/人工验收改为
独立 advisory evidence，缺失时为 `not_requested`，不再阻塞发布。

## 已落地

- 候选版本固定在 `<project>/.index/book-wiki/versions/<release_id>`，校验
  manifest canonical digest、闭合集合文件哈希、路径安全、项目/Book 身份、
  快照新鲜度和生命周期。
- `publish_validated_candidate` 是普通发布和 Apply-from 共用的原子发布 seam；
  旧 `lock=None` 直调和同 run_id 幂等契约保持兼容。
- `human-approval.json` 绑定 release ID、manifest 哈希和可识别身份；不进入
  manifest 的不可变文件 hash map。
- fresh outline 预算估算复用与 `plan_outline` 相同的 prompt payload；新的
  call-site 元数据使用 `requested`，预算不足在 provider 构造/调用前阻断。
- Book 结果显式 `vector_index: not_updated`；LanceDB 通过 `vector status` /
  `vector reconcile` 单独处理。

## 验证

- 完整确定性回归：`836 passed`。
- Apply-from provider-free promotion、快照过期拒绝、CLI 参数约束和人工审批
  sidecar 均有 focused tests。
- 未执行真实 MiniMax 调用；未 force-add 被 Git 忽略的项目 policy 文件。

## 操作记忆

发布前只批准 preview 的 manifest/call-site 证据；发布时必须引用同一
`release_id`。不要重新运行 `--apply` 生成新版本，也不要把 Book 发布误认为
LanceDB 已刷新。
