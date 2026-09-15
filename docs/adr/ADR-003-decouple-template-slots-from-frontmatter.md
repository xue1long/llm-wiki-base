# ADR-003: 解耦模板槽位与 Frontmatter 字段

Status: accepted

Date: 2026-09-11

## Context

novel-wiki 当前的 4 个 wiki 模板（`.wiki-templates/{source,entity,concept,synthesis}.md`，版本号 v3.0.0）把 **Markdown 正文结构（h2 标题 = 槽位）** 与 **frontmatter 字段（id/title/type/sources/created_at/updated_at/relations/tags）** 这两件事绑在一起。

后果：
1. **改槽位 = 改字段**：想在 `concept` 模板加 `## 适用阶段`，要么落到 frontmatter（污染白名单），要么放在 body（无法被机器检索）。
2. **template_version 与 schema_version 平行存在**：模板 v3.0.0 / frontmatter V4 / Schema 5.0.0——三套版本号各管各的，谁也不知道以谁为准。
3. **slot:xxx 注释只给人看**：`<!-- slot:definition -->` 在 LLM 生成时容易被吞掉/复制粘贴丢，机器解析要重写一套 YAML。
4. **lint 没法强制槽位顺序/必填**：因为槽位是 Markdown 而不是结构化数据。

## Decision

**模板槽位（body 结构指导）和 frontmatter 字段（结构化元数据）彻底解耦**，分别走两套规则：

| 维度 | Frontmatter | 模板槽位 |
|---|---|---|
| 存储位置 | YAML 顶部 `---` 块 | YAML frontmatter 之后的 body 之前 |
| 表征形式 | 字段名 → 值（列表/标量） | 槽位名 → Markdown 内容 |
| 版本号 | `NOVEL_WIKI_FIELD_SCHEMA_VERSION` (V6) | `novel-wiki-template-version` (v4.0.0 起) |
| 校验工具 | `scripts/validate_novel_wiki_frontmatter.py` | `scripts/validate_novel_wiki_template_slots.py` |
| 变更流程 | RFC + ADR | 模板目录 RFC |
| 是否计入严格白名单 | ✅ V6 18 键白名单 | ❌ 不进白名单 |
| 机器可解析 | ✅ YAML 原生 | ✅ 通过文件级索引文件 `.wiki-templates/index.yaml` 注册 |

### 槽位声明格式（嵌在 frontmatter 之后、body 之前）

```markdown
---
id: kai-pian-xie-fa
type: concept
title: 开篇写法
sources: [raw/sources/...]
created_at: 2026-09-11T10:00:00
updated_at: 2026-09-11T10:00:00
relations: [...]
tags: []
template: concept
template_version: "4.0.0"
---

<!-- template-slots: 4.0.0 -->
<!-- required: [definition, context, anti_patterns, references] -->
<!-- optional: [examples, related_concepts, evidence] -->

## 定义

(slot:definition)

## 适用阶段

(slot:stage)  <!-- 新增槽位 -->

## 适用场景

(slot:context)
...
```

### 槽位索引文件 `.wiki-templates/index.yaml`

```yaml
template_version: "4.0.0"
schema_version: "6.0.0"
templates:
  concept:
    required_slots: [definition, stage, context, anti_patterns, references]
    optional_slots: [examples, related_concepts, evidence]
    min_references: 1   # lint 强制 ≥1 条 source
    min_relations: 2    # lint 强制 ≥2 条 relations
  entity:
    required_slots: [basic_info, summary, craft_value]
    optional_slots: [aliases]
  ...
relations:
  builtin:
    - taxonomy_of
    - references
    - referenced_by
    - is_part_of
    - supported_by
    - caused_by
    - x-*
  rejected_v6:    # 14 个低频关系显式标注 deprecated
    - contains
    - supersedes
    - ...
```

### 写盘合同

```python
# 旧 (V6)
write_page(paths, WikiPage(id=..., relations=[...]))

# 新 (V7)
write_page(
    paths,
    WikiPage(id=..., relations=[...]),
    template="concept",
    template_version="4.0.0",
    slots={"definition": "...", "stage": "开篇", "context": "..."}
)
```

`WikiPage.slots: dict[str, str]` 字段加入 V7 frontmatter 的 `_ko_extra` 兄弟槽位（不进白名单、写入时落盘到 body 区域，由模板版本控制）。

## Invariants

- **frontmatter 仍严格白名单**（V6 18 键 + `template` + `template_version`）
- **slot 名称与索引文件保持一致**：`required_slots` 名称就是合法 `slot:xxx` 名字
- **模板槽位可独立演化**：加槽位不需要走 ADR，只需更新 `index.yaml` + RFC
- **lint 双轨**：frontmatter 用 `validate_frontmatter.py`、槽位用 `validate_template_slots.py`
- **向后兼容**：V4/V5/V6 页面无 `template_version` 字段时，读取时按"最近祖先版本"补默认值（concept→v3.0.0 兜底）

## Rejected alternatives

### A. 把槽位也升级为 frontmatter 字段
- 问题：`definition`、`context` 这些 1000+ 字的 Markdown 塞进 YAML 会让 frontmatter 膨胀到 30+ KB，违反"V6 严格白名单"原则
- 决策：拒绝

### B. 保持现状（槽位即 Markdown h2）
- 问题：机器不可解析、版本号混乱、lint 没法强制必填
- 决策：拒绝

### C. 用 JSON block 取代 Markdown
- 问题：破坏人类阅读体验；现有 4918 页全部要转
- 决策：拒绝（保留 Markdown 作为人读格式，机器解析走 index.yaml）

## Consequences

- ✅ 模板可独立迭代（加 `## 适用阶段` 不需要碰 V6 规范）
- ✅ LLM 生成时能识别"槽位名"→ 强制对应到 `slot:xxx` 锚点
- ✅ 索引文件给机器消费（知识图谱、跨库映射、AI Agent 都能直接 parse）
- ⚠️ 4918 页存量需要补 `template_version` 字段（CI 跑一遍兜底即可）
- ⚠️ 写盘路径要扩展（`WikiPage.slots` 字段 + `write_page` 新参数）

## References

- ADR-002: V4 8 键白名单
- docs/guides/wiki-spec.md §1
- knowledge/novel-wiki/.wiki-templates/{source,entity,concept,synthesis}.md (v3.0.0)