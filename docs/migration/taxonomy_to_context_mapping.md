# Taxonomy → Context Mapping (K-5 加固, spec §5.1 + §8.3)

> Status: A-3 / G6 — K-5 hardening companion to the new `ConflictClassifier`
> (`src/kc/conflicts/classifier.py`, commit 36fac1e6).
> Owner: spec-roadmap §A-3 subagent.
> Audience: anyone wiring WikiPage frontmatter into the spec §8.3 Context
> 8-dimension schema, or extending the conflict resolution layer.

## 背景

`WikiPage` (`src/wiki/core/types.py`) currently carries two taxonomy-related
frontmatter fields:

- `category: str` — taxonomy axis 1 (introduced in spec v3.1)
- `taxonomy_sub: str` — taxonomy axis 2

The spec §8.3 **Context** schema lists 8 dimensions that any conflict-bearing
KnowledgeObject must populate:

| # | Dimension    | Required? | Cardinality | Description                          |
|---|--------------|-----------|-------------|--------------------------------------|
| 1 | `domain`     | yes       | single      | Knowledge area (e.g. `novel_writing`) |
| 2 | `platform`   | yes       | single      | Delivery surface (e.g. `web`)         |
| 3 | `audience`   | no        | single      | Reader/consumer class                |
| 4 | `geography`  | no        | single      | Geographic scope                     |
| 5 | `language`   | yes       | single      | ISO 639-1 / BCP-47 tag                |
| 6 | `goal`       | no        | single      | Intended outcome                      |
| 7 | `conditions` | no        | multi       | Preconditions / qualifiers            |
| 8 | `perspective`| no        | single      | Stance / POV (CF-007 / CF-008 anchor) |

The 10 gold cases in `docs/evaluation/cases/conflict.yaml` (C-3.2, commit
9aed7e2b) use only `domain` + `platform` + `perspective`; the other 5 dimensions
are reserved for future schema expansion (B-3 / B-5).

## Mapping 规则

| WikiPage frontmatter | Context dimension | Default | Notes |
|----------------------|-------------------|---------|-------|
| `category`           | `domain`          | direct  | 主分类映射到知识领域（如 `novel_writing` → `Context.domain = "novel_writing"`）。空字符串映射到 `unknown`，触发 `ConflictClassifier._has_unknown_dimension` → unresolved (spec §8.2 X-9)。 |
| `taxonomy_sub`       | `platform`        | direct  | 子分类映射到平台（如 `web` → `Context.platform = "web"`）。同上的 `unknown` 降级。 |
| `language`           | `language`        | direct  | frontmatter 字段已存在；保持 ISO 639-1 形式（如 `zh` / `en`）。 |
| _新字段 (A-3+)_     | `audience`        | none    | 待 Phase 4 batch 19+ 增加 frontmatter 字段。 |
| _新字段 (A-3+)_     | `geography`       | none    | 同上。 |
| _新字段 (A-3+)_     | `goal`            | none    | 同上。 |
| _新字段 (A-3+)_     | `conditions`      | none    | 同上；multi-value list。 |
| _新字段 (A-3+)_     | `perspective`     | none    | 同上；CF-007/CF-008 用 `environmentalist` / `economist` 标记立场。 |

**降级规则**：当源 WikiPage 缺少某个维度且该维度对冲突判定为决定性时
（`domain` / `platform` / `perspective`），写入字面量 `"unknown"` 而非
省略字段。这样 `ConflictClassifier._has_unknown_dimension` 能可靠识别，
并把潜在互斥路由到 `unresolved` (CF-009 模式)。

## Phase 4 batch 18 warn 决策

Phase 4 batch 18 ingestion 出现 2 处 `taxonomy unknown` warn（spec v3.1 引入
taxonomy 后批量摄入的新页 `category` 为空）：

- 标记为 missing `Context.domain`
- 由用户在 Phase 4 batch 19+ 决策：
  - 选项 1：补全 taxonomy（domain 已知）
  - 选项 2：保留 `unknown`（domain 未明）
- **默认**：保留 `unknown`（保守，不假装知道）

理由：unknown 是诚实信号，spec §11.4 #7 (Unresolved Conflict) 要求遇到
unknown decisive dimension + 潜在互斥 → `unresolved` + `quarantine`。伪装为
已知 domain 会绕过 quarantine 路径。

## ConflictClassifier 集成点

`src/kc/conflicts/classifier.py` 已实现以下与本映射直接相关的判定逻辑：

| Classifier 方法 | 触发的映射规则 | spec 引用 |
|------------------|----------------|-----------|
| `_context_disjoint` | 无共同 `domain`/`platform` → `none` (CF-010) | §8.3 |
| `_temporal_disjoint` | 跨 `valid_to_a` / `valid_from_b` → `temporal` (CF-005/006) | §8.2 X-6 |
| `_has_unknown_dimension` | `domain` / `platform` 出现 `unknown` → `unresolved` (CF-009) | §8.2 X-9 |
| `_context_partial_overlap` | 部分 key 同值 + 部分不同 → `conditional` (CF-003/004) | §8.2 X-3 |
| `_differs_only_in_perspective` | 仅 `perspective` 不同 → 跳过 conditional 直达 `perspective` (CF-007/008) | §8.2 X-4 |
| `_statements_contradict` | 反义词对触发 → `actual` (CF-001/002) | §8.2 X-2 |

## 后续任务

- **A-3 (本任务)**：✅ Conflict 6 类型分类器已落地；本映射文档记录
  WikiPage ↔ Context 字段对应关系。
- **B-3**：默认发布闭包校验 `domain` 非 `unknown`（spec §11.3 closed-loop
  precondition）。本映射为该校验提供字段来源。
- **Phase 4 batch 19+**：决策 `taxonomy unknown` → `domain: unknown` 是否
  阻断 ingest；本映射明确推荐"不阻断，但写入 unknown 触发 quarantine"。
- **C-7.5**（待规划）：扩 8 维度 WikiPage frontmatter 字段（`audience` /
  `geography` / `goal` / `conditions` / `perspective`）。

## 验收

- 8/8 `tests/test_kc/test_conflict_classifier.py` PASS（commit 36fac1e6）。
- 1176 baseline test passed；0 regression（6 pre-existing failure 与本任务无关）。
- `delivery_reports/A-3.yaml` CI passed。