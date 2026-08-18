# LLM 输出后确定性字段与链接归一化实施方案

> 目标项目：`knowledge/novel-wiki`
>
> 关联整改：`docs/superpowers/plans/2026-08-18-tag-normalization-remediation.md`
>
> 当前触发问题：batch 9 在 pre-commit Gate 被阻断，20 个源文件零写入。失败链接为：
>
> ```text
> 飞书云文档 -> [[入门教程角色篇完善小说的技法-e8ca1866]]
> 北京圣东方国信科技有限公司 -> [[入门教程角色篇完善小说的技法-e8ca1866]]
> ```
>
> 当前 raw 文件名为 `入门教程角色篇完善小说角色的技法.md`，说明 LLM 返回了标题漂移 + 旧 hash 的 source 链接。

## 1. 目标与非目标

> **编码门槛（最终复审整改）**：本方案当前仍未通过 plan-audit，禁止进入 Task 1 编码。必须先完成 Task 0，并通过两轮复审。

### 1.1 目标

1. LLM 只负责语义内容和候选引用，脚本最终决定稳定的页面元数据与引用标识。
2. 现有数据的兼容优先级固定为：同 canonical raw key 的已有 source 页 → 已登记且真实存在的 legacy alias → 新 canonical ID；不得因 hash 版本变化直接重复创建 source 页。
3. source ID/hash 规则采用带版本的 canonical key；旧 hash 只作为只读兼容候选，自动修复必须产生审计，不自动创建 alias。
2. 统一处理 body 中的 `[[wikilink]]` 与 `relations[].target`，避免两套解析逻辑继续漂移。
3. source page 的 `id`、`title`、`sources` 使用 raw 路径确定性生成。
4. 对现有页面和当前 batch 兼容，不通过放宽 Gate 来隐藏真实断链。
5. 对无法安全解析的目标保留 Gate 阻断，并输出可诊断的目标与候选映射。

### 1.2 非目标

- 不让脚本根据任意模糊相似度自动重连普通概念页面。
- 不把所有未知 wikilink 自动指向当前 source page。
- 不在本轮改变策略 1 标签政策：带标签页面仍自动补 `素材/ugc` + `可信度/ugc`。
- 不重写历史全库页面，除非明确运行迁移/cleanup 命令。
- 不修改 Gate 的严格阻断语义。

## 2. 字段责任边界

### 2.1 脚本最终接管

以下字段由 pipeline/writer 最终覆盖，LLM 返回值只作候选或直接忽略：

| 字段 | 确定性来源 |
|---|---|
| `id` | 现有 canonical ID；新 source 页由 `raw_path stem + path hash` 生成；新概念/实体页由规范化标题生成并去重 |
| `type` | Schema/页面路由/任务上下文；非法类型拒绝或回退到明确的基础类型 |
| `sources` | 当前 ingest 的规范化 raw 路径 |
| `created_at` / `updated_at` | writer 时间戳 |
| `grade` | pipeline 质量结果与 Gate 规则；不信任 LLM 自评 |
| `processing_depth` | 任务模式/页面类型；仅 operation 任务可进入 operation |
| `is_immutable` | 默认值或显式人工配置 |
| `heat` / `last_used_at` / `zombie_since` | 运行时状态，不接受 LLM 修改 |
| `custom_type` | 项目 Schema 路由结果 |

### 2.2 脚本归一化后接受

| 字段 | LLM 责任 | 脚本责任 |
|---|---|---|
| `title` | 提议语义标题 | Unicode/空白清洗、已有标题复用、冲突检测 |
| `tags` | 提议候选标签 | `normalize_tags()`、值域校验、mandatory 补齐、审计 |
| `category` / `taxonomy_sub` | 提议分类 | 对项目 taxonomy 校验；非法值清空或进入 Gate |
| `relations[].type` | 提议关系类型 | 只接受注册类型；未知类型拒绝/审计 |
| `relations[].weight` | 提议置信度 | 转数值并限制在 `[0, 1]`；缺失使用默认值 |
| `related_entities` | 提议关联实体 | 规范化、去重、目标解析与 gap/Gate 检查 |

### 2.3 LLM 继续负责

- `slots.*` 语义内容：摘要、要点、例子、背景、关系上下文。
- 概念/实体页的候选标题和候选目标。
- 标签的语义选择，但不能决定 namespace 合法性。
- 分类候选，但不能绕过项目 taxonomy。

## 3. 核心设计：统一 Target Resolver

> **最终复审门槛**：Task 0 必须先通过 reingest 删除恢复、项目级并发/fencing、Gate 副作用、TOCTOU 和多 source context 矩阵；否则不进入 Task 1。

新增公共模块（优先放在 `src/wiki/features/target_resolver.py`），并固定一次生成操作内的解析上下文：

```python
@dataclass(frozen=True)
class ResolutionContext:
    source_candidates: tuple[SourceRef, ...]
    existing_page_candidates: Mapping[str, tuple[PageRef, ...]]
    alias_snapshot: AliasSnapshot
    index_snapshot: IndexSnapshot
    project_root: Path
    resolver_version: str

resolve_wiki_target(
    raw_target: str,
    *,
    context: ResolutionContext,
) -> TargetResolution
```

`ResolutionContext` 在 `generate_ingest()` 计算 canonical raw path、source slug map、现有 index、SchemaRegistry 页面目录和 alias 快照后创建；同一次操作中 body wikilink、relation target、related_entities 都只使用这个 context，不在各 Generator 分支重新扫描磁盘或重新 slugify。

解析上下文必须由以下四条入口显式传递：

| 入口 | context 创建/传递位置 | body | relation |
|---|---|---|---|
| unified | `generate_ingest()` → `unified_generate()` | resolver | resolver |
| legacy/two-step | `generate_ingest()` → `generate()` | resolver | resolver |
| candidate | `generate_from_candidate()` | resolver | resolver |
| KnowledgeObject | `generate_from_knowledge_object()` | resolver | resolver |

四条入口不得保留独立的 inline source-link `difflib`/`_slugify` 修复。完成 Task 2 后，旧 inline 逻辑必须删除。

`TargetResolution` 至少包含：

```python
raw_target: str
canonical_target: str | None
kind: Literal["exact", "source", "alias", "title", "legacy_hash", "unresolved"]
confidence: Literal["high", "medium", "low"]
changed: bool
candidates: list[str]
warning: str | None
```

### 3.1 解析优先级

严格按以下顺序：

1. 去除 `[[...]]`、alias、fragment 后的精确 canonical ID。
2. 当前 batch 的 `source_slug_map` 精确匹配。
3. 已有 wiki index 的精确标题匹配。
4. `SlugAliasRegistry` 的已登记 alias，且 canonical 页面实际存在。
5. 确定的旧 hash alias：目标带 8 位十六进制后缀，去后缀后与当前唯一 raw stem 高度相似。
6. 其他情况返回 `unresolved`，不自动改写。

### 3.2 模糊匹配安全门

只允许用于 source link 的窄场景：

- 目标必须带 8 位 hash 后缀；
- 当前 source map 中必须只有一个候选；
- 标题相似度达到固定阈值；
- 候选必须来自当前 raw path，而不是任意 wiki 页面；
- 任何多候选、低相似度或普通概念链接都不得自动替换。

当前 batch 9 的错误目标应映射为：

```text
入门教程角色篇完善小说的技法-e8ca1866
→ 入门教程角色篇完善小说角色的技法-<当前 path hash>
```

## 4. 应用边界

### Task 0：关闭 Gate 前写盘与运行时提交边界（编码前置）

**原因**：现有 `generate_ingest()` 的 sanitizer reject 分支调用 `_write_rejected_source_page()`，会在 Gate 前写入 `wiki/`；这与本方案 §8 的 Gate 前零写入承诺冲突。当前 batch runner 还存在按 raw 提交、vector pending、batch state 和锁的恢复边界未证明问题。

**文件候选**：

- `src/pipeline/ingest.py`
- `src/orchestrator/batch_runner.py`
- `src/lib/atomic_ctx.py`
- `src/services/batch_state.py`
- `tests/test_pipeline/test_ingest_generate_commit_split.py`
- `tests/test_scripts/test_batch_executor.py`

**实施与验收**：

1. 将 sanitizer reject 改为只返回内存 `WikiPage`/诊断 metadata；任何 `wiki/`、index、log、gap、alias、vector pending 写入延迟到明确 commit 边界。
2. 增加 reject + Gate fail、reject + Gate pass、reject retry 测试；Gate fail 时除允许的 batch state 控制面字段外，生产数据 hash 必须不变。
3. 对 `AtomicContext` 做 fault injection：page 写入中断、index/log 写入中断、gap/vector pending 写入中断；明确实际语义是 item-atomic、partial_commit 或可恢复重放，不能笼统宣称事务回滚。
4. 固定 `partial_commit` 状态、已写文件清单、重试恢复判据；若无法证明 page/index/log 一致，Task 0 失败即阻塞后续 Task。
5. 明确 project ingest lock、operation owner token、batch state CAS/version 和旧 worker 停止点；同一 project 的 batch/curator/CLI 可写入口必须共享锁，无法共享时标记阻塞。
6. 增加页面 content hash（mtime 仅辅助）TOCTOU 测试；schema/purpose/taxonomy、alias、index、raw source、custom directory manifest 变化时返回 `STALE-CONTEXT`，不得继续提交。
7. **reingest 删除顺序必须单独验收**：pre-commit Gate 通过不等于旧数据可删除；`cascade_delete`/旧 vector 删除必须进入带 manifest 的单 raw commit。若删除后 page/index/log 新写入失败，必须进入 `partial_commit` 并有恢复路径；不能把旧页面已删除的状态标记为普通 `failed` 后直接重试。
8. **多 source context**：同一 batch 的每个 raw 生成操作冻结自己的 immutable `ResolutionContext`；同 stem、不同目录、同一页面多 source、重复 canonical key 都必须形成明确候选和 `ambiguous` blocker，禁止使用 dict 插入顺序覆盖。
9. **alias/title/字段冲突**：固定 `alias_cycle`、`alias_depth_exceeded`、`alias_invalid`、`canonical_missing`、`ambiguous` 状态；标题 key 使用 NFC、空白归一化和稳定排序；人工编辑后的 body/relations/title 与系统字段 ownership 必须有 content-hash 冲突策略。

Task 0 未通过前，不得实现 Target Resolver 或重跑 batch 9。

### Task 1：Target Resolver 与 contract tests

**文件候选**：

- `src/wiki/features/target_resolver.py` 或现有 slug/link feature 模块
- `tests/test_wiki/test_target_resolver.py`

**测试必须覆盖**：

1. canonical ID 原样保留。
2. `[[target|alias]]` 只改变目标解析，不丢 alias。
3. source map 精确替换。
4. 已有标题精确复用。
5. 已登记 alias 且页面存在时替换。
6. 旧 hash + 标题小漂移的唯一 source 候选可替换。
7. 多候选时返回 unresolved，不猜测。
8. 普通概念页面的相似标题不被 source 规则误改。
9. 未知目标保持 unresolved，Gate 可以阻断。
10. resolver 幂等。

### Task 2：四条 Generator 入口统一 body wikilink 与 relation target

**文件候选**：

- `src/pipeline/generator.py`
- `src/wiki/features/target_resolver.py`
- `src/wiki/features/relations.py`
- `src/wiki/features/wikilink.py`
- `src/pipeline/stages/generator.py`
- `tests/test_pipeline/test_generator.py`
- `tests/test_wiki/test_target_resolver.py`
- `tests/test_wiki/test_relations_sync.py`

**入口矩阵（必须逐项测试）**：

| 入口 | 具体函数 | 必测输出 |
|---|---|---|
| unified/legacy | `unified_generate()` / `generate()` | body + relations |
| candidate | `generate_from_candidate()` | body + relations |
| KnowledgeObject | `generate_from_knowledge_object()` | body + relations |
| pipeline stage adapter | `src/pipeline/stages/generator.py` writer seam | finalized WikiPage |

**实施**：

- 从 Generator 两条页面构造路径抽出重复的 source wikilink 替换逻辑。
- body 中所有 wikilink 使用同一 resolver。
- `relations[].target` 在 `parse_relations_from_response()` 或其上游统一解析。
- relation target 与 body wikilink 使用同一个 canonical 结果。
- unresolved 目标保留原始值并附审计 warning，不静默删除语义关系。

### Task 3：脚本接管 WikiPage 系统字段

**文件候选**：

- `src/pipeline/ingest.py`
- `src/pipeline/generator.py`
- `src/wiki/storage/page_writer.py`
- `tests/test_pipeline/test_ingest_generate_commit_split.py`
- `tests/test_wiki/test_page_writer.py`

**实施**：

- source 页统一由 `generate_ingest()` 构造，不采用 LLM 的 source `id/title/sources`。
- downstream 页的 `sources` 统一绑定当前 raw path。
- `created_at/updated_at`、运行时字段由 writer/pipeline 覆盖。
- `type/custom_type` 通过 Schema 路由确定。
- `grade/processing_depth` 由 pipeline 质量与任务模式覆盖。
- 保留现有 `write_page()` 的结构校验，不让 writer 静默修复任意手工页面。

### Task 4：taxonomy、relation 元数据与页面目录归一化

**页面目录闭环（Task 4 必须完成）**：

- 新增/复用 `SchemaRegistry.iter_page_dirs(paths)`（确切命名以现有 registry API 为准），统一返回内置目录、custom type 目录和 `_stubs` 策略。
- `src/pipeline/reconcile.py`、`src/wiki/features/wikilink.py`、`src/wiki/features/batch_gate.py`、index reader 和 Target Resolver 全部改用该目录枚举；不允许继续硬编码四个固定目录。
- 为 custom type 页面增加 exact ID、title resolution、body wikilink、relation target、Gate/reconcile contract tests。

**文件候选**：

- `src/wiki/features/relations.py`
- `src/wiki/features/wikilink.py`
- `src/pipeline/reconcile.py`
- `src/wiki/features/batch_gate.py`
- `src/wiki/schema_registry.py` 或现有 taxonomy registry
- `src/pipeline/ingest.py`
- 对应测试文件

**实施**：

- 新增/复用 SchemaRegistry 的统一页面目录枚举函数，返回内置目录、custom type 目录和明确的 `_stubs` 策略。
- `existing_wiki_index`、Target Resolver、`reconcile`、wikilink existence check、Gate 均复用该枚举结果；禁止各模块继续硬编码四个目录。
- 定义 `PageRef(id, title, type, custom_type, path)`；标题索引为 `title -> list[PageRef]`，多候选必须 unresolved。
- 增加 custom type 页面 exact ID、标题、多候选、relation、body wikilink 和 Gate contract tests。

- relation type 只接受 built-in 或已注册 `x-*` 类型。
- weight 统一为有限 `[0,1]` 浮点数。
- target 通过 Task 2 resolver。
- `category/taxonomy_sub` 通过项目 registry 验证。
- 非法值产生审计日志；阻断规则由现有 Gate 决定。

### Task 5：生成后最终校验报告与 blocker 生命周期

**文件候选**：

- `src/wiki/features/batch_gate.py`
- `src/pipeline/ingest.py`
- `src/wiki/features/target_resolver.py`
- `tests/test_scripts/test_batch_executor.py`

**实施**：

- 定义 `TargetResolution.kind` 状态集合：`exact/source/alias/title/legacy_hash/alias_missing/alias_invalid/canonical_missing/ambiguous/unresolved`；alias 最大解析深度和环检测行为固定在 contract。
- Resolver failure 生成独立内存 blocker（例如 `TARGET-UNRESOLVED` / `TARGET-AMBIGUOUS`），不得转换成 `KnowledgeGapStore` 的业务缺口；`pending_gap_slugs` 只豁免真实业务缺口。
- Gate 失败只返回内存 report/临时诊断，不写 wiki、index、log、gap、alias 或 vector pending；增加 side-effect sentinel 测试。
- commit 中断的真实语义先通过 fault injection 验证；本方案只承诺 Gate 前零写入，commit 阶段若已有部分写入则必须证明幂等恢复，否则 Task 6 标记阻塞，不宣称事务回滚。
- 旧 source ID 兼容优先级固定为：已有 canonical raw key 页面 → 已登记且存在的旧 slug alias → 新 canonical slug；不得直接新建重复 source 页。

- 不放宽 Gate。
- 在 Gate 前输出确定性修复审计：`field/page/raw/candidate/canonical/action`。
- unresolved 目标输出候选列表，便于判断是 LLM 漂移、缺页还是 manifest 问题。
- Gate 的 `BROKEN-LINK` 保持阻断。

### Task 6：batch 9 回归与后续批次

1. 先完成 Task 1–5 测试。
2. 重新运行 batch 9；上次 pre-commit 失败是零写入，可安全重试。
3. Gate PASS 后检查 `batch_build_state.json`：20 个 raw 应为 done，状态为 committed。
4. 若仍失败，只处理实际 Gate issue，不重复无关 LLM 运行。
5. 通过后再继续 batch 10。

## 5. 当前已存在的临时变更

当前工作区已经有一处未验证的窄范围补丁：`src/pipeline/generator.py` 对带 8 位 hash 的 source wikilink 做相似度替换，并新增 `difflib` 导入。

编码前必须先决定：

- 将其收敛为 Task 1/2 的公共 resolver 实现；或
- 删除临时逻辑，避免 Generator 保留第二套解析规则。

禁止在公共 resolver 完成后继续保留重复的 inline 替换逻辑。

## 6. 验收标准

### 自动化

- 标签相关定向测试全绿：现有 116 项基线不回归。
- 新增 resolver/relations/body wikilink 回归测试全绿。
- `tests/test_scripts/test_batch_executor.py` 的 Gate 与 commit 测试全绿。

### 数据与批处理

- batch 9 pre-commit 不再因当前两个错误 source link 阻断。
- batch 9 生成的 source 页 ID 等于脚本 canonical mapping。
- `飞书云文档` 与 `北京圣东方国信科技有限公司` 的链接指向 canonical source ID。
- 无新增 `BROKEN-LINK`、非法 relation type、非法 taxonomy 或 legacy tag。
- batch 9 失败时仍保持零写入和可重试。

### 非功能

- resolver 对同一输入幂等。
- 不通过模糊匹配改写普通概念链接。
- 审计日志不包含 API key、请求头或其他凭据。
- 不改变现有策略 1 标签语义和 Gate 严格阻断行为。

## 7. 编码前置约束（审查整改）

以下约束在 Task 1 开始前必须固化为 contract tests；未满足时不得进入编码：

1. **canonical raw path**：新增/复用单一函数，先以项目 root 解析为相对路径；拒绝或显式标记 root 外路径；统一 `/`、Unicode NFC、`.`/`..`、Windows casefold 策略和 symlink 策略。source hash、`WikiPage.sources`、`source_slug_map` key 必须全部来自同一 canonical key。路径 hash 算法与版本写入 contract，不能在不同入口直接对原始 `str(Path)` 求 hash。补齐 Windows/POSIX、NFC/NFD、大小写、绝对/相对、越界路径 golden-vector tests。
2. **source map 契约**：`source_slug_map` 必须以 canonical raw key 查找；Analyzer/Candidate/KnowledgeObject 的 source path 进入 Generator 前先 canonicalize。重复 key 或多 source 候选返回 `ambiguous`，禁止按插入顺序选择。
3. **多路径覆盖**：resolver 接入 legacy `generate()`、candidate `generate_from_candidate()`、KnowledgeObject `generate_from_knowledge_object()` 及 unified path；body wikilink 与 relation target 必须使用同一个 `ResolutionContext`/解析结果。
4. **页面身份消歧**：source 页可按 canonical raw key 确定性复用；普通 concept/entity 标题只建立 `title -> list[PageRef]` 候选，单候选才可复用，多候选返回 unresolved，不按目录遍历顺序合并。
5. **alias 安全**：alias 解析必须检查 canonical 页面真实存在、支持有限多级链并检测环；alias 缺失、损坏、canonical 缺失、多候选分别返回可诊断状态，不自动创建 alias。
6. **custom type 覆盖**：Resolver、existing index、reconcile、Gate 必须复用 SchemaRegistry 的全部页面目录，不能只扫描四个固定目录。
7. **字段 owner**：生成管线使用显式 `finalize_generated_page()` 接管系统字段；通用 `write_page()` 继续负责结构校验、不可变保护和序列化，不隐式改写人工页面。首次创建与 reingest 的 `created_at` 保留规则必须测试。
8. **失败边界**：Resolver unresolved 不等同于业务 KnowledgeGap。确定性解析失败使用独立 blocker/审计状态，不得仅通过 pending gap 豁免 Gate。Gate 失败时只保留内存/临时审计，不污染 wiki、index、log、gap、alias 或 vector pending。
9. **提交边界**：复用现有 `AtomicContext`、batch state 锁和 commit 顺序，不新增事务框架；Task 6 前必须验证 pre-commit 失败零写入、commit 中断可重试、已有页重写可恢复。若发现现有 item-atomic 语义不足，先记录阻塞，不静默扩大范围。

## 8. 运行时语义与压力测试整改

### 8.1 提交原子性边界

本轮**不新增跨文件 WAL/事务框架**，也不宣称 batch 级回滚。明确采用现有实现可验证的分层语义：

- **Gate 前**：`wiki/`、`wiki/index.md`、`wiki/log.md`、gap、alias、vector pending 均不得因本批页面产生写入；允许更新 `batch_build_state.json` 的 `gate_failed`、fail streak 和诊断字段。
- **单 raw commit**：复用 `AtomicContext`，目标是 page 文件、index、log 在一次 raw commit 中保持 item-atomic；通过 fault injection 验证。若当前 `safe_write` 不能保证，必须把状态标为 `partial_commit` 并停止后续 raw，不得伪称回滚成功。
- **batch commit**：现有按 raw 提交的 item-atomic 语义保留；中断后依据 batch state + 磁盘事实跳过已完成 raw，重试未完成 raw。不得把“可重试”写成“全批回滚”。
- **vector**：向量 pending 是可重建派生状态；page commit 成功后登记 pending，向量失败不回滚 wiki，但必须可重试并可诊断。

### 8.2 并发与旧 worker

- 同一 project 的 batch ingest 在 generate→Gate→commit 生命周期内持有现有项目级 ingest 锁；batch state 文件锁不足以保护 wiki/index/vector。
- 已运行 worker 必须通过 `operation_id`/batch state fencing 检查；发现新 owner 或状态版本变化时，旧 worker 停止 commit。
- 不同 project 可以并行；同一 project 的 curator/CLI 写操作若无法共享同一锁，Task 3 必须先增加冲突测试并将风险标为 blocker。

### 8.3 人工编辑 TOCTOU

- 对即将 overwrite 的页面记录 preflight content hash/mtime；commit 前再次检查。
- hash/mtime 变化时默认拒绝覆盖并输出 `WRITE-CONFLICT`，不以 `allow_overwrite` 静默覆盖人工修改。
- immutable 页面仍然优先拒绝；首次创建不需要旧 hash。

### 8.4 Gate 与副作用验收

增加 sentinel 测试，验证 Gate 失败后以下对象不发生本批新增或修改：

```text
wiki/**/*.md（除允许的 batch_build_state）
wiki/index.md
wiki/log.md
.index/knowledge_gaps.json
.llm-wiki/slug_aliases.json
.index/vector pending / lancedb
.index/staging / quarantine（除明确诊断文件）
```

batch state 的 `gate_failed`、失败计数和最多 50 条诊断 issue 属于允许的控制面写入，不属于 wiki 数据写入。

### 8.5 custom type 全链路矩阵

custom type 页面必须覆盖以下组件；任何一个仍硬编码固定目录都不能宣称完成：

```text
SchemaRegistry 目录枚举
→ page_path_for / read_page
→ index reader
→ Target Resolver
→ body wikilink existence
→ relations/reconcile
→ batch Gate
→ cascade/immutable probe/lint
```

测试至少包含：custom page exact ID、唯一标题、多候选标题、body link、relation target、reingest、cascade、immutable 和 Gate。

### 8.6 source/alias 快照与消歧

- 一次 generate 操作冻结 `ResolutionContext`：canonical raw path、source candidates、existing index、SchemaRegistry 目录、alias snapshot、resolver version。
- alias 解析最大深度固定为 8；检测环、损坏 JSON、canonical 缺失、多候选时 fail-closed，状态分别为 `alias_invalid`、`canonical_missing`、`ambiguous` 等，不自动创建 alias。
- source 解析优先 canonical raw key；普通标题仅在唯一候选时复用；多 source、重复标题、同 canonical key 冲突均返回 ambiguous。
- body 与 relation 必须消费同一批不可变 `TargetResolution`；一侧 unresolved 时页面不能通过 Gate。

## 9. 执行顺序与提交边界

1. 方案审查（本文件）→ 两轮审查；压力测试必须覆盖 §8 的 item-atomic、锁、TOCTOU、Gate 副作用和 custom type 全链路。
2. Task 0：关闭 Gate 前写盘、定义 partial_commit/恢复、项目锁/fencing、TOCTOU 快照 + 单独提交；未通过则停止。
3. Task 1：canonical path + Target Resolver contract/实现 + 单独提交。
4. Task 2：四条 Generator 入口与统一 `ResolutionContext`、body wikilink、relation target 接入；删除旧 inline resolver + 测试 + 单独提交。
5. Task 3：系统字段接管 + `finalize_generated_page()` 时序、custom type 全链路目录枚举、首次创建/reingest/TOCTOU 测试 + 单独提交。
6. Task 4：taxonomy/relation 元数据归一化 + alias/source 消歧 + 测试 + 单独提交。
7. Task 5：Gate 审计输出、unresolved blocker、零写入、kill/retry、并发锁测试 + 单独提交。
7. Task 6：batch 9 实际运行与 Gate 验收；不与代码提交混在一起。验收只承诺 Gate 前零写入、单 raw item-atomic/可重试，不承诺全批事务回滚。
8. 最后执行全局 diff/review，再询问是否 push。

每个 Task 必须先有失败测试，再实现、验证、更新 `.superpowers/sdd/progress.md`。不在审查通过前进入编码阶段。
