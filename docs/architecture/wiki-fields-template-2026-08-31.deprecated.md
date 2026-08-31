# Wiki 字段模板与示例（V3 · **DEPRECATED** · 2026-08-31）

> ## ⚠️ 本模板已弃用（2026-08-31）
>
> **原因**：V3 模板基于**错误数据假设**得出"16 字段冻结"——
> 通过对 novel-wiki 4892 个存量页面做字段填充率 + 取值分布审计，发现：
>
> - 5 个 V3 新增字段（`confidence` / `provenance` / `versions` / `lifecycle` / `lock_until`）
>   在 novel-wiki **0% 填充**——这些字段**从未在生产中使用**
> - 5 个 v2.2 现状字段（`heat` / `is_immutable` / `last_used_at` / `zombie_since` / `related_entities`）
>   在 novel-wiki **100% 取固定值**——属于**死字段**
> - V3 模板把"死字段保留 + 新增字段冻结"作为终态，**背离了"精简"目标**
>
> **替代方案**：见
> [novel-wiki-fields-template-2026-08-31.md](./novel-wiki-fields-template-2026-08-31.md)
> （**14 键精简态**：6 必填 + 6 可选 + 2 派生，5 个死字段识别 + 5 个未用字段禁入）。
>
> 本文档保留作为**历史决策追溯**，不作为实施依据。

---

> **以下为 V3 原文档内容（2026-08-31 14:04 冻结声明的"16 字段"）**

> **本模板为最终字段定义，自 2026-08-31 起冻结。**
>
> **字段集 = 16 键**（9 L1 事实 + 2 L2 派生 + 3 L3 治理 + 2 时间戳），不再变更。  
> 实施指引见 [wiki-fields-ideal-state-2026-08-31.md](./wiki-fields-ideal-state-2026-08-31.md)（WT-1~WT-6）。  
> 设计决策追溯见 [ADR-002](~/wiki-wiki-base/docs/adr/ADR-002-wiki-fields-long-term-evolution.md)（accepted）。  
> 本模板的所有示例**均来自 `knowledge/novel-wiki/wiki/` 的真实存量页面**，可逐项核对。


## 0. 字段速查（终态 16 键 · 已冻结）

> **冻结声明**：自 2026-08-31 14:04 起，**16 字段不得新增、不得删除、不得重命名**。
>
> - 如需表达新语义：优先用 `relations: {type: x-*, target: <namespaced>}` 扩展（D2 关系体系）
> - 如需记录新元数据：用 `_ko_extra` 逃生舱（受限白名单，详见 §1.3）
> - 如需修改业务规则：CI 断言调整而非字段改动



| #  | 字段             | 层   | 类型              | 必填    | 取值约束                                                                                                                                    | 不可移除理由                 |
| -- | -------------- | --- | --------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| 1  | `id`           | L1  | str             | ✅     | 与文件名一致；`^(card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-\u4e00-\u9fff]+\|[a-z0-9-\u4e00-\u9fff]+)$`，≤64 字符                                      | 文件系统唯一键；wikilink 路由    |
| 2  | `type`         | L1  | enum            | ✅     | `source` | `entity` | `concept` | `synthesis`                                                                                           | 路由 + KB 目录约定           |
| 3  | `title`        | L1  | str             | ✅     | 非空，≤80 字符                                                                                                                               | 人类可读唯一标识               |
| 4  | `confidence`   | L1  | float           | ✅     | `[0.0, 1.0]`；决定 `grade` 派生                                                                                                              | 信任度本源                  |
| 5  | `provenance`   | L1  | dict            | ✅     | `source_path: str`（必填）、`source_paths: tuple`（默认空）、`page: int\|null`、`quote: str ≤200 字符`、`ingested_at: int`（ms）、`ingestor_version: str` | 知识溯源唯一路径               |
| 6  | `relations`    | L1  | list            | ⛔ 可选  | 17 内置 + 4 新增 + `x-*` 自定义（命名空间见 §2）                                                                                                      | 知识图谱边                  |
| 7  | `sources`      | L1  | list[str]       | ⛔ 可选  | 与 `provenance.source_paths` 同步                                                                                                          | 兼容 KO 字段镜像             |
| 8  | `versions`     | L1  | list            | ⛔ 可选  | `[{version_id, timestamp, change_description}]`；触发条件见 §1.2                                                                              | 审计追踪                   |
| 9  | `lifecycle`    | L1  | enum            | ✅     | 8 态：CREATED/PROCESSING/REVIEWING/ACTIVE/DEPRECATED/ARCHIVED/FAILED/REJECTED；**无 draft**                                                 | 治理动作依据                 |
| 10 | `grade`        | L2  | enum            | ✨ 派生  | A(≥0.7) | B(≥0.5) | C(<0.5)；**不得手写**                                                                                                    | 业务侧强查询依赖               |
| 11 | `slug`         | L2  | str             | 🔧 注入 | 与文件路径派生；**LLM 不得指定**                                                                                                                    | gbrain 链接图路由           |
| 12 | `lock_until`   | L3  | int (ms) | null | ⛔ 可选  | Unix ms 截止时间戳；null=未锁；过去时间戳（含 0）=已解锁                                                                                                    | 编辑守卫（替代旧 is_immutable） |
| 13 | `category`     | L3  | str             | ✅     | 命中项目 `taxonomy.md`；空 taxonomy 时 WARN 而非 PASS                                                                                            | 业务过滤                   |
| 14 | `taxonomy_sub` | L3  | str             | ⛔ 可选  | 命中项目 `taxonomy.md`                                                                                                                      | 细粒度过滤                  |
| 15 | `created_at`   | 时间戳 | int (ms)        | ✅     | Unix 毫秒时间戳                                                                                                                              | 物理时间锚点                 |
| 16 | `updated_at`   | 时间戳 | int (ms)        | ✅     | Unix 毫秒时间戳；与 versions.last 一致                                                                                                           | 与 KO 时间戳解耦             |

### 0.1 字段冻结声明（frozen schema）

```
WIKI_FIELD_SCHEMA_VERSION = "3.0.0"
WIKI_FIELD_SCHEMA_FROZEN_SINCE = "2026-08-31T14:04:00+08:00"
WIKI_FIELD_SCHEMA_FROZEN_FIELDS = 16
WIKI_FIELD_SCHEMA_CHANGE_POLICY = "addition: rejected, deletion: rejected, rename: rejected"
```

**例外**：仅以下情况允许字段级变更：

1. KO 模型演进引入新必填字段（必须经 ADR 修订 + KB 全量重新生成）
2. 字段类型/取值约束微调（CI 断言同步更新，不影响 schema 形态）
3. 字段命名空间新增（如新增 `audience/` 前缀——属 §2 扩展，非字段改动）

### 0.2 L1/L2/L3/时间戳 四层语义

| 层         | 含义             | 写入路径        | 数量 |
| --------- | -------------- | ----------- | -- |
| **L1 事实** | KO 镜像 + 知识原子信息 | KO 强同步 + 写入 | 9  |
| **L2 派生** | 渲染层计算，禁止手写     | 渲染时计算       | 2  |
| **L3 治理** | 人/流程判定         | 治理流程写入      | 3  |
| **时间戳**   | 物理时间锚点         | 物理写入        | 2  |

---


## 1. 标准模板（V3 终态 · 可直接复制）

```yaml
---
# ===== L1 事实层（KO 镜像）=====
id: <与文件名一致，13-64 字符>
type: <source|entity|concept|synthesis>
title: <非空，≤80 字符>
confidence: <0.0-1.0>
provenance:
  source_path: <raw/sources/... 相对项目根>
  source_paths: []
  page: <null>
  quote: ""                   # ≤200 字符
  ingested_at: <Unix ms>
  ingestor_version: "2.0.0"
relations: []                  # 17+4 内置 + x-* 扩展；命名空间见 §2
sources: []                    # 与 provenance.source_paths 同步
versions:                      # 触发条件见 §1.2
- version_id: v1
  timestamp: <Unix ms>
  change_description: 初始摄入
lifecycle: <CREATED|PROCESSING|REVIEWING|ACTIVE|DEPRECATED|ARCHIVED|FAILED|REJECTED>

# ===== L2 派生层（禁止手写）=====
grade: <A|B|C>                 # render_grade(confidence)
slug: <自动注入>

# ===== L3 治理层 =====
lock_until: <null>             # null=未锁；99999999999999=永久锁
category: <命中 taxonomy.md>
taxonomy_sub: <命中 taxonomy.md>

# ===== 时间戳 =====
created_at: <Unix ms>
updated_at: <Unix ms>
---




```

### 1.1 注释要点（V3 终态）

- **`grade` 禁止手写**：写盘前由 `render_grade(confidence)` 渲染；CI 不一致行为：WARN + 覆盖为派生值（不拒写）
- **`slug` 禁止手写**：写盘层注入 `gbrain_slug_for_path`，手写值被覆盖
- **`ingestor_version` = "2.0.0"**：pyproject.toml 实测，禁止捏造
- **lifecycle 不写 `draft`**：KO 8 态无 draft，CI 直接 fail
- **`lock_until` 是 is_immutable 的时间戳升级**：
  - `null` = 未锁
  - `0` 或过去时间戳 = 已解锁（写盘通过）
  - 未来时间戳 = 锁定期内，写盘拒绝（`LockActiveError`）
  - 永久锁：`99999999999999`（约 5138 年）
- **`provenance.quote` ≤200 字符**：超长 WARN 不阻断
- **空 taxonomy 时 `category` WARN**：不阻断，仅记录

### 1.2 `versions` 触发条件（终态约定）

| 触发事件                               | version_id      | change_description           |
| ---------------------------------- | --------------- | ---------------------------- |
| 初始摄入                               | `v1`            | `初始摄入`                       |
| confidence 重跑                      | `v<last+1>`     | `confidence: <old> → <new>`  |
| Lifecycle 状态机迁移                    | `v<last+1>`     | `lifecycle: <from> → <to>`   |
| Schema 变更（type/provenance）         | `v<last+1>`     | `schema 升级: <field>=<value>` |
| `lock_until` 修改                    | `v<last+1>`     | `lock_until: <old> → <new>`  |
| metadata 变更（category/taxonomy_sub） | **不触发** version | metadata 不算内容演化              |

**CI 断言**：grade/lifecycle/provenance.source_path/lock_until 任一变更时，`versions[]` 必须追加新条目。

### 1.3 `_ko_extra` 逃生舱（受限白名单）

仅当 16 字段无法表达时才使用；白名单由 ADR 修订控制。当前允许的子键：

| 子键           | 含义                 | 备注                     |
| ------------ | ------------------ | ---------------------- |
| `provenance` | KO.Provenance 完整字段 | WikiPage.provenance 真源 |

任何 `_ko_extra.<other>` 子键**触发 CI fail**。

---

## 2. 关系体系（D2 落地 · 已冻结）

分类信息完全迁移到 `relations`。**新增 4 个内置 relation type**（命名空间已锁定）：

| relation type         | target 命名空间          | 替的旧 tag 前缀            | 命名冻结 |
| --------------------- | -------------------- | --------------------- | ---- |
| `taxonomy_of`         | `taxonomy/<名>`       | `题材/功能/角色/事件/情绪/场景阶段` | ✅    |
| `belongs_to_audience` | `audience/<名>`       | `读者群`                 | ✅    |
| `hosted_on_platform`  | `platform/<名>`       | `平台`                  | ✅    |
| `has_credibility`     | `credibility/<name>` | `可信度`                 | ✅    |

**RelationsRegistry**（V3 新增）：x-* 自定义扩展需在 `wiki/<project>/relations.md` 注册，未注册触发 `LINT-UNKNOWN-RELATION-TYPE`。

### 2.1 与旧 12 前缀 tags 的迁移映射（V3 已完成）

| 旧 tag     | 新 relation                                          |
| --------- | --------------------------------------------------- |
| `题材/玄幻`   | `{target: taxonomy/玄幻, type: taxonomy_of}`          |
| `功能/方法论`  | `{target: taxonomy/方法论, type: taxonomy_of}`         |
| `场景阶段/战斗` | `{target: taxonomy/战斗, type: taxonomy_of}`          |
| `读者群/女性向` | `{target: audience/女性向, type: belongs_to_audience}` |
| `平台/飞书`   | `{target: platform/飞书, type: hosted_on_platform}`   |
| `可信度/ugc` | `{target: credibility/ugc, type: has_credibility}`  |
| `素材/ugc`  | **删除**（已被 credibility/ugc 表达）                       |

---

## 3. 真实场景示例（4 种 type × 4 种 lifecycle）


### 3.1 示例 1：concept / ACTIVE（高质量已审核）

**源页面**：`knowledge/novel-wiki/wiki/concepts/1vs1-公平对决-打斗七公式之一.md`

```yaml
---
id: 1vs1-公平对决-打斗七公式之一
type: concept
title: 1VS1 公平对决（打斗七公式之一）
confidence: 0.62
provenance:
  source_path: raw/sources/02_进阶技巧/计谋格斗打斗七公式重要.md
  source_paths: []
  page: null
  quote: 打斗七公式中的第一个公式，详细规定了书写一场1对1公平对决的完整流程和写作要点
  ingested_at: 1787122533131
  ingestor_version: "2.0.0"
relations:
- target: 打斗七公式
  type: is_part_of
  weight: 1.0
  context: 是"打斗七公式"体系的第一个具体公式
- target: 七分铺垫三分打斗法则
  type: supports
  weight: 0.8
  context: 该公式的前半部分（铺垫）是"七分铺垫三分打斗"的具体实践
- target: taxonomy/玄幻
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/仙侠
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/方法论
  type: taxonomy_of
  weight: 1.0
- target: credibility/ugc
  type: has_credibility
  weight: 1.0
sources:
- raw/sources/02_进阶技巧/计谋格斗打斗七公式重要.md
versions:
- version_id: v1
  timestamp: 1787122533131
  change_description: 初始摄入
lifecycle: ACTIVE
grade: B
slug: concepts/1vs1-公平对决-打斗七公式之一
lock_until: null
category: 写作技法
taxonomy_sub: 情节与冲突
created_at: 1787122533131
updated_at: 1787122533131




```

### 3.2 示例 2：source / REVIEWING（高分但未审核）

**源页面**：`knowledge/novel-wiki/wiki/sources/1写作选材之以小见大第1段-bafab45e.md`

```yaml
---
id: 1写作选材之以小见大第1段-bafab45e
type: source
title: (1)写作选材之以小见大第1段
confidence: 0.78
provenance:
  source_path: raw/sources/07_看电影学写作/1写作选材之以小见大第1段.md
  source_paths: []
  page: null
  quote: 本视频教程讲解作文选材中的"以小见大"技法
  ingested_at: 1787290014426
  ingestor_version: "2.0.0"
relations:
- target: taxonomy/教程
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/写作
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/全篇
  type: taxonomy_of
  weight: 1.0
- target: credibility/ugc
  type: has_credibility
  weight: 1.0
sources:
- raw/sources/07_看电影学写作/1写作选材之以小见大第1段.md
versions:
- version_id: v1
  timestamp: 1787290014426
  change_description: 初始摄入
lifecycle: REVIEWING
grade: A
slug: sources/1写作选材之以小见大第1段-bafab45e
lock_until: null
category: 写作技法
taxonomy_sub: 选材与切入点
created_at: 1787290014426
updated_at: 1787290014426
```


### 3.3 示例 3：synthesis / ARCHIVED（早期未引用页）

**源页面**：`knowledge/novel-wiki/wiki/synthesis/东方玄幻创作中的中国古典典籍应用指南.md`

```yaml
---
id: 东方玄幻创作中的中国古典典籍应用指南
type: synthesis
title: 东方玄幻创作中的中国古典典籍应用指南
confidence: 0.55
provenance:
  source_path: raw/sources/04_题材专题/东方玄幻古典书籍名国学科目.md
  source_paths: []
  page: null
  quote: 如何将中国古典经部与史部典籍有效融入东方玄幻小说创作
  ingested_at: 1787243109006
  ingestor_version: "2.0.0"
relations:
- target: 东方玄幻古典书籍名--素材库
  type: references
  weight: 1.0
- target: 东方玄幻
  type: analogous_to
  weight: 0.8
- target: taxonomy/玄幻
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/写作技巧
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/设定
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/大纲设计
  type: taxonomy_of
  weight: 1.0
- target: credibility/ugc
  type: has_credibility
  weight: 1.0
sources:
- raw/sources/04_题材专题/东方玄幻古典书籍名国学科目.md
versions:
- version_id: v1
  timestamp: 1787243109006
  change_description: 初始摄入
lifecycle: ARCHIVED
grade: B
slug: synthesis/东方玄幻创作中的中国古典典籍应用指南
lock_until: null
category: 写作技法
taxonomy_sub: 世界观设定
created_at: 1787243109006
updated_at: 1787243109006
```


### 3.4 示例 4：source / FAILED（结构损坏）

**源页面**：`knowledge/novel-wiki/wiki/sources/借鉴素材套路-81291264.md`

⚠️ 该页面存在未解决的 git merge 标记（frontmatter 与 body 内均有 `<<<<<<< Updated upstream` 残留），属结构损坏。

```yaml
---
id: 借鉴素材套路-81291264
type: source
title: 借鉴素材套路
confidence: 0.71
provenance:
  source_path: raw/sources/01_新手入门/借鉴素材套路.md
  source_paths: []
  page: null
  quote: 本文档提供了现言宠文类（总裁文）的写作套路指南
  ingested_at: 1786967065232
  ingestor_version: "2.0.0"
relations:
- target: 现言宠文类
  type: references
  weight: 1.0
- target: 总裁文
  type: references
  weight: 1.0
- target: 降服高官老公
  type: references
  weight: 1.0
- target: 总裁的私有宝贝
  type: references
  weight: 1.0
- target: 先婚厚爱
  type: references
  weight: 0.8
- target: taxonomy/现言
  type: taxonomy_of
  weight: 1.0
- target: taxonomy/教程
  type: taxonomy_of
  weight: 1.0
- target: credibility/ugc
  type: has_credibility
  weight: 1.0
sources:
- raw/sources/01_新手入门/借鉴素材套路.md
versions:
- version_id: v1
  timestamp: 1786967065232
  change_description: 初始摄入
lifecycle: FAILED
grade: A
slug: sources/借鉴素材套路-81291264
lock_until: null
category: 案例与素材
taxonomy_sub: 桥段与梗
created_at: 1786967065232
updated_at: 1786967065232
```

### 3.5 示例 5：concept / DEPRECATED + lock_until

演示：页面被新版推翻 + 永久锁定防止误改。

```yaml
---
id: 旧版-foo-概念
type: concept
title: 旧版 Foo 概念（已被 v2 替代）
confidence: 0.40
provenance:
  source_path: raw/sources/02_进阶技巧/foo-旧版.md
  source_paths: []
  page: null
  quote: ""
  ingested_at: 1700000000000
  ingestor_version: "2.0.0"
relations:
- target: 新版-foo-概念
  type: superseded_by
  weight: 1.0
- target: credibility/ugc
  type: has_credibility
  weight: 1.0
sources:
- raw/sources/02_进阶技巧/foo-旧版.md
versions:
- version_id: v1
  timestamp: 1700000000000
  change_description: 初始摄入
- version_id: v2
  timestamp: 1750000000000
  change_description: lifecycle: ACTIVE → DEPRECATED
- version_id: v3
  timestamp: 1750000001000
  change_description: lock_until: null → 99999999999999
lifecycle: DEPRECATED
grade: C
slug: concepts/旧版-foo-概念
lock_until: 99999999999999
category: 写作技法
taxonomy_sub: 概念定义
created_at: 1700000000000
updated_at: 1750000001000
```

---

## 4. 反例（**不要这么写** · 7 项 · V3 终态）

| # | 反例 | CI 触发 | 正确做法 |
|---|---|---|---|
| 1 | 保留 `tags:` 字段 | `test_no_tags.py` fail | 用 `relations: [{target: taxonomy/玄幻, type: taxonomy_of}]` 替代 |
| 2 | 写 `processing_depth` | M1 5 套枚举冲突 fail | 删除，由 `type` 派生 |
| 3 | `lifecycle: draft` | `test_lifecycle_enum.py` fail | 用 `CREATED` 或 `REVIEWING` |
| 4 | `provenance.ingestor_version: "3.0.0"` | `test_provenance_version.py` fail | 用 `"2.0.0"` |
| 5 | `confidence: 0.62; grade: A` | `test_grade_consistency.py` WARN + 覆盖 | 删除 grade，由 `render_grade(confidence)` 渲染 |
| 6 | `relations: target: 玄幻小说`（缺前缀）| `test_relation_namespace.py` fail | 必带命名空间前缀 `taxonomy/玄幻` |
| 7 | `lock_until: "2099-12-31T23:59:59Z"`（字符串）| `test_lock_until_type.py` fail | 必须 int (ms)；永久锁 `99999999999999` |

---

## 5. CI 断言清单（12 项 · V3 终态 · 永远生效）

| # | 测试文件 | 断言 | 优先级 |
|---|---|---|---|
| 1 | `test_no_tags.py` | 全仓 frontmatter 不含 `tags:` | P0 |
| 2 | `test_lifecycle_enum.py` | `WikiPage.lifecycle ∈ LifecycleState` 8 态 | P0 |
| 3 | `test_confidence_present.py` | `confidence ∈ [0, 1]`，100% 必填 | P0 |
| 4 | `test_grade_consistency.py` | `render_grade(confidence) == grade` 不一致时 WARN+覆盖 | P0 |
| 5 | `test_sources_present.py` | `sources` 与 `provenance.source_paths` 同步 | P0 |
| 6 | `test_provenance_required.py` | `provenance.source_path != ""` | P0 |
| 7 | `test_no_heat.py` | 全仓 frontmatter 不含 `heat:` | P0 |
| 8 | `test_no_custom_type.py` | 全仓 frontmatter 不含 `custom_type:` | P0 |
| 9 | `test_no_is_immutable.py` | 全仓 frontmatter 不含 `is_immutable:` | P0 |
| 10 | `test_versions_trigger.py` | grade/lifecycle/provenance.source_path/lock_until 变更时必追加 version | P0 |
| 11 | `test_quote_length.py` | `provenance.quote ≤ 200 字符` 超长 WARN 不阻断 | P1 |
| 12 | `test_taxonomy_required.py` | 空 taxonomy 时 WARN 不阻断 | P1 |

---

## 6. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| [wiki-fields-ideal-state-2026-08-31.md](./wiki-fields-ideal-state-2026-08-31.md) | **理想态实施指引**（本模板配套） |
| [ADR-002](~/wiki-wiki-base/docs/adr/ADR-002-wiki-fields-long-term-evolution.md) | accepted（V3 终态决策） |
| [wiki-fields-remediation-plan-2026-08-31.md](../evaluations/wiki-fields-remediation-plan-2026-08-31.md) | 整改方案（WT 任务编排来源） |
| [wiki-fields-template-multiview-review-2026-08-31.md](../evaluations/wiki-fields-template-multiview-review-2026-08-31.md) | 多视角评审（P0/P1 已在 V3 落地） |
| [wiki-fields-audit-2026-08-31.md](../evaluations/wiki-fields-audit-2026-08-31.md) | 初轮审计（V3 已纠正 P0-1~P0-4） |
| `docs/guides/wiki-spec.md` | **WT-6 任务**重写为本模板的精简版 |

---

## 7. 验证步骤（每页必过）

1. **frontmatter 解析**：`WikiPage.from_dict(raw_frontmatter)` 成功
2. **L1 必填齐全**：`id` / `title` / `confidence` / `provenance.source_path` / `sources[]` / `lifecycle` / `grade` / `slug` / `created_at` / `updated_at` / `category` / `lock_until` 全部非空
3. **lifecycle 枚举**：值 ∈ 8 态（无 draft）
4. **L2 一致性**：`render_grade(confidence) == grade`；`slug` 与路径派生一致
5. **锁守卫**：写入时若 `lock_until > now` 拒覆盖
6. **`versions` 触发**：grade/lifecycle/provenance.source_path/lock_until 任一变更时 `versions[]` 必追加
7. **relation 命名空间**：4 新类型 target 必带前缀
8. **provenance 合法**：`ingestor_version == "2.0.0"`；`quote ≤ 200` 字符
9. **空 taxonomy 处理**：`category` 写入空 taxonomy 时 WARN 不阻断

---

## 8. V3 实施前必答 3 件事

1. **`LOCK_FOREVER = 99999999999999` 是否提取为 `src/wiki/features/constants.py` 的命名常量**？建议：是
2. **4 个 KB 重新生成的优先级顺序**：novel-wiki-staging → novel-wiki-clean-staging → novel-wiki → 其余？建议：是
3. **本模板 v3.0.0 是否作为 KO 侧 `provenance.ingestor_version` 的下一次 bump 触发条件**？建议：V3 实施后即 bump 到 `"3.0.0"`

---

**字段冻结生效**：`WIKI_FIELD_SCHEMA_FROZEN_SINCE = 2026-08-31T14:04:00+08:00`