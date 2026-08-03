# 性核对报告

> Date: 2026-08-03  
> 范围：`docs/guides/wiki-spec.md` ↔ 当前 `src/` 实现  
> 结论：**大体一致，但存在 1 处严重偏差 + 1 处中等偏差 + 2 处轻微偏差**。规范整体落后于代码演进。  
> 约束：**本次仅核对，未改动任何代码 / 文档**。

---

## 一、核对结论速览

| 维度                                        | 结果                                          |
| ----------------------------------------- | ------------------------------------------- |
| ID 规则（pattern / max_length 64 / reserved） | ✅ 一致                                        |
| `card_` UUID v7 生成格式                      | ✅ 一致                                        |
| slugify CJK 行为                            | ✅ 完全一致（含 `混Test合`→`混-test-合`、`café`→`café`） |
| Frontmatter 必填字段                          | ✅ 一致                                        |
| Body 规则（min1/max50000/wikilink/子集）        | ✅ 一致                                        |
| 标签前缀（10 中文前缀）                             | ✅ 一致                                        |
| v2.3 slots 生成 + 模板版本 2.0.0                | ✅ 一致                                        |
| LINT-MISSING-SECTION / CLI 子命令 / sync 脚本  | ✅ 一致                                        |
| **PageType 数量（4 vs 8）**                   | 🔴 **严重不一致**                                |
| **bundled 模板覆盖（4 vs 8）**                  | 🔴 **严重不一致**                                |
| Frontmatter 可选字段集合                        | 🟡 不一致（代码多 5 个字段）                           |
| v2.4 行号引用（`:174-180`）                     | 🟡 不一致（行号已失效）                               |
| 标签示例值（`素材/book`、`素材/excerpt`）             | 🟢 与 TAG_VALUES 冲突                          |

---

## 二、完全一致项（核对通过）

| #  | 规范声称                                                                    | 代码实证                                            | 位置                                                                                                                   |
| -- | ----------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 1  | ID 正则 `^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-一-鿿]+｜[a-z0-9-一-鿿]+)$` | 完全相同                                            | `src/wiki/core/id_generator.py:32`、`src/maintenance/checks/h4_id_format.py:16`、`src/pipeline/wiki_rules_prompt.py:4` |
| 2  | `max_length: 64`、reserved `[index, log]`                                | 相同                                              | `wiki_rules_prompt.py:5-6`                                                                                           |
| 3  | `card_` 格式 `card_<13hex>_<8hex>_<slug>`                                 | `f"card_{millis:013x}_{rand}_{slug}"`           | `src/wiki/core/id_generator.py:8-11`                                                                                 |
| 4  | slugify：`混Test合`→`混-test-合`、`café`→`café`、CJK 保留、NFC                    | 行为逐字吻合                                          | `src/utils/slugify.py:26-38`（docstring 示例）+ 实现                                                                       |
| 5  | Frontmatter 必填 `[id, title, type]`                                      | `WikiPage` 三字段必填                                | `src/wiki/core/types.py:55-57`                                                                                       |
| 6  | Body：`min_length 1` / `max_length 50000` / `[[slug]]` / 子集              | `BODY_RULES` 一致                                 | `wiki_rules_prompt.py:14-19`                                                                                         |
| 7  | 标签 10 中文前缀                                                              | `TAG_PREFIXES` 10 项吻合                           | `src/wiki/features/tag_namespace.py:15-29`                                                                           |
| 8  | v2.3 `slots` 替代 `body_markdown` + 模板 2.0.0                              | Generator 强制 slot 填充；bundled 模板含 \`\`           | `src/pipeline/generator.py:5-11,168+`、`src/wiki/templates/bundled/concept.md:1`                                      |
| 9  | `LINT-MISSING-SECTION` 仅对 ≥2.0.0 页面                                     | 规则存在                                            | grep `LINT-MISSING-SECTION` 命中                                                                                       |
| 10 | `wiki-templates` / `wiki-migrate-source-slugs` CLI                      | 子命令存在                                           | `src/cli_ext/wiki_templates_cmd.py`、`migrate_source_slugs_cmd.py:193`                                                |
| 11 | 规范由 `scripts/sync_wiki_spec.py` 自动生成规则文件                                | 脚本存在；`wiki_rules_prompt.py:1` 标注 auto-generated | `scripts/sync_wiki_spec.py`                                                                                          |

---

## 三、不一致项（按严重度）

### 🔴 1. PageType 数量：规范写 4，代码是 8（严重）

- **规范**（wiki-spec.md:78、§"PageType 语义（4 种）"107-128）：`type` 只有 `source | entity | concept | synthesis` 四类，并详述 4 类判定标准。
- **代码**（`src/wiki/core/types.py:10-18`）：`PageType` 枚举实际有 **8 个值**：
  ```
  SOURCE, ENTITY, CONCEPT, SYNTHESIS, CLAIM, DECISION, PROCEDURE, EVENT
  ```
- **影响**：
  - `CLAIM / DECISION / PROCEDURE / EVENT` 四类**在规范中完全无文档**（无语义、无判定标准、无例子）。
  - 自动生成的 `wiki_rules_prompt.py:78` 同样只写 4 类——说明 `sync_wiki_spec.py` 的读取源（规范正文）从未更新，导致**规则文件也落后于枚举**。
  - LLM 提示词里若仍只引导 4 类，新类型页面可能永远不被生成；或 Analyzer 输出的 `type` 落到 8 值之一时，规范无法解释其语义。
- **根因**：枚举在 v2.x 后期扩展（KOS 演进引入 claim/decision/procedure/event），但规范与 sync 脚本未同步。

### 🔴 2. bundled 模板只覆盖 4 类（严重）

- **规范**（wiki-spec.md:173）："每种 PageType 在 bundled/ 都有 4-5 个章节骨架"。
- **代码**（`src/wiki/templates/bundled/`）实际只有：
  ```
  concept.md  entity.md  source.md  synthesis.md
  ```
  **`claim/decision/procedure/event` 四类无任何 bundled 模板。**
- **影响**：按 v2.3 流程，Generator 按 `type` 取模板填充 slot；缺少模板的类型要么回退到通用模板（结构不一致），要么渲染失败。规范"每类型都有骨架"的承诺对 4 个新类型不成立。

### 🟡 3. Frontmatter 可选字段：代码比规范多 5 个（中等）

- **规范 optional 列表**（wiki-spec.md:9）：`sources, relations, grade, processing_depth, is_immutable, heat, last_used_at, zombie_since, tags`
- **代码 `to_frontmatter_dict()`**（`types.py:79-102`）实际还写出：
  ```
  created_at, updated_at          # 时机字段，规范未列入 required/optional
  category, taxonomy_sub          # v3.1 分类字段（规范完全未提）
  related_entities                # C3 内联实体引用（规范完全未提）
  _ko_extra                       # 知识层扩展（条件写入）
  ```
- **影响**：规范 + 自动生成的 `FRONTMATTER_RULES.optional` 都落后于 `WikiPage`，导致：
  - lint / 审计工具若按规范 optional 列表校验，可能把 `category`/`taxonomy_sub`/`related_entities` 误报为未知字段。
  - 接手者无法从规范得知这 3 个业务字段的存在与含义。

### 🟡 4. v2.4 行号引用已失效（中等，逻辑仍对）

- **规范**（wiki-spec.md:240）声称 source_slug 实现在 `src/pipeline/ingest.py:174-180`。
- **实际**：`ingest.py:174-186` 当前是 `_resolve_wikilinks` / `_compute_reverse_relations`（wikilink 解析），**并非 source_slug 代码**。
- **真实位置**：`src/pipeline/ingest.py:561-565`：
  ```python
  _norm_stem_for_slug = unicodedata.normalize("NFC", _raw_stem_for_slug)
  _slug_stem_for_map = slugify(_norm_stem_for_slug)
  _path_hash_for_slug = hashlib.md5(...).hexdigest()[:8]
  ```
- **影响**：代码逻辑（NFC stem + md5[:8]）与规范描述一致，仅**行号引用过期**，会误导接手者定位。

### 🟢 5. 标签示例值与 TAG_VALUES 冲突（轻微）

- **规范**（wiki-spec.md:98）标签示例：`素材/ugc`、`素材/book`、`素材/excerpt`。
- **代码** `TAG_VALUES["素材"]`（`tag_namespace.py`）= `{ugc, official, 转载, 原创, 投稿}`。
- **冲突**：`素材/book` 与 `素材/excerpt` **不在允许值集合内**，会被 `is_valid_value()` 判为非法。规范示例本身在代码侧不合法。

---

## 四、建议动作（未执行）

| 优先级 | 动作                                                                                 | 说明                                                                          |
| --- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| P0  | 更新 wiki-spec.md 的 PageType 章节为 8 类，补 claim/decision/procedure/event 的语义+判定+例子      | 并重新运行 `scripts/sync_wiki_spec.py` 让 `wiki_rules_prompt.py` 同步（消除规则文件也落后的问题） |
| P0  | 为 claim/decision/procedure/event 补 bundled 模板（4 个 `.md`）                           | 否则 v2.3 渲染对这 4 类无骨架                                                         |
| P1  | 在规范 frontmatter 章节补 `created_at/updated_at/category/taxonomy_sub/related_entities` | 保持与 `to_frontmatter_dict()` 一致                                              |
| P1  | 修正 v2.4 行号引用 `:174-180` → `:561-565`                                               | 避免误导定位                                                                      |
| P2  | 修正标签示例 `素材/book`、`素材/excerpt` 为合法值（如 `素材/ugc`、`素材/原创`）                             | 与 `TAG_VALUES` 对齐                                                           |

> 注：以上动作涉及**修改文档**（wiki-spec.md）和**新增模板文件**（bundled/*.md），不属于本次"仅核对"范围。如确认，可单独执行。
