# Claim-level Evidence Lifecycle Plan

## Dependency and scope

依赖 KC 主线通过。复用现有 evidence、integrity、semantic support、storage、projection、retrieval 模块；不新增第二套 evidence gate 或状态机。

## State model

`anchored → structurally_verified → entailed`

固定映射：`supports → entailed`；`partially_supports → needs_human_review`；`insufficient → unsupported`；`irrelevant → unsupported`；`contradicts → needs_human_review`。异常、超时、未知 verdict 一律 `needs_human_review`。

异常分支为 `unsupported` 或 `needs_human_review`。其中 `entailed` 只能由语义支持判断产生，不能由 quote 存在、generator 输出或结构校验单独产生。

## Tasks

### 1. Normalize binding

- 将 candidate statement 适配为稳定 claim `id/text/source`，保留 claim → evidence 关系。
- 统一 source identity、canonical block、短 quote、quote hash、refs 类型和去重规则。
- 明确 `source_path` 一致性：evidence 的 source 必须与 canonical source identity 匹配，禁止只靠文件名或短 quote 通过。
- source canonicalization 固定为：URL 保留 scheme/host/path 规范形式；本地路径转绝对路径、统一分隔符并按平台大小写规则比较；比较键为 `canonical_source_id + canonical_block_id + quote_hash`，basename 不参与身份判定。
- 短 quote 防护：空白归一化后长度不足 20 个 Unicode 字符，或无法唯一定位 canonical block，直接拒绝结构验证。

### 2. Run structural and semantic review

- 结构校验成功后进入 `anchored` / `structurally_verified`。
- `supports` 才能进入 `entailed`；其余 verdict 严格按上方固定映射处理，并保留 reason，不允许调用方自行选择状态。
- strict failure 在 projection/commit 前终止；review failure 进入 ReviewItem，不产生正式写入。

### 3. Make all consumers use one state source

- `EvidenceStorage` 保存 evidence 真相；Wiki 只保存稳定 refs 和展示投影。
- 状态唯一来源为 EvidenceStorage：KnowledgeObject 只保存发布所需派生结果，Wiki 只保存 refs/展示投影，retrieval 通过统一查询读取状态，不自行推导状态。
- retrieval 默认过滤 candidate、quarantined、unsupported；审计查询可显式查看。
- legacy 页面必须带明确 legacy 标识；默认检索不把 legacy 当作已验证 evidence，迁移只能通过显式迁移流程产生新 evidence。
- source 页可回到 canonical source/block/quote；新页面、旧页面、legacy 页面分别验证，不伪造补齐旧 evidence。
- 验证 `src/kc/compiler/evidence.py`、`integrity/gates.py`、`integrity/orchestrator.py`、`semantic_support/checker.py`、`evidence/storage.py`、`adapters/wiki_projection.py`、`adapters/wiki_writer.py`、`retrieval/filter.py` 及相关服务/测试的状态一致性。

### 4. Acceptance tests

- 覆盖 source mismatch、短 quote、跨 block、malformed refs、quote hash、重复 evidence、strict/review/quarantine 和 retrieval leakage。
- 覆盖 claim → evidence → canonical block 的完整回溯，以及 atomic failure 无 Wiki/index/vector 写入。
- 语义判定输入固定为 `claim.text + canonical_source_block + normalized evidence`；覆盖异常/超时/未知 verdict、孤儿 evidence、部分发布和重复重试。
- 测试命令：`python -m pytest tests/test_kc/test_evidence_gate.py tests/test_kc/test_provenance_gate.py tests/test_kc/test_evidence_storage.py tests/test_kc/test_semantic_support.py tests/test_kc/test_default_retrieval_filter.py -v --import-mode=importlib`，并追加本阶段新增的 lifecycle integration test。

## Completion gate

状态只有一个权威来源；所有下游消费同一状态；`entailed` 不可被结构证据伪造；回溯和失败原子性测试通过。否则停止，不处理 WebUI 或批量 Wiki 产物。

验收记录保存为 `evidence-report.md`，包含每个 verdict→status 映射、source canonicalization 样例、失败写入断言和 claim/evidence/block 回溯样例。
