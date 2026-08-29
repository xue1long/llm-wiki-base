# KC Trustworthy MVP 后续实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项执行。每个任务使用 checkbox 跟踪，并在任务完成后独立测试、审查和提交。

**Goal:** 在现有 src/kc、src/knowledge、Wiki 和 L3 vector publication intent 基础上，完成一个可交付、可恢复、可审计的 Knowledge Core MVP。

**Architecture:** Wiki 继续作为用户可见内容的事实来源，原始资料保持只读，KC 负责结构化候选、证据链、完整性判定、检索过滤和版本恢复。复用现有 src/kc、src/knowledge/storage、KnowledgeKernel、VersionManager、vector_pending 和已有 Wiki writer，不迁移到新目录、不增加第二套 writer、不新增全局 waterline。

**Tech Stack:** Python 3.11+、现有 dataclass/Pydantic 契约、JSON/JSONL 文件存储、现有 WikiPaths、LanceDB/vector pending、pytest。

**Spec:**
- 原始需求参考：C:/Users/HP/Documents/Codex/2026-08-26/referenced-chatgpt-conversation-this-is-an/outputs/DEVELOPMENT_PLAN.md
- 已完成的 L3 边界：docs/superpowers/plans/2026-08-28-kc-l3-vector-publication-intent.md
- 本文是对原始大计划的裁剪执行版；原始计划中的目录结构、Book、插件平台、100/20 数量仪式和固定实现顺序不属于本 MVP。

## Global Constraints

- Wiki 是用户可见页面和发布状态的事实来源；向量、缓存、报告均为可重建派生数据。
- 原始资料只读；任何候选事实必须保留 CanonicalDocument → Block → Evidence → Claim/Fact → projection 的可追溯链路。
- LLM 只能生成候选，不得直接把候选标记为 verified 或写入默认检索结果。
- structurally_verified 仍只表示结构性证据校验通过；本方案不引入 entailed 或 claim truth。
- 复用现有 src/kc 和 src/knowledge；禁止创建 src/knowledge_compiler 平行目录。
- 复用现有 Wiki writer、KnowledgeKernel、VersionManager、JSONLEventStore 和 vector_pending；禁止第二套页面 writer、第二套向量 ledger 或隐式全局 registry。
- 所有新增失败路径必须 fail-closed，并留下可诊断 reason code；不得以“假设通过”掩盖缺失输入。
- 所有重试、恢复和重建操作必须幂等；重复执行不能产生重复页面、索引记录、事件或向量工作项。
- 不迁移或改写现有历史 Wiki 页面；兼容旧 frontmatter 和旧 vector ledger。
- 不 push；每个逻辑任务单独提交，提交前只添加本任务文件。

## MVP 边界

### 必须交付

1. 真实可判定的证据链和发布闭包，移除 closure 中的假设通过。
2. WikiPage 的最小时间字段和检索时间过滤，未知时间语义明确且可观察。
3. RetrievalResult 携带 evidence、provenance、knowledge mode、context、validity、publication/version 信息，缺失时显式标识而不是伪造。
4. 复用现有 KnowledgeKernel/VersionManager/EventStore 完成最小持久化、版本、回放和备份恢复闭环。
5. L3 intent → pending → reconcile/observability 保持可恢复，并覆盖 ledger 失败、Wiki 提交失败、向量失败、孤儿 intent 和重复扫描。
6. Wiki 视图可从 Core/证据输入重建，重建失败不覆盖现有有效页面。
7. 以真实的 30–50 条首领域案例建立可执行评估基线；所有 evidence_refs 和 expected_top_k 必须非空或明确标为不适用。

### 明确不做

- Book/Chapter compiler、PDF/EPUB renderer、复杂 Book Planner。
- Plugin Manager、Marketplace、多语言 SDK、远程 sandbox。
- claim truth、entailed、claim-to-page mapping。
- 全局 publication waterline、跨视图原子事务、分布式锁和第二套 writer。
- 为满足数量而执行 20 次批处理或强行凑满 100 条 gold cases。
- 固定目录迁移、重复维护 JSON Schema/Pydantic/dataclass 三套契约。
- 为每种可能关系预先建立完整分类；只保留现有白名单和可诊断未知关系。

## 文件和边界地图

当前实现已经存在并优先复用：

- 证据和候选：src/kc/compiler/normalize.py、src/kc/compiler/evidence.py、src/kc/compiler/compile.py、src/kc/extraction/structured_extractor.py
- 完整性：src/kc/integrity/gates.py、src/kc/integrity/orchestrator.py、src/kc/integrity/closure.py
- 时间和冲突：src/kc/compiler/temporal.py、src/kc/conflicts/classifier.py
- 版本和持久化：src/knowledge/kernel.py、src/knowledge/core/version_manager.py、src/knowledge/storage/event_store.py、src/knowledge/storage/facade.py
- Wiki 适配：src/knowledge/core/adapter.py、src/knowledge/storage/wiki_adapter.py、src/kc/views/wiki_template_compiler.py
- 向量发布：src/vector/pending.py、src/pipeline/ingest.py、src/cli_ext/vector_cmd.py、src/server/app.py
- 评估资产：docs/evaluation/、scripts/kc_eval.py、scripts/kc_agent_eval.py

不得因为原始计划列出了另一套模块树，就复制或迁移以上能力。

---

### Task 0: 固化 MVP 基线和真实评估资产

**Files:**
- Create: docs/evaluation/kc_mvp_cases.yaml
- Modify: scripts/kc_eval.py
- Modify: scripts/kc_agent_eval.py
- Test: tests/test_kc/test_eval_contract.py
- Test: tests/test_kc/test_agent_eval.py

**Interfaces:**
- kc_eval.py 保留现有命令行入口，并新增对非空 expected_top_k、evidence_refs、source_type 的检查。
- kc_mvp_cases.yaml 使用现有 case schema；每条案例至少包含非空 source_type、query、context、object_truth、一个可定位 evidence span、一个 expected result 或显式的 not_applicable。
- kc_agent_eval.py 必须区分 mock_response dry-run 与真实 runtime；dry-run 结果不能被报告为产品通过率。
- evaluate_gold_case(case) 在现有 scores 中增加 invalid_fields；evaluate_agent_task_dataset(path) 在现有结果中增加 mode="dry-run" 和 runtime_verified=False。CLI 只渲染这些已有报告。

- [ ] **Step 1: 写失败测试**

    def test_mvp_case_rejects_empty_expected_results():
        case = {"case_id": "case-1", "source_type": "file", "expected_top_k": []}
        result = evaluate_gold_case(case)
        assert result["passed"] is False
        assert "expected_top_k" in result["scores"]["invalid_fields"]

    def test_agent_eval_marks_mock_mode_as_non_runtime(tmp_path):
        path = tmp_path / "tasks.yaml"
        path.write_text(
            "- task_id: t1\n"
            "  success_criteria:\n"
            "    min_units_returned: 0\n"
            "    min_citations_valid: 0\n"
            "  mock_response: {knowledge_items: []}\n",
            encoding="utf-8",
        )
        report = evaluate_agent_task_dataset(path)
        assert report["mode"] == "dry-run"
        assert report["runtime_verified"] is False

- [ ] **Step 2: 运行并确认 RED**

运行：

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_eval_contract.py tests/test_kc/test_agent_eval.py -q

预期：新增断言失败，且失败原因是当前 evaluator 只检查字段存在、不能区分空值和 mock runtime。

- [ ] **Step 3: 实现最小基线校验**

复用现有 YAML 读取和报告格式，只增加：

1. REQUIRED_FIELDS 的非空值校验；
2. not_applicable 的显式例外；
3. agent evaluator 的 mode、runtime_verified 和现有 citation_accuracy 字段；
4. 不修改现有生产检索或摄入逻辑。

- [ ] **Step 4: 运行 GREEN 和资产检查**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_eval_contract.py tests/test_kc/test_agent_eval.py -q
    python scripts/kc_eval.py --dataset docs/evaluation/kc_mvp_cases.yaml

预期：测试通过；案例总数在 30–50 之间；空 evidence/top-k 数为 0（显式 not_applicable 除外）；报告不把 mock 结果标为 runtime 通过。

- [ ] **Step 5: 提交**

    git add docs/evaluation/kc_mvp_cases.yaml scripts/kc_eval.py scripts/kc_agent_eval.py tests/test_kc/test_eval_contract.py tests/test_kc/test_agent_eval.py
    git commit -m "test(kc): establish trustworthy mvp evaluation baseline"

### Task 1: 让默认发布闭包真实 fail-closed

Note: Task 0 may intentionally add a closure contract test that conflicts with the old
`tests/test_kc/test_default_closure.py` simplified-pass baseline. Do not "fix" that in
Task 0 by loosening the contract or editing unrelated old tests; resolve the conflict in
Task 1 when `closure.py` and the legacy test fixtures are updated together.

**Files:**
- Modify: src/kc/integrity/closure.py
- Modify: src/kc/integrity/orchestrator.py
- Modify: tests/test_kc/test_default_closure.py
- Create: tests/test_kc/test_closure_fail_closed.py

**Interfaces:**
- 保持 check_default_closure(obj, integrity_report=None) -> ClosureReport 兼容。
- 保持 ClosureCheck、ClosureReport 字段兼容；新增失败必须通过现有 condition_name 和 details 表达。
- ClosureReport.hard_gates_passed 必须反映真实 IntegrityReport；没有报告时不得默认宣称全部 hard gate 通过。

- [ ] **Step 1: 写失败测试**

    def test_missing_concept_status_is_not_assumed_passed():
        report = check_default_closure(SimpleNamespace(id="x", status="verified"))
        failed = report.get_failed_conditions()
        assert "concept_status_verified" in failed
        assert "assumed" not in report.checks[1].details

    def test_missing_integrity_report_does_not_pass_hard_gates():
        report = check_default_closure(SimpleNamespace(id="x", status="verified"))
        assert report.hard_gates_passed is False

    def test_failed_integrity_report_blocks_closure():
        from types import SimpleNamespace
        from src.kc.integrity.gates import GateVerdict
        from src.kc.integrity.orchestrator import GateResult, IntegrityReport

        obj = SimpleNamespace(id="x", status="verified", knowledge_mode="observed",
                              claim_ids=[])
        integrity = IntegrityReport(
            object_id="x",
            gate_results=(GateResult("context", 7,
                                     GateVerdict.block(["unresolved_context"]),),),
            passed=False,
            blocked=True,
        )
        report = check_default_closure(obj, integrity)
        assert report.passed is False
        assert report.hard_gates_passed is False

- [ ] **Step 2: 运行 RED**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_default_closure.py tests/test_kc/test_closure_fail_closed.py -q

预期：当前 simplified/assumed 路径导致新增断言失败。

- [ ] **Step 3: 实现最小真实检查**

按当前对象实际拥有的字段实现，不新建完整对象 registry：

1. 缺少必需关联数据时返回失败和明确 missing_* reason；
2. knowledge_mode=observed 时检查可见 claim/fact 的 mode 一致性；
3. synthesized 时检查 provenance、derived_from 和 approval；
4. evidence/status/trust/context 只在输入提供对应集合时检查，缺失则 fail-closed；
5. integrity_report 缺失或 blocked 时 hard_gates_passed=False；
6. 删除所有 “assumed passed” 和 “simplified: no integrity_report” 结果。

不得为了通过旧测试把缺失依赖改成通过；应更新旧测试夹具，使其提供完整的最小输入。

- [ ] **Step 4: 运行相关完整性回归**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_default_closure.py tests/test_kc/test_closure_fail_closed.py tests/test_kc/test_integrity_gate.py tests/test_kc/test_mode_fail_closed.py tests/test_kc/test_provenance_gate.py -q

预期：所有测试通过；搜索 src/kc/integrity 不再发现将缺失数据标为通过的假设路径。

- [ ] **Step 5: 提交**

    git add src/kc/integrity/closure.py src/kc/integrity/orchestrator.py tests/test_kc/test_default_closure.py tests/test_kc/test_closure_fail_closed.py
    git commit -m "fix(kc): make publication closure fail closed"

### Task 2: 补齐 Wiki 时间语义和检索结果契约

**Files:**
- Modify: src/wiki/core/types.py
- Modify: src/knowledge/core/adapter.py
- Modify: src/kc/compiler/temporal.py
- Modify: src/kc/retrieval/filter.py
- Modify: src/kc/retrieval/__init__.py
- Modify: src/kc/integrity/gates.py
- Create: tests/test_wiki/test_temporal_fields_roundtrip.py
- Create: tests/test_kc/test_knowledge_adapter_temporal.py
- Modify: tests/test_kc/test_default_retrieval_filter.py
- Modify: tests/test_kc/test_temporal_gate.py
- Modify: tests/test_kc/test_candidate_adapter.py

**Interfaces:**
- WikiPage 增加 valid_from: int | None = None、valid_to: int | None = None，并在 to_frontmatter_dict()/from_dict() 双向兼容。
- 时间区间采用 [valid_from, valid_to)。为兼容未迁移的旧页面，frontmatter 完全没有 valid_from/valid_to 时保留旧的 current 兼容行为；只有显式声明这两个字段且两边均为空时才表示 unknown，并在默认检索中排除。
- DefaultFilter.passes(page, query_time) 保持签名；非法区间 fail-closed，未来生效和已失效页面默认不通过。
- from_dict() 使用不序列化的内部标记记录 validity 是否由 frontmatter 声明，避免旧页面在无迁移时全部变成 unknown。
- RetrievalResult 在现有字段上增加可选字段：knowledge_unit_id、publication_version、knowledge_mode、context、valid_from、valid_to、temporal_status、conflict_status、version。旧调用仍可构造。

- [ ] **Step 1: 写失败测试**

    def test_wiki_page_round_trips_validity_fields():
        page = WikiPage(id="p", title="P", type=PageType.CONCEPT,
                        valid_from=100, valid_to=200)
        restored = WikiPage.from_dict(page.to_frontmatter_dict(), body="body")
        assert (restored.valid_from, restored.valid_to) == (100, 200)

    def test_default_filter_uses_half_open_interval():
        page = WikiPage(id="p", title="P", type=PageType.CONCEPT,
                        workflow_state="verified", valid_from=100, valid_to=200)
        assert DefaultFilter().passes(page, query_time=100)
        assert not DefaultFilter().passes(page, query_time=200)

    def test_legacy_frontmatter_without_validity_stays_compatible():
        page = WikiPage.from_dict({
            "id": "legacy", "title": "Legacy", "type": "concept",
            "workflow_state": "verified",
        })
        assert DefaultFilter().passes(page, query_time=100)

    def test_explicit_empty_validity_is_unknown_and_excluded():
        page = WikiPage.from_dict({
            "id": "unknown", "title": "Unknown", "type": "concept",
            "workflow_state": "verified", "valid_from": None, "valid_to": None,
        })
        assert not DefaultFilter().passes(page, query_time=100)

    def test_unknown_validity_is_explicit_in_result():
        result = normalize_result({"id": "p", "title": "P"})
        assert result.valid_from is None
        assert result.valid_to is None
        assert result.provenance == "legacy"

    def test_knowledge_object_adapter_round_trips_validity():
        obj = KnowledgeObject(
            id="ko-1", type=KnowledgeType.ENTITY, title="K",
            content="body", lifecycle=LifecycleState.ACTIVE, confidence=0.9,
            provenance=Provenance(source_path="raw/k.md"),
            valid_from=100, valid_to=200,
        )
        page = knowledge_object_to_wiki_page(obj)
        restored = wiki_page_to_knowledge_object(page)
        assert (restored.valid_from, restored.valid_to) == (100, 200)

- [ ] **Step 2: 运行 RED**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_wiki/test_temporal_fields_roundtrip.py tests/test_kc/test_knowledge_adapter_temporal.py tests/test_kc/test_default_retrieval_filter.py tests/test_kc/test_temporal_gate.py tests/test_kc/test_candidate_adapter.py -q

预期：WikiPage 没有字段、filter 忽略 query_time、RetrievalResult 没有新字段，新增断言失败。

- [ ] **Step 3: 实现最小时间和结果扩展**

复用 src/kc/compiler/temporal.py 的状态推导；不要再复制一套时间算法。更新 lint/反序列化默认值，保证旧页面可读取。from_dict() 记录不序列化的 validity_declared 标记：旧 frontmatter 无两个字段时沿用 current 兼容路径，显式写出两个 null 时才返回 unknown 并被默认过滤。normalize_result() 对新字段只做明确的类型归一化，不把缺失字段转换成 verified/current。

- [ ] **Step 4: 运行回归**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_wiki/test_temporal_fields_roundtrip.py tests/test_kc/test_knowledge_adapter_temporal.py tests/test_kc/test_default_retrieval_filter.py tests/test_kc/test_temporal_gate.py tests/test_kc/test_temporal.py tests/test_kc/test_candidate_adapter.py -q

预期：时间边界、旧 frontmatter 兼容、显式 unknown 排除、KO/Wiki adapter round-trip、检索兼容和证据保留全部通过。

- [ ] **Step 5: 提交**

    git add src/wiki/core/types.py src/kc/retrieval/filter.py src/kc/retrieval/__init__.py src/kc/integrity/gates.py tests/test_wiki/test_temporal_fields_roundtrip.py tests/test_kc/test_default_retrieval_filter.py tests/test_kc/test_temporal_gate.py tests/test_kc/test_candidate_adapter.py
    git commit -m "feat(kc): expose temporal retrieval contract"

### Task 3: 接通现有 Core 存储、版本、事件和恢复

**Files:**
- Modify: src/knowledge/kernel.py
- Modify: src/knowledge/core/version_manager.py（仅修复恢复/幂等缺口）
- Modify: src/kc/api.py
- Modify: src/kc/backup/core_snapshot.py
- Modify: src/kc/backup/drill.py
- Create: tests/test_kc/test_core_repository_integration.py
- Modify: tests/test_kc/test_core_backup.py
- Modify: tests/test_kc/test_core_backup_drill.py

**Interfaces:**
- 不新增 Repository 类；使用现有 KnowledgeKernel、VersionManager、StorageFacade.events 和 KnowledgeObject。
- 在 src/kc/api.py 增加最小可测试入口 compile_and_store(source: dict, project_path: Path, agent: AgentType) -> StoreResult；StoreResult 返回 object_id、version、event_version 和 projection。
- 在 src/kc/api.py 增加 replay_core(project_path: Path) -> dict[str, KnowledgeObject]；它只从现有事件/版本存储重放，不写 Wiki。
- create_snapshot(paths, objects=None) 在未提供 objects 时从现有 Core storage/event snapshot 读取；当前项目没有 Core 对象时返回空快照而不是假装备份成功。
- 版本写入和事件追加使用已有 safe_write/JSONL；事件 payload 必须包含稳定 idempotency_key，重复 key 不再追加第二条业务事件。replay_core 只接受 kc.object.created/kc.object.updated 两种对象事件，遇到未知或损坏事件抛出 ValueError，不返回部分状态。
- get_kernel(project_path) 按规范化项目根目录隔离 singleton；旧的无参调用仅在已有唯一 kernel 时兼容返回，不能把一个项目的事件写入另一个项目。

- [ ] **Step 1: 写失败测试**

    def test_compile_and_store_is_replayable(tmp_path):
        source = {
            "source_path": "raw/a.md",
            "text": "Knowledge Core stores one cited fact.",
            "candidate": {
                "claims": [{
                    "statement": "Knowledge Core stores one cited fact.",
                    "evidence_refs": [0],
                }],
                "evidence": [{
                    "source_path": "raw/a.md",
                    "quote": "Knowledge Core stores one cited fact.",
                }],
            },
        }
        first = compile_and_store(source, tmp_path, agent=AgentType.PROCESSOR)
        second = compile_and_store(source, tmp_path, agent=AgentType.PROCESSOR)
        assert first.object_id == second.object_id
        first_state = replay_core(tmp_path)
        second_state = replay_core(tmp_path)
        assert first_state == second_state

    def test_snapshot_without_explicit_objects_reads_core_state(tmp_path):
        kernel = KnowledgeKernel(tmp_path)
        obj = KnowledgeObject(
            id="ko-1",
            type=KnowledgeType.ENTITY,
            title="Entity ko-1",
            content="content",
            lifecycle=LifecycleState.ACTIVE,
            confidence=0.9,
            provenance=Provenance(source_path="raw/ko-1.md"),
        )
        kernel.create_object(obj, AgentType.PROCESSOR)
        snapshot = create_snapshot(WikiPaths(tmp_path))
        assert "ko-1" in snapshot.identity_keys

    def test_replaying_duplicate_event_key_has_one_business_effect(tmp_path):
        store = JSONLEventStore(tmp_path / ".index")
        obj = KnowledgeObject(
            id="ko-1", type=KnowledgeType.ENTITY, title="Entity ko-1",
            content="content", lifecycle=LifecycleState.ACTIVE, confidence=0.9,
            provenance=Provenance(source_path="raw/ko-1.md"),
        )
        payload = {
            "idempotency_key": "create:ko-1:v1",
            "object": _serialize_object(obj),
        }
        store.append("ko-1", "kc.object.created", payload)
        store.append("ko-1", "kc.object.created", payload)
        state = replay_core(tmp_path)
        assert sorted(state) == ["ko-1"]

    def test_kernel_instances_do_not_cross_project_events(tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        assert get_kernel(first) is not get_kernel(second)

- [ ] **Step 2: 运行 RED**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_core_repository_integration.py tests/test_kc/test_core_backup.py tests/test_kc/test_core_backup_drill.py -q

预期：当前 KC API 没有 durable store 入口，snapshot 未提供 objects 会直接失败；当前事件 store 也不会去重重复业务事件。

- [ ] **Step 3: 复用现有存储实现**

1. 将编译结果通过现有 KnowledgeKernel/StorageFacade 写入；
2. 对 create/update 事件写入稳定 idempotency_key，并将 version/event id 写入返回值和审计事件；
3. replay_core 按事件顺序恢复对象，重复 key 只保留第一次业务效果，未知 event type 或 malformed payload 立即失败；
4. get_kernel 按项目根目录隔离实例；
5. 让 backup 从同一真实存储读取，而不是依赖调用者临时传入 list；
6. 保留现有显式 objects= 兼容路径；
7. 不改变 Wiki writer 的所有权，不从此任务新增页面写入。

- [ ] **Step 4: 运行恢复验证**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_core_repository_integration.py tests/test_kc/test_core_backup.py tests/test_kc/test_core_backup_drill.py tests/test_kc/test_knowledge_unit.py -q

预期：创建、更新、重放、snapshot、损坏恢复和重复执行均通过；恢复后 identity_key 集合一致。

- [ ] **Step 5: 提交**

    git add src/knowledge/kernel.py src/knowledge/core/version_manager.py src/kc/api.py src/kc/backup/core_snapshot.py src/kc/backup/drill.py tests/test_kc/test_core_repository_integration.py tests/test_kc/test_core_backup.py tests/test_kc/test_core_backup_drill.py
    git commit -m "feat(kc): connect core storage and replay recovery"

### Task 4: 保证 Wiki 视图可重建且不会破坏有效页面

**Files:**
- Modify: src/kc/views/wiki_template_compiler.py
- Modify: src/kc/views/wiki_template.py
- Modify: src/kc/adapters/wiki_projection.py
- Modify: src/knowledge/storage/wiki_adapter.py
- Create: tests/test_kc/test_wiki_rebuild_contract.py
- Modify: tests/test_kc/test_wiki_template_compiler.py
- Modify: tests/test_kc/test_candidate_adapter.py

**Interfaces:**
- 扩展现有 WikiTemplateCompiler.compile(...) -> WikiView，使 evidence、knowledge_mode、context、validity 和 conflict 信息进入同一个 WikiView。
- 增加 rebuild_wiki_view(paths, topic_scope, knowledge_units, conflicts, evidence_lookup, publication_version) -> RebuildReport；它只能生成内存结果或 staging 文件，正式写入仍走既有 writer。
- RebuildReport 至少包含 published: bool、page_ids: tuple[str, ...] 和 failures: tuple[dict, ...]；失败项必须含 object_id 和 reason_codes。
- 现有 WikiPageAdapter/既有 writer 仍是唯一正式写入入口。
- rebuild 必须先完成完整编译和完整性检查，任一对象失败则不覆盖现有页面，并返回失败对象和 reason codes。
- 输出保留 source、evidence、knowledge_mode、context、validity 和 conflict 信息；不能把 synthesized 渲染成 observed。

- [ ] **Step 1: 写失败测试**

    def test_rebuild_failure_does_not_overwrite_existing_page(tmp_path):
        paths = ensure_knowledge_base(tmp_path)
        old = WikiPage(id="topic", title="Topic", type=PageType.CONCEPT,
                       workflow_state="verified", body="old")
        write_page(paths, old)
        old_path = page_path_for(paths, PageType.CONCEPT, "topic")
        invalid = {"id": "topic", "status": "candidate",
                   "knowledge_mode": "observed", "claim_ids": []}
        result = rebuild_wiki_view(paths, {}, [invalid], [], {}, 1)
        assert result.published is False
        assert read_page(old_path).body == "old"

    def test_wiki_projection_preserves_mode_and_evidence():
        observed = {"id": "observed-1", "title": "Observed",
                    "knowledge_mode": "observed"}
        evidence = {"document_id": "doc-1", "block_id": "block-1",
                    "evidence_id": "evidence-1"}
        view = WikiTemplateCompiler().compile(
            {}, [observed], [], {"observed-1": evidence}, 1, query_time=100
        )
        rendered = view.sections_content["knowledge_units"]
        assert "(observed)" in rendered
        assert "block-1" in rendered

- [ ] **Step 2: 运行 RED**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_wiki_rebuild_contract.py tests/test_kc/test_wiki_template_compiler.py tests/test_kc/test_candidate_adapter.py -q

预期：当前只有投影/模板骨架，没有完整的失败不覆盖和证据模式验收。

- [ ] **Step 3: 实现 staging-first 重建**

先编译全部页面到内存或 .index/staging/，统一运行 closure/integrity；全部通过后才调用既有 writer。失败时清理本次 staging，不删除或覆盖旧页面。禁止实现第二套写盘路径。

- [ ] **Step 4: 运行验证**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_kc/test_wiki_rebuild_contract.py tests/test_kc/test_wiki_template_compiler.py tests/test_kc/test_candidate_adapter.py tests/test_pipeline/test_ingest_generate_commit_split.py -q

预期：重建成功、重建失败保护、证据链和现有 ingest commit 语义全部通过。

- [ ] **Step 5: 提交**

    git add src/kc/views/wiki_template_compiler.py src/kc/adapters/wiki_projection.py src/knowledge/storage/wiki_adapter.py tests/test_kc/test_wiki_rebuild_contract.py tests/test_kc/test_wiki_template_compiler.py tests/test_kc/test_candidate_adapter.py
    git commit -m "feat(kc): make wiki projection rebuildable"

### Task 5: L3 运行观测、演化恢复和最终交付验收

**Files:**
- Modify: src/vector/pending.py（仅修复本任务发现的语义缺口）
- Modify: src/cli_ext/vector_cmd.py
- Modify: src/server/app.py
- Modify: scripts/kc_agent_eval.py
- Test: tests/test_vector/test_pending.py
- Test: tests/test_pipeline/test_ingest_vector_publication.py
- Test: tests/test_kc/test_incremental_drill.py
- Create: tests/test_kc/test_delivery_e2e.py

**Interfaces:**
- 保持 reconcile_pending() 现有字段，并只 additive 增加 intent、pending、recovered、failed、orphaned。
- CLI/server 只暴露现有 caller 可获得的计数；不引入新的后台 worker、队列语义或全局 waterline。
- E2E 覆盖一次导入、向量失败、重启 reconcile、源更新、证据缺失阻断、Wiki rebuild、重复运行和备份恢复。

- [ ] **Step 1: 写失败测试**

    def test_vector_failure_remains_pending_and_reconcile_is_idempotent(tmp_path):
        wiki_paths = ensure_knowledge_base(tmp_path)
        page = WikiPage(id="p1", title="P1", type=PageType.CONCEPT,
                        workflow_state="verified", body="body")
        write_page(wiki_paths, page)
        mark_intent(wiki_paths, [page])
        promote_intent(wiki_paths, ["p1"])
        failed = reconcile_pending(wiki_paths, lambda *_: False)
        recovered = reconcile_pending(wiki_paths, lambda *_: True)
        again = reconcile_pending(wiki_paths, lambda *_: True)
        assert failed["failed"] == 1
        assert recovered["ok"] == 1
        assert again["attempted"] == 0

- [ ] **Step 2: 运行 RED**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py tests/test_kc/test_delivery_e2e.py -q

预期：仅当发现现有实现与这些边界不一致时失败；若测试已通过，记录为已覆盖，不重复实现。

- [ ] **Step 3: 补齐最小观测和演化闭环**

1. 验证 intent/pending/reconcile 的状态计数和重复扫描；
2. 验证 ledger 写失败、Wiki commit 失败、promotion 失败、vector upsert 失败各自的可恢复状态；
3. CLI/server 仅接入这些 additive counters；
4. 若已有可用 provider，运行一次真实 runtime agent evaluation；否则记录 unavailable。两种情况都必须明确记录 provider、输入资产、结果和是否 dry-run，且 provider 不可用不阻塞本 MVP；
5. 不把失败的上游 provider、缺少 pyarrow/lancedb、嵌套 pytest hang 伪装成产品通过或产品失败。

- [ ] **Step 4: 运行分层验收**

    $env:PYTHONPATH='.'
    python -m pytest --import-mode=importlib tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py tests/test_kc -q
    python -m pytest --import-mode=importlib tests/test_wiki tests/test_pipeline tests/test_server tests/test_cli_ext -q
    python -m pytest --import-mode=importlib -q
    git diff --check

预期：KC/L3、L1/L2 相关套件和全套测试通过；无 diff whitespace 错误；环境问题单独记录，不扩大产品范围。

- [ ] **Step 5: 做最终边界审查并提交**

必须逐项证明：

- evidence 缺失不会发布；
- closure 缺少依赖不会默认通过；
- 时间未知、未来、已失效、非法区间均有明确结果；
- 未配置语义模型时，确定性 semantic support 只作为规则结果，不计入真实 LLM 质量指标；
- 向量失败只留下可重试 pending，不删除 Wiki；
- 预提交 intent 孤儿只删除 intent，不删除已提交页面；
- 重复 ingest/reconcile/rebuild/replay 不产生重复副作用；
- 旧 Wiki/frontmatter/旧 ledger 可读取；
- 未引入 claim truth、第二 writer、Book、插件平台或全局 waterline。

    git status --short
    git diff --stat HEAD~1
    git add src/vector/pending.py src/cli_ext/vector_cmd.py src/server/app.py scripts/kc_agent_eval.py tests/test_vector/test_pending.py tests/test_pipeline/test_ingest_vector_publication.py tests/test_kc/test_incremental_drill.py tests/test_kc/test_delivery_e2e.py
    git commit -m "test(kc): verify trustworthy mvp delivery boundaries"

## 验收标准

### 必须通过

- [ ] src/kc/integrity 不再含任何将缺失数据标为通过的假设路径。
- [ ] WikiPage 时间字段可 round-trip；DefaultFilter 对 [from, to)、unknown、scheduled、expired、invalid 区间有测试。
- [ ] RetrievalResult 可携带证据、来源、模式、上下文、时间和版本；缺失信息可观察。
- [ ] Core 编译结果通过现有 kernel/storage/version/event 路径持久化，并可重复回放。
- [ ] snapshot/restore 从真实存储读取；恢复后 identity 集合和事件 hash 一致。
- [ ] Wiki 重建采用 staging-first，失败不覆盖旧页面。
- [ ] L3 intent/pending/reconcile 所有失败边界和重复执行测试通过。
- [ ] MVP 评估资产的关键字段非空，agent mock 与 runtime 结果分离。
- [ ] KC focused、L1/L2 回归、全套 pytest 和 git diff --check 通过。

### 不作为阻塞项

- Book compiler 尚未实现。
- Plugin/Marketplace/远程 SDK 尚未实现。
- 未达到任意预设的 0.95/0.99/0.90 阈值；需先用真实数据建立 baseline。
- 未执行 20 次批处理。
- graphify 生成物或关系图本身不完整；它是导航辅助，不是产品验收依据。

## 风险和回滚

- 每个任务单独提交；任务失败时只回滚该任务 commit，不回滚用户已有工作区改动。
- Wiki 写入仍由现有 writer 负责；任何新重建入口在 writer 前失败都只清理 staging。
- 新增 frontmatter 字段使用默认值兼容旧页面；删除字段或迁移历史数据不在本计划内。
- vector ledger 使用现有兼容读取规则；新字段只 additive，恢复失败保留 pending。
- 真实 LLM/provider 不可用时使用 deterministic fixture 完成单元测试，并将 runtime evaluation 标为 unavailable，不修改生产语义。

## 两轮方案审查

### Round 1：全面漏洞审计

审查结论：无致命缺陷；以下重大隐患已在本文修正或转为明确 stop condition。

1. 把实现目录当需求：会触发大规模迁移和双模块并存。已改为复用现有 src/kc/src/knowledge。
2. closure 缺字段仍默认通过：会让未经验证对象发布。Task 1 要求缺失输入 fail-closed。
3. Wiki 没有时间字段但声称支持历史检索：会产生静默错误。Task 2 要求字段 round-trip 和半开区间测试。
4. backup 依赖调用者传入对象：调用链漏传时备份会虚假成功或直接失效。Task 3 要求从真实现有存储读取并保留兼容参数。
5. 为重建增加第二 writer：会造成 Wiki/index/log 不一致。Task 4 强制 staging-first 并复用唯一 writer。
6. mock agent 结果冒充真实质量：会让评估数字无意义。Task 0/5 分离 dry-run 和 runtime。
7. 评估集 evidence/top-k 为空：只验证 schema key 存在，不能验证产品质量。Task 0 加非空约束。
8. 新增任务触碰全局 waterline 或 queue：会扩大 L3 风险面。Global Constraints 明确禁止。
9. 重放、重建、reconcile 重复产生副作用：会污染页面、索引和事件。每个任务都要求幂等测试。
10. 旧数据不兼容：已有 Wiki/frontmatter/ledger 可能无法读取。所有新字段默认兼容，不做历史迁移。

复核：上述问题均已在 Global Constraints、任务接口或验收标准中有具体约束；未保留致命或重大未决项。

### Round 2：压力测试推演

| 场景 | 预期行为 | 加固位置 |
|---|---|---|
| ledger 写入失败 | 首个 Wiki 写入前终止，不产生半发布 | Task 5，保留 L3 pre-commit intent |
| Wiki 写入中途失败 | 不把页面标成已发布；现有 atomic/partial commit 语义保留 | Task 5 E2E |
| Wiki 成功、promotion 失败 | 页面存在且 intent 可被 reconcile 发现 | Task 5 |
| vector upsert 超时/抛错 | pending 保留，下一次重试；Wiki 不回滚 | Task 5 |
| intent 对应页面不存在 | 只清理 orphan intent，pending 页面记录不删除 | Task 5 |
| 旧页面没有时间字段 | 视为 unknown，不能假装 current；旧页面仍可读取 | Task 2 |
| valid_from > valid_to | 检索和发布均 fail-closed，给出 reason code | Task 2/1 |
| evidence 数据缺失 | closure 不得默认通过，并返回 missing evidence reason | Task 1 |
| Core 事件重复/乱序重放 | identity/version 不重复，无法应用的事件报告失败 | Task 3 |
| Wiki rebuild 中途崩溃 | staging 可丢弃，旧页面不被覆盖 | Task 4 |
| 测试依赖缺失或嵌套 pytest 挂起 | 分层运行并单独标注环境限制，不改生产逻辑 | Task 0/5 |

方案压力测试后仍保留的已知上限：单机 JSON/JSONL 存储不提供分布式事务；高并发、多租户、Book 多视图原子发布和全局版本水位需另立方案，不能在本 MVP 中偷渡。

### Round 3：可执行性复核和整改结果

本轮逐项对照当前代码的真实入口、参数和数据结构，完成以下整改：

1. evaluator 命令改为现有的 dataset 参数，不再使用不存在的 cases 参数。
2. gold case 改用现有 case_id 和 REQUIRED_FIELDS，不再虚构 id/source_path 契约。
3. agent 评估复用现有 evaluate_agent_task_dataset()，只增加 dry-run 标记，不新增平行 evaluator。
4. Wiki 时间逻辑明确区分旧 frontmatter 缺字段和显式 null，避免无迁移时全库页面退出默认检索。
5. 时间改动覆盖 WikiPage、KO/Wiki adapter 和唯一的 src/kc/compiler/temporal.py 推导入口。
6. Wiki rebuild 使用现有 WikiTemplateCompiler、WikiPageAdapter 和 page writer；未引入第二套 writer。
7. Core 事件增加稳定 idempotency_key，且 get_kernel() 按项目根目录隔离，避免跨项目污染。
8. 删除未纳入 MVP 的 semantic provider 接线；确定性规则结果不伪装成真实 LLM 质量。
9. 所有最终 git add 命令均列出具体文件，不会把工作区其他改动加入提交。

结论：Round 1 的 10 个风险已整改，Round 2 的 11 条压力路径均有任务或明确边界覆盖，Round 3 未发现致命缺陷或未定义的生产入口。方案达到进入编码阶段的可执行标准。

### 执行停止条件

出现以下任一情况时，停止当前任务并重新评审范围，不以临时兼容代码绕过：

- 需要新增第二个 Wiki/page writer、第二份 vector ledger 或全局 publication waterline；
- 无法区分旧页面缺失时间字段与显式 unknown，且会导致历史页面默认检索结果大面积变化；
- 事件无法获得稳定 idempotency_key，或 replay 只能返回部分状态；
- closure 仍必须把缺失 provenance/evidence/context/trust 当作通过才能保持旧测试；
- staging 失败会覆盖或删除已有有效 Wiki 页面；
- pytest 失败原因无法与已知环境限制区分，或需要改生产代码才能绕过测试 harness；
- provider、LanceDB、pyarrow 或网络不可用，但任务没有 deterministic fixture 兜底；
- 发现需要修改 workflow_state=verified、structurally_verified 或队列重试语义。

### Round 4：机械校验

- git diff --check：通过。
- 占位符扫描：未发现待办伪步骤、空泛实现描述或未定义的示例 fixture 名称。
- 现有入口校验：评估使用 --dataset，Wiki 使用现有 WikiTemplateCompiler.compile 和 page writer，向量使用现有 reconcile_pending。
- 暂存边界校验：计划中的 git add 均为具体文件列表；当前工作区只有本计划文档新增，未触碰源码和用户改动。
- 结果：文档可直接交给执行 agent，进入 Task 0 的 TDD RED 阶段。

## Spec 覆盖和有意缺口

| 原始计划能力 | 本方案处理 |
|---|---|
| A0 契约/评估 | Task 0，使用现有 docs/evaluation，不复制目录 |
| A1/A2 raw/canonical/evidence/extraction | 现有实现保留；Task 0/1/4 验证真实链路 |
| A3 identity/context/temporal | Task 1/2；只实现当前产品实际需要的最小字段和 reason codes |
| A4 Core/version/backup/replay | Task 3，复用现有 kernel/storage/version/event |
| A5 integrity/closure | Task 1，删除假设通过 |
| A6 retrieval | Task 2，补时间和结果契约 |
| A7 Wiki | Task 4，补重建安全性 |
| A8 Book | 明确移出 MVP |
| A9 incremental evolution | Task 5 的最小恢复/E2E；复杂长期演化另立计划 |
| 插件/市场/复杂编书 | 明确移出 MVP |

## 完成报告

- 最终 commit：待执行
- 测试：待执行
- 静态检查：待执行
- 评估资产：Task 0 完成后记录实际数量和非空校验结果
- 方案状态：planned
- 进度账本：所有任务提交后更新 .superpowers/sdd/progress.md
