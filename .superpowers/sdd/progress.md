# progress — novel-wiki v3 写作知识库方案（执行账本）

> 方案：`docs/superpowers/specs/2026-08-15-novel-wiki-writing-template-design.md`
> 计划：`docs/superpowers/plans/2026-08-15-novel-wiki-writing-template.md`
> 续接：`.memory/handoff-novel-wiki-phase1-2026-08-15.md`（Phase 0-2）、`.memory/handoff-novel-wiki-phase3-2026-08-16.md`（Phase 3 续接）
>
> **新计划（2026-08-26）：** 模块规范性与统一化改造 — `docs/superpowers/plans/2026-08-26-module-standardization-unification.md`
>
> **P0-A 注册 ruflo CLI → ✅ `be5417ec`**
> **P0-B 中央配置模块 → ✅ `bca225a6`**
> **P1-A BatchRunner 收编脚本 → ✅ 4 子任务（`c4d50dee` 3a 门禁真源 / `68029bcf` 3b 拆引擎 / `2237df22` 3c BatchRunner ABC / `2ac5ef60` 3d ruflo batch CLI）**
> **P1-B 根目录清理 → ✅ `d64a17bd`**
> **P2-A 文档双文件同步 → ✅ `96a9466d`**（正文同步 4 处差异 + pre-commit 钩子校验）
> **P2-B superpowers 归档 → ✅ `409b0dc2`**（73→9 文档，64 归档）
> **P3 公共层边界 → ✅ `257d7777`**（src/shared → tests/support）

## 状态总览

| Phase | 状态 | 说明 |
|---|---|---|
| Phase 0 基线+盲区+index | ✅ | 见 handoff（0.1/0.2/0.3） |
| Phase 1 平台改造 | ✅ 10/10 | 见 handoff（1.1–1.9） |
| **Phase 2 场景模板落地** | ✅ 2/2 | schema/purpose/taxonomy/taxonomy_tags 落盘 + 模板确认 |
| **Phase 3 实测首轮** | ✅ **达标** | 首批 batch_001 全指标过（2026-08-16，含 10 个修复 commit） |
| **Phase 4 全量分批重摄入** | 🔄 进行中 | **batch 0-1 全量 40/40 完成**（7 缺陷修复，0.021 USD）；batch 2-68 待跑 |
| Phase 4.5 synthesis 聚合 | ✅ 完成 | **11 页分歧汇聚页全部生成+质量门过**（写作技法/技巧/题材体系/读者与市场/创作原则/平台规则/叙事技巧/心态与职业/案例与素材/小说创作/小说结构） |
| Phase 5 终验 | ✅ 完成 | **M1-M12 指标表 + 缺口分析 + 挂账清单**；4 项未达标需全量摄入后自动达标，挂账记录于 `.index/batch_reports/phase5_report.md` |

## Phase 3 实测首轮记录（2026-08-16）✅ 达标

**执行**：
- `scripts/plan_gap_first_batch.py`：B12 缺口优先清单（20 个 ≤8000 字符 .md）
- `scripts/phase3_accept.py`：批内验收（精确 page_ids + v3.0.0 过滤 + M1 未登记口径）
- 最终批次：18 raw → 95 页 commit，`gate PASS`、`POSTCHECK 过`；gap 账本 32 条

**验收结果（batch_001）**：门禁 PASS；M1 未登记断链 0；M4 missing_sections=0 + placeholders=0；M6 synthesis=2；M7 全文污染=0。

**Phase 3 实测发现并修复的 10 个缺陷（均有测试）**：
| # | commit | 缺陷 |
|---|---|---|
| 1 | fe2e484b | `commit_ingest` 无 `event` 参数 → extras 反向关系页提交必失败 |
| 2 | e601cc30 | lint MISSING-SECTION 版本门：v3.0.0 模板下 2.0.0 页被误要求 v3.0.0 槽 |
| 3 | 9c45665c | phase4_batch 丢弃 `missing_slugs` → gap 账本在 batch 路径从未写入 |
| 4 | 99480152 | M1 断链判定未归一 slug（`--` 双横线假断链） |
| 5 | 5fa387d9 | generator prompt 教 LLM 填「来源未提供具体例子」与 lint ERROR 冲突 |
| 6 | 78aae1b7 | missing_slugs 采集在 reverse 之前 → extras 反向断链不入 gap |
| 7 | 8f691ff7 | batch_gate_v3 gap 剔除未归一化匹配 |
| 8 | cd35bf13 | relations[].type JSON schema 无 17 型 enum 约束 → LLM 非法 relation |
| 9 | c193407b | 渲染后清洗 LLM 惯性占位符 + 必填槽缺失不再填系统占位 |
| 10 | de93c9f7 + 85e9f7ac | 非法 relation 过滤覆盖 extras 存量页 + extras 占位符清洗 + batch 记录 page_ids |

**关键运行事实（Phase 3 追加）**：
- LLM provider：`sfkey-glm`（glm-5.2 @ api.sfkey.cn），注册于 `%LOCALAPPDATA%\ruflo-kb\ruflo-kb\llm-providers.json`（非 `~/.config/ruflo-kb`！）
- 真实摄入：`PYTHONPATH=. python scripts/phase4_batch.py --manifest knowledge/novel-wiki/.index/reingest_backlog.json --batch 0 --project 0ff37d87-de3d-4a99-82bb-6cf288c65410 --allow-overwrite --concurrency 3 [--skip-files ...]`
- 每批 ~25 分钟（20 文件），LLM 调用 ~27 次/批
- 2 个问题文件需 --skip-files：`借鉴素材套路.md`（跨类型 slug 冲突）、`借鉴素材20个签约条件新人必看.md`（LLM 截断，其 source 缺口已入 gap）
- 验收：`PYTHONPATH=. python scripts/phase3_accept.py`
- 真实解释器：`C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe`（WindowsApps 别名是空 stub）

## Phase 4 全量分批重摄入执行记录（2026-08-16，进行中）

**已完成任务（每任务 TDD + commit + reviewer）**：
| # | commit | 任务 |
|---|---|---|
| 4.1 | 18b650a9 + 1fec69a7 | `scripts/plan_reingest_batches.py` 全量分批清单（缺口优先→主题目录，每批≤20 .md，扩展名白名单 + 排除 download_progress；review 整改：gap hint 契约白名单/黑名单/越界防护 + wrong-shape 降级 + batch_no 1-based + theme mixed）——1361 raw → 69 批，gap_priority=3 |
| 4.2 | e752a5e0 | `src/utils/idempotency.py` generate_task_hash 重建轮次维度（round_key=reingest:{batch}:{raw}，轮次间可重投，缺省向后兼容） |
| 4.3 | 238ea381 | `src/vector/store.py` 维度校验（init_vector_store_for_paths(expected_dim)，禁静默 drop；rebuild_vector_schema 显式迁移决策） |
| 4.4 | 1358f3e6 + 59b85691 | `src/services/ingest.py` reingest 直跑分支（probe→cascade+删向量→重建，不经队列；pending_deletion 补偿禁裸窗口）+ `src/services/batch_state.py` 统一 schema/文件锁（三写者 H①）；review 整改：folder 写者迁统一 schema(C1) + 续跑清残留向量(I1) + 重建失败契约(I2) |
| 4.5 | ff969919 + 1534d906 | `scripts/batch_executor.py` 直跑批执行器（每 raw 状态机 + kill-9 各阶段注入测试 + 崩溃续跑 + pre-commit 门禁 NDG/fields/tags/lint/对账 失败零写入 + 预算自动暂停 + is_immutable 跳过 + 3-strike blocklist + git 快照）；review 整改：provider 解析(C1) + WikiPage relations 对账(C2) + 门禁 lint 版本门/阈值/深度对齐(C3) + 复核失败独立 exit3 提示回滚(I1) + 真实费用估算(I2) + 每批向量 upsert 与删向量补偿(I3) + --resume 语义/锁纪律(M1/M3) + 真实路径 gate 测试(I5) |
| 4.6 | f67cec27 | `scripts/rollback_batch.py`（git checkout+clean wiki + 显式向量重建双动作）+ `.gitignore` 门禁文件白名单例外（batch_build_state/knowledge_gaps/reingest_plan/batch_reports，lancedb 不入 git） |
| 4.7 | 最新 | stub 清理：`cleanup_stub_pages.py --apply` 删除 165 个 stub 页（重指 24 引用 / 移除 26 引用），wiki 从 509 页降至 344 页 |

**待完成**：首批全量试跑（验收：kill-9 续跑正确、首摄不炸、无裸窗口、门禁零写入、M2≥80%、M8/M9=0、M11 批均净增≤5）→ progress 账本回填。

**试跑进展（2026-08-16 晚）**：
- 单文件真实路径冒烟测试 ✅：`batch_executor --root knowledge/novel-wiki --batch 0`（1 raw）→ RC=0，provider(RetryLLMProvider/glm-5.2) 正常调用、pre-commit 门禁 PASS（6 页）、reingest cascade 删除旧产出 7 页 + 更新 1 页、commit 成功；向量 upsert 因 CLI 无 embedding provider 降级（WARN，search degrade，预期行为）
- **batch 0 全量 20/20 ✅** + **batch 1 全量 20/20 ✅**（2026-08-17，累计 0.021 USD，完整金句率~95%）
  - 三轮试跑暴露 6 个缺陷（A-F，均修复 + 测试），第四轮全面通过
  - 产出的 5605 行新增 + 2998 行删除（cascade 重建 29 旧页 → 74 新页 + 存量更新）
  - 门禁 PASS（pre-commit 零问题 + 整批复核 PASS）
  - page_ids 持久化（14 页），gap 账本自动更新，budget 0.011 USD

**Phase 4 试跑实测发现并修复的 6 个缺陷（均有测试）**：
| # | commit | 缺陷 |
|---|---|---|
| A | `bd3d4133` | `_commit_raw` 丢弃 `meta["missing_slugs"]` → gap 账本在 batch 路径从未写入（同 Phase 3 修复 #3，batch_executor 新代码重犯） |
| B | `bd3d4133` | `run_precommit_gate` 对 extras（存量 reverse-touch 旧英文 tag 页）检查新 tag/lint 标准 → 整批被拦（修复：extras 不参与批内判定） |
| C | `b3318261` | batch_executor 缺 `_auto_tag_ugc` 步骤（phase4_batch 有）→ UGC carrier 派生页缺 素材/ugc + 可信度/ugc tag → P4b blocker |
| D | `b3318261` | P7（extra-pages 覆盖保护）对占位符清洗后的 extras body 误判 destructive overwrite（修复：P7 放行"仅占位符清洗"差异，与写入路径同语义） |
| E | `58598a1b` | `_rerun_gate_batch` 按 source 关联全扫磁盘页 → 存量 extras（东方玄幻 历史非法 relation contrasts）被误拦（修复：page_ids 过滤只查本批新页） |
| F | `64dfef31` | glm-5.2（reasoning 模型）thinking 占满 max_tokens=8192 预算 → content 空 + finish_reason=length → 被误判为 0-char 空截断不升级 → 3 次全失败（修复：provider 检测 reasoning_content 并上报 content_length>0，解锁升级路径） |
| G | `0608e5a9` | batch 1 清洗兜底缺「待补充」「见下游概念页」→ 扩句法/切割法/曲折法 3 页被 LINT-PLACEHOLDER 拦（修复：补清洗映射，渲染后自动替换） |
| H | `1dd40053` | **根治缺陷 F**：provider 层升级 max_tokens 只是兜底，正确解法是 API 请求传 `reasoning=false` 从源头禁 thinking。ProviderConfig 新增 `extra_body` 字段，sfkey-glm 配置 `{"reasoning": false}` → 实测 reasoning_tokens 从 200 降到 59，无截断 |

**关键运行事实（补充）**：
- glm-5.2 是 reasoning 模型；对 6400+ chars 的源文件，thinking 独占总预算导致 0-char 空截断是特点，非 bug，修复后正确升级 max_tokens 自动解决
- 2 个文件（借鉴素材小说主题分类的内容详细.md / 借鉴素材书籍如何商业化_8111d1.md）从 blocklist 中解封后第四轮成功生成
- 累计消耗 0.011 USD（远低于 0.2 上限）
- **根治方案（H）**：llm-providers.json `sfkey-glm` 加 `extra_body: {"reasoning": false}`，实测 API 认可该参数、thinking 显著减少（reasoning_tokens 200→59），后续批次不再依赖 max_tokens 升级兜底

## Phase 4.5 多源 synthesis 聚合（2026-08-17）✅

- **新增** `scripts/aggregate_synthesis.py`：按 taxonomy category 聚合多源 concept 页 → `provider.complete()` 直接调用 LLM（JSON 模式 `{"synthesis": {...}}`）→ 空 slots 质量门 → 写盘 + index + relations
- **候选**：48 个 category 中 11 个多源候选（写作技法 70 页/26 源、题材体系 17 页/7 源、平台规则 15 页/3 源等）
- **产物**：11 页全部生成，LINT-SYNTHESIS-GATE（各方观点 ≥2 wikilink）全过——v3.0.0 synthesis 模板 5 槽（议题与分歧点/各方观点/共识/证据对比/待定与结论）
- **测试**：`tests/test_scripts/test_aggregate_synthesis.py` 4 测试（分组/生成/空候选/空 slots 质量门）
- **修复**：ProviderConfig.extra_body + openai_provider 合并（根治 thinking 截断）

## Phase 5 终验（2026-08-17）✅ 完成

**报告**：`knowledge/novel-wiki/.index/batch_reports/phase5_report.md`

**指标摘要**：
| 指标 | 当前值 | 目标 | 状态 |
|---|---|---|---|
| M1 断链率 | 9.9% (249/2525) | gap-exempt 未登记 | ⚠ 部分（45 条 open gap 已登记） |
| M2 深引用率 | 4.2% (57/1361) | ≥80%（覆盖范围内） | ❌ 需全量摄入 |
| M4 placeholder | 0 | 0 | ✅ |
| M6 synthesis 页 | 11 | ≥68（1364 raw 换算） | ⚠ 部分（候选全过，全量后更多） |
| M7 全文污染 | 6 | 0 | ❌ 需全量摄入 |
| M8 旧英文 tag | 142 | 0（覆盖范围内） | ❌ 需全量摄入 |
| M9 非法 relation | 19 | 0（覆盖范围内） | ❌ 需全量摄入 |
| M10a raw 文件数 | 1361 | 1361 | ✅ |
| M11 gap 净增 | 45/45 open | ≤5/批 | ⚠ 部分（batch 0-1 合规） |
| M12 向量检索 | 25KB 空库 | 可用 | 🔲 挂账（CLI 无 embedding provider） |

**挂账**：4 项未达标 + M12 向量检索需全量摄入完成后重新验证。

**回归状态**：test_scripts 59+ 绿（4.1-4.6 全量）；test_services 绿；全树 3-5 个既存收集 ERROR + test_pipeline 4 个既存失败（均为兄弟 conftest 级联，基线一致，与 Phase 4 改动无关）。

## git 纪律

`git add <specific files>`；工作区他人改动勿碰：`discovery.py`/`start.bat`/`web/*`/`docs/evaluations/`/`knowledge/_batch*/`。`.memory/` 与 `.index/` gitignore（Phase 4 P1 例外：门禁文件白名单）。

## P1-A BatchRunner 收编记录（2026-08-18）✅ 完成

**目标：** `scripts/` 38 个脚本 → `BatchRunner` 框架收编。按计划 4 子任务分步执行，每步独立 commit。

| 子任务 | Commit | 说明 |
|---|---|---|
| 3a 门禁真源 | `c4d50dee` | 提取 `_gate_fields`/`_gate_tags`/`_gate_lint`/`_gate_reconcile`/`run_precommit_gate` → `src/wiki/features/batch_gate.py`（签名不变）；更新 4 个调用方 import |
| 3b 拆引擎 | `68029bcf` | 引擎逻辑（状态机/三阶段原子流程/崩溃续跑/预算/门禁编排/测试钩子）→ `src/orchestrator/batch_runner.py`（718 行）；CLI 壳留 `scripts/batch_executor.py`（~75 行 re-export） |
| 3c BatchRunner ABC | `2237df22` | `Batch`/`GateReport`/`BatchResult` dataclass + `BatchRunner(ABC)`（load_batch/run_one 抽象 + gate/execute/commit/rollback/emit_metrics 框架方法）+ `_on_phase_start/_on_phase_end` 生命周期钩子（崩溃注入在框架级生效）+ `DefaultBatchRunner` 具体实现 |
| 3d 收编 CLI | `2ac5ef60` | `src/cli_ext/batch_cmd.py` 注册 `ruflo batch {run,plan}`；`src/cli.py` 挂载；脚本与 CLI 双入口兼容 |

**关键决策：**
- **门禁真源** `src/wiki/features/batch_gate.py` 现被 5 个调用者引用（batch_executor/batch_commit/accept_batch/diagnose_batch_gate/tests），消除单点复制（验收 #4 ✓）。
- **`sys.path.insert(0, ...)` 移除**：引擎迁入 `src/` 后不再需要（handoff 记录点）。
- **生命周期钩子**：`run_batch` 在 generate/gate/commit/recheck 四阶段调用 `args._batch_runner._on_phase_start/_on_phase_end`，`_crash_at` 在钩子内触发——`os._exit(137)` kill-9 模拟在框架级生效。
- **测试红线**：`test_batch_executor.py` 的崩溃注入测试全套保留（`os._exit(137)` generate/gate/cascade/commit 四阶段），改 import 指向引擎。

**验证：**
- `tests/test_scripts/test_batch_executor.py` 18 tests passed（含崩溃注入全套）
- `tests/test_scripts/test_batch_generate_commit.py` 7 tests passed
- `ruflo batch run --help` / `ruflo batch --help` 正常
- 端到端冒烟（fake mode）：`ruflo batch run` → exit 0, 2 files done, gate PASS

**遗留（后续 P 处理）：**
- ~~`batch_ingest`/`phase4_batch`/`phase5_accept`/`pilot_ingest` 等遗留脚本未逐一改成继承 `BatchRunner` 子类~~ → ✅ **已收编**（见下文「遗留脚本全量收编」）
- `batch_gate_check`/`batch_gate_v3`/`diagnose_batch_gate` 的 `ruflo batch gate` 子命令未建 → ✅ **已收编**（`ruflo batch gate-check/gate-v3/diagnose-gate`）

## P2-A 文档双文件同步（2026-08-18）✅ `96a9466d`

**目标：** `AGENTS.md` / `CLAUDE.md` 双文件正文逐字节一致 + pre-commit 钩子强制。

**同步的 4 处差异：**
| # | 差异 | 方向 |
|---|---|---|
| 1 | `custom_type` 行（自定义类型字段） | CLAUDE 有 → AGENTS 补上 |
| 2 | schema.md/purpose.md 注入段落 | CLAUDE 有 → AGENTS 补上 |
| 3 | dev-relay 路径统一为 `.agents/skills/` | 两文件同步（原 `.Codex`/`.claude` 遗留 → 规范值） |
| 4 | graphify 两行规则（dirty 容忍 + 跳过条件） | AGENTS 有 → CLAUDE 补上 |

**钩子实现（`scripts/setup_git_hooks.py` 扩展）：**
- 在 `sync_wiki_spec.py` 前增加 AGENTS/CLAUDE 正文校验
- **跳过前 3 行**（H1 标题 / 空行 / 工具说明行）后逐字节比较余下内容；不一致 → ERROR + exit(1)
- 两文件合法差异仅 H1 标题（`# AGENTS.md` vs `# CLAUDE.md`）+ 第 3 行工具名（Codex vs Claude Code）

**验收：**
1. 两文件同步 → 钩子通过（EXIT=0）✅
2. 故意改 CLAUDE.md 不同步 → 钩子拦截（EXIT=1）✅
3. 正文（跳前 3 行）长度一致 27369 bytes ✅

## P2-B superpowers 归档（2026-08-18）✅ `409b0dc2`

**分档原则：** 按 git 最后提交时间（非 mtime——73 文件 mtime 均为 8/14 批量复制时间）。

**保留 9 个活跃文档（< 30 天）：**
- 当前计划 `2026-08-26-module-standardization-unification.md`（8/17）
- novel-wiki 活跃：`2026-08-15-*-writing-template*.md`（plan + spec，8/16）
- 8/12 的 4 个近期规划（knowledge-os-docs-integration 等）
- `PLAN_TEMPLATE.md` + `README.md`

**归档 64 个（2026-07-21 ~ 2026-08-11 已完结）：**
- 移至 `docs/archive/superpowers/`（保留 plans/specs 目录结构）
- `docs/archive/README.md` 说明"此目录为历史规划归档，不反映当前状态"

**验收：**
1. `docs/superpowers/` 73→9 文档（≤15 ✅）
2. `docs/archive/superpowers/` 64 文件可访问 ✅
3. `.superpowers/sdd/progress.md` 3 个链接全部指向保留文件，无需更新 ✅
4. 其他 docs 中指向已归档文件的引用（ARCHITECTURE/CONSTRAINTS/README 等）**保持原路径**——历史文档引用保留完整链，避免链式断链（记录：`docs/archive/` 内交叉引用同样保留原绝对路径）

## P3 公共层边界（2026-08-18）✅ `257d7777`

**迁移：** `src/shared/test_helpers.py` → `tests/support/test_helpers.py`

**动作：**
- `git mv src/shared/test_helpers.py tests/support/test_helpers.py`
- 删除 `src/shared/__init__.py`（空目录，src/shared/ 整体消失）
- 更新 9 个测试文件 import：`from src.shared.test_helpers` → `from tests.support.test_helpers`

**命名约定（明确 src/ 分层）：**
- `src/utils/`：纯函数、无副作用工具（path/slugify/text/similarity/idempotency）
- `src/lib/`：框架性代码、有副作用辅助（atomic_ctx/write_hooks/project/context_budget/budgeted）
- `src/*/core/`：业务领域核心（wiki/core、knowledge/core）

**验收：**
1. `src/shared/` 目录不存在 ✅
2. 9 个文件 `from tests.support.test_helpers import ScriptedLLMProvider` 可导入 ✅（traceback 证实实际走 tests.support 路径）
3. 非模板依赖测试 24/24 通过 ✅（预存模板解析失败 TemplateParseError 与 P3 无关，基线一致）
4. 未动 `src/utils/`/`src/lib/` 内容（仅文档化边界）

## 遗留脚本全量收编（2026-08-18）✅ `c8ace1da`

**目标：** 按 plan 3d 表，将 `scripts/` 中 38 个遗留脚本全部注册为 `ruflo` 子命令。

**收编范围（四组 38 子命令）：**

| 组 | 子命令数 | 清单 |
|---|---|---|
| `ruflo batch` | 17 | run/plan（进程内）+ gate-check/gate-v3/diagnose-gate/accept/generate/commit/build/ingest/rollback/pilot/phase3-accept/phase4/phase5-accept/plan-first/plan-backlog（子进程转发） |
| `ruflo migrate` | 5 | legacy-tags/pinyin-to-cjk/slug-aliases/timestamps/vector-paths |
| `ruflo audit` | 4 | blindspots/placeholder-classify/wiki-baseline/quality-check |
| `ruflo util` | 12 | aggregate-synthesis/cleanup-stubs/cleanup-tags/fix-mojibake/ndg-calibrate/normalize-sources/rebuild-index/stress-test/sync-wiki-spec/setup-git-hooks/ingest-d/ingest-manual |

**实现方式：** 薄 CLI 包装 + 子进程转发（`subprocess.run`），原脚本保留 `python scripts/<name>.py` 直跑入口（兼容过渡期）。环境变量继承完整 `os.environ` + `PYTHONPATH` 确保 Windows 下模块加载正常。

**新增文件：**
- `src/cli_ext/scripts_cmd.py` — migrate/audit/util 三组，子进程转发
- `src/cli_ext/batch_cmd.py` — 扩展（原 71 行 → 134 行），追加 15 个子进程转发
- `tests/test_cli_ext/test_scripts_cmd.py` — 5 测试（注册 + 转发验证）

**遗留问题清零：**
- ~~`batch_ingest`/`phase4_batch` 等未收编~~ → ✅ 全部收编
- ~~`batch_gate_check` 等 gate 子命令未建~~ → ✅ `ruflo batch gate-check/gate-v3/diagnose-gate`

**验证：**
1. `ruflo {batch,migrate,audit,util} --help` 列全子命令 ✅
2. `ruflo batch diagnose-gate -- --help` 透传至原脚本 ✅（exit=2, 输出含原脚本名）
3. 5/5 CLI 注册测试通过 ✅
4. 19/19 batch_executor 崩溃注入测试通过 ✅（含 os._exit(137) 子进程）

## 架构整改（2026-08-18，Wave 0+1 完成）✅

**计划**：`docs/superpowers/plans/2026-08-18-architecture-remediation.md`（15 项风险，Wave 0/1/2）
**范围确认**（用户批准）：受控单机单 worker / 单一 Bearer Token / 上传上限 50MiB / 候选链路冻结+删除

### Wave 0 — 外部暴露止损（P0）✅

| 风险 | Commit | 摘要 |
|---|---|---|
| R1 管理面认证+Key 脱敏 | `cdf25b53` | Bearer Token（`ruflo auth-token {generate,show,clear}`）+ /api/v1 写操作与 provider 管理需 Token；无 Token 非回环绑定拒绝；provider 响应强制脱敏；修复 `_default_providers` 缺 settings import |
| R2 上传上限 | `445bc2df` | `RUFLO_MAX_UPLOAD_BYTES`（默认 50MiB）；HTTP 路由分块读取超限 413；Collector 统一源读取层限制（URL/本地文件/文件夹摄取不可绕过） |
| R15 凭据/出境边界 | `26416a42` | 启动权限检查（非 0600 警告）；show/add 出境提示（stderr 保 JSON 契约）；`llm-providers rotate-key`（不回显新 key） |

### Wave 1 — 数据正确性与可用性（P1）✅

| 风险 | Commit | 摘要 |
|---|---|---|
| R4 拒绝分支 | `59ed6c0d` | `_write_rejected_source_page` 改用同步 AtomicContext + 真签名；拒绝分支返回 (pages, extra, meta) 三元组；slug 只取 basename |
| R3 提交失败语义 | `266d6f16` | `AtomicCommitError(failed_paths)`；flush 失败抛聚合异常不再吞错；callback 失败也传播；body 异常仍优先 |
| R6 单实例 + R14 显式 project root | `00e0cb60` | `serve --workers>1` 拒绝；`--project-root` 必填（拒绝 CWD 猜测）；`.llm-wiki/server.lock` 实例锁（死 PID 自动清理）；`RUFLO_PROJECT_ROOT` 传递 |
| R5 /ready | `7f705792` | 分项检查 queue/wiki/vector/provider，200/503；provider 探测 60s 缓存防抖动 |
| R7 向量补偿 | `9617540a` | `.index/vector_pending.json` 账本；commit 后 mark、upsert 成功 clear、启动 scan 兜底；`ruflo vector {status,reconcile}` |
| R8 异常分类 | `a905db25` | `RetryableDependencyError`/`InvalidInputError`/`DataConsistencyError`/`ProgrammingError`；`[no-retry]` 标记 → 立即死信 |

### Wave 2 进行中

R9 候选链路删除 → R10 routes 收敛 → R11 依赖 profile → R12 关联 ID+告警 → R13 版本+runbook

### Wave 2 — 演化与运维（P2）✅ 完成

| 风险 | Commit | 摘要 |
|---|---|---|
| R9 候选链路删除 | `95cfc9d2` | 删除未接入的 Reviewer/Promoter/ClaimExtractor stage（生产零引用，-1855 行）；保留 KnowledgeCandidate 数据模型与 generator 工具函数 |
| R10 routes 收敛 | `76398c59` | heat 写操作收敛到 `src/services/heat.py`；route 变薄适配器；新增 test_route_boundary.py 静态守卫（禁 route 直接 import wiki 写内部） |
| R11 依赖 profile | `2e219eaa` | pyproject 新增 `[embedding]` extra；`embed_profile.embedding_mode()` = remote/local/keyword-only；/ready 诚实报 degraded；新增 requirements.lock |
| R12 关联ID+告警 | `94363bfc` | 4 类告警指标（dead_letter/backlog/provider_failure/write_failure）；`src/lib/correlation.py` request_id/task_id/project_id 日志关联；docs/ops/runbook.md |
| R13 版本+runbook | `f02bd971` | `src.__version__` 单一真源（health/app 派生）；start.bat 移除 netstat 误杀、改用 serve-stop + --project-root |

### 整改全量验收（Wave 0/1/2 全部完成）✅

**15/15 风险整改完成**，全部有测试 + 提交。运行验证：
- 测试回归：858 + 1278 + 389 + 78 = **2603 测试通过**（含 15 项整改的新增测试约 100+）
- 冒烟验证：`serve --project-root` 启动 → `/health` 返回 version=2.0.0（R13）、`/ready` 分项 200（R5/R14）、无 Token 非回环绑定被拒 exit 2（R1/R6）
- 已知基线（未改动前即存在）：全量收集 5 文件兄弟 conftest 级联错误；test_url_redirect_to_loopback_blocked 需真实 DNS

**整改后架构状态**：信任边界（Token 认证 + Key 脱敏 + 上传上限 + 凭据边界）、数据正确性（AtomicContext 失败传播 + 拒绝分支修复 + 单实例护栏 + 显式 project root + /ready + 向量补偿 + 异常分类）、演化运维（唯一主链路 + services 收敛 + 依赖锁定 + 告警 + 版本统一 + runbook）三大块全部落地。

## Phase 4 批量重摄入续跑（2026-08-18，架构整改后）🔄

**状态恢复**（batch_build_state.json）：batch 0 孤儿（legacy smoke，postcheck_failed）；batch 1-7 committed（160 文件）；**batch 8 起待跑（63 批 1241 文件）**。

**运行命令**（BatchRunner 收编后入口，provider 默认 sfkey-glm/glm-5.2）：
```bash
PYTHONPATH=. python -m src.cli batch run --root knowledge/novel-wiki --batch <N> --concurrency 3
```
- batch 8（01_新手入门 剩余 20 文件）2026-08-18 16:18 启动
- 整改兼容性：R2 50MiB 上限不影响（源文件均小）；R4 拒绝分支返回三元组（batch 兼容）；R7 vector_pending 在 batch upsert 成功后自动 clear
- 每批 ~25 分钟，LLM ~27 次/批

## 标签规范化整改（2026-08-18，进行中）🔄

**计划**：`docs/superpowers/plans/2026-08-18-tag-normalization-remediation.md`
**背景**：batch 8（20 源文件已落盘）Gate re-check 失败；根因 = legacy 英文前缀
（`func/`、`genre/` 等）绕过 Generator 规范化写入磁盘 + Gate 使用严格中文命名空间。
**政策决策**：保持兼容政策（策略 1，任何带标签页面自动补 `素材/ugc`+`可信度/ugc`），
来源感知政策（策略 2）延后（方案 §3 决策注记）。

**已实施（代码已改，待宿主恢复后跑测试验证 + 提交）**：
| Task | 内容 | 文件 |
|---|---|---|
| 1 | 规范化契约测试按策略 1 修正（2 个测试期望补 mandatory） | `tests/test_wiki/test_tag_normalization.py` |
| 2 | Generator `_normalize_tags` 增加审计日志；`build_tag_prompt_section` 增加 legacy 前缀禁用行；analyzer 内联注释同步 12 前缀 | `src/pipeline/generator.py`、`src/wiki/features/tag_namespace.py`、`src/pipeline/analyzer.py` |
| 3 | `commit_ingest()` 对 `pages + extra_pages` 写盘前统一 `normalize_tags` + TAG-MAPPED/TAG-REMOVED/TAG-MANDATORY 审计日志；新增 3 测试 | `src/pipeline/ingest.py`、`tests/test_pipeline/test_ingest_generate_commit_split.py` |
| 4 | `cleanup_invalid_tags.py` 改用公共 `normalize_tags`（mapping/removal/mandatory 输出 + `--apply`）；新增 4 测试；Gate 保持严格校验（复用 `validate_tag_compliance`） | `scripts/cleanup_invalid_tags.py`、`tests/test_scripts/test_cleanup_invalid_tags.py` |
| 2/4 | Generator legacy 前缀解析测试（`func/教程`→`功能/教程` 且过 `validate_tag_compliance`） | `tests/test_pipeline/test_generator.py` |
| docs | `docs/reference/ingest-prompts.md` 标签规则纠偏（12 中文前缀 + legacy 禁用）；`docs/guides/novel-wiki-ingest-spec.md` 更新 legacy 迁移说明 | 两个文档 |

**待办（宿主恢复后）**：
1. 跑测试（`pytest tests/test_wiki/test_tag_normalization.py tests/test_wiki/test_tag_namespace.py tests/test_pipeline/test_generator.py tests/test_pipeline/test_ingest_generate_commit_split.py tests/test_scripts/test_cleanup_invalid_tags.py tests/test_scripts/test_batch_executor.py -v`）→ 修复 → 逐 Task 提交
2. batch 8：`diagnose_batch_gate.py` / `accept_batch.py --root knowledge/novel-wiki --batch 8` 确认当前 Gate 实际失败项（静态检查未发现 batch 8 页面含 legacy 标签——需运行确认原 `func/结构`、`func/关系`、`genre/平台` 的出处）
3. 按需 `cleanup_invalid_tags.py --page-ids <受影响>` 修复 → `accept_batch` → batch 8 committed
4. 继续 `python -m src.cli batch run --root knowledge/novel-wiki --batch 9 --concurrency 3`
5. 可选后续：全库 `cleanup_invalid_tags.py --all --apply` 清理存量 129 处 legacy 标签（M8 指标）

## 确定性字段与链接整改（2026-08-18，Task 0 完成，Task 1+ 进行中）🔄

**计划**：`docs/superpowers/plans/2026-08-18-deterministic-page-fields-and-links.md`
**背景**：batch 9 pre-commit Gate 阻断（`飞书云文档`/`北京圣东方国信科技有限公司` →
`[[入门教程角色篇完善小说的技法-e8ca1866]]` 旧 hash + 标题丢词的 source 链接）。
方案经 plan-audit 两轮审查（致命 0 → 重大 2 → Task 0 前置）。**编码门槛**：Task 0
未证明提交/并发/TOCTOU/custom-type 边界前不进入 Task 1，也不重跑 batch 9。

**Task 0（✅ 已提交 `19ea1ed2`）**

| 切片 | 内容 | 文件 |
|---|---|---|
| 0.1 | sanitizer reject 改纯内存返回（Gate 前零 wiki 写入）；回归测试改显式 commit 断言 | `src/pipeline/ingest.py`、`tests/test_pipeline/test_rejected_source_page.py` |
| 0.2 | `AtomicCommitError` → raw `partial_commit`（+failed_paths）+ 停止批次（rc 4）；flush 故障注入钩子 `RUFLO_FLUSH_FAIL_PATHS`；`log_event` 按 (event,task_id,detail) 去重；partial 重试幂等测试 | `src/orchestrator/batch_runner.py`、`src/lib/write_hooks.py`、`src/wiki/features/logger.py`、`tests/test_scripts/test_batch_executor.py` |
| 0.3 | 跨进程 `project_commit_lock()`（`.index/commit.lock`）包裹提交循环；`write_page(expected_content_hash)` CAS → `WriteConflictError`；批级 `write_conflict`（rc 5）| `src/services/batch_state.py`、`src/wiki/storage/page_writer.py`、`tests/test_wiki/test_page_writer.py` |
| 0.4 | `SchemaRegistry.iter_page_dirs()` 统一目录枚举；`_collect_existing_wiki`/`_resolvable_set` 改用；custom type 发现/对账测试 | `src/wiki/schema_registry.py`、`src/pipeline/reconcile.py`、`tests/test_wiki/test_schema_registry.py` |
| 0.0 | `BATCH_STATUSES` 增加 `partial_commit`；测试常量同步 | `src/services/batch_state.py`、`tests/test_services/test_batch_state.py` |

**验证**：139 项定向测试全绿（batch 状态机、lib 原子写、reject、commit split、reconcile、
page_writer、schema_registry、cascade、immutable）。

**Task 0 已证实的语义**：Gate 前零 wiki 写入；单 raw 提交部分失败 → `partial_commit`
可发现可重试（page/index 幂等、log 去重）；人工编辑 → `WRITE-CONFLICT` 拒绝覆盖；
同项目并发提交由跨进程锁串行化；custom type 页全目录可见。
**已知上限（ponytail）**：`AtomicContext` 仍是线程局部缓冲（async 同线程任务间可能
串桶，服务器并发摄入未覆盖）；owner-token fencing 未实现（由提交锁串行化替代）。

### 待办

1. ~~提交 Task 0~~ ✅ `3675f1f4`（标签 Task 1-4）+ `19ea1ed2`（Task 0）
2. Task 1（✅ 待提交）：canonical raw path（`canonical_raw_key` v1：NFC/root 外拒绝/golden vectors）+ Target Resolver（`src/wiki/features/target_resolver.py`，优先级 exact→source→alias→title→legacy_hash→unresolved/ambiguous；legacy_hash 仅带 hash 后缀 + 唯一 source 候选内允许 0.88 相似度）；17 contract tests `tests/test_wiki/test_target_resolver.py` 全绿
3. Task 2（✅ 待提交）：`generate_ingest` 冻结 `ResolutionContext`（canonical key + source 候选 + index/title/alias 快照）→ `_normalize_generated_pages` 统一重写 body wikilink + relation target；删除 generator 两处 inline source-link 修复（含 difflib）；`test_generate_ingest_rewrites_legacy_hash_source_link` 通过
4. Task 3（✅ 待提交）：提取 `finalize_generated_page()` 显式字段 owner 边界（grade/depth/id/title/时间戳）；custom type 全链路目录枚举已在 Task 0.4 覆盖（iter_page_dirs → collect/reconcile；Gate 经 index.md 覆盖 custom 页）；休眠入口 `generate_from_candidate`/`generate_from_knowledge_object` 无仓库内调用方，接入待后续（ponytail: 无调用方不接线）
5. Task 4（✅ 待提交）：`SlugAliasRegistry.get_canonical` 有界链解析（`_MAX_ALIAS_DEPTH=8`，环/自环/超深 fail-closed）+ `add` 拒绝自环；`finalize_generated_page` 归一化 relation weight（越界/NaN → 1.0）；taxonomy 已由 `write_page` 严格校验
6. Task 5（进行中）：`run_precommit_gate` 接受 `resolution_context`；`_gate_reconcile` 未解析目标经统一 resolver 判别——多候选 → `TARGET-AMBIGUOUS`（可诊断，不受 pending_gap 豁免），否则 `BROKEN-LINK`；batch_runner 收集整批 source 候选传入 Gate
4. Task 3：`finalize_generated_page()` 字段接管 + custom type 全链路
5. Task 4：relation/taxonomy/alias 归一化
6. Task 5：Gate 审计输出 + unresolved blocker + 副作用 sentinel
7. Task 6：batch 9 重跑验收（Gate 前零写入 + partial 恢复 + 并发锁已就位）
