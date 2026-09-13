# Wiki-to-Book V4.1 — 写作百科全书增强实施计划（安全整改版）

> 状态：V4-Core 实施完成；验收证据见 [`docs/reports/2026-09-05-book-wiki-v4-acceptance.md`](../../reports/2026-09-05-book-wiki-v4-acceptance.md)。V4-Encyclopedic 保留为显式可选分支，当前无 provider 时按 exit 6 fail-closed。
> 前置：V3.2 计划 [`docs/superpowers/plans/2026-09-05-wiki-to-book-v3.md`](2026-09-05-wiki-to-book-v3.md)（安全结构化编译器）。
> 用户决策（2026-09-05）：V4 = V3.2 + V4 一体化；quality gate = 规则硬限必修，LLM 软评分可选增强。

**Goal：** 把 wiki 编译从"可审计的 Wiki 拼装器"提升为可验证的写作知识产品——保留 V3.2 全部安全底线，新增阅读体验、读者任务验收和受证据约束的跨页面索引。V4 不把 LLM 推断自动写入正文，也不把有限 fixture 的通过率宣称为百科全书质量。

**Architecture（与 V3.2 一致 + V4 增量）：**

- 安全底线沿用 V3.2（preflight / 快照 / 守恒 / 原子发布 / 锁双条件 / reader 契约）；
- 阅读体验层（V4 新增）：`reading_experience_mode`（`rule_only` → `llm_enhanced` → `encyclopedic`）；
- 知识融合层（V4 新增）：跨页面的"议题"与"共识/分歧"索引（仅在 `encyclopedic` 模式下激活，结果只进入独立索引和 manifest）；
- 质量门（V4 新增）：规则硬限（block-ID 多重集、unresolved 比例、未匹配 heading、术语表覆盖）必修；LLM 软评分（4 维）仅在显式启用时运行；
- 读者任务验收（V4 新增）：至少 5 个、最多 10 个固定场景 + 验收样本 + 自动化 rubric 评分；实际数量必须在 manifest 声明。

**Tech Stack：** Python 3.11+、现有 `WikiPage`、现有 `LLMProvider.complete`、标准库、pytest。T17 若继续使用 YAML，必须同步声明 `pyyaml` 运行依赖并提供离线安装方案；否则改用现有标准库可解析的 JSON。

---

## 与 V3.2 的边界

| 能力 | V3.2 | V4 |
|---|---|---|
| 安全底线（preflight / 快照 / 守恒 / 发布 / 锁） | ✅ 必修 | ✅ 沿用 |
| 阅读体验三件套（过渡 / 术语 / 章节内排序） | ⚠ 占位 + 基础 | ✅ 完整增强 |
| 跨页面知识融合 | ❌ | ✅ 议题/共识/分歧（encyclopedic 模式） |
| 读者任务验收 | ❌ | ✅ 至少 5 个、最多 10 个场景 + 样本 |
| 质量门 | ⚠ unresolved 比例硬限 | ✅ 规则硬限；LLM 软评分可选 |
| 跨页面 wikilink 推荐 | ❌ | ✅ 候选生成（LLM 启用时） |

> V4 **不**承诺：自动生成新事实（不替代作者）、商业成功指标、读者主观偏好学习。这些属于 V5+。

---

## 任务优先级三级排序

> 三级原则：P0 是 V3.2 安全基线（不可裁剪）；P1 是 V4 阅读体验；P2 是规则质量门与读者验收，encyclopedic 融合为显式可选模式。每级内部按依赖顺序串行；同级可并行但受资源上限约束。

### P0 — V3.2 安全基线（前置依赖，必须先完成）

> 来源：V3.2 Tasks 0–8。V4 计划按"前置 + 增量"模式整合；P0 完成前不得进入 P1。

P0 复用 V3.2 已实现的安全基线；V3.2 中标为可选的 LLM 润色、缓存和用量统计不因列入 P0 表格而变成强制前置。这里只验证其接口兼容性。

| 任务 | V3.2 任务号 | V4 增量 | 输出 |
|---|---|---|---|
| T0 Fail-closed preflight + 锁 | V3.2 Task 0 | 仅增加 `mode`/授权参数透传，不重写既有锁协议 | `preflight.py` |
| T1 严格扫描 + 快照 | V3.2 Task 1 | 无增量 | `scanner.py` |
| T2 Outline schema + 覆盖校验 | V3.2 Task 2 | 仅扩展可选字段并保持向后兼容 | `outline_validate.py` |
| T3 确定性分区 + LLM 大纲 | V3.2 Task 3 | 仅为 encyclopedic 索引提供固定 page/block 引用，不改变分区归属 | `partition.py` / `outline_llm.py` |
| T4 规则聚合 + 阅读辅助 | V3.2 Task 4 | 复用既有 glossary/index/order 实现，不重复建模块 | `aggregator.py` |
| T5 LLM 润色 + 过渡 | V3.2 Task 5 | 复用正文守恒校验；过渡仍是可选 LLM 层 | `polish_llm.py` |
| T6 编译 + 发布 | V3.2 Task 6 | + `glossary.md` / `index.md` / `reading_experience_mode` 入 manifest | `compiler.py` |
| T7 CLI 注册 | V3.2 Task 7 | + `--encyclopedic` / `--quality-gate` / `--rubric` flags + exit codes 9/10 | `cli_ext/book_cmd.py` |
| T8 E2E + 故障注入 | V3.2 Task 8 | + 规则质量门故障注入（unresolved 超阈值） | `test_book_wiki_e2e.py` |

**P0 验收门槛：** V3.2 Acceptance Gates 全部通过 + 未传 `--use-llm` 的纯规则路径 E2E 通过；不得假设 V3.2 存在 `--no-llm` 参数。

### P1 — 阅读体验完整化（V4 增量第一阶段）

> 目标：把 V3.2 占位变成"读者能读的章节"，不依赖知识融合。
> 依赖前提：P0 全部完成（含 T6 compiler 发布可工作），否则 P1 任务无可用的 manifest/artifact。

| 任务 | 内容 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|
| **T9 ChapterSort 语义启发式** | 在 V3.2 既有规则排序上增加可验证的 tie-break 规则；不得另建第二套排序器 | snapshot + outline | `ChapterDraft.intra_chapter_order` | T0–T4 |
| **T10 GlossaryBuilder 全量提取** | 在 V3.2 glossary 上增加术语规范化/别名索引；先定义术语 ID 集合再计算覆盖率 | snapshot | `glossary.md` + `glossary_index.json` | T1 |
| **T11 IndexBuilder 章节映射** | 扩展 V3.2 index 的 grade 字段并保持 `page_id` 全量映射，不重复实现 reader | snapshot + outline | `index.md` | T2 |
| **T12 TransitionWriter（LLM 路径）** | 在 token 预算内生成 `transition_in/out` 与 `overview`；强制 cite block_id；超预算回退规则版 | draft + provider | `PolishedChapter.transition_in/out` | T5 |
| **T13 ReadingExperience Manifest** | `reading_experience_mode` (`rule_only` / `llm_enhanced` / `encyclopedic`) 与 glossary/index hash 入 manifest | 全部上游 + glossary.md + index.md | manifest.json 增量字段 | T6 + T10 + T11 |
| **T14 阅读体验验收** | fixture 三件套 (重复标题 / 多种 page_type / 含 wikilink) + 纯规则 E2E；配置了 provider 时再验收 LLM 路径 | fixture | 定向测试 + `--json` 输出样例 | T9–T13 |

> **并行约束**：T9 / T10 / T11 互不依赖，**可以并行**；但 T13 必须等待 T6 + T10 + T11 全部完成；T14 必须在 T13 之后串行收口。

**P1 验收门槛：**
- 纯规则路径：`glossary.md` / `index.md` 全量生成；`intra_chapter_order` 跨运行稳定；
- LLM 路径：`transition_in/out` 全部 cite 合法 block_id；`reading_experience_mode=llm_enhanced` 在 manifest 标注；
- `--encyclopedic` 路径失败时直接返回 exit 6 并保留旧 release；不得自动切换到其它 mode。需要低级模式时必须由操作者显式重新运行。

### P2 — 读者任务验收 + 规则质量门（V4 增量第二阶段）

> 目标：让"读者读完能否写出 X"成为机器可测的验收项；规则硬限必修，LLM 软评分只作为可选诊断。

| 任务 | 内容 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|
| **T15 QualityGate 规则硬限** | 4 条硬阈值：block-ID 多重集 / unresolved 比例 / 未匹配 heading 比例 / glossary 覆盖率；任一超阈值阻断发布（exit 9） | artifact + manifest | `QualityGateReport.rule_blockers` | T6 |
| **T16 QualityGate LLM 软评分（可选）** | 4 维 LLM 评分（覆盖性 / 可读性 / 准确性 / 连贯性），每维 0–1；不阻断但入 manifest；阈值固定在受控配置中 | draft 的安全摘要 + provider | `QualityGateReport.llm_scores` | T5 + LLM provider |
| **T17 RubricSpec YAML schema** | 读者任务验收 schema：`task_id` / `scenario` / `expected_evidence` / `rubric_dimensions`；versioned；locator 必须可执行 | 输入 YAML | `RubricSpec` 校验器 | T15 |
| **T18 ReaderTaskRunner 自动化** | 在 fixture 上运行 RubricSpec：对每条规则从产物中找证据（wikilink/heading/quote）；产出 `ReaderTaskReport` | artifact + RubricSpec | `ReaderTaskReport` JSON | T17 |
| **T19 EncyclopedicOutline（显式可选模式）** | 跨页面议题索引：Issue / Consensus / Disagreement 必须绑定 block-level evidence；仅在 `--encyclopedic` 模式生成，不写入正文 | snapshot + 安全摘要 + provider | `encyclopedic_outline.json` | T3 + T5 + LLM provider |
| **T20 CrossLinkSuggester（可选，manifest-only）** | 生成候选 wikilink，必须指向已存在 page_id；只写 manifest，不修改正文，不参与 V4 必修验收 | encyclopedic_outline | manifest.cross_link_candidates | T19 |
| **T21 验收 fixture + E2E** | 5 条 RubricSpec 样例；自动化通过率按任务级公式计算，≥ 80% 才算读者验收通过 | fixture + RubricSpec | `test_reader_tasks_e2e.py` | T18 |
| **T22 V4 全量验收 + 双向回归** | V3.2 → V4 升级后：(a) P0 全部测试通过；(b) P1 阅读体验 fixture 通过；(c) P2 规则质量门与读者任务通过；(d) 未传 `--use-llm` 与显式 `--use-llm` 双路径回归；encyclopedic 另行验收 | 全部上游 | 全量测试报告 + 风险清单 | T21 |

**P2 验收门槛：**
- 规则质量门 4 项硬阈值全部通过，否则阻断（exit 9）；
- 启用 LLM 软评分时才写入 4 维分数；provider 失败写入明确的 `unavailable` 状态，不得伪造分数；
- 5 条 RubricSpec 自动化任务级通过率 ≥ 80%；不达标项入挂账清单，**不**允许 V4 完成宣称"读者任务验收 100%"。

---

## 实施顺序与并行策略

```
P0: T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8   (V3.2 串行, 每 task 由独立 subagent 执行 + per-task review)
                ↓
P1: T9/T10/T11 → T12 → T13 → T14                 (V4 阅读体验, 先并行再汇合)
                ↓
P2: T15 → T17 → T18 → T21 → T22                 (必修验收主链)
    T16（可选诊断）并行于 T15；T19 → T20（可选 encyclopedic 分支）不阻塞主链
```

**并行机会（subagent-driven-development 视角）：**
- T9 / T10 / T11 在 P1 阶段可并行（都依赖 T0–T4，但彼此无依赖）；
- T15 / T16 在 P2 阶段可并行（规则硬限与可选 LLM 软评分互不依赖）；
- T20 必须等待 T19；两者均为显式 encyclopedic 可选链路，不阻塞规则质量门或读者任务验收。

**串行依赖（不可并行）：**
- T3 → T5 → T12（仅 LLM 增强路径需要；纯规则路径跳过）；
- T6 → T13 → T14（manifest → 模式标注 → E2E）；
- T17 → T18 → T21（rubric schema → runner → fixture）；
- T19 → T20（融合数据 → 推荐链接）。

---

## 新增 Exit Codes（V4 增量）

> V3.2 的 exit 7 保留为 unresolved-relation-over-threshold；V4 新增 exit 9 仅表示其它规则质量门阻断，不修改既有退出码。

| Code | 含义 | 来源 |
|---|---|---|
| 0 | 成功 | V3.2 沿用 |
| 1 | build/publish 失败 | V3.2 |
| 2 | project unresolved | V3.2 |
| 3 | no eligible pages | V3.2 |
| 4 | snapshot/fingerprint mismatch | V3.2 |
| 5 | lock busy | V3.2 |
| 6 | budget exhausted / LLM provider unavailable | V3.2（含 V4 扩展） |
| 7 | unresolved-relation-over-threshold | V3.2 沿用 |
| 8 | disk-pressure | V3.2 |
| **9** | **quality-gate rule blocker（V4 新增，不含 exit 7）** | T15 |
| **10** | **reader-task-rubric < 80% pass（V4 新增；非阻断，仅警告）** | T18 |

> V4 完成不要求 reader task 100% 通过；80% 阈值是机器可测的"工程阈值"，不是"百科全书质量阈值"。

### CLI 与模式契约

- `python -m src.cli book build-from-wiki --project <id> [--use-llm] [--encyclopedic] [--quality-gate {rule,both,off}] [--rubric <path>] [--apply]`。
- 默认 `--use-llm` 关闭，`--quality-gate rule`；`both` 才启用 LLM 软评分，`off` 仅允许 dry-run，不得用于 `--apply`。
- `--encyclopedic` 必须同时出现 `--use-llm`，且失败只返回 exit 6，不自动切换模式。
- `--rubric` 的内容 hash、质量阈值配置 hash 和 `mode` 必须进入 BuildFingerprint；阈值只能来自受控配置，不能由产物 manifest 自行降低。

---

## 全局约束（V4 增量）

### 数据契约新增

```python
@dataclass(frozen=True)
class LLMResponse:
    """Provider adapter contract used by T12/T16/T19."""
    text: str
    truncated: bool
    content_length: int
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None

@dataclass(frozen=True)
class ReadingExperienceMode:
    """Three-level reading experience quality indicator."""
    mode: Literal["rule_only", "llm_enhanced", "encyclopedic"]
    rationale: str          # 何时/为何切换；纯规则永远 rule_only
    glossary_hash: str
    index_hash: str

@dataclass(frozen=True)
class QualityGateReport:
    """Dual-mode quality gate output (V4)."""
    rule_blockers: tuple[str, ...]            # 4 维硬阈值
    llm_scores: dict[str, float] | None       # 4 维软评分；不可用或未启用时为 None
    llm_status: Literal["disabled", "available", "unavailable"]
    rule_thresholds: dict[str, float]         # 实际生效阈值
    overall: Literal["pass", "fail"]          # 由 rule_blockers 决定

@dataclass(frozen=True)
class EncyclopedicOutline:
    """Evidence-bound cross-page index; never a body rewrite."""
    chapter_id: str
    issues: tuple[str, ...]                   # 议题
    consensus: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]   # (claim, (page_id, block_id)[])
    disagreement: tuple[tuple[str, tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]], ...]
    evidence_page_ids: tuple[str, ...]
    cross_link_candidates: tuple[tuple[str, str, str], ...]  # (from_page, to_page, reason)

@dataclass(frozen=True)
class RubricSpec:
    """Reader task acceptance rubric."""
    task_id: str
    scenario: str
    expected_evidence: tuple["EvidenceLocator", ...]   # 见 EvidenceLocator 类型
    rubric_dimensions: tuple[str, ...]       # 可量化维度 (e.g. "提及钩子类型数", "cite 数")
    threshold: float                         # task locator 通过率阈值 (0–1)

@dataclass(frozen=True)
class EvidenceLocator:
    """机器可验证的证据定位器；不使用 grep 模糊匹配。

    source 类型决定 EvidenceLocator 在 ReaderTaskRunner 中如何查找证据。
    """
    locator_type: Literal["wikilink", "heading", "quote", "page_id"]
    pattern: str                               # wikilink/heading/quote 为规范化精确匹配；page_id 必须是完整稳定 ID，不支持隐式通配
    min_count: int = 1                         # 至少匹配次数

@dataclass(frozen=True)
class ReaderTaskReport:
    """Automated rubric outcome.

    pass_rate 分母 = "声明的全部 EvidenceLocator 数"；跳过或执行失败计为失败。
    """
    spec: RubricSpec
    pass_rate: float                           # passed_locators / expected_locators
    evaluated_count: int                       # 实际评估的 EvidenceLocator 数，必须等于 expected_count
    expected_count: int
    skipped_count: int                         # 跳过即失败，不从分母剔除
    evidence_found: tuple[str, ...]
    evidence_missing: tuple[str, ...]
    failures: tuple[str, ...]
```

### LLM 边界（V4 加严）

- **必须**强制执行"LLM 原始响应**不**保存"（V3.2 沿用）；
- **必须**强制执行"正文不可改写"（V3.2 沿用）；`EncyclopedicOutline.cross_link_candidates` 只写入独立索引和 manifest，V4 不提供正文应用开关；
- **必须**新增"encyclopedic 模式外发审计"：每个 claim/cross_link_candidate 入 manifest 时记录 from/to、reason、page_id hash 和 block-level evidence hash；
- **必须**为 T12/T16/T19 固定外发字段白名单（page_id、标题、taxonomy、经脱敏的摘要和 block 引用）；正文、原始 source、凭据和未授权 PII 不得发送。页面内容按不可信数据处理，不能改变系统提示或工具权限。
- **必须**显式判别 LLM 不可用三态：`LLMResponse.truncated=True` / `content_length=0` / `finish_reason=length`，任一态触发按"LLM 不可用"处理；
- **必须**新增 "LLM 不可用 + encyclopedic 模式" → exit 6（**不**回退到 `llm_enhanced`，避免静默降级）；
- **必须**新增 token-bounded encyclopedic fusion：按 `context_window - output_reserve` 切块，单页超限时生成规则索引并标记未融合；每块独立生成带 block 引用的 consensus，合并规则必须定义 claim 规范化和重叠阈值，禁止按固定页数切块。

### 质量门硬阈值（默认值来自受控配置，不可由 manifest 自行调整）

| 维度 | 默认阈值 | 覆盖率分母定义 |
|---|---|---|
| block-ID 多重集相等 | 100%（阻断级） | `|draft.block_ids|` |
| unresolved-relation 比例 | ≤ 5%（阻断级） | `|unresolved| / |total_relations|`；总关系数为 0 时定义为 0 |
| 未匹配 heading 比例 | ≤ 10%（阻断级） | `|unmatched_headings| / |total_headings|`；无 heading 时定义为 0 |
| glossary 覆盖率 | ≥ 95%（阻断级，V4 新增） | 分母 = 规范化后的 `term_id` 集合；分子 = 已生成且可解析的 `term_id` 数量；page_id 不与术语条目混用 |
| LLM 软评分（4 维平均） | ≥ 0.6（软阈值，不阻断） | 4 维：覆盖性/可读性/准确性/连贯性 |

规则阈值来自版本化配置文件并纳入 fingerprint；配置必须声明 schema、来源、最小允许值和生效时间。构建产物不得修改阈值后重新计算自身通过状态。

### 读者任务验收硬阈值

- RubricSpec 通过率 ≥ 80%（工程阈值，非百科全书质量阈值）；
- 单条 RubricSpec 阈值可在 fixture YAML 中声明；
- 5 条样例 RubricSpec 必须覆盖：(1) 钩子写法多样性；(2) 大纲三段结构；(3) 冲突应对策略；(4) 平台规则引用；(5) 案例素材可追溯；
- 每个 locator 必须有 pass/fail 结果；`pass_rate = passed_locators / expected_locators`，跳过或执行错误计为失败。每个 task 的分数为其 locator 通过率；总体通过率为 5 个 task 分数的等权平均，且 `evaluated_count == expected_count`。

---

## Acceptance Gates（V4 完整版）

### P0 门槛（V3.2 沿用）

- 所有 V3.2 Acceptance Gates 通过；
- 未传 `--use-llm` 的纯规则路径 E2E 完整通过。

### P1 门槛（V4 阅读体验）

- 纯规则路径：`glossary.md` / `index.md` 全量生成（glossary 覆盖率 ≥ 95%）；`intra_chapter_order` 跨运行稳定；
- LLM 路径：`transition_in/out` 全部 cite 合法 block_id；`reading_experience_mode=llm_enhanced` 入 manifest；
- `--encyclopedic` 失败返回 exit 6 并保留旧 release；不得自动降级，低级模式必须显式重新运行；
- **P1 完成后必须重跑 V3.2 全部测试**（P1 增量改动可能破 V3.2 接口契约）；任何 V3.2 测试失败必须挂账，禁止静默跳过。

### P2 门槛（V4 验收 + 融合）

- QualityGate 4 维规则硬限全部通过，否则 exit 9；
- 启用 LLM 软评分时，4 维分数或 `unavailable` 状态入 manifest；
- 5 条 RubricSpec 自动化任务级通过率 ≥ 80%；不达标项入挂账清单；
- EncyclopedicOutline 仅在显式 `--encyclopedic` 模式下生成；cross_link_candidates 只进 manifest，不修改正文。

### 全局门槛

- `--encyclopedic` 模式需 `--use-llm`；不满足时拒绝而非静默降级；
- 所有 V3.2 退出码 + exit 9 (rule blocker) + exit 10 (rubric warn) 全部覆盖 CLI 测试；
- LLM provider 不可用时 exit 6（沿用 V3.2 预算耗尽语义，需扩展为"provider 不可用"也走 exit 6 并在 stderr 标注原因）；
- V3.2 安全、发布、锁、守恒和回滚测试必须 100% 通过；其它非安全体验测试可按 95% 作为阶段性指标，但失败项必须逐项挂账。

---

## 风险与挂账

> V4 残余风险（工程上需记录；未能通过规则或人工门禁的项不得被包装成已解决）：

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 软评分 provider 不稳定 | 诊断分数缺失 | LLM 评分失败 → 仅规则硬限生效，`llm_status=unavailable`；不影响 rubric 计算，也不伪造分数 |
| EncyclopedicOutline 跨页面 fusion 超 token | 章节级融合需多页输入 | 按 provider context window 切块；单页超限只生成未融合索引并明确挂账，禁止固定页数假设 |
| 5 条 RubricSpec 不足以代表读者任务 | 验收通过率不能反映真实质量 | 显式声明 RubricSpec 是"工程阈值"；读者主观验收需人工放行（V4 仍保留人工 review 环节） |
| 跨页面 wikilink 候选质量参差 | 推荐错链影响信任 | 仅在 encyclopedic 模式启用；只入 manifest，不进入正文；正文应用另立安全变更与人工审核 |
| 阅读体验三件套在不同 page_type 下差异大 | 同一 fixture 不一定覆盖所有 case | fixture 必须包含 3 类 page_type（concept/entity/synthesis） |

---

## 与现有 KC book 的边界（V4 沿用 V3.2 + 增量）

- **不**覆盖：KC `book/manifest.json` 的发布协议；KC `book/` 目录的内容；
- **不**修改：现有 `src/kc/views/book/rebuild.py` 的 release 模式；
- **不**接触：`knowledge/novel-wiki/`（受保护 staging）；
- **新增**：encyclopedic 模式仅在 `--encyclopedic` 显式启用时激活；未传 `--use-llm` 时纯规则路径仍可达；
- **新增**：V4 完成后产出 `docs/reports/2026-09-05-book-wiki-v4-acceptance.md`。

---

## Rollback（V4 增量）

V4 在 V3.2 基础上增加两类回滚：

1. **模式失败处理**：encyclopedic 失败不自动降级；旧 release 保持可读，操作者可显式重新运行 `llm_enhanced` 或纯规则模式；`mode_history` 只记录实际运行，不记录未执行的降级。
2. **质量门回滚**：质量门阻断（exit 9）时旧 release 仍可读；reader task 未达阈值属于验收失败，不得发布为“V4 完成”，但不修改已激活 release。

---

## Open Preconditions（V4 增量）

V4 启动前（与 V3.2 共用 + 增量）：

- V3.2 全部 Acceptance Gates 通过；
- 只有启用 T12、T16 或 T19 时才要求对应 LLM provider 已配置并测试可达；纯规则路径不得被该前置条件阻断；
- RubricSpec YAML 必须在进入 P2/T17 前完成用户与域专家联合评审；P0/P1 规则路径不应被尚未定义的 rubric 阻断；
- encyclopedic 模式仅在显式传入 `--encyclopedic` 时启用；它必须依赖 `--use-llm`，不能与 LLM 开关形成两套独立降级逻辑；**CLI 默认值单一来源**：`src/cli_ext/book_cmd.py` parser，其他位置只引用不重复声明；
- 人工 review 放行门禁（V4 仍保留）：encyclopedic 模式下必须有"写作熟练读者"签名放行（与 V3.2 pilot 放行门禁一致）。

### RubricSpec YAML 草案（5 条样例；进入 P2/T17 前完成）

以下 page_id 是 fixture 内固定的测试 ID，不代表生产库 ID；fixture 必须同时提供这些页面和对应 heading/quote。生产验收不得把示例 ID 当作通用规则。

```yaml
# docs/fixtures/rubric/writing_handbook_v4.yaml
schema_version: rubric-spec-v1
tasks:
  - task_id: hook-writing-variety
    scenario: "新手读完应该能找到至少 3 类钩子写法"
    expected_evidence:
      - locator_type: heading
        pattern: "## 钩子"
        min_count: 1
      - locator_type: wikilink
        pattern: "[[钩子-悬念]]"
        min_count: 1
      - locator_type: quote
        pattern: "开篇抛出悬念"
        min_count: 1
    rubric_dimensions: ["hook_type_count", "cite_count"]
    threshold: 0.8

  - task_id: outline-three-act
    scenario: "章节大纲应呈现开端-发展-高潮三段结构"
    expected_evidence:
      - locator_type: heading
        pattern: "## 开端"
        min_count: 1
      - locator_type: heading
        pattern: "## 发展"
        min_count: 1
      - locator_type: heading
        pattern: "## 高潮"
        min_count: 1
    rubric_dimensions: ["three_act_complete"]
    threshold: 0.8

  - task_id: conflict-resolution
    scenario: "冲突应对章节至少展示 3 种策略"
    expected_evidence:
      - locator_type: heading
        pattern: "## 冲突策略"
        min_count: 1
      - locator_type: wikilink
        pattern: "[[冲突-升级]]"
        min_count: 1
      - locator_type: wikilink
        pattern: "[[冲突-缓和]]"
        min_count: 1
      - locator_type: wikilink
        pattern: "[[冲突-反转]]"
        min_count: 1
    rubric_dimensions: ["strategy_count"]
    threshold: 0.8

  - task_id: platform-rules
    scenario: "平台规则章节至少引用 2 个平台的签约条款"
    expected_evidence:
      - locator_type: page_id
        pattern: "fixture-platform-start"
        min_count: 1
      - locator_type: page_id
        pattern: "fixture-platform-tomato"
        min_count: 1
    rubric_dimensions: ["platform_count"]
    threshold: 0.8

  - task_id: case-traceability
    scenario: "案例素材必须可追溯到至少 3 个 source page"
    expected_evidence:
      - locator_type: page_id
        pattern: "fixture-case-01"
        min_count: 1
      - locator_type: page_id
        pattern: "fixture-case-02"
        min_count: 1
      - locator_type: page_id
        pattern: "fixture-case-03"
        min_count: 1
    rubric_dimensions: ["traceable_case_count"]
    threshold: 0.8
```

---

## Subagent 编排建议（按 P0/P1/P2 分级）

| 阶段 | subagent 数量 | 关键约定 |
|---|---|---|
| P0 | 每个 Task 1 个 implementer + 1 个 reviewer（共 18 个 subagent 任务） | per-task review + Critical/Important 必须修复 |
| P1 | 6 个 implementer（T9–T14）+ 1 个全段 reviewer | T9/T10/T11 可并行；T14 必须串行收口 |
| P2 | 主链 T15/T17/T18/T21/T22 + 可选 T16/T19/T20 | 可选分支不阻塞主链；T22 为 final whole-branch review |

---

## V4 完成判定（不是完成 = 不是百科全书）

> V4 完成 ≠ 写作百科全书目标已达成。V4 是百科全书的**工程基础**：
>
V4 有两个可审计交付档位：

- **V4-Core（必修）**：P0 安全基线 + P1 阅读体验 + P2 规则质量门与 Rubric 主链；不要求 provider，也不运行 encyclopedic 分支。
- **V4-Encyclopedic（可选）**：在 V4-Core 已通过后，显式启用 `--use-llm --encyclopedic`，额外验收 T19/T20、外发审计和人工签名；失败不影响 V4-Core，也不得伪称已完成融合。

> - ✅ V3.2 安全底线已建立；
> - ✅ 阅读体验三件套落地（机械可达）；
> - ✅ 至少 5 条、最多 10 条读者任务可机器验证；
> - ⚠️ 真正"读者读完能写出 X"仍需人工放行；
> - ⚠️ 跨页面语义融合的深度仍受 LLM 能力天花板限制。

V4 完成后应明确：
- 哪些"读者任务"被自动化覆盖；
- 哪些"读者任务"仍需人工验证（挂账清单）；
- 哪些"百科全书能力"被推迟到 V5+（如：商业成功指标、读者偏好学习、跨语言版本）。

---

## 与 AGENTS.md / CLAUDE.md 工作流对齐

- **plan-audit 两轮审查**：本草案完成后需执行 Round 1（全面漏洞审计）+ Round 2（压力测试推演）；两次审查通过 + 人工复核后才进入编码；
- **dev-relay 阶段路由**：需求澄清/架构设计阶段用 mattpocock 系 → 编码用 ponytail → 评审切回 mattpocock；
- **TDD per task**：每个 Task 先 RED 后 GREEN，单一 commit；
- **commit 格式**：`type(scope): 中文描述`，每任务一个 commit。

---

## 起草记录

- v0.1（2026-09-05）：基于 V3.2 草案 + 用户决策（一体化范围、双模式质量门）起草；待 plan-audit Round 1/2 审查；
- v0.2（2026-09-05）：Round 1 审查 + Round 2 压力测试整改完成（见下"Round 1/2 审查整改记录"）；
- v0.3（待）：人工复核 + 用户决策（V4 进入编码 / 推迟 / 拆分）后定稿；
- v1.0（待）：进入编码阶段的正式版本。

## Round 1/2 审查整改记录（v0.3）

### Round 1 致命缺陷（3 项已整改）

| ID | 整改位置 |
|---|---|
| B1 P1 依赖图模糊 | T9/T10/T11 并行约束段 + T13 依赖 T6+T10+T11 |
| B2 exit code 冲突 | 保留 V3.2 exit 7；V4 exit 9 仅表示其它规则质量门阻断 |
| B3 LLM 静默失败 | 数据契约新增 `LLMResponse.truncated/content_length/finish_reason` 三态判别 |

### Round 1 重大隐患（6 项已整改）

| ID | 整改位置 |
|---|---|
| I1 CLI 默认值单一来源 | Open Preconditions 段明示 src/cli_ext/book_cmd.py parser 为唯一来源 |
| I2 RubricSpec 前置 | Open Preconditions 段改为 P2/T17 前完成，不阻塞 P0/P1 |
| I3 glossary 覆盖率分母 | 质量门硬阈值表明示分母定义 |
| I4 encyclopedic 失败语义 | 失败只返回 exit 6 并保留旧 release，不自动降级 |
| I5 cross-link 守恒边界 | 候选只进入 manifest；融合结论绑定 block-level evidence |
| I6 EvidenceLocator | 数据契约新增 `EvidenceLocator` 类型，禁止 grep 模糊匹配 |

### Round 1 优化疏漏（3 项）

| ID | 状态 |
|---|---|
| S1 P1 后 V3.2 回归 | ✅ 已整改：P1 门槛增加"重跑 V3.2 全部测试" |
| S2 RubricSpec YAML 草案 | ✅ 已整改：5 条样例 YAML 已附 |
| S3 文档结构 | ✅ 不拆分（单一草案合理） |

### Round 2 压力测试（5 路径）

| 失败路径 | 加固方案 |
|---|---|
| Provider 突然下线（encyclopedic 跑到一半超时） | LLM 三态判别 + chunked fusion 部分结果保存 + exit 6 |
| 融合超 token | 按 provider context window 切块；定义 claim 规范化与重叠阈值后合并 |
| RubricSpec 单条评估失败 | pass_rate 分母固定为全部 locator，跳过/错误计为失败 |
| Glossary 同词多义冲突 | disambiguation 子条规则 |
| 磁盘满在写 encyclopedic_outline.json 时 | 沿用 V3.2 原子指针；写入失败阻止 pointer 切换 |
