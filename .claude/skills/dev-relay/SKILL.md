---
name: dev-relay
agent_created: true
description: 分段接力开发流水线的阶段路由——需求澄清/架构设计（mattpocock 系）→ 编码实现（ponytail）→ 评审（mattpocock 系）之间的切换规则与约束。This skill should be used when 开始新功能或大型需求开发、需要在架构设计/编码/评审阶段之间切换、或用户提到"分段接力""切换 ponytail""进入编码阶段""开始评审""架构方案已定"。
---

# 分段接力开发流水线（dev-relay）

适用：单人开发工具软件、模块化架构、多设备 Git 同步。

**核心原则：mattpocock/skills 与 ponytail 分段接力使用，禁止两套同时全局常驻。** 两套技能的策略相互冲突，同时常驻会导致输出不稳定。

**切换由用户指令驱动。** 识别当前所处阶段、在阶段任务完成时给出切换建议，但不擅自切换模式、不主动执行下一阶段命令。

## 阶段路由

| 阶段 | 启用 | 关闭 | 依次执行 |
|---|---|---|---|
| 1 需求澄清 + 领域建模 + 架构设计 | mattpocock 系 | ponytail | `/grill-with-docs` → `/domain-modeling` → `/to-spec` |
| 2 编码实现 | ponytail full | mattpocock 流程引导 | 按 spec 编码 |
| 3 评审 | mattpocock 系 | ponytail | `/ponytail off` → `/code-review` |
| 4 定期架构体检 | — | — | `/improve-codebase-architecture` |

阶段 1 产出：模块边界、对外 API 契约、Spec 文档（含验收标准）。
阶段 1 的方案在进入阶段 2 之前，必须先过 `plan-audit` 技能的两轮审查。

## 进入编码阶段（阶段 1 → 2）的强制约束

用户下发切换指令后，编码全程遵守：

1. 精简代码不得破坏预先约定的模块边界；模块仅允许通过 `api.ts` 对外暴露接口；
2. 不允许为简化实现制造模块耦合；
3. 禁止删除必要类型定义、参数校验、异常处理、边界容错；
4. 如果为了简洁牺牲规范，必须添加 `ponytail:` 注释标记技术债务；
5. 严格遵守项目根目录 `PROJECT_SOP.md`（若存在）。

⚠️ 禁止使用 `ponytail ultra`——激进模式易破坏模块化所需抽象。ponytail 仅在编码阶段启用，架构设计与方案审查阶段务必关闭。

## 评审阶段（阶段 3）重点

执行 `/code-review` 时重点检查：跨模块私有导入、循环依赖风险、被精简掉的必要校验/异常处理。

## 优先级排序（冲突时生效）

`PROJECT_SOP.md` > 已确认的架构方案 > ponytail 内置规则 > mattpocock 默认规则 > CLAUDE.md 行为准则。

## 避坑清单

- 不要两套技能同时常驻自动运行；
- 新增大型功能必须先走完 `/grill-with-docs` + 方案自我审查，再启动编码；
- 不可完全依赖 AI 自查，人工最终把关；
- 架构决策写入 `docs/adr/`，领域术语统一维护在 `CONTEXT.md`；
- `.claude/skills/`、`CONTEXT.md`、`docs/adr/` 全部提交 Git，保障多设备同步。
