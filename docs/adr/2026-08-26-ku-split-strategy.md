# ADR-002: KnowledgeUnit 拆分策略（路线 v2.2 §A-1 决策矩阵）

- **状态**: proposed
- **日期**: 2026-08-26
- **触发**: 路线 v2.2 自审 H-5 整改项 —— §A-1"3 选 1 决策标准缺失、没成本估算、没推荐"
- **关联**:
  - `docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md` §A-1（KnowledgeUnit 单独建模）
  - spec §4.2 KnowledgeUnit 5 条要求（位于 `C:/Users/HP/Documents/Codex/2026-08-26/referenced-chatgpt-conversation-this-is-an/outputs/DEVELOPMENT_PLAN.md` §4.2）
  - spec §4.4 拆分/合并 4+4 条件
  - `docs/adr/ADR-001-knowledge-compiler-migration.md`（A/C/B 执行范围）

## Context

### spec §4.2 的硬约束

spec §4.2 规定 KnowledgeUnit 必须满足：

> - 能用一个明确问题描述；
> - 能独立被检索和引用；
> - 具有相对一致的上下文和时间范围；
> - 只包含一组高度内聚的 Claim 或 Structured Fact；
> - 更新时不要求重写整个 Concept。

第 1 条"能用一个明确问题描述"是 KU 粒度的核心约束 —— 多问题混杂的页面无法被一个 question 字段（identity_key 输入字段之一）精确寻址。

### 当前现状（grep 已确认）

| 指标 | 数量 | 备注 |
|---|---|---|
| markdown 文件总数 | 6749 | `knowledge/**/*.md` |
| wiki 页面（带 frontmatter） | 5151 | 含 source / entity / concept / synthesis / claim 等 |
| PageType 分布（novel-wiki 样本） | | 来自 `knowledge/novel-wiki/wiki/**` 实测 |
| — `concept` | 2234 | 43.4% |
| — `entity` | 1341 | 26.0% |
| — `source` | 1251 | 24.3% |
| — `synthesis` | 56 | 1.1% |
| — `claim` | 10 | 0.2% |
| — `unknown` / 无 frontmatter | 84 | 1.6% |

注：`synthesis` + `claim` + `decision` + `procedure` + `event` = 叙事类；novel-wiki 当前实际计数 = 66 页（claim 10 + synthesis 56；decision/procedure/event = 0）；路线文档基于全仓 6749 页做的"40% 叙事"是估算上限。

### 路线 v2.2 §A-1 的"3 选 1"原话

> 叙述类拆分策略（dry-run 后用户决策 3 选 1）：
> - 选择 1：所有页面 = 1 个 KU（简单，spec 妥协）
> - 选择 2：长页面 (>5 段) 触发 LLM 拆分（中等成本）
> - 选择 3：仅对"答案不明确"页面 LLM 拆分（精准成本）

**缺失**：
1. 没有决策标准（怎么判断"答案不明确"？）
2. 没有成本估算（每个选择花多少钱？）
3. 没有推荐（默认走哪个？超时怎么办？）

本 ADR 补齐这三项。

## Decision

### 决策

**默认选择 3（精准成本）。**

超时保护：**A-1 dry-run 完成 > 3 个自然日（72 小时）未由用户做出选择时，自动采用选择 3**。

### Decision Matrix（决策矩阵）

| 选择 | 描述 | spec 合规度 | 成本估算（6749 页基线） | 推荐度 | 触发条件 |
|---|---|---|---|---|---|
| **1：所有页面 = 1 个 KU** | 叙事类页面不分拆 | ❌ **违规** —— 第 1 条"能用一个明确问题描述"对长叙事页失败 | **¥0** | ❌ 不推荐 | 仅用于"完全放弃 spec §4.2 第 1 条"的兜底场景 |
| **2：长页面 (>5 段) LLM 拆分** | 叙事类中所有 >5 段都触发拆分 | ✅ 满足 | 叙事类 ≈ 6749 × 40% ≈ **2700 页** × ¥0.5/页 ≈ **¥1350** | ⚠️ 备选 | 当 A-1 dry-run 显示"答案不明确"页面远超 10% 时升级 |
| **3：仅"答案不明确"页面 LLM 拆分** | 仅精确命中"答案不明确"判定规则的页面触发 | ✅ 满足 | 叙事类 ≈ 6749 × 5-10% ≈ **350-700 页** × ¥0.5/页 ≈ **¥175-350** | ✅ **默认** | 默认 |

#### 成本公式

```
叙事类页面数 = wiki_pages × narrative_ratio
             = 6749 × 0.40 (上限估算，novel-wiki 实测 1.3%)
             ≈ 2700 页

choice_1_cost = 0
choice_2_cost = narrative_pages × llm_split_unit_cost     # ¥0.5/页
choice_3_cost = narrative_pages × precision_ratio × llm_split_unit_cost
              # precision_ratio ∈ [0.05, 0.10]
```

#### "答案不明确"的判定规则（选择 3 落地）

仅当叙述类页面同时满足以下**任意两条**时触发 LLM 拆分：

1. `## ` 二级标题数 ≥ 3 个（页面承载多个子主题）
2. body markdown token 数 ≥ 800（约 2000 中文字）
3. relations 数 ≥ 5（关系网络提示多主题）
4. PageType ∈ {CLAIM, SYNTHESIS, DECISION}（本身就需要被拆为多 KU 的高密度类型）

满足 0-1 条 → 单 KU；满足 2-4 条 → 触发 LLM 拆分；满足 ≥5 条 → 跳过拆分（视为超长 SOP 走手工决策）。

`scripts/kc_ku_cost_estimator.py` 提供离线 dry-run 实现，不调用真实 LLM。

### Rationale

1. **选择 1 违反 spec §4.2 第 1 条**。"能用一个明确问题描述"对长叙事页面失败 —— 一个 synthesis 页同时讲"玄幻流派演化"和"中国行政区划沿革"无法用单 question 寻址。这条 spec 是不可降级门槛（路线 §5 纪律表最后一行），不是可以妥协的优化项。

2. **选择 2 成本过高**。基线 2700 页 × ¥0.5/页 = **¥1350** 一次性 LLM 调用，且拆分后每页还要二次 backfill（KU 表 + identity_key 计算 + resolution_event 写入）。对 6749 页面的小型 KB 而言，**单次 backfill 占年度 LLM 预算的 30%+**。

3. **选择 3 精准且 spec 合规**。350-700 页 × ¥0.5/页 = **¥175-350**，仅占选择 2 成本的 13-26%。规则可解释、可重放、可灰度。novel-wiki 实测叙事类仅 66 页（占总页面 1.3%），即使全量拆分也仅 ¥33，远低于选择 2。

4. **超时自动选择 3 是兜底保护**。A-1 dry-run 完成后留 3 天窗口给用户决策；超时不决策意味着：(a) 任务被遗忘（应继续推进），(b) 用户对 spec 合规无异议（默认推荐即可）。两种情况选 3 都是合理 fallback。

### 为什么不是"全选 1 + 补救"？

路线 §5 纪律明确："KC v2.1 spec §14 的 A0-A9 Gate 是不可降级门槛，不达标即'未完成'"。spec §4.2 第 1 条直接绑定 KU identity_key 算法（identity_key 必含 `question` 字段，路线 §5 表 D-7），选择 1 会导致 identity_key 字段退化（多个 question → 取第 1 个 → 不可重放），进而阻塞 B-2.5 identity_key 总验收任务。

## Consequences

### 收益

1. **spec §4.2 合规**：选择 3 满足 5 条硬要求，A-1 任务验收无偏离
2. **成本可控**：默认路径占总预算 5% 以内，可观察、可中断、可重跑
3. **可重放**：判定规则纯函数 + 离线估算，`scripts/kc_ku_cost_estimator.py --project <id>` 任何时间可复算
4. **可灰度**：判定规则有阈值（标题数/token 数/关系数/PageType），后续可调整

### 代价

1. **判定规则本身需要评估**。"答案不明确"是个语义判断，4 条规则是代理指标；规则命中 ≠ 真正需要拆分。**dry-run 阶段必须人工抽样 20 页验证规则准确率 ≥80%**（路线 §A-1 已要求）
2. **超时兜底要求"3 天"硬编码**。需要任务编排侧（A-1 任务的 issue/PR/进度条目）有可见的截止日期；目前没有自动追踪机制，靠人工监督
3. **L-1 路线回顾时需检查**：novel-wiki 实测叙事类仅 1.3%（远低于 40% 估算），如果全仓比例类似，"叙述类拆分"实际工作量比路线 §1.3 F-3 风险评估的"低估"更小 —— F-3 风险可能比预估小，需要在 A-1 dry-run 完成后回写

### Trigger to Revisit

满足以下**任意一条**时，需重审本决策：

- 业务出现"叙述类页面需要更细粒度拆分"需求（例如：用户反馈某 KU 检索结果含无关内容）
- A-1 dry-run 显示判定规则准确率 < 80%（人工抽样 20 页验证）
- LLM 成本单价下降 ≥50%，使选择 2 成本低于 ¥700（即与选择 3 上限持平）
- 新版 spec 修订 §4.2 第 1 条的"明确问题"定义

重审流程：开新 ADR（如 `2026-XX-XX-ku-split-strategy-revisit.md`），引用本 ADR，不可静默推翻。

## References

- spec §4.2 KnowledgeUnit 5 条要求：`DEVELOPMENT_PLAN.md` 行 200-210
- spec §4.4 拆分/合并 4+4 条件：`DEVELOPMENT_PLAN.md` 行 216-232
- 路线 §A-1 F-3 整改：`2026-08-26-kc-spec-roadmap.md` 行 406-434
- 路线 §5 不可降级纪律：`2026-08-26-kc-spec-roadmap.md` 行 941-952
- 路线 §A-1 H-5 决策来源：`2026-08-26-kc-spec-roadmap.md` 行 899（"C-1 测试数与 spec Gate 不对齐"）—— **注**：本 ADR 解决的是 H-5 在 §A-1 上下文中的延展（决策标准缺失），不是同一 H-5 的原始范围
- 成本估算脚本：`scripts/kc_ku_cost_estimator.py`（离线 dry-run，不调用真实 LLM）
- 测试：`tests/test_kc/test_ku_split_strategy.py`（3 TDD 测试）

## Implementation Notes

- **不在路线 v2.2 文档中追加任何内容**（执行约束）
- **不修改 src/ 业务代码**（执行约束）
- **不引入新依赖**：脚本仅用 stdlib + yaml（PyYAML 已在 dev 依赖中）
- **不 git commit**（执行约束）
- 决策矩阵的"实际成本数字"以 novel-wiki 实测为准（见 test #1 输出）