# V7 extract Stage 4–7 实施记录（2026-09-14）

## 结果

- Stage 4：`topic_clusterer.py` 提供 3–5 主题边界、LLM JSON 注入和规则回退；`concept_deduplicator.py` 按 id/标题合并来源，新候选冲突稳定加后缀并保持幂等。
- Stage 5：`slot_filler.py` 输出 `ConceptPage`，固定五个 concept 槽位：`definition`、`characteristics`、`examples`、`related_concepts`、`references`；LLM 缺字段时回退，不泄漏额外键。
- Stage 6：`relation_extractor.py` 输出去重后的 `PageRelation`，当前支持 `refines` 与 `supported_by`，过滤自环、未知目标和未知类型。
- Stage 7：`wiki_writer.py` 与 `audit_logger.py` 提供原子写入、checkpoint、3 次重试、index 幂等和 source→concept 审计映射。

## 验收证据

- V7 extract 专项：`46 passed, 2 skipped`。
- `tests/test_pipeline/`：`658 passed, 2 skipped, 43 warnings`。
- 各 Stage 已分别提交：`e6649c52`、`f1b23d38`、`4c21132c`、`f4f713de`。
- `graphify update .` 未执行成功：宿主工具报 `uv trampoline failed to canonicalize script path`；不属于测试或代码失败。

## 后续约束

- 当前实现位于 `src/pipeline/v7_extract/`，未改动稳定的旧 `src/pipeline/ingest.py`。
- 尚未 push；需要用户明确授权后才能执行。
