# ADR 模板：指标阈值变更（Metric Threshold Change）

> **强制约束**（spec §15.3 末尾）：任何指标阈值变更**必须**：
> 1. 在固定数据集上做前后对比（前 = 当前生产阈值，后 = 拟改阈值）；
> 2. 填写本 ADR 模板（9 个必填字段）；
> 3. ADR 引用到对应 plan / spec 段落，并在 `.superpowers/sdd/delivery_reports/`
>    配套登记。
>
> **本模板是 `docs/adr/_template.md` 的特化**——增加 §Metrics / §Dataset Diff /
> §Threshold Before / §Threshold After / §Rollback 五段，便于审计与回放。

---

# ADR: <MTC-NNN 指标阈值变更 — <指标名> from <old> to <new>>

- **状态**: proposed | accepted | superseded by <other ADR>
- **日期**: YYYY-MM-DD
- **触发**: <什么信号表明阈值需调整（如：金标漂移、误报/漏报投诉、合规审计）>
- **关联**: spec §15.<X> / plan <plan-id> §<Y> / 上一份 MTC ADR
- **ADR 类型**: `metric-threshold-change`（CI 可扫描此类型做门控）

## Context（背景）

<1-2 段说明：当前阈值的来源、首次确立时间、为什么现在需要变更。>
<引用 spec 段落、相关 issue、上游指标趋势图（若有）。>

## Decision（决策）

将指标 **`<metric_name>`** 的阈值由 **`<threshold_before>`** 调整为 **`<threshold_after>`**。

- 涉及代码路径: <文件 + 行号或函数名>
- 涉及配置: <`.index/quality_settings.json` key / 环境变量 / 默认值>
- 影响范围: <该指标被哪些下游消费者使用（搜索、PR gate、CI、看板）>

## Rationale（理由）

为什么调整为 `<threshold_after>` 而非 `<threshold_before>`？bullet：

- **理由 A**: <观测数据 / 量化趋势，如"近 30 天 precision 下降 4.2pp">
- **理由 B**: <业务诉求，如"产品要求降低误报率 30%">
- **理由 C**: <合规 / spec 段落对齐>

## Consequences（后果）

- **正面**: <预期改进，如"precision 提升至 0.93，召回保持 0.85">
- **负面**: <预期代价，如"误杀率上升 1.5pp，下游 5 个 query 模板需调权">
- **风险**: <可能漏检的边角场景>
- **触发重审**: <什么条件触发再次重审，如"误报率再次突破 5%">

## Metrics（指标）

受影响指标的完整列表（含阈值变更前后的目标值）：

| Metric | 类型 | Threshold Before | Threshold After | 单位 | 消费者 |
|---|---|---|---|---|---|
| `<metric_name>` | primary | `<old>` | `<new>` | ratio / ms / count | <下游模块> |
| `<side_effect>` | secondary | `<old>` | `<new>` | ratio | <下游模块> |

> **说明**：primary = 本次变更对象；secondary = 因 primary 变更可能受影响的指标
> （如阈值放宽通常伴随误杀率上升）。

## Dataset Diff（数据集前后对比）

> **必填项**：必须在**固定数据集**（spec §15.2 评估数据集版本）上跑前后两次指标，
> 附 raw 输出。

| Metric | Before (production) | After (proposed) | Δ | 备注 |
|---|---|---|---|---|
| `<metric_name>` | `<old_value>` | `<new_value>` | `<delta>` | `<观察 / 解释>` |
| `<side_effect>` | `<old_value>` | `<new_value>` | `<delta>` | `<观察>` |

**数据集版本（必须固定）**: `<evaluation_dataset_version>`（spec §15.2）

**对比脚本**:
```bash
# Before
PYTHONPATH=. python scripts/kc_eval.py \
  --dataset <evaluation_dataset_version> \
  --threshold <threshold_before> \
  --output .index/eval/before.json

# After
PYTHONPATH=. python scripts/kc_eval.py \
  --dataset <evaluation_dataset_version> \
  --threshold <threshold_after> \
  --output .index/eval/after.json
```

**对比报告附件**: <链接到 .index/eval/before.json / .index/eval/after.json>
（commit 时附 .index/eval/2026-MM-DD-<metric>-diff.md）

## Threshold Before（变更前）

```yaml
threshold_before:
  value: <old_value>
  unit: <ratio | count | ms | bool>
  source: <哪个文件 / 行号 / 配置键>
  effective_since: <YYYY-MM-DD 该阈值生效日期>
  set_by: <上一份 MTC ADR ID / 首次建立时无>
```

## Threshold After（变更后）

```yaml
threshold_after:
  value: <new_value>
  unit: <ratio | count | ms | bool>
  source: <哪个文件 / 行号 / 配置键>
  effective_from: <本次 ADR 落地后立即生效 / 下一发版>
  set_by: <本次 ADR ID>
```

## Rollback（回滚）

> **必填项**：必须给出**一行可执行的回滚命令 / 操作**。

- **回滚命令**:
  ```bash
  # 例如
  git revert <commit-hash-of-threshold-change>
  # 或
  sed -i 's/<threshold_after>/<threshold_before>/' .index/quality_settings.json
  ```
- **回滚验证**: <跑哪个 eval / CI job 确认回到 before 状态>
- **数据迁移**: <是否需要重新跑 batch / 重建索引（一般不需要）>
- **回滚 SLA**: <P0 即时 / P1 24h / P2 7d>
- **回滚负责人**: <on-call 团队 / 个人邮箱>

---

## Alternatives Considered（备选方案）

| Option | 阈值 | Pros | Cons | Verdict |
|---|---|---|---|---|
| 维持现状 | `<threshold_before>` | 稳定 | 已知问题持续 | ❌ rejected |
| 本提案 | `<threshold_after>` | <优势> | <代价> | ✅ chosen |
| 备选 B | `<alt_value>` | <优势> | <代价> | ❌ rejected |

## References（参考）

- spec §15.<X>
- plan file: <plan-id>
- 上一份 MTC ADR: <ADR ID>
- eval 报告: `.index/eval/2026-MM-DD-<metric>-diff.md`
- 相关 issue: <#123>

## Implementation Notes（实施笔记）

- **代码改动**: <文件 + 行号>
- **测试**: <新增 / 修改的 test 文件>
- **delivery_report**: `.superpowers/sdd/delivery_reports/<task-id>.yaml`
  - `metrics` 字段必须填入 §Metrics 与 §Dataset Diff 中的真实数值。
  - `hard_gate_failures` 必须为空（否则 `next_phase_ready=false`）。
- **发布 checklist**:
  - [ ] ADR 落地（本文件提交）
  - [ ] 阈值已写入配置 / 默认值
  - [ ] delivery_report 校验通过（`scripts/kc_check_delivery_report.py`）
  - [ ] eval diff 已归档到 `.index/eval/`
  - [ ] 影响下游消费者已通知（搜索 / 看板 / CI）