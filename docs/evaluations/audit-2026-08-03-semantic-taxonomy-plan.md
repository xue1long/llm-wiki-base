# 独立审计报告：Semantic Taxonomy System 融合执行计划

> 审计日期：2026-08-03（v3，经二轮元审计修正）  
> 审计对象：`docs/superpowers/plans/2026-08-03-semantic-taxonomy-execution.md`  
> 审计立场：独立第三方，批判性审查  
> 修正记录：v1 F1/F2/F3 严重程度偏高；v2 修正分级+补充3个遗漏；v3 F2代码实证推翻、F1分析细化、新增2遗漏、删除A1

---

## 0. 审计结论速览

| 分类 | 数量 | 最严重项 |
|------|------|---------|
| ① 致命缺陷 | **1** | MANDATORY_PAIRS 迁移逻辑歧义（analyzer侧硬编码未处理） |
| ② 重大隐患 | **10** | ReviewerStage语义适配、tag store存储格式、标注成本、并发安全… |
| ③ 优化疏漏 | **10** | 阈值无实证、observability缺失、值域校验历史兼容、analyzer硬编码… |

**总评：方案方向正确。1个致命缺陷阻塞P0执行，10个重大隐患影响P1-P3落地可靠性。致命缺陷修复成本低（让analyzer也用`build_tag_prompt_section()`+方案文本澄清），不涉及架构变更。**

---

## 1. ① 致命缺陷（方案不可落地）

### F1. MANDATORY_PAIRS 迁移逻辑歧义 — analyzer侧硬编码未纳入迁移范围

**漏洞位置：** Phase 0 任务 0.4 — "UGC 强制标签配对从 analyzer/generator 提示词移到 MANDATORY_PAIRS 配置"

**现状（经代码验证）：**

- **Generator** 已通过 `TAG_NAMESPACE_RULES = build_tag_prompt_section()`（`generator.py:44`）动态读取 `MANDATORY_PAIRS`，注入全部 7 个 prompt 模板。把 UGC 配对加入 `MANDATORY_PAIRS` 后，generator **自动**获得引导。✅
- **Analyzer**（`analyzer.py:46-58`）硬编码了 10 个前缀 + UGC 配对规则。**不使用** `build_tag_prompt_section()`。❌

**风险后果：**

"移到配置"有两种解读：
- **解读 A（正确）：** Analyzer 也改用 `build_tag_prompt_section()` → 提示词自动从 MANDATORY_PAIRS 生成 guidance → LLM 仍被引导产出配对标签 + 写入时防御性校验
- **解读 B（有问题）：** 仅从 analyzer 删除硬编码引导、加入 MANDATORY_PAIRS，但 analyzer 不使用动态生成函数 → analyzer **丢失** UGC 引导。Generator 侧 `TAG_NAMESPACE_RULES` 仍会提供引导，但 analyzer 是 tags 首次赋值点，丢失引导意味着 LLM 在 analyzer 阶段不产出配对标签，依赖 generator 事后修正。

解读 B 不是 v1/v2 声称的"系统性写入失败"（generator 兜底 + 写入校验可捕获），但会导致：analyzer 产出不完整 → generator 额外 LLM 调用修正 → token 浪费 + 质量下降。

**注意：** v2 审计未区分 generator（已动态化）和 analyzer（硬编码），笼统说"提示词改为从配置动态生成"。实际 generator 不需要改，analyzer 需要改。

**整改建议：**
```
P0.4 分三步：
  Step 1: 让 analyzer 也使用 build_tag_prompt_section()（替换 analyzer.py:46-58 硬编码 tag 规则）
  Step 2: 将 ("素材","ugc") 和 ("可信度","ugc") 加入 MANDATORY_PAIRS
  Step 3: 删除 analyzer.py 和 generator.py 中的硬编码 UGC 引导文本
  Step 4: write_page 加 missing_mandatory_tags() 防御性校验（与 P0.3 的 validate_tag_values() 一起接入）
```

**严重性：致命。方案未识别 generator/analyzer 在 tag prompt 机制上的不对称，歧义可能导致执行者只改 MANDATORY_PAIRS 而忽略 analyzer 硬编码。**

---

## 2. ② 重大隐患（在特定条件下失败）

### H1. ReviewerStage 语义适配风险 — 不经适配用于 tag 场景可能失败

**漏洞位置：** Phase 2 任务 2.3 — "LLM 提取新概念 → `KnowledgeCandidate` → 复用 `ReviewerStage`"

**风险后果：**
`ReviewerStage` 的四个检查是为 source page 设计的：
- `_check_schema`: 检查 `source_id`、`title` 等字段 — tag candidate 的 schema 不同，这些字段可能不存在
- `_check_evidence`: 检查 `claims[].evidence_refs` 边界 — tag candidate 的 claims 结构未定义
- `_check_references`: 检查 evidence 的 `source_path` 指向真实文件 — tag candidate 的 evidence 可能是"引用该 tag 的文档列表"，语义不同
- `_check_confidence`: 较通用，可能可直接复用

**注意：** v1 审计断言 ReviewerStage 会"必然崩溃"是过度推理。tag candidate schema 尚未定义，设计者可能使其与 ReviewerStage 兼容。实际风险是**语义漂移**而非**类型崩溃**——检查会通过但检查的内容不对。

**整改建议：**
- 定义 TagCandidate schema 后，逐项对照 ReviewerStage 四个检查，标记哪些可直接复用、哪些需适配、哪些需跳过
- 如有 ≥2 个检查需要跳过，则值得写独立的 `TaxonomyReviewer`

**严重性：重大隐患。取决于 tag candidate schema 的最终设计。**

---

### H2. Tag store 存储格式未指定 — 选错实现可能导致性能/一致性问题

**漏洞位置：** Phase 2 任务 2.1 — "基于 file/JSONL 存储（PG 可选）"

**风险后果：**
"file/JSONL" 是模糊描述，有多种实现路径：
- 独立 JSON 文件 per entity（覆盖写入）→ 无问题
- 单文件 JSON 对象（`safe_write` 原子覆盖）→ 1000 个 tag × 500 bytes = 500KB，性能可接受
- JSONL append-only（复用 `event_store.py` 模式）→ tag 实体需改名/合并/废弃，append-only 无法原地更新

JSONL 仅应用作审计日志（记录变更事件），不作为真相源。

**注意：** v1 审计断言"使用 JSONL 必然失败"是错误的——方案未指定复用 `event_store.py`，tag store 是新建模块。但 v2 的"推荐独立 JSON 文件"建议不够具体，缺少 tag_id 格式、CJK 文件名兼容性说明。

**整改建议：**
- P2.1 明确存储格式：`tag_entities/{tag_id}.json`（独立 JSON 文件，更新时原子覆盖写入）
- `tag_id` 使用 `namespace` + `value` 的规范化 slug（非 hash，人类可读）
- JSONL 仅用作审计日志（append-only，记录所有变更事件），不作为真相源
- 此前建议的 SQLite 方案会引入 schema migration 需求，与 H5 冲突，撤回

**严重性：重大隐患。取决于执行者的实现选择。**

---

### H3. LLM 分类质量基准测试 — 标注成本未被承认

**漏洞位置：** Phase 2 任务 2.2 — "跑 20 篇不同题材文档，统计精确率/召回率/粒度一致性"

**风险后果：**
精确率/召回率需要 ground truth——人工标注"这 20 篇文档应该产出哪些概念"。谁来做标注？标注 20 篇文档的概念需要网文写作领域专业知识，工作量 ≥1 人天。方案完全不提标注资源。如果开发者自己标注，标注质量不可信（既是裁判又是运动员）。如果找不到标注人，质量门禁形同虚设。

**整改建议：**
- 2.2 拆为两个子任务：
  - 2.2a：标注（1-2d）— 从 1358 文档中选 20 篇（每题材 ≥2 篇，含长短文档），由有网文写作经验的人标注 ground truth
  - 2.2b：评估（0.5d）— 跑 LLM + 统计指标
- 工期从 1d → 2.5d（含标注等待）
- 降级方案：如果找不到标注人，改为"人工复查 LLM 产出"（只判断产出是否合理，不统计召回率）

**严重性：重大隐患。找不到标注人则质量门禁不可操作。**

---

### H4. KO.tags 与 WikiPage.tags 关系未定义

**漏洞位置：** Phase 1 任务 1.1 — KO 增加 `tags: list[TagReference]`

**风险后果：**
两者类型不同（`TagReference` vs `str`）。方案未定义转换关系。

**补充分析（v3修正）：** P1.1 只是给 KO dataclass 加一个字段——纯数据结构变更，不依赖 KO↔WikiPage 关系。序列化/反序列化问题影响的是 P1.3（检索消费 tags）+ Writer pipeline（KO→WikiPage 写入时 TagReference→str 转换），不影响 P1.1 本身。

**整改建议：**
- P1.1 可正常启动（加字段+向后兼容 from_dict）
- P1.3 启动前确认：`WikiPage.tags: list[str]` 保留为人类可读格式（`namespace:value`），`KO.tags: list[TagReference]` 通过 `to_tag_string()` 派生 WikiPage.tags
- 如果 KO 无独立持久化路径（仅 WikiPage 持久化），则是纯序列化问题，不涉及双写

**严重性：重大隐患。影响 P1.3+Writer 实现，不阻塞 P1.1。**

---

### H5. 无恢复/回滚/迁移策略

**漏洞位置：** 全文

**风险后果：**
- tag store 文件损坏 → 所有 tag 丢失，恢复路径未定义
- 规则引擎 yaml 写错 → tag 写入系统性失败，回滚路径未定义
- alias 自动合并误操作 → `/unmerge` API 提到了但未定义级联行为

**整改建议：**
- 每个 Phase 增加"回滚与恢复"段落
- Tag store 启动时做完整性检查，损坏时从审计日志重建
- 所有自动合并操作写入 undo 日志

**严重性：重大隐患。系统无灾备能力。**

---

### H6. 并发安全未考虑

**漏洞位置：** P2.1 (tag store) + P2.3 (TaxonomySync 挂摄取末段)

**风险后果：**
压力测试显示队列可 6 并发。2 个文档同时完成摄取 → 2 个 TaxonomySync 同时写 tag store：
- 同一 tag candidate 被重复创建（无 idempotency 检查）
- `tag_relations` 的边被并发修改导致不一致

**整改建议：**
- Tag store 写入操作使用项目已有的 `AtomicContext` 或 `threading.Lock`
- Tag candidate 创建前做 idempotency 检查（`concept_name + namespace` hash）
- P1 阶段添加并发写入测试用例

**严重性：重大隐患。并发下数据不一致风险高。**

---

### H7. LLM Provider 单点依赖

**漏洞位置：** 全方案隐式假设

**风险后果：**
当前运行环境：openai unreachable, ollama 502, minimax 唯一在线。如果 minimax 宕机，所有 LLM 调用（摄取 + 分类 + 相似度判断）全部中断。

**整改建议：**
- P2 启动前完成 provider fallback 配置（minimax 超时 → 降级为 stub 模式或排队等待）
- 作为独立运维任务，不挂靠任何 Phase

**严重性：重大隐患。但不应阻塞 P0-P1。**

---

### H8. Phase 3 Gate 阈值无依据

**漏洞位置：** Phase 3 前置 Gate — "≥50 approved tag_entities" + "稳定运行 ≥1 周，alias 误合并率 <5%"

**风险后果：**
如自生长质量一般、审核速度慢，每周可能只有 2-3 个 approved。50 个目标需 4-6 个月。"稳定运行 ≥1 周"过于主观——如果那周恰好没有新文档摄入，如何判断稳定性？

**注意：** v2 审计说"方案没有定义出口"——不准确。方案 R2 已定义"LLM 分类质量不达标→退化为人工分类模式，不自生长"。P2.2 质量门禁失败是有出口的。本隐患针对的是"质量通过但审核慢"的场景。

**整改建议：**
- 将"稳定运行 ≥1 周"改为"≥50 次审核操作"（更客观、可加速）
- 增加降级路径："若 4 周内未达 50 approved，Gate 自动转为人工决策：是否接受部分图整合（仅用已 approved tag 构建子图）"

**严重性：重大隐患。P3 可能因审核带宽不足而无限期推迟。**

---

### H9. 关系索引接入的原子性 — 需代码验证

**漏洞位置：** P1.2 — "关系索引接入摄取末段"

**风险后果：**
`write_page` 走 `safe_write` → `AtomicContext` 事务性写入。如果 `write_outgoing`/`write_backlinks` 不在同一个 `AtomicContext` 内，部分成功场景会出现 wiki 页面已写入但索引缺失（或相反）。

**注意：** v1 断言此问题一定存在——在未读 `relation_index.py` 实际代码的情况下预判了最坏情况。应在 P1.2 启动前抽查 `write_outgoing` 是否使用了 `safe_write`。

**整改建议：**
- P1.2 启动前：读 `relation_index.py` 源码，确认写入方式
- 如果独立 `safe_write`：改为纳入 `write_page` 的 `AtomicContext`

**严重性：重大隐患（待代码验证后可能降级为无风险）。**

---

### H10. 验收标准未按文档特征分层

**漏洞位置：** P0.5 验收标准 — "10 文档 ≥8 非 stub"

**风险后果：**
压力测试显示短文档可能触发 `confidence < 0.5` 阈值。如果 10 个验证文档中有 3 个短文档，达标压力大。方案未区分文档长度。

**注意：** v1 批评方案"1 个文档验证就断定修复完成"不准确——方案确实包含 10 文档验证步骤（P0.5）。核心问题是验收阈值未分层。

**整改建议：**
- 短文档 (<500 字) ≥60% 非 stub
- 中文档 (500-5000) ≥80%
- 长文档 (>5000) ≥90%

**严重性：重大隐患。验收标准粒度不足。**

---

### H11. 隐含假设：人工审核者存在且可用

**漏洞位置：** P2.4 审核 API (`approve/reject/merge`)

**风险后果：**
整个自生长流程依赖人工审核。但方案未定义审核者是谁、SLA 是什么、审核队列积压时怎么办。如果审核者不响应，tag candidate 堆积，自生长停摆。

**整改建议：**
- 明确审核者角色（管理员？领域专家？Agent？）
- 定义 SLA（如 48h 内审核）
- 超时降级策略：超时自动 reject 但保留 candidate 可复活（reject-safe）

**严重性：重大隐患。人工环节是自生长流程中最脆弱的节点。**

---

## 3. ③ 优化疏漏

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| **O1** | 相似度阈值 0.95/0.85 无实证依据 | P2.4 | 在 2.2 基准测试中增加"同义/近义/不相关"的 embedding 距离分布统计，根据实测设定阈值 |
| **O2** | 无 observability | 全方案 | 每个 Phase 增加 metrics 产出物（tag 数量趋势、审核队列深度、alias 合并率……） |
| **O3** | `degradation_counter` 阈值 5 无依据 | P1.4 | 基于历史 stub 分布计算动态阈值 |
| **O4** | Tag store per-project vs global 未定义 | P2.1 | Novel-wiki 和 perf-test 是否共享 namespace？明确边界 |
| **O5** | 20 篇基准测试文档的代表性 | P2.2 | 指定选文策略：每题材 ≥2 篇，含长短文档，含纯中文和混合格式 |
| **O6** | `from_dict` 向后兼容 scope 太模糊 | P1.1 | 列出旧 schema → 新 schema 迁移路径，写兼容性测试 |
| **O7** | 缺少"不做 STS"的对比基线 | 全文 | 增加 §0：维持现状 3 个月的预期状态，衡量方案增量价值 |
| **O8** | 从零执行需补充服务器重启步骤 | P0.1→0.2 | 0.1 标 "done" 反映现状正确，但若从零执行需在 0.2 前加重启+单文档烟雾测试 |
| **O9** | P0.3 值域校验历史标签兼容 — 1页需修复 | P0.3 | 实测 748 页面中仅 1 页有非空且不合规 tags（`['教程','转录','人物描写']`），P0.3 前手动修复即可，无需扫描脚本（v2→v3 降级，原 F2） |
| **O10** | "全量回归"含义歧义 | P0.5 | "全量回归"应明确指 pytest 全量测试，非全量重摄取 748 文档（后者会导致 token 成本爆炸） |

---

## 4. 隐含假设穷举

| # | 隐含假设 | 不确定性 | 原因 |
|---|---------|---------|------|
| A1 | LLM API 持续可用 | **高** | 3 个 provider 中只有 1 个在线 |
| A2 | 人工审核者存在且可用 | **高** | 方案从未定义审核者是谁、SLA 是什么（见 H11） |
| A3 | embedding 模型对中文分类词有合理区分度 | **中** | 未验证。中文近义词/上下位词 embedding 行为未知 |
| A4 | 30 个 stub 代表全部失败模式 | **中** | 30 个文档全部来自同一来源（飞书云文档），可能有系统性偏见 |
| A5 | LanceDB metadata filter 延迟可接受 | **中** | 未实测。1358 文档 × 平均 5 tag = 6790 条目 |
| A6 | Tag store 执行者不会选错存储实现 | **中** | "file/JSONL" 歧义，取决于执行者选择（见 H2） |
| A7 | 开发者有网文写作领域知识做标注 | **高** | 标注 tag ground truth 需要领域专业知识（见 H3） |
| A8 | WikiPage 和 KO 的关系是序列化/反序列化 | **中** | 需代码验证（见 H4）；如果 KO 有独立持久化路径则是双写问题 |

**已删除：** v2 的 A1（"reviewer bug 是唯一失败原因"）——方案 R5 明确写"P0 修复后管线仍有残余 bug"，此假设不成立。

---

## 5. 异常场景/边缘情况清单

1. 摄取文档中 LLM 返回 0 个 candidate → TaxonomySync 空跑（应记录而非报错）
2. 两个 TagCandidate 的 embedding 完全相同 → 自动合并是否合理？
3. 同一文档重复摄取 → TagCandidate 去重逻辑在哪？
4. Namespace 被删除 → 孤儿 tag 引用（WikiPage.tags 仍含已删除 namespace 的 tag）
5. Tag store 文件损坏 → 重启时 crash 还是降级？
6. 标签值域变更（新增值 / 删除值）→ 历史文档迁移策略未定义
7. 相似度检查时 embedding provider 超时 → 降级跳过还是阻塞摄取？
8. `/unmerge` 后，已用被合并 tag 的页面需要级联更新吗？
9. 检索 `taxonomy_filters` 指定不存在的 namespace → 返回空还是报错？
10. Perf-test 项目不需要 taxonomy → KO tags 字段为 null 还是空列表？
11. 文档从项目 A 移动到项目 B → tag 引用是否跟随？
12. LLM 产出一个已 deprecated 的 tag 的 candidate → 跳过还是重新激活？
13. wiki 页面含裸字符串 tags（如 `['教程','转录','人物描写']`）→ 经实测仅 1 页，P0.3 前手动修复

---

## 6. 方案积极方面（完整审计不应只批判）

- ✅ P0.1 reviewer 修复已实施并端到端验证（非纸上谈兵）
- ✅ PG 风险已被正确识别并降级为可选后端（STS 可行性评估的核心贡献）
- ✅ 复用优先策略（Candidate/Lifecycle/GraphBuilder/Conflicts 全部复用，不做平行重建）
- ✅ P2.2 质量门禁机制（虽然标注资源未定义，但门禁这个思路是正确的）
- ✅ 相似度合并的可逆设计（`/unmerge` API）
- ✅ 检索集成优先的策略（投入产出比最高）
- ✅ Generator 已通过 `TAG_NAMESPACE_RULES` 动态读取 MANDATORY_PAIRS——P0.4 对此组件是零代码变更

---

## 7. 整改优先级

```
必须在 P0 启动前修复（否则 P0 自身有缺陷）：
  F1: P0.4 — Analyzer 改用 build_tag_prompt_section() + MANDATORY_PAIRS 三步迁移
  O9: P0.3 前手动修复唯一不合规页面

必须在 P1 启动前澄清（否则 P1 架构决策悬空）：
  H4: KO.tags ↔ WikiPage.tags 序列化/反序列化路径确认
  H9: relation_index.py 写入方式代码验证

必须在 P2 启动前解决（否则 P2 不可落地）：
  H1: TagCandidate schema + ReviewerStage 适配方案
  H2: Tag store 存储格式明确（推荐独立 JSON 文件 per entity）
  H3: 2.2 标注资源确认（找不到标注人则启动降级方案）
  H6: Tag store 并发安全

P3 之前解决：
  H8: Gate 增加降级出口 + 阈值客观化

持续改进（基础设施/运维，不阻塞任何 Phase）：
  H5: 恢复/回滚/迁移策略
  H7: LLM provider 容灾
  H10: 验收标准分层
  H11: 审核者 SLA 定义
  O1-O8, O10: 阈值调优、observability、基线对比……
```
