# Knowledge Compiler C-phase E2E

当前最小链路：

`Markdown/TXT/URL → CanonicalDocument → Claim + Evidence → Verification → KnowledgeObject → WikiProjection`

入口：

- CLI：`python -m src.kc.api <source-file> '<candidate-json>'`
- HTTP：`POST /api/v1/kc/compile`

HTTP 请求字段：`source`、`content`、`candidate_json`。响应中的
`document_id`、`knowledge_object_id`、`evidence_ids` 和
`projection_version` 用于反查链路。

当前投影是只读对象，不写 Wiki；正式 Writer 接入属于后续 C-05/B 阶段，
避免在验证链路未稳定前产生半发布数据。
