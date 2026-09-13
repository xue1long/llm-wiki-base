# novel-wiki 生产级全量推广执行记录

## 授权与范围

- 2026-09-11，用户明确批准将 `knowledge/novel-wiki/raw` 内容发送到 MiniMax-M3 执行全量摄取。
- raw 仍只读；生产派生写入仅走现有 batch executor、原子提交和状态账本。
- fake generate 未启用；批次并发 1；累计预算上限 1.00 USD；任一批次非零退出立即停止。

## 前置事实

- Manifest：69 批，1361 个 `.md` 文件；另有 3 个非 `.md` 文件被明确跳过。
- 当前知识页：1718 页，3829 个切块。
- 向量模型：本地 `thenlper/gte-small-zh`，512 维；重建 run：`prod-vector-20260911`。
- LLM provider：注册名 `minimax`，类型 `openai-compatible`，模型 `MiniMax-M3`，端点为已配置的 MiniMax API；密钥不写入报告。
- 历史批次状态已补齐 raw 状态：398 个历史成功文件标记为 `done`；缺失的 `gap-raw.md` 记录为 legacy orphan/permanent failed；batch 19/20 的各 1 个历史失败文件保留待重试。

## 执行状态

- 向量重建先在 `.index/migration/prod-vector-20260911/` staging 中运行，完成行数校验后才 promote 到 live store。
- 原受控串行器已启动，但在 raw batch 开始前停止；本次没有向 MiniMax 发送 raw 内容。
- 停止原因：用户确认 raw 已摄取，重新生成不是必要动作。当前只继续向量重建与派生状态对账。
- 向量重建已完成：1718/1718 主目录页面、3829/3829 切块、512 维；manifest hash 为 `e9012bc124ae3129880787cbce8fc483f63670fe1633ac575c5d0f2c39d434f8`。
- live 向量库对账：1718/1718 页面 ID、3829/3829 行，无缺页、无多余页；pending ledger=0，ready entries=1718。
- `wiki/_stubs/` 的 22 个占位页按设计不向量化，因此底层 all-scan readiness 会保留 `page_unpublished`；正式主目录和 actionable 写作范围均 ready。

## 验收规则

- 向量：checkpoint 完成、维度一致、row count 与切块数一致后，才更新 ready ledger。
- 原始摄取：每批必须通过现有 pre-commit gate；批次失败、预算暂停、写入冲突或 partial commit 时停止并保留状态。
- 完成声明需补充：最终 raw 快照哈希、批次成功/失败统计、向量 ready/pending 统计、raw 未修改校验。
