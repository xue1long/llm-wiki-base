# Knowledge Core Mainline Plan

## Dependency and scope

依赖 `2026-08-28-workspace-recovery.md` 通过。范围限于 `src/kc/`、`src/collector/`、`src/pipeline/`、`src/services/`、`src/server/routes/`、`src/queue/` 中确认的接线文件及对应测试；Evidence 的完整生命周期留到下一子方案。

## Target flow

`Collector → CanonicalDocument → JSON Analyzer → KnowledgeCandidate → KC review → KnowledgeObject → Wiki projection/writer → index/vector commit`

## Tasks

### 1. Establish the baseline

- 运行 `tests/test_kc/`、`tests/test_collector/`，按 KC 缺陷、迁移接线、环境问题分类。
- 校验 `CanonicalDocument`、`Evidence`、`KnowledgeObject`、`IntegrityGate`、`EvidenceStorage`、Wiki projection 的输入输出合同。
- 确认 `src/kc/api.py` 的 source → candidate → evidence → projection 最小闭环可重复运行。

### 2. Connect the real caller

- 先写失败集成测试，证明 HTTP/programmatic ingest 在 Wiki/index/vector 写入前进入 KC review。
- 检查 `generate_ingest()` 和实际 service/route caller；当前仅有 candidate generator 定义而非正式调用时，以此作为接线缺口。
- 接入 JSON Analyzer、candidate adapter、KC review、现有 generator/projection 和 commit boundary。
- legacy/unified 仅作为显式 shadow/兼容路径，不得与 candidate 同时以不同标准写正式 Wiki。
- 对 HTTP ingest、`run_ingest`、queue worker、CLI/MCP 和 shadow/legacy 逐一列出 caller、被测入口、最终 writer；没有接入 KC 的入口必须标记为兼容/禁止，不得默认为已覆盖。
- 若语义支持服务超时、异常或返回未知 verdict，默认进入 `needs_human_review`，不得放行到正式发布。

### 3. Verify and isolate

- 测试顺序覆盖 Collector → Analyzer → candidate → review → projection → commit。
- 只暂存确认的 KC 接线文件；提交前检查 staged name/status/stat，并执行定向测试。
- 使用写入探针验证 review 前没有 Wiki、index、vector 正式写入；验证 `validate → stage → publish` 的失败路径，保存为 `integration-report.md`。
- 精确测试范围：`tests/test_pipeline/test_ingest_generate_commit_split.py`、`tests/test_pipeline/test_generate_from_candidate.py`、`tests/test_pipeline/test_generate_from_knowledge_object.py`、`tests/test_server/test_service_ingest.py`、`tests/test_server/test_routes.py`，并补充缺失入口测试后再纳入验收。

## Completion gate

真实 candidate caller 可达；所有正式写入均在 review/projection 之后；legacy 不绕过闭包；定向测试可重复通过。否则停止，不进入 evidence lifecycle。
