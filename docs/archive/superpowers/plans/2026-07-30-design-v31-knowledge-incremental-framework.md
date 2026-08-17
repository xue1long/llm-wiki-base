# WikiPage 字段补漏 + processing_depth 枚举修复

> 三个实际存在的 bug，不是设计优化。

## 问题

### 1. `category` / `taxonomy_sub` 不在 WikiPage dataclass 中

wiki 规范要求页面有这两个字段，YAML 里可能存在（手动编辑或旧版 pipeline），但 `WikiPage` dataclass 没这两个字段——每次读页面靠 YAML 宽松解析"碰巧"读到。且当前 LLM prompt 未引导 LLM 输出它们，即使落了字段也永远是空字符串。无类型安全、无默认值、无法校验。

### 2. `processing_depth` 白名单太窄，拒绝合法值

`fields_cmd.py:46` 硬编码白名单 `("concept", "memory")`，但代码实际产出了另外 4 个值：

| 值 | 来源 | 状态 |
|----|------|------|
| `"source"` | `ingest.py:524` 写死在 source 页上 | 被 fields_cmd 拒绝 |
| `"entity"` | `generator.py:62` `_DEPTH_BY_TYPE` fallback | 被 fields_cmd 拒绝 |
| `"synthesis"` | `generator.py:64` `_DEPTH_BY_TYPE` fallback | 被 fields_cmd 拒绝 |
| `"stub"` | `ingest.py:577` 写死在 stub 页上 | 被 fields_cmd 拒绝 |

任何 entity/synthesis/source/stub 页面跑 `fields validate` 都 FAIL。这不是功能缺失——是已有功能被校验误伤。

### 3. `wiki_rules_prompt.py` 文档与代码不一致

`WIKI_RULES_SUMMARY` 说 processing_depth 只有 `concept | memory`，但代码实际有 6 个值（4 个系统产生 + 2 个 LLM 可选）。这个文档被注入到 LLM prompt——LLM 看到的规范是错的。

---

## 改动

### A. WikiPage 补两个字段

```python
# src/wiki/core/types.py
category: str = ""       # 一级分类，空字符串 = 未分类
taxonomy_sub: str = ""   # 二级分类，空字符串 = 未分类
```

`to_frontmatter_dict()` 和 `from_dict()` 同步更新。

### B. processing_depth 正式分层

```python
# src/cli_ext/fields_cmd.py — 白名单从 2 值扩展到 6 值
_VALID_DEPTHS = {"memory", "concept", "source", "entity", "synthesis", "stub"}

if page.processing_depth not in _VALID_DEPTHS:
    errors.append(...)
```

### C. LLM schema + 构造调用同步

在 unified prompt 的 JSON schema 和旧 GENERATOR_PROMPT schema 中新增 `category`、`taxonomy_sub`（optional string），以及 `processing_depth`（enum: `["memory", "concept"]`）。

同步更新 `unified_generate()` 和 `generate()` 中 `WikiPage(...)` 构造调用，加 `category=p.get("category", "")` 和 `taxonomy_sub=p.get("taxonomy_sub", "")`。LLM 不输出时 fallback 到空字符串。

### D. wiki_rules_prompt.py 同步

`WIKI_RULES_SUMMARY` 和 `FRONTMATTER_RULES` 更新为与代码一致。

---

## 修改文件

```
src/wiki/core/types.py           # +category +taxonomy_sub, to_frontmatter_dict/from_dict 更新
src/cli_ext/fields_cmd.py        # processing_depth 白名单从 2 值扩展到 6 值
src/pipeline/generator.py        # unified + legacy schema 加 category/taxonomy_sub/processing_depth
src/pipeline/wiki_rules_prompt.py # WIKI_RULES_SUMMARY 同步
```

## 验收标准

- [ ] `WikiPage(category="", taxonomy_sub="")` 构造正常，`from_dict` → `to_frontmatter_dict` 往返一致
- [ ] 已有 entity 页（`processing_depth: entity`）跑 `fields validate` → OK
- [ ] 已有 source 页（`processing_depth: source`）跑 `fields validate` → OK
- [ ] 新摄取页面 category/taxonomy_sub 字段正确落盘
- [ ] 全量测试通过（注意：`test_types.py` 中断言 `to_frontmatter_dict()` 输出 key 集合的用例需同步更新——多了 2 个新字段 key）

---

## 不做的（有意识放弃）

| 放弃项 | 原因 |
|--------|------|
| `source_tier` 输入分级 | 按字数分级不合理——你 domain 的短内容（技巧总结、书评）信息密度往往高于长内容 |
| `maturity` 字段 | solo 项目不需要 draft→ready→verified 审批流 |
| 砍 `is_immutable` | 工作正常，不值得为"更优雅"改 6 个文件 |
| LLM 不再输出 `grade` | LLM 自评 grade 是有效的质量信号，pipeline 二元判定（有/无下游页）反而丢失信息 |
| 默认值省略 | 纯 cosmetic，solo 项目没差 |
| taxonomy 词表校验 | 项目就一个 domain，靠 LLM 自由发挥够用 |
| export / health 三档 / skip 分析 | 等实际痛了再建，现在建可能猜错需求 |
