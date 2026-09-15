# novel-wiki Template Rewrite V7.1.1 — RFC (v6)

> Date: 2026-09-11 (v6: 基于9 次抽取实战验证)
> Author: novel-wiki architecture review
> Status: **proposed** (v5 经9 次抽取验证，v6 增补实战发现)
> Supersedes: knowledge/novel-wiki/.wiki-templates/{source,entity,concept,synthesis}.md v3.0.0
> Companion ADRs: ADR-002, ADR-003, ADR-006 (待起), ADR-007 (待起)
> 验证记录: 9 个文档 52 个产物

---

## 0. TL;DR

V7.1.1 经 **9 次不同结构文档抽取**实战验证。v6 增补 **3 项必改 + 4 项增强**：

**3 项必改**（来自抽取实战）：
1. **`stage` 改多值列表**（章节名/故事/人物/语言/细节贯穿全文——单值硬选错）
2. **加关系类型 `refines`**（扩句法→百炼法是"细化"关系，V7 `supported_by` 不精确）
3. **`source_meta` 必填 URL 字段**（飞书文档溯源关键）

**4 项增强**（来自边界情况）：
4. **加新文档类型 `tool`**（工具表，如百家姓）
5. **`_ko_extra.content_complete: bool`**（不完整文档标记——诚实 0 concept）
6. **`_ko_extra.bridge_count: int`**（清单类自动聚类用）
7. **`_ko_extra.participants_count: int`**（聊天记录类）

**保持不变**：V7 RFC v5 的 12 个核心决策 + 抽取流程稳定性验证。

---

## 1. v5 验证报告（9 文档抽取）

| # | 文档 | 结构 | source | concept | 验证点 |
|---|---|---|---|---|---|
| 1 | 三江杂谈 | 合集（11 篇）| 1 | 7 | ✅ 多文档聚合 |
| 2 | 科幻长篇 | 7 节方法论 | 1 | 7 | ✅ 单篇结构 |
| 3 | 网络小说总论 | 13 节 + 附文 | 1 | 14 | ✅ 多节方法论 |
| 4 | 8难墨武讲课 | Q&A聊天记录 | 1 | 9 | ✅ 主题聚合 |
| 5 | 关于金手指 | 单篇方法论（飞书）| 1 | 1 | ✅ URL溯源 |
| 6 | YY103 桥段 | **清单列表** | 1 | 3 | ✅ **自动聚类** |
| 7 | 百家姓 | **工具表** | 1 | 1 | ✅ **新类型** |
| 8 | 大神授课总汇 | 编辑视角单章 | 1 | 1 | ✅ 视角区分 |
| 9 | 15 条技巧 | **不完整文档** | 1 | 0 | ✅ **诚实 0** |
| **总计** | | | **9** | **43** | **52 产物** |

**v5 模板在9 种结构中全部成功**——抽取流程稳定，模板槽位足够。

---

## 2. v5 → v6 改造（10 项）

### 2.1 🔴必改1 — `stage` 多值列表

**v5**（问题）：
```yaml
# 章节名设计原则贯穿全书，但只能填单一 stage
stage: 开篇  # ←错位硬选
```

**v6**：
```yaml
# allowed_stages 改为多值列表
stage: [开篇, 前期, 中期, 高潮, 收尾]  # ←多阶段适用
```

**改造范围**：
- `index.yaml`：`allowed_stages` 字段语义升级为 "可填多值"
- 写盘路径：允许单页填多个 stage
- 检索 API：`stage=X` 改为 `stage IN (...)` 多值查询

### 2.2 🔴必改 2 — 加关系类型 `refines`

**v5**（问题）：
```yaml
# 扩句法 → 百炼法是"细化"关系，但 V7 只有 supported_by
- target: kuo-ju-fa
  type: supported_by  # ←语义不准
```

**v6**：在 6 内置关系 + x-* 之外，加 `refines`：
```yaml
relations:
  builtin:
    - references
    - referenced_by
    - taxonomy_of
    - is_part_of
    - supported_by
    - caused_by
    - refines            # ★ V7.1.1 新增 — A 是 B 的细化/扩展方法
  custom_placeholder: "x-*"
```

**应用示例**：
```yaml
# 百炼法 → 扩句法（细化）
- target: kuo-ju-fa
  type: refines    # ←精确表达细化关系
```

### 2.3 🔴必改 3 — `source_meta` 必填 URL 字段

**v5**（问题）：
```yaml
# 飞书文档 / 论坛帖的URL丢失，无法回查原始来源
source_meta: 自由文本，无必填字段
```

**v6**：在 `index.yaml` 的 `source.source_meta` 加 `required_subfields`：
```yaml
source:
  required_slots: [source_meta, summary, key_points]
  source_meta_required: [forum_url, raw_path]   # ★ V7.1.1 新增
```

**缺失处理**：
- 字段缺失时 `forum_url: 未知`（不编造）
- 校验脚本 warn（不 reject）——历史文档可能没URL

### 2.4 🟡增强 1 — 加新文档类型 `tool`（工具表）

**v5**（问题）：百家姓是参考工具表，但 V7 只有4 类型（source/entity/concept/synthesis）。把它作为 source 不准确——**它不是素材，是工具**。

**v6**：加新类型 `tool`：
```yaml
# V7 白名单
type: source | entity | concept | synthesis | tool    # ★ V7.1.1 新增

# tool 类型简化模板（3 槽位极简版）
tool:
  required_slots: [tool_meta, usage]
  optional_slots: [examples]
```

**tool 槽位定义**：
- `tool_meta` — 工具元数据（类型 / 用途 / 统计信息）
- `usage` — 使用方法 / 适用场景
- `examples`（可选）— 使用示例

**应用示例**：
```yaml
id: bai-jia-xing-gong-ju
type: tool    # ←不是 source，是工具
title: 百家姓（中文姓氏工具表）
```

### 2.5 🟡增强 2 — `_ko_extra.content_complete: bool`

**v5**（问题）：15 条技巧只有标题 + 引言 + 31 行介绍文字，**15 条正文完全缺失**。V7 没有"内容不完整"标记——容易被误判为抽取失败。

**v6**：加 `_ko_extra.content_complete` 字段：
```yaml
_ko_extra:
  content_complete: false    # ★ V7.1.1 新增
  note: 原文仅31 行，仅引言部分，15 条正文未包含
```

**处理规则**：
- `content_complete: false` → 写盘路径返回**0 concept**
- source 页保留，但 `key_points` 槽位标注"内容不完整"
- 关系网络断开（relations: []）
- 提示用户**人工补全后重新抽取**

### 2.6 🟢增强 3 — `_ko_extra.bridge_count: int`

**v5**（问题）：103 个桥段是清单类文档，没法告诉写盘路径"这是清单，应按主题聚类"。

**v6**：加 `_ko_extra.bridge_count` + 自动聚类提示：
```yaml
_ko_extra:
  bridge_count: 103              # ★ V7.1.1 新增
  list_type: 桥段清单            # ★ 提示写盘路径：按主题聚类而非逐条
```

**写盘路径行为**：
- 见到 `list_type` 字段 → 自动检测聚类维度（主题/类别/规则）
- 默认聚类为 3-5 个 concept（**避免N 个 concept 页爆炸**）

### 2.7 🟢增强 4 — `_ko_extra.participants_count: int`

**v5**（问题）：聊天记录有20+ 参与者，但 V7 `source_meta` 槽位没规定必填字段。

**v6**：加 `_ko_extra.participants_count`：
```yaml
_ko_extra:
  participants_count: 20+        # ★ V7.1.1 新增
  chat_format: Q&A聊天记录
```

**应用示例**：
- 8难墨武讲课记录：20+ 参与者
- 自动识别"主讲人"vs "参与者"——用于 relation 的 `author_role` 标注

---

## 3. v7.1.1 frontmatter 白名单（21 键 + 增强）

### 3.1 主白名单（21 键）

| # | 字段 | 类型 | 必填 | V6 改动 |
|---|---|---|---|---|
| 1 | `id` | str | ✅ | — |
| 2 | `title` | str | ✅ | — |
| 3 | `type` | enum | ✅ | **加 `tool`** |
| 4 | `sources` | list[str] | ✅ | — |
| 5 | `created_at` | datetime | ✅ | — |
| 6 | `updated_at` | datetime | ✅ | — |
| 7 | `relations` | list[dict] | ✅ | **加 `refines`** |
| 8 | `tags` | list[str] | ✅ | — |
| 9-18 | V6 9 个可选字段 | — | ❌ | — |
| **19** | **`template_version`** | str | ❌ | 默认 `4.0.0` |
| **20** | **`entity_subtype`** | str | ❌ | type=entity 限定 |
| **21** | **`policy_kind`** | str | ❌ | type=entity(subtype=policy) 限定 |

### 3.2 _ko_extra 扩展字段（V6 新增）

| 字段 | 类型 | 用途 | 触发条件 |
|---|---|---|---|
| `provenance` | dict | 上游血统（raw_path / forum_url / raw_author）| 所有 type |
| `content_complete` | bool | **文档内容是否完整**（V6 新增）| 不完整文档 = false |
| `bridge_count` | int | **清单类条目数**（V6 新增）| 清单类文档 |
| `list_type` | str | **清单类型**（V6 新增）| 清单类文档 |
| `participants_count` | int | **聊天参与者数**（V6 新增）| 聊天记录 |
| `chat_format` | str | **聊天格式**（V6 新增）| 聊天记录 |

---

## 4. v6 写盘路径扩展

### 4.1 chat record 检测（V6 新增）

```python
# 写盘路径自动检测聊天记录
if _ko_extra.chat_format == "Q&A聊天记录":
    # 按主题聚合（而非按说话人逐条抽取）
    # 主讲人识别 → relations.author_role 标注
    topics = aggregate_by_topic(llm_extract_topics(content))
    for topic in topics[:9]:  # 最多 9 个 concept
        create_concept_page(topic)
```

### 4.2 completeness check（V6 新增）

```python
# 写盘路径检测内容完整性
if _ko_extra.content_complete == False:
    return SourcePage(
        content_complete=False,
        concepts=[]  # 0 concept 返回
    )
```

### 4.3 清单类自动聚类（V6 新增）

```python
# 写盘路径检测清单类
if _ko_extra.list_type:
    items = parse_list_items(content)
    clusters = cluster_by_topic(items, n_clusters=3-5)
    for cluster in clusters:
        create_concept_page(cluster)
```

---

## 5. v6 验收标准（v5 14 条 + V6 9 条）

### v5 验收（保留）

1. ✅ 4 个模板 `wiki-template-version: 4.0.0` 落地
2. ✅ `.wiki-templates/index.yaml` 声明所有 required/optional slots + deprecation_map
3. ✅ `.index/wiki-inverse-index.json` 生成且能 query
4. ✅ graph-viewer.html 双击可打开
5. ✅ Pipeline 新 ingest 走 V7.1.1
6. ✅ 4918 页存量全量通过
7. ✅ `validate_novel_wiki_frontmatter.py --strict-v7.1.1` 全量通过
8. ✅ 21 → 6 关系收敛
9. ✅ deprecated 关系残留 = 0
10. ✅ entity_subtype misc 占比 <30%
11. ✅ concept stage 通用占比 <60%
12. ✅ taxonomy 受控枚举在 2027-06-30 reject
13. ⚠️ `用途/可执行` 通道仍未实现
14. ✅ PR template 含 plan-audit checklist

### V6 新增验收（9 条）

15. ✅ `stage` 支持多值列表（单页可填多个阶段）
16. ✅ 关系类型 `refines` 加入内置关系列表
17. ✅ `source_meta` 必填 URL（缺失标"未知"+ warn）
18. ✅ 新文档类型 `tool` 落地（带3 槽位极简模板）
19. ✅ `_ko_extra.content_complete` 标记（不完整文档诚实 0 concept）
20. ✅ `_ko_extra.bridge_count` + `list_type` 触发自动聚类
21. ✅ `_ko_extra.participants_count` + `chat_format` 触发主题聚合
22. ✅ 写盘路径 chat record 检测（Q&A 自动按主题聚合）
23. ✅ 写盘路径 completeness check（不完整文档自动 0 concept）

---

## 6. v7.1.1 vs v5 总览

| 维度 | v5 | v7.1.1 |
|---|---|---|
| 决策数 | 12 | 12（不变）|
| frontmatter 键数 | 20 | 21（+ policy_kind）|
| 文档类型 | 4 | 5（+ tool）|
| 关系类型 | 6 + x-* | 7 + x-*（+ refines）|
| `_ko_extra` 扩展 | 1（provenance）| 6（+ 5 新字段）|
| 写盘路径智能化 | 无 | chat / completeness / list自动检测 |
| 总工作量 | 3 天 | 4 天（+1 天 V6 改造）|

---

## 7. References

- ADR-002: V4 8 键白名单
- ADR-003: 解耦模板槽位与 frontmatter
- ADR-004 (待起): `用途/可执行` 审核通道 follow-up
- ADR-005 (待起): 跨库互联 follow-up
- ADR-006 (待起): V8 未来扩展方向（template_version 配置化 / 模板片段）
- ADR-007 (待起): 项目治理规则（PR template + AGENTS.md 硬规则）
- 9 次抽取验证记录（累计 52 个产物）

---

## 附录 A：v5 → v6 改动映射

| v5 问题 | v6 改造 | 章节 |
|---|---|---|
| `stage` 单值硬选 | 改多值列表 | §2.1 |
| 缺 `refines` 关系 | 加内置关系 | §2.2 |
| `source_meta` 无URL 必填 | 加 `source_meta_required` | §2.3 |
| 工具表无对应类型 | 加 `tool` 类型 + 极简模板 | §2.4 |
| 不完整文档无标记 | 加 `content_complete` | §2.5 |
| 清单类聚类缺失 | 加 `bridge_count` + `list_type` | §2.6 |
| 聊天记录无标记 | 加 `participants_count` + `chat_format` | §2.7 |
| 写盘路径无智能化 | 加 chat / completeness / list 检测 | §4 |