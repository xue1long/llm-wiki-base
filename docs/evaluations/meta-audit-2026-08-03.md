# 审计的审计 v2 — 对 semantic-taxonomy-plan 审计报告的二次自我审查

> 审查对象：`docs/evaluations/audit-2026-08-03-semantic-taxonomy-plan.md` (v2)  
> 审查者：同一审计者，切换为反向立场  
> 方法论：逐条验证事实准确性 + 代码实证 + 检查推理链路 + 暴露自我矛盾

---

## v2 变更记录

| 版本 | 日期 | 主要修正 |
|------|------|---------|
| v1 | 2026-08-03 | 初版：4致命→修正为1致命，发现3个遗漏 |
| **v2** | 2026-08-03 | 二次审查：F2代码实证推翻、A1不准确、新遗漏2个、F1分析不完整 |

---

## 0. 总体判断

v2审计报告相比v1大幅改善，但**仍有一处严重程度被代码实证推翻**：

| 发现 | v2标注 | 代码实证 | 实际应为 | 原因 |
|------|--------|---------|---------|------|
| F2 (P0.3历史数据兼容) | 致命 | **不成立** | **优化疏漏** | 实测748页面中747个tags为空，仅1个有裸字符串tags |
| A1 (reviewer是唯一失败原因) | 高不确定性 | **不成立** | **删除** | 方案R5明确写了"P0修复后管线仍有残余bug" |
| F1 (MANDATORY_PAIRS歧义) | 致命 | **成立但分析不完整** | **致命** ✅ | generator已有TAG_NAMESPACE_RULES自动读取MANDATORY_PAIRS，但analyzer硬编码——审计未区分两者 |

**修正后：1 致命、10 重大隐患、10 优化疏漏。新增 2 个遗漏发现。**

---

## 1. F2 代码实证推翻 — "748个页面"说法不成立

### 原始断言

> "当前有 748 个已有 wiki 页面。如果其中存在不符合 TAG_VALUES 值域的历史标签……任何触发这些页面重新写入的操作都会因 TagValidationError 而失败。"

### 代码实证

```bash
$ grep -rh "^tags:" wiki/sources/ wiki/entities/ wiki/concepts/ wiki/synthesis/ \
  | grep -v "tags: \[\]" | grep -v "tags: $" | sort -u
tags:
tags: ['教程', '转录', '人物描写']
```

**实测结论：**
- ~747 个页面 tags 为空（YAML null 或 `[]`）。`validate_tag_values([])` 返回 `[]`，直接通过。
- **仅 1 个页面**（`2-刻画人物形象之语言动作描写第-2-段-94eb302e.md`）有非空 tags：`['教程', '转录', '人物描写']`
- 这 3 个 tag 是**裸字符串**（无 `prefix/` 格式），确实会触发 `TagValidationError`——但影响范围是 **1/748**，不是 748/748。

### 为什么犯了"748页"的错误

我**假设了历史标签违规普遍存在**，没有去验证。正确的审计流程应该是：
1. 写一个扫描脚本
2. 实际跑在 knowledge/novel-wiki 上
3. 基于实际数据判断严重度

我跳过了第2步，直接基于假设下了"致命"结论。

### 修正

**降为优化疏漏（O9）。** 1 个不合规页面可在 P0.3 前手动修复（改 tags 为合规格式或清空），成本=30秒。

重新表述为：P0.3 前扫描全部 wiki 页面确认无不合规 tags（1分钟脚本），如有则一次性修复。不建议为此加 `strict` 参数——增加代码复杂度但只解决 1 个页面的问题。

---

## 2. F1 分析不完整 — 未区分 generator 和 analyzer

### 问题

v2 审计 F1 说"提示词改为从 MANDATORY_PAIRS 配置动态生成 guidance"。但未识别：

- **Generator 已经做到了。** `generator.py:44` 的 `TAG_NAMESPACE_RULES = build_tag_prompt_section()` 在模块加载时读取 `MANDATORY_PAIRS`，并注入到全部 7 个 prompt 模板中。如果把 UGC 配对加入 `MANDATORY_PAIRS`，generator 的 prompt 会自动包含它们。
- **Analyzer 没有。** `analyzer.py:46-58` 硬编码了 10 个前缀 + UGC 配对规则。`build_tag_prompt_section()` 没有被 analyzer 使用。如果 P0.4 从 analyzer 删除硬编码引导但不补偿，analyzer 会失去 tag 引导。

### 为什么重要

审计的"解读 B（致命）"场景需要修正：

- **Generator 侧**：即使执行者选择了"解读 B"（删除硬编码引导），generator 仍通过 `TAG_NAMESPACE_RULES` 获得 MANDATORY_PAIRS 引导。不会完全丢失。
- **Analyzer 侧**：确实会丢失引导——因为 analyzer 不使用 `build_tag_prompt_section()`。但 analyzer 的 tag 产出是"建议页的 tags 字段"，不是最终写入。generator 会补充/修正。
- **实际的最坏情况**：analyzer 不产出 UGC tags → generator 的 TAG_NAMESPACE_RULES 引导 LLM 补充 → 写入时校验兜底。**不是系统性失败，而是多了一层 LLM 修正。**

### 修正

F1 仍保持"致命"——因为方案文本歧义真实存在，且 analyzer 侧确实有硬编码需处理。但风险后果描述需修正：最坏情况不是"系统性写入失败"，而是"analyzer 丢失 tag 引导，依赖 generator + 写入校验兜底，LLM token 浪费 + 质量下降"。

**整改建议需要更精确**：不是泛泛的"分两步"，而是：
1. 让 analyzer 也使用 `build_tag_prompt_section()`（替换硬编码 tag 规则）
2. 将 UGC 配对加入 `MANDATORY_PAIRS`
3. 删除 analyzer.py 和 generator.py 中的硬编码 UGC 引导
4. write_page 加 `missing_mandatory_tags()` 防御性校验

---

## 3. A1 与方案原文矛盾

### 问题

审计隐含假设表 A1：

> "reviewer bug 是管线唯一失败原因" | 不确定性：**高** | "只验证了 1 个文档。stress test 中有 3.3% confidence 失败"

但方案 R5 明确写：

> "P0 修复后管线仍有残余 bug | P0 | 低 | 高 | 0.5 全量回归 + 10 文档验证"

方案**已经承认可能有残余 bug**，并计划用 0.5 验证。审计 A1 与方案原文矛盾。

### 修正

**删除 A1**。方案未假设 reviewer bug 是唯一失败原因。

---

## 4. H8 — 方案已定义质量门禁失败出口

### 问题

审计 H8 说：

> "如果 P2.2 质量门禁不过、自生长直接关闭，**50 个永远达不到**——方案没有定义出口。"

但方案风险 R2 明确写：

> "LLM 分类质量不达标（2.2 gate 不过）| P2 | 中 | 高 | **退化为人工分类模式，不自生长**"

方案已经定义了出口。H8 的"50个可能达不到"仍然有效（质量通过但产出慢的情况），但"没有定义出口"不准确。

### 修正

H8 保留为重大隐患，但删除"方案没有定义出口"的批评。重新聚焦在"50 的阈值无依据"和"稳定运行≥1周太主观"。

---

## 5. 新遗漏发现（本轮补充）

### M4. Analyzer 不使用 `build_tag_prompt_section()`

**遗漏内容：** Generator 已通过 `TAG_NAMESPACE_RULES = build_tag_prompt_section()` 动态读取 MANDATORY_PAIRS。但 Analyzer（`analyzer.py:46-58`）将 10 个前缀 + UGC 配对**硬编码在 prompt 字符串中**。这意味着：

- TAG_VALUES 变更时，analyzer prompt 不会自动更新
- P0.4 将 UGC 配对移到 MANDATORY_PAIRS 后，analyzer 的硬编码引导与配置不同步
- 存在两份 tag 规则（analyzer 硬编码 + tag_namespace.py），违反 DRY

**整改：** P0.4 应包括让 analyzer 也使用 `build_tag_prompt_section()`，实现单一真相源。

### M5. write_page 缺少 mandatory_pairs 校验

**遗漏内容：** P0.3 计划接入 `validate_tag_values()`（值域校验），但 P0.4 将 UGC 配对移到 MANDATORY_PAIRS 后，写入路径还需校验**配对完整性**。`missing_mandatory_tags()` 已存在于 `tag_namespace.py:111`，但未被任何写入路径调用。

**整改：** P0.4 的 Step B（write_page 防御性校验）应同时包含 `validate_tag_values()` + `missing_mandatory_tags()`，或在 P0.3 统一接入两个校验。

---

## 6. v2 审计中仍然存在的其他小问题

### 6.1 H4 "P1.1 无法正确实现"过度陈述

审计 H4 说"关系不澄清则 P1.1 无法正确实现"。P1.1 只是给 KO dataclass 加一个 `tags: list[TagReference]` 字段——这是纯数据结构变更，不依赖 KO↔WikiPage 关系。序列化问题影响 P1.3（检索）+ Writer pipeline，不影响 P1.1。

H4 保留但修改 urgency 声明：从"P1.1 无法实现"改为"P1.3+Writer 有序列化风险"。

### 6.2 H2 建议中的存储格式推荐不够具体

H2 推荐"独立 JSON 文件（`tag_entities/{tag_id}.json`）"。但没有说明：
- tag_id 的格式（hash？human-readable slug？）
- 文件名编码（CJK tag 名称直接做文件名？）
- 跨 platform 兼容性

补充到 H2 整改建议中。

### 6.3 审计风格：P0.5 "全量回归"的解读

审计未质疑"全量回归"的具体含义。执行计划 P0.5 写"全量回归 + 随机 10 文档摄取验证"，验收标准"回归全绿（扣除预存 6 个失败），10 文档 ≥8 非 stub"。这里的"全量回归"应该是指 pytest 全量测试，不是"重摄取全部 748 文档"。如果执行者理解为后者，会出现 token 成本爆炸。审计应增加这个澄清。

---

## 7. 修正后的审计发现分级（建议版）

### 致命缺陷 (1)
- **F1** (保持): MANDATORY_PAIRS 迁移逻辑歧义——但改写风险后果（见 §2）

### 重大隐患 (10)
- H1-H12 中合并/调整：
  - H1: ReviewerStage 语义适配风险
  - H2: Tag store 存储格式未指定
  - H3: 标注成本未被承认
  - H4: KO.tags ↔ WikiPage.tags 关系未定义（降 urgency，不影响 P1.1 字段添加）
  - H5: 无恢复/回滚/迁移策略
  - H6: 并发安全未考虑
  - H7: LLM provider 容灾策略缺失
  - H8: Gate 阈值无依据（删除"未定义出口"，方案 R2 已定义）
  - H9: 关系索引原子性需代码验证
  - H11: 人工审核者角色未定义

### 优化疏漏 (10)
- F2' (ex-F2): P0.3 历史标签兼容 — 降级（实测仅 1 页违规）
- H10: 验收标准未按文档特征分层
- O1-O8 (原 8 项)
- **M4** (新增): Analyzer 未使用 build_tag_prompt_section()
- **M5** (新增): write_page 缺少 mandatory_pairs 校验
- **O9** (新增): "全量回归"含义需澄清（pytest vs 全量重摄取）

---

## 8. 审计方法论的改进（本次学到的）

### 这次暴露的问题模式

| 错误类型 | 实例 | 根因 |
|---------|------|------|
| **未验证的数值声称** | F2 "748个页面有风险" | 假设数据而非实测 |
| **未区分系统组件差异** | F1 未区分 generator vs analyzer | 把两个组件当作同构 |
| **与方案原文矛盾的声称** | A1 + H8 | 未逐字对照方案风险矩阵 |

### 改进规则

1. **数值声称必须有实证。** 说"N个页面有问题"，先去 grep 验证。
2. **区分同类组件的差异。** Generator 和 Analyzer 都是 prompt，但一个用 `build_tag_prompt_section()` 一个不用。
3. **批评前先检查方案是否已经说了同样的话。** 方案的风险矩阵是审计必读项。
4. **严重程度判断前先评估 blast radius。** 1/748 的问题不应标"致命"。
