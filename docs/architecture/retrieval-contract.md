# Retrieval Contract

新代码统一使用 `src.kc.retrieval.RetrievalResult`：

- `id/title/score/content`：兼容现有搜索结果。
- `evidence`：只有明确的 `document_id + block_id + quote` 才进入此字段。
- `provenance=evidence`：存在 block 级证据。
- `provenance=legacy`：只有旧页级来源或没有证据，不能冒充新 Evidence。

`search()` 是现有搜索服务的薄适配器；`get_evidence()` 和
`get_relations()` 只读取，不改变底层存储。

现有 Wiki 的真实搜索结果目前仍是 `legacy`，因为旧页面没有 block 级
Evidence；这属于数据能力缺口，不在适配器中伪造证据。

写作检索合同：`hybrid` 和 `vector` 请求必须先通过项目的 Wiki/Vector
`ready` 判断；存在 pending、failed、模型不一致或页面/向量 hash 不一致时，
返回空结果并带 `ready=false` 与诊断原因。显式 `keyword` 是可用的诊断回退，
不依赖向量状态。通过 ready 后，语义写作检索只返回带人工审核标签
`用途/可执行` 的页面；请求的 `mode` 必须传入底层搜索器。
