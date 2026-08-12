# 知识库设计文档吸收与项目增量完善方案

> 日期：2026-08-12  
> 阶段：plan-audit 两轮通过，等待用户指令进入编码  
> 输入：用户提供的 9 份个人知识体系 / 摄取流程 / KOS 设计文档  
> 原则：迁移已有能力，补齐缺口；不把个人学习系统整体移植进工作 Wiki

## 1. 目标与边界

### 1.1 目标

把文档中对本项目真正有价值的部分收敛为四个项目能力：

1. 项目级受控分类：由项目中的 `taxonomy.md` 定义分类词表，摄取时重读并以文本注入 LLM；不在代码中切换提示词。
2. 原料分级与处理深度：在 LLM 之前完成确定性质量分流，并让概念型、记忆型、实操型内容有明确路由。
3. 质量闭环：保留低质量原料和候选，不静默丢弃；提供可追踪的等级日志、跳过原因和健康报告。
4. 模板/场景统一：现有 `source/entity/concept/synthesis` 模板作为通用知识库模板；场景模板可携带 schema、purpose、taxonomy 和页面模板。

### 1.2 明确不纳入本期

- `mastery`、`review_at`、`priority`、`value_score`、闪卡和个人复习日程。
- 自动 Curator 直接改写线上知识；任何改写先生成候选/评审项。
- 以单个 JSON 文件承载全量知识图谱、全量冲突检测和四图统一查询。
- 一次性把现有 WikiPage 重写成新的 KnowledgeObject 存储格式。
- 用 5 个个人固定领域替代所有项目分类；这些领域只作为个人场景模板的默认配置。

## 2. 现状对照结论

| 文档建议 | 当前项目状态 | 处理决定 |
|---|---|---|
| A/B/C 原料或页面等级 | `WikiPage.grade`、prefilter、C-grade handler、quality gate 已存在，但语义分散 | 统一为可追踪的 source triage 结果，保留兼容字段 |
| 处理深度 concept/memory/operation | 当前主要支持 concept/memory，内部还有 source/stub | 增加 operation 前先统一合法值、模板和回退规则 |
| taxonomy 受控词表 | 有 `category`/`taxonomy_sub` 和标签规则，但没有项目级 taxonomy 文本契约 | 新增轻量 TaxonomyRegistry，兼容旧页面空值 |
| schema/purpose 摄取注入 | 已有场景模板 loader 和注入链路 | 扩展场景模板资产，不另造 prompt 选择器 |
| export | 已有 ZIP 导出 | 增加导出事件日志，不改变导出格式 |
| content health | 已有基础 health/lint/relations/stubs/dedup 能力 | 增加聚合报告，复用现有检查，不新建重复扫描器 |
| 自动 Curator / 四图 / 自主进化 | 主要仍是方案文档，没有安全闭环 | 暂缓，先输出候选和报告 |

## 3. 目标边界与数据流

```text
项目模板
  ├─ schema.md       → SchemaRegistry → Analyzer/Generator 注入
  ├─ purpose.md      → Purpose 注入
  ├─ taxonomy.md     → TaxonomyRegistry → Analyzer/Generator 注入 + Writer 校验
  └─ .wiki-templates → 页面结构渲染

原始材料
  → deterministic triage (grade/action/reason)
  → source_only / reference_list / process / skip
  → Analyzer
  → Reviewer/QualityGate
  → WikiPage 原子写入
  → health/export/grade 日志
```

边界规则：

- LLM 只能从 `schema.md`、`purpose.md`、`taxonomy.md` 读取当前项目上下文；代码不根据场景切换一套提示词。
- taxonomy 校验只约束新生成或显式更新的页面；旧页面读取兼容，不强制回填。
- `skip` 必须持久化原因和原料标识，未来可重试；不能用“跳过”代替删除。
- health 报告是只读诊断；不自动修改页面，不自动提升等级。

## 4. 分段实施

### Phase 0：契约与兼容层

文件/模块方向：`src/templates/`、`src/wiki/`、`src/pipeline/`、项目初始化和模板文档。

- 为场景模板补齐可选 `taxonomy.md`，定义最小格式：一级分类、二级分类、别名和说明。首版只接受稳定的 Markdown heading 结构：`# Taxonomy`、`## 一级分类`、`- 二级分类（aliases: 别名1, 别名2）`；不执行其中的代码或 YAML。
- 新增 `TaxonomyRegistry`：读取项目文件、解析、返回注入文本和校验结果；文件不存在或格式无效时回退为空 registry 并记录 warning。
- 将 taxonomy 文本接入已有 schema/purpose 注入上下文；不新增按模板分支的 prompt 代码。
- 增加 taxonomy 校验的 warn/strict 开关，默认 warn，避免旧库无法继续摄取。
- 限制 taxonomy 文件大小和递归读取范围，只读取项目根目录的 `taxonomy.md`；strict 模式下解析错误、重复 canonical value 和未知二级分类阻止新页面写入，warn 模式只记录问题。

验收：新项目可读取 taxonomy；无 taxonomy 的旧项目行为不变；非法分类在 strict 模式阻止写入并留下可读错误。

### Phase 1：摄取分流统一

- 将现有 prefilter、sanitizer、C-grade 和 source-only 行为收敛成一个 `TriageResult` 契约。
- 记录 source id、grade、action、reason、规则版本和时间；日志写入项目 `.index`，不污染 WikiPage 正文。
- 明确默认回退：无法判断时 `process + grade=B`；空/明显占位材料 `skip`；低质量但有溯源价值的材料 `source_only + grade=C`。
- 保持现有 `source_grade` 兼容，不在本阶段重命名字段。
- `TriageResult` 只作为摄取任务元数据和日志契约；写入 WikiPage 时仍使用现有 `grade`/`source_grade` 字段，避免同一页面出现两个竞争真相源。

验收：每次摄取都有可查询的分流结果；重复摄取幂等；所有 skip/source_only 都能定位到源文件和原因。

### Phase 2：处理深度与通用模板

- 增加 `operation` 处理深度及通用实操卡模板，包含步骤、前置条件、验证、失败处理、踩坑和变更记录。`source` 和 `stub` 仍作为内部流水线状态保留，不作为 LLM 可选值；对外合法内容深度为 `concept|memory|operation`，旧 `source/stub` 页面继续兼容读取。
- 将“处理深度”作为内容路由和结构约束，不创建新的 PageType；无法识别时回退 `concept`。
- 更新 Analyzer/Generator 的 schema、验证器、Adapter 和旧页面兼容读取。
- 把 `source/entity/concept/synthesis` 现有页面模板作为通用知识库场景模板的标准资产。

验收：operation 页面可生成、读取、导出和重新摄取；旧 concept/memory/stub 页面不回归；LLM 不能修改受保护 frontmatter。

### Phase 3：健康报告与导出审计

- 新增只读 `content health` 聚合报告，复用现有 H1-H5、lint、relations、stubs、dedup 和 review 数据。
- 首版只输出：页面总量/等级/处理深度分布、孤立页、断链、stub/C 级趋势、待审核数、taxonomy 违规数、最近摄取失败数。
- 导出时追加 `export_log`，记录项目、输出文件、页面数量、schema/taxonomy 版本和时间。
- CLI/API 先提供 JSON 和人类可读文本，不引入后台 cron；后续由外部调度执行。
- 报告生成失败时不影响摄取和导出；单项检查失败以 `check_errors` 返回，退出码只在 CLI 的 `--strict` 下阻止自动化任务。

验收：报告不修改 Wiki；重复运行结果稳定；导出日志可用于追踪一次 ZIP 的内容范围。

## 5. 关键设计决策

1. **Taxonomy 是项目配置，不是全局枚举。** 不同场景可以有不同分类词表，模板只提供默认值。
2. **Schema/purpose/taxonomy 是注入文本的来源。** 它们影响 LLM 的行为，但不构成运行时 prompt 分支。
3. **质量等级和处理深度分离。** grade 表示原料/产出可信度，processing_depth 表示内容加工深度，不能互相推导。
4. **规则先于 LLM。** 原料分流、字段保护、taxonomy 校验和健康统计均由确定性代码完成。
5. **自动化只产出候选和报告。** 任何升级、合并、改写都必须走现有 review/atomic write 路径。
6. **阶段可回滚。** 每一阶段新增字段和文件都采用兼容读取；关闭开关时不改变旧摄取路径。

## 6. 需要在编码前确认的验收口径

- `taxonomy.md` 是否允许用户直接编辑：允许；项目启动/摄取时重新读取。
- taxonomy 严格校验默认值：推荐 `warn`，稳定运行后由项目自行切换 `strict`。
- operation 是否进入默认通用模板：推荐进入，但不把它设为所有场景必选。
- 健康报告是否自动定时运行：本期不内置调度，先提供 CLI/API。

## 7. 每阶段文件与测试边界

| 阶段 | 主要文件 | 必须新增/修改的测试 |
|---|---|---|
| Phase 0 | `src/templates/`、`src/wiki/`、注入上下文 | taxonomy 解析、别名、重复项、缺失文件、warn/strict、注入快照 |
| Phase 1 | `src/pipeline/`、`.index` 日志服务 | 四类 triage、幂等、异常落盘、旧 `source_grade` 兼容 |
| Phase 2 | `src/wiki/core/types.py`、generator、validator、模板 | operation 生成/读取/导出、旧 source/stub 读取、非法值回退 |
| Phase 3 | `src/maintenance/` 或既有 health service、export | 统计稳定性、单检查失败隔离、export_log 内容和重复导出 |

每个阶段完成后必须执行：目标测试、静态编译、`python -m src.cli serve --port <free>` 及 `/health` smoke test；测试环境不可用时必须记录阻塞原因，不能把静态通过当作功能验收。

## 8. 依赖与风险

- 当前工作区已有场景模板相关未提交改动，本方案只在其上增量扩展，不覆盖或重置。
- Python 测试运行环境目前不完整；编码阶段需先恢复可用测试解释器，至少完成静态编译、目标测试和 server `/health` smoke test。
- 个人知识体系文档的 5 域分类只进入 personal 场景默认 taxonomy，不改变 general/research/business 场景。
