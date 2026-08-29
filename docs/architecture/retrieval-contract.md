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
