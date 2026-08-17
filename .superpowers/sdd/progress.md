# progress — novel-wiki v3 写作知识库方案（执行账本）

> 方案：`docs/superpowers/specs/2026-08-15-novel-wiki-writing-template-design.md`
> 计划：`docs/superpowers/plans/2026-08-15-novel-wiki-writing-template.md`
> 续接：`.memory/handoff-novel-wiki-phase1-2026-08-15.md`（Phase 0-2）、`.memory/handoff-novel-wiki-phase3-2026-08-16.md`（Phase 3 续接）
>
> **新计划（2026-08-26）：** 模块规范性与统一化改造 — `docs/superpowers/plans/2026-08-26-module-standardization-unification.md`
>
> **P0-A 注册 ruflo CLI → ✅ `be5417ec`**
> **P0-B 中央配置模块 → ✅ `bca225a6`**
> **P1-A BatchRunner 收编脚本 → 待执行（下一会话）**
> **P1-B 根目录清理 → 待执行**
> **P2-A 文档双文件同步 → 待执行**
> **P2-B superpowers 归档 → 待执行**
> **P3 公共层边界 → 待执行**

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
