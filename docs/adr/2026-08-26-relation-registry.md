# ADR-003: Relation Registry (B-2.10 commit 1)

- status: accepted
- date: 2026-08-26
- context: |
  spec §3.6 列出 9 类受控关系 (is_a / part_of / related_to / depends_on /
  supports / contradicts / example_of / supersedes / derived_from)。

  WikiPage 现有 17 built-in 关系 (src/wiki/features/relations.py) + x-* 命名空间
  自定义关系。新增正式关系需 Relation ADR (spec §3.6 末尾)。

  B-2.10 Relation Gate 是 11 Gate 中唯一"受控集合收敛"前置依赖
  (其他 10 Gate 不依赖此 ADR)。

decision: |
  1. Relation Registry 作为"权威受控集合"落地:
     - 路径: .kc/relation_registry.yaml (versioned alongside code)
     - 内容: 9 类 spec 受控关系 (mode: spec) + 17 类 WikiPage built-in (mode: legacy)
     - 自定义: x-* 命名空间保留 (向后兼容)
  2. Relation Gate 校验关系类型必须属于:
     a. spec §3.6 9 类 (mode: spec) — 必须有 ADR
     b. 17 类 WikiPage built-in (mode: legacy) — 自动允许 (back-compat)
     c. x-* 命名空间 (mode: custom) — 必须在 relation_registry.yaml 中登记
  3. 新增关系: 提交 ADR 登记到 relation_registry.yaml 后, Relation Gate 自动允许

rationale: |
  - 解决 spec §3.6 9 类与 WikiPage 17 类的冲突 (5 类重复 + 3 类独有 + 9 类独有)
  - 保留 x-* 自定义空间, 避免破坏现有 17 类关系
  - ADR 留位让未来关系扩展 (基于真实查询需求)

consequences: |
  - WikiPage.relations 字段保持不变 (17 类 + x-* 继续工作)
  - 新建关系优先 spec §3.6 9 类
  - 17 类 WikiPage built-in 标记为 legacy (不推荐新增, 但兼容历史)
  - x-* 命名空间需要 relation_registry.yaml 登记

trigger_to_revisit: |
  - 新增关系类型时
  - 17 类 legacy 收敛到 9 类 spec 时
  - x-* 自定义空间滥用时