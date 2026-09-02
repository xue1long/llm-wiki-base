# Evidence Contract 解耦重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将证据绑定从 LLM 输出中移出，使 Analyzer 只选择证据 block，系统确定性生成 quote、hash 和 evidence_id，同时保持现有 Wiki 产出、模板和落盘兼容。

**Architecture:** 保留 Collector → Analyzer → Reviewer → Generator → Writer 外层流程，仅替换 Analyzer 到 Reviewer 的候选契约。新增 Evidence Block Registry 作为单一证据来源，LLM 输出稳定 `block_id`，Evidence Binder 从 canonical block 注入 quote；旧 candidate 格式通过兼容 Adapter 转换，不立即删除旧路径。

**Tech Stack:** Python 3.11+, dataclass, JSON structured output, pytest, 现有 `CanonicalDocument`、`CandidateReviewer`、`run_ingest`、Wiki Writer。

**Spec:** 本文档前置设计结论；原有模板与摄取边界见 `docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md` 及 `docs/guides/wiki-spec.md`。

## Global Constraints

- 不改变业务目标：源文档仍生成对应 Wiki。
- 不改变 Wiki 模板、PageType、Writer 原子写入和现有目录结构。
- LLM 不再生成 evidence quote、quote_hash 或 evidence_refs 数组。
- 系统只接受可见且存在于本次 Evidence Block Registry 的 block_id。
- quote、quote_hash、evidence_id 必须由系统生成。
- 不因单个 claim 失败而丢弃整篇文档；无有效 claim 时才进入 `REVIEW_REQUIRED`。
- 所有自动重试必须有固定上限；禁止递归重试或整链路重跑。
- 兼容期保留旧 candidate 输入，旧格式只能经过 Adapter 进入新契约。
- 不新增第三方依赖。
- 每个任务完成后执行对应测试并单独提交。

---

## 目标数据契约

### Analyzer 输出契约

```json
{
  "source_id": "raw/sources/demo.md",
  "type": "concept",
  "title": "写作方法",
  "claims": [
    {
      "statement": "作者需要长期坚持写作。",
      "confidence": 0.9,
      "evidence_block_ids": ["block_001"]
    }
  ]
}
```

禁止 Analyzer 输出以下字段作为可信输入：`quote`、`quote_hash`、`evidence_refs`、不存在的 block_id。

### 系统绑定后的内部契约

```python
EvidenceBinding(
    evidence_id="evidence_<hash>",
    block_id="block_001",
    quote="作者需要长期坚持写作。",
    quote_hash="<sha256>",
    status="structurally_verified",
)
```

### 失败策略

```text
非法 block_id / 不可见 block_id → 丢弃对应 claim并记录 reason_code
claim 无任何有效 evidence       → 丢弃该 claim
全部 claim 被丢弃                 → REVIEW_REQUIRED
Wiki link 未解析                  → 进入既有 gap ledger，不阻塞 evidence
```

---

### Task 1: 建立 Evidence Block Registry 与新候选类型

**Files:**
- Create: `src/kc/contracts/candidate_v2.py`
- Create: `src/kc/contracts/evidence_binding.py`
- Create: `src/pipeline/evidence_registry.py`
- Modify: `src/pipeline/text_preprocessing/types.py`
- Test: `tests/test_pipeline/test_evidence_registry.py`
- Test: `tests/test_kc/test_candidate_v2.py`

**Interfaces:**
- `EvidenceBlockRegistry.from_preprocess(result: PreprocessResult) -> EvidenceBlockRegistry`
- `EvidenceBlockRegistry.visible_block_ids() -> frozenset[str]`
- `EvidenceBlockRegistry.get(block_id: str) -> EvidenceBlock | None`
- `bind_claim(statement: str, block_ids: list[str], registry: EvidenceBlockRegistry) -> BoundClaim | None`
- `BoundCandidate` 包含 `source_id`、`title`、`claims`、`evidence`，不包含 LLM quote。

- [ ] **Step 1: Write the failing test**

测试 `from_preprocess` 必须保留 canonical block_id，同时记录 `prompt_content` 和可见性；绑定必须从 canonical content 生成 quote，不能读取 LLM quote。

```python
def test_bind_claim_injects_canonical_quote_only():
    prepared = preprocess_source("标题\n\n正文证据。", source_id="raw/sources/a.md")
    registry = EvidenceBlockRegistry.from_preprocess(prepared)
    block = next(iter(registry.visible_block_ids()))
    bound = bind_claim("正文证据。", [block], registry)
    assert bound.evidence[0].quote == registry.get(block).canonical_content
    assert bound.evidence[0].quote_hash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_evidence_registry.py tests/test_kc/test_candidate_v2.py --import-mode=importlib -q`

Expected: FAIL because the registry and new contract do not exist.

- [ ] **Step 3: Write minimal implementation**

实现 `EvidenceBlock` 保存 `block_id`、`canonical_content`、`prompt_content`、`visible`；`bind_claim` 只接受 `visible=True` 且存在的 block，并使用 `canonical_content` 计算 quote/hash/evidence_id。重复 block_id 去重；没有有效 block 返回 `None`。

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_evidence_registry.py tests/test_kc/test_candidate_v2.py --import-mode=importlib -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/kc/contracts/candidate_v2.py src/kc/contracts/evidence_binding.py src/pipeline/evidence_registry.py src/pipeline/text_preprocessing/types.py tests/test_pipeline/test_evidence_registry.py tests/test_kc/test_candidate_v2.py
git commit -m "feat(evidence): add deterministic block registry"
```

### Task 2: 将 Analyzer 改为只输出 block_id

**Files:**
- Modify: `src/pipeline/analyzer.py`
- Modify: `src/pipeline/text_preprocessing/api.py`
- Test: `tests/test_pipeline/test_analyzer_json.py`

**Interfaces:**
- `analyze(...) -> KnowledgeCandidate` 继续保留外部调用签名。
- `KnowledgeCandidate.claims[*]` 在新模式下使用 `evidence_block_ids: list[str]`。
- Analyzer prompt 的 block registry 只列出可见 block 的 `block_id` 与 `prompt_content`。

- [ ] **Step 1: Write the failing test**

新增测试断言生成的 Analyzer prompt 不要求模型生成 quote 或 evidence_refs，并要求 block_id 只能从列出的可见 registry 选择。

```python
def test_json_prompt_makes_block_ids_authoritative_and_quote_system_owned():
    prompt = ANALYZER_JSON_PROMPT
    assert "evidence_block_ids" in prompt
    assert "quote由系统生成" in prompt
    assert "evidence_refs" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_analyzer_json.py -k block_ids --import-mode=importlib -q`

Expected: FAIL because the old prompt still asks for quote/evidence_refs。

- [ ] **Step 3: Write minimal implementation**

修改 JSON schema 和 prompt：`claims` 只接受 `statement`、`confidence`、`evidence_block_ids`；删除 quote 生成要求；在 prompt 中明确“只允许使用上方可见 block_id，quote 由系统绑定”。解析器保留旧字段读取能力，但不把旧 quote 当作新契约的可信证据。

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_analyzer_json.py --import-mode=importlib -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/analyzer.py src/pipeline/text_preprocessing/api.py tests/test_pipeline/test_analyzer_json.py
git commit -m "refactor(analyzer): select evidence blocks only"
```

### Task 3: 增加 Legacy Adapter 与确定性 Evidence Binder

**Files:**
- Create: `src/kc/adapters/candidate_v2.py`
- Modify: `src/kc/api.py`
- Modify: `src/kc/mainline.py`
- Test: `tests/test_kc/test_candidate_v2_adapter.py`
- Test: `tests/test_kc/test_candidate_adapter.py`

**Interfaces:**
- `adapt_candidate(candidate, document, registry, source_root=None) -> BoundCandidate`
- `CandidateReviewer.review(...)` 接收 `BoundCandidate` 或旧 candidate；旧 candidate 统一先过 Adapter。
- `candidate_to_payload(...)` 只接收系统生成的 bound evidence，不再依赖模型 quote。

- [ ] **Step 1: Write the failing test**

覆盖三种行为：错误 quote 不影响系统注入的 canonical quote；错误 block_id 的 claim 被隔离；隐藏 block 不能绑定。

```python
def test_adapter_ignores_llm_quote_and_binds_visible_block():
    prepared = preprocess_source("标题\n\n正文证据。", source_id="raw/sources/a.md")
    document = prepared.canonical_document
    registry = EvidenceBlockRegistry.from_preprocess(prepared)
    block_id = next(iter(registry.visible_block_ids()))
    candidate = {
        "source_id": "raw/sources/a.md",
        "claims": [{"statement": "正文证据。", "evidence_block_ids": [block_id]}],
    }
    bound = adapt_candidate(candidate, document, registry)
    assert bound.evidence[0].quote == "正文证据。"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_kc/test_candidate_v2_adapter.py --import-mode=importlib -q`

Expected: FAIL because current adapter直接信任 candidate quote。

- [ ] **Step 3: Write minimal implementation**

新 Adapter 以 `evidence_block_ids` 为唯一入口；按 claim 绑定可见 block；为旧 candidate 提供一次性转换：若旧 quote 在唯一可见 block 中匹配则保留对应 block_id，否则不猜测，隔离该 claim。禁止通过模糊相似度或标题猜 block。

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_kc/test_candidate_v2_adapter.py tests/test_kc/test_candidate_adapter.py --import-mode=importlib -q`

Expected: PASS，旧的隐藏 block 拒绝测试必须继续 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/kc/adapters/candidate_v2.py src/kc/api.py src/kc/mainline.py tests/test_kc/test_candidate_v2_adapter.py tests/test_kc/test_candidate_adapter.py
git commit -m "refactor(kc): bind evidence deterministically"
```

### Task 4: 接入摄取主线并隔离 claim 级失败

**Files:**
- Modify: `src/pipeline/ingest.py`
- Modify: `src/pipeline/reconcile.py`
- Test: `tests/test_pipeline/test_ingest_candidate.py`
- Test: `tests/test_pipeline/test_reconcile.py`

**Interfaces:**
- `run_ingest(...)` 创建一次 `EvidenceBlockRegistry`，Analyzer、Reviewer、audit 使用同一实例。
- `review_candidate` 返回有效 claim、隔离 claim、reason_codes。
- `missing_slugs_resolver` 只处理 Wiki link，不处理 Evidence block。

- [ ] **Step 1: Write the failing test**

构造一个包含 3 个 claim 的 candidate，其中 1 个使用隐藏 block、1 个有效、1 个 block_id 不存在；断言最终保留 1 个有效 claim，且无有效 claim 时返回 `REVIEW_REQUIRED`。

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_ingest_candidate.py -k claim_isolation --import-mode=importlib -q`

Expected: FAIL because current reviewer 对任一 evidence 错误都拒绝整篇 candidate。

- [ ] **Step 3: Write minimal implementation**

在 candidate review 前建立 registry，调用 Adapter 生成 BoundCandidate；只将有效 claim 送入 `compile_source`；把隔离 claim 写入现有 review/audit metadata，不写 Wiki page；全部失效时抛出已有 review rejection 类型并进入 quarantine。删除 generator 对 evidence quote 的任何修复责任，保留其 Wiki link gap 处理。

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_ingest_candidate.py tests/test_pipeline/test_reconcile.py --import-mode=importlib -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/ingest.py src/pipeline/reconcile.py tests/test_pipeline/test_ingest_candidate.py tests/test_pipeline/test_reconcile.py
git commit -m "refactor(ingest): isolate invalid evidence claims"
```

### Task 5: 保持 Generator/Writer 兼容并移除 Evidence 重试耦合

**Files:**
- Modify: `src/pipeline/generator.py`
- Modify: `src/pipeline/ingest.py`
- Test: `tests/test_pipeline/test_generator.py`
- Test: `tests/test_pipeline/test_ingest_e2e.py`

**Interfaces:**
- Generator 输入只包含已绑定的 claims/evidence 和模板上下文。
- `_call_with_slot_retry` 仅负责 JSON、截断和必填 slots；不读取或修复 Evidence。
- Writer 输入输出结构保持不变。

- [ ] **Step 1: Write the failing test**

新增回归测试：candidate 含无效 Evidence claim 时，Generator 不触发 Evidence retry；Wiki link 缺失仍只进入 gap ledger。

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_generator.py tests/test_pipeline/test_ingest_e2e.py --import-mode=importlib -q`

Expected: FAIL because current generator retry path仍可能接收并处理未绑定 evidence。

- [ ] **Step 3: Write minimal implementation**

删除 Generator 对 candidate evidence quote/block 的判断和修复分支；保留已有一次性 unresolved Wiki link retry 上限。确保 `generate_from_candidate` 和 `generate_from_knowledge_object` 对新 BoundCandidate 与旧适配结果使用同一输入形状。

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. pytest tests/test_pipeline/test_generator.py tests/test_pipeline/test_ingest_e2e.py --import-mode=importlib -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/generator.py src/pipeline/ingest.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_ingest_e2e.py
git commit -m "refactor(generator): remove evidence retry coupling"
```

### Task 6: 兼容迁移、Shadow 对比与真实验收

**Files:**
- Modify: `src/pipeline/ingest.py`
- Modify: `src/config.py`
- Create: `tests/test_e2e/test_evidence_contract_migration.py`
- Create: `docs/adr/ADR-003-deterministic-evidence-binding.md`
- Modify: `docs/environment/SETUP.md` only if a new test command is required

**Interfaces:**
- `RUFLO_EVIDENCE_CONTRACT=v1|v2`，默认 `v1`，验收通过后显式切换 `v2`。
- `RUFLO_SHADOW_MODE=true` 时同时执行旧 Adapter 与新 Binder，只比较候选/evidence/gap，不重复 Writer 写入。
- 回滚仅需切回 `RUFLO_EVIDENCE_CONTRACT=v1`，不迁移已有 Wiki 页面。

- [ ] **Step 1: Write the failing test**

建立固定 fixture 覆盖：旧 candidate、v2 candidate、隐藏 block、错误 quote、错误 refs、重复 quote、无有效 claim；断言 v1/v2 的 Wiki 页面字段兼容，v2 不产生 LLM quote。

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. pytest tests/test_e2e/test_evidence_contract_migration.py --import-mode=importlib -q`

Expected: FAIL because the feature flag、shadow comparison and rollback path do not exist.

- [ ] **Step 3: Write minimal implementation**

增加单一配置开关和 Adapter 路由；shadow 结果写入 `.index/shadow/<task_id>/evidence-contract.json`，不写 Wiki；新增 ADR 记录新契约、兼容期、切换条件和回滚动作。禁止默认切换生产模式。

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
PYTHONPATH=. pytest tests/test_e2e/test_evidence_contract_migration.py tests/test_kc/ tests/test_pipeline/ --import-mode=importlib -q
```

Expected: PASS；现有测试不得出现新增失败。

- [ ] **Step 5: Run isolated real acceptance**

从 `knowledge/novel-wiki/raw/sources/` 选择 3 篇写作文档，在临时项目副本中执行 v2：

```text
1. 方法论写作目的和心态.md
2. 进阶教程大纲书写格式.md
3. 大纲示例武炼巅峰.md
```

验收每篇必须同时满足：

- source screening 完成；
- Analyzer 输出至少 1 个有效 claim；
- 每个发布 claim 的 evidence 由系统注入 quote/hash；
- 不出现 quote mismatch、evidence_refs invalid；
- Generator 完成且引用重试不超过 1 次；
- Writer 原子落盘 source page 与生成页；
- 失败 claim 可在 audit metadata 中追踪；
- 原始实例目录无写入。

- [ ] **Step 6: Commit**

```bash
git add src/pipeline/ingest.py src/config.py tests/test_e2e/test_evidence_contract_migration.py docs/adr/ADR-003-deterministic-evidence-binding.md docs/environment/SETUP.md
git commit -m "feat(evidence): add compatible contract migration"
```

## 迁移退出条件

满足以下全部条件后，才允许把默认值从 `v1` 改为 `v2`：

1. 三篇真实写作文档连续两次运行全部完成。
2. 生成的每条 evidence 的 quote 都来自系统 canonical block。
3. 连续 20 个固定回归 fixture 无 evidence contract 失败。
4. Shadow 对比没有出现 source、claim、evidence 数量异常下降。
5. v1 回滚在临时副本验证成功。
6. 无新增第三方依赖，无 Writer/Wiki 模板回归。

## 方案审计基线

### 第一轮：漏洞审计

- **致命缺陷：** 若 registry 的 block_id 与 prompt block_id 不同，所有 evidence 会被隔离。防护：Task 1 固定同一 registry 实例，Task 6 加 hash/数量 shadow 对比。
- **致命缺陷：** Adapter 通过模糊匹配自动重连，会产生错误证据。防护：只允许显式 block_id；旧格式只允许唯一可见 quote 映射，不能相似度猜测。
- **重大隐患：** claim 级隔离后可能整篇只剩无证据内容。防护：全部 claim 无效时 `REVIEW_REQUIRED`，禁止空证据发布。
- **重大隐患：** canonical quote 与 prompt view 不同。防护：LLM 不再返回 quote，系统只从 canonical block 注入。
- **重大隐患：** v1/v2 同时写盘导致重复页面。防护：shadow 只写比较文件，不调用 Writer。
- **重大隐患：** evidence contract 切换后无法回滚。防护：配置开关、无数据迁移、Task 6 回滚验收。
- **优化疏漏：** 审计结果未暴露 claim 隔离原因。防护：写入 reason_codes 和原 block_id。
- **优化疏漏：** 旧测试只验证错误被拒绝，未验证新契约的绑定来源。防护：Task 1、3、6 增加来源独立性测试。

### 第二轮：压力测试

- LLM 输出不存在 block_id：claim 被隔离，不能阻塞其他 claim。
- LLM 输出空 block_id：同上，不能 fallback 到标题或相似文本。
- 所有 block 被去噪隐藏：进入 `REVIEW_REQUIRED`，不生成无证据 Wiki。
- LLM 输出旧格式：Legacy Adapter 仅在唯一可见 quote 匹配时转换，否则隔离。
- Generator 输出幽灵 wikilink：进入 gap ledger，不触发 Evidence 重试。
- provider 超时：沿用现有 provider/queue 重试上限，不增加 contract 层重试。
- shadow 结果数量差异：只记录比较结果，不影响生产写入；切换前阻止 v2 默认启用。
- v2 运行中回滚：新任务切回 v1，已写页面无需迁移，避免破坏已有 Wiki。

## 当前明确不做

- 不重写模板解析器。
- 不新增远程模板中心。
- 不改变 Vector/Writer 架构。
- 不引入新的 LLM 评分器或二次语义审查。
- 不删除旧 candidate 字段和 legacy pipeline，直到迁移退出条件满足。
