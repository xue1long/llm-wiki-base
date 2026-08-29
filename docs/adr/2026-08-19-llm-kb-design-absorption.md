# ADR: 从 LLM_Knowledge_base_v2 吸收 wiki 摄取设计

- **状态**: Proposed — plan-audit 四轮完成,所有致命缺陷 + 重大隐患已整改,待人工复核后进编码
- **日期**: 2026-08-19
- **作者**: agent(w/ 第一性原理判断)
- **触发**: 用户对比 `LLM_Knowledge_base_v2` 与本项目的摄取 wiki 模板,询问哪些值得吸收
- **关联**:
  - `docs/superpowers/plans/2026-08-19-capture-template-and-quick-entry.md`(capture 模板 6 轮审查 plan)
  - `src/wiki/features/tag_namespace.py`(已存在的命名空间机制)
  - `D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\30_System\`(对比源)

## Context(背景)

`LLM_Knowledge_base_v2`(下文简称 **LLM_KB**) 是一个 B 站/抖音视频笔记专用库,经过多轮设计迭代形成了一组健壮性补丁:

- `processing_depth` × `source_grade` 二维分桶 + 决策树强制路由
- C 级碎片 mini-wiki 兜底(不 skipped)
- 命名空间标签 `tool/scene/status`
- `use_context` 职能上下文
- `workflow_state` 状态机(`draft → ready → verified → outdated`)
- `maturity` 中文 + 英文内部映射(两轴正交)
- `@@FIELD: name @@` sentinel 解析(防 LLM 输出污染)
- 模板锁死 + LLM 只填 `{{placeholder}}`

**问题**:本项目 `ruflo-kb` 是否应该吸收这些设计?如果不区分"有真实缺口"与"已有等价",会导致 over-engineering。

## 决策(Decision)

按"是否解决本项目真实缺口 + 是否与现有架构冲突"分级:

| 级别 | 设计 | 决定 | 理由 |
|---|---|---|---|
| 🟢 A | C 级碎片 mini-wiki 兜底路径 | **吸收** | 本项目无"短内容特殊路径",50 字金句会被 Generator 强行扩写,产生注水。`ReviewerStage` 是事后检查,不是事前分桶。 |
| 🟢 A | `workflow_state` 状态机(`draft/ready/verified/outdated`) + `verified_at` 字段 | **吸收** | 本项目 `grade` A/B/C 是 **内容质量**、`heat` 是 **使用频率**,但 **没有"是否经过人工核验"的标记**。LLM 输出 + Agent 引用之间缺一道人工 trust 边界。 |
| 🟡 B | `use_context` 职能上下文 | **部分吸收**(评估后再定) | `custom_type` + `relations` 已部分表达"上下文归属",但缺少显式"按职能筛选"的检索维度。**先做检索需求调研,确认有真实用例再吸收**。 |
| 🟡 B | `maturity` 中文 + 英文内部映射思想 | **不搬具体方案,只吸收思想** | `maturity`(质量)和 `workflow_state`(生命周期)是 **正交两轴**,不要混。具体中文枚举不要搬(本项目走英文 grade)。 |
| 🔴 C | `@@FIELD:` sentinel 解析 | **不吸收** | 本项目 `WikiPage.from_dict()` 走"严格白名单 + frontmatter/body 物理分离",污染路径已被切断。sentinel 是 LLM_KB 历史包袱的特解,搬来反而改 Generator 协议,破坏已有 7 个模板。 |
| 🔴 C | 模板锁死 + LLM 只填 `{{placeholder}}` | **不吸收,哲学冲突** | 本项目设计哲学是"LLM 是创造者,人是审核者"(Generator 拼 slot);LLM_KB 是"人是创造者,LLM 是填空工具"。两套哲学不能并存。 |
| 🔴 C | 命名空间标签 `tool/scene/status` | **不吸收,会冲突** | 本项目 `src/wiki/features/tag_namespace.py` 已有 **12 个中文 prefix**(题材/功能/角色/事件/情绪/实体/场景阶段/状态/素材/可信度/读者群/平台)。LLM_KB 的 3 个英文 prefix 与之不兼容,且本项目定位是"网文写作域",LLM_KB 是"通用工具栈域"。 |
| 🔴 C | `compare_candidates` 异步扫描 | **不吸收,等价已有** | 本项目 `RUFLO_SHADOW_MODE=true` 双路径对比 + `ReviewerStage` 多轮 + `relations` 字段已实现 synthesis 提炼。两种范式不同,二选一。 |
| 🔴 C | DB 强制 backup + dry-run | **不吸收,等价已有** | `src/schemas/Migration` 框架 + `.backup/` + `Migration.preview()` 已实现。 |
| 🔴 C | raw 文件归档到 `_archive/` | **不吸收,等价已有** | `ingest.py` 自动归档 + `compile.py` 已实现。 |

## plan-audit 第一轮整改记录(2026-08-19)

### 致命缺陷整改

| # | 原始漏洞 | 整改 |
|---|---|---|
| **F1** | Generator 不读取 `processing_depth` 字段,短内容仍被扩写 | **新增 Task 2.5:Generator 路由逻辑**。在 `src/pipeline/generator.py` 中读取 `page.processing_depth`,若为 `memory` 则使用 `short-form` 模板;若为 `concept` 则使用现有模板 |
| **F2** | `processing_depth=memory` 对应的模板缺失 | **新增 Task 2.6:创建 short-form 模板**。在 `src/templates/bundled/general/` 下新增 `short-form.md`(通用精简模板,2-3 段:摘要/核心观点/来源);同时在 `capture` 模板的 `schema.md` 中声明 `memory` 路由 |

### 重大隐患整改

| # | 原始漏洞 | 整改 |
|---|---|---|
| **H1** | 短内容判定阈值一刀切,未按领域调整 | **模板级阈值覆盖**:`template.json` 新增可选字段 `short_form_thresholds:{ chars, steps }`,`detect_short_form()` 接受可选 `template_thresholds` 参数。未设置时用默认 200/3 |
| **H2** | `processing_depth` 字段未做枚举校验 | **`from_dict` 中加枚举校验**: `processing_depth = d.get("processing_depth", "concept")` + `if processing_depth not in {"concept", "memory"}: processing_depth = "concept"` |
| **H3** | capture 写入的卡无法变成 `verified` | **新增 `capture mark-verify` CLI 子命令**: 调用 `workflow.py::transition(page, "verified")`,同时提供 `POST /api/v1/projects/{id}/pages/{page_id}/verify` API |

### 优化疏漏整改

| # | 原始漏洞 | 整改 |
|---|---|---|
| **M1** | `workflow_state` 字段未做白名单校验 | **`lint.py` 加白名单**: `if page.workflow_state not in VALID_STATES: issues.append(...)` |
| **M2** | 短内容判定边界值测试用例缺失 | **测试列表补充**: 增加 200 字中文+2 步骤(memory)、200 字中文+3 步骤(concept)、199 字中文+3 步骤(memory) 三组边界值 |
| **M3** | `_count_chinese_chars` 只统计基本汉字 | **扩展 Unicode 范围**: `re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", content)` |
| **M4** | `_count_steps` 不匹配 "第1步"(阿拉伯数字) | **添加模式**: `steps += len(re.findall(r"第\d+[步点节]", content))` |
| **M5** | `draft` 状态包含待审核,状态不准确 | **设计选择**: 保持 `draft` 包含待审核(简化状态机),在文档中明确说明这是设计选择。`NEEDS_HUMAN_REVIEW` 不触发状态流转,卡片保持 `draft` |

## Consequences(后果)

### 收益(吸收 A + B 级后)

1. **防注水**:C 级碎片自动走 short-form 模板,Generator 不强行扩写 → wiki 质量提升、可信度提升
2. **人工 trust 边界**:`workflow_state=verified` 的卡可直接被下游 agent 引用,`draft` 必须先过校验 → 降低"LLM 输出直接喂下游"的幻觉风险
3. **设计哲学一致**:所有吸收项都基于本项目"LLM-as-creator"哲学,不引入填空式模板冲突
4. **模板级可配置**:短内容阈值可通过 `template.json` 覆盖,未来新增场景模板时可按领域调整

### 成本(必须承担)

1. **`WikiPage` dataclass 改动**:`workflow_state` + `verified_at` + `processing_depth` 字段必须同步 `to_frontmatter_dict/from_dict`(AGENTS.md "Things to know before editing" #4)
2. **Pipeline 改动**:Collector 后插入 `detect_short_form()` 决策点;Generator 路由逻辑需读取 `processing_depth`
3. **新增模板**:`short-form.md` 通用精简模板 + Generator prompt 路由逻辑
4. **测试覆盖**:存量 7 个场景模板的 round-trip 不能受影响;边界值测试需覆盖
5. **文档同步**:`docs/webui-buttons.md` + WebUI 状态筛选 UI 必须同步(AGENTS.md "Things to know before editing" #1)

### 风险

1. **`workflow_state` 与 `grade` 语义重叠风险 → 通过字段名清晰区分:**`grade`=内容质量(谁写得好),`workflow_state`=生命周期(卡片的当前状态)
2. **存量卡片兼容**:未设 `workflow_state` 的旧卡视为 `draft`,不破坏现有 `lint`/`heat`/`zombie` 行为
3. **`processing_depth` 字段被 LLM 改坏 → `from_dict` 枚举校验 + `lint.py` 白名单双保险**

## Alternatives Considered(备选方案)

### 备选 A:全量吸收 LLM_KB 的 8 项设计

- ❌ 拒绝:7 项与现有架构冲突(命名空间、sentinel、模板锁死),会带来"两套机制并存"的维护负担

### 备选 B:完全不吸收,保持现状

- ❌ 拒绝:C 级碎片注水 + 无人工 trust 边界是两个 **真实缺口**,不补会持续产生低质量数据

### 备选 C:只吸收 `workflow_state`,不吸收 mini-wiki 兜底

- ⚠️ 不推荐:C 级注水问题影响面更广(markdown wiki 质量),人工核验是后置补丁。优先补前置分桶。

## Implementation Plan(实施计划)

实施以 **6 个 task** 落地,详见同目录下的 `2026-08-19-llm-kb-design-absorption.md`(plan 文件):

1. **Task 1**: `WikiPage` 加 `processing_depth` + `workflow_state` + `verified_at` 字段(round-trip 兼容 + 枚举校验)
2. **Task 2**: 短内容分桶决策函数 `detect_short_form()`(纯函数 + 边界值测试 + Unicode 扩展)
3. **Task 2.5**: Generator 路由逻辑(读取 `processing_depth` → 选择模板,plan-audit F1 整改)
4. **Task 2.6**: 创建 `short-form.md` 通用精简模板(plan-audit F2 整改)
5. **Task 3**: `workflow_state` 与 `ReviewerStage` 联动(RESOLVED → `verified` + capture mark-verify)
6. **Task 4**: WebUI 状态筛选 UI + 文档同步 + `lint.py` 白名单校验

## References(参考)

- 对比源:`D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\30_System\`(taxonomy.md / DESIGN_V2_OPTIMIZED.md / Templates/)
- 已有 plan:`docs/superpowers/plans/2026-08-19-capture-template-and-quick-entry.md`(capture 6 轮审查,部分设计参考)
- 已有命名空间:`src/wiki/features/tag_namespace.py`(12 个中文 prefix)
- AGENTS.md "Things to know before editing" #1 / #4
- plan-audit 第一轮审查记录(2026-08-19):`docs/superpowers/plans/2026-08-19-llm-kb-design-absorption.md` "审计追踪" 章节

## 决策记录更新

- 本 ADR 一旦 approved,写入 `docs/adr/INDEX.md`
- 实施完成后再补一份"实施后回溯"附录,记录实测成本/收益