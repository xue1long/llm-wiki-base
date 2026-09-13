# Plan-Audit Round 1.5 复审报告：v2 → ruflo-kb 数据迁移（整改后复审）

> **审计人**：独立第三方 subagent（Round 1.5 复审）
> **审计日期**：2026-09-06
> **待审文档**：
> - `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration-audit-r1-comprehensive.md`（Round 1 综合报告）
> - `docs/research/2026-09-06-v2-to-ruflo-migration-survey.md`（调研报告 · 已新增 §12 D9a + §18 V6）
> - `docs/superpowers/plans/2026-09-06-v2-to-ruflo-migration.md`（实施方案 · 已新增 V6 路线图 + PR 1/2/3）
> - `docs/migration/2026-09-06-v2-acceptance.md`（验收清单 · 已新增 §V V6 + §K D9a）
> - `docs/adr/0008-v6-wiki-schema-extension-for-v2-migration.md`（ADR-0008 V6 schema 设计）
> **事实核查**：已回看 `src/wiki/core/types.py:194-308`、`src/wiki/storage/page_writer.py:117-121`、`src/services/capture.py:118-122`、`src/wiki/features/slug_aliases.py:57-145`、`src/wiki/features/tag_namespace.py:18-89`、`src/vector/store.py:39`

---

## 致命缺陷 ①（4 项 · 验证）

### ①-1 `_ko_extra` 不持久化

- **整改后状态**：✅ **已修复**（结构性升级）
- **证据**：
  - ADR-0008 §"Decision" D1-D4（行 42-65）列出 V6 9 字段写盘（`processing_depth / source_grade / platform / category / taxonomy_sub / use_context / workflow_state / capture_type / v2_origin`），明确"to_frontmatter_dict() 改为输出 V6 完整白名单（8-key + 9 字段 = 17-key）"。
  - 实施方案 §"PR 1"（行 79-150）：给出 `test_v5_frontmatter_round_trip` + `test_v6_full_frontmatter_round_trip` + `test_novel_wiki_card_no_regression` 三个 TDD 用例，要求 V5 8-key byte-level round-trip + V6 17-key round-trip + novel-wiki 抽样 10 张不回归。
  - 验收清单 §V-1（行 357-366）量化：WikiPage 字段 18 → 27、to_frontmatter_dict 输出 8 → 17、`_ko_extra` 逃生口保留、测试 ≥ 5 用例。
  - 验收清单 §V-5（行 401-435）有 `verify_v6_fields_persisted()` 脚本，抽样 50 张迁移卡断言 V6 9 字段全部在 frontmatter。
- **如何验证**：PR 1 合并后跑 `pytest tests/test_core/test_types.py -k "v5 or v6"` + `python scripts/verify_v6_persistence.py`，50 张抽样断言通过即可视为 ①-1 修复。
- **新引入风险**：
  1. **真实场景**：PR 1 引入 9 个 V6 字段后，`src/llm/prompts/generator.py` 等下游读取 `WikiPage.to_frontmatter_dict()` 输出的代码会看到 17-key，若按 `for k, v in dict.items()` 写盘会无变化（OK），但若下游代码假设 `_ko_extra` 是"全部未知字段聚合点"，则 V6 后某些字段（`processing_depth` 等）不再落到 `_ko_extra`，下游聚合逻辑会丢字段 → **需要在 ADR-0008 §"Consequences" 显式标注下游 grep `_ko_extra` 的代码位置**（目前 ADR 仅说"保留逃生口"，未 grep 调用点）。
  2. **真实场景**：V6 schema 落地后，`capture_context` / `evidence` 等历史 `_ko_extra` 字段仍走 `_ko_extra`（from_dict 第 263-296 行已处理 `source_status / memory.decision / evidence` 迁移），但迁移器 T1 是否同步移除这些键以避免双重存储？目前方案未说明 → **可能造成 frontmatter 字段冗余但不影响正确性**。
- **判定**：✅ **通过**（结构上修复；附带下游影响需在 PR 1 review 时补充）

---

### ①-2 capture type 映射冲突（v2 concept vs source）

- **整改后状态**：✅ **已修复**（用户拍板 D9a）
- **证据**：
  - 调研报告 §12 行 352-396：新增 D9a 决策 `type: concept` 落 `wiki/concepts/`；视频回溯走 `_ko_extra.video_id`；body 顶部插入 `<!-- capture-type: video-transcript -->`；设置 `page.capture_type = "video-transcript"`（V6 schema 字段）。
  - 调研报告 §12 行 359-376 提供 D9a vs D9b 对比表：清晰说明 D9a 保持路径一致 + capture 子类型仅作 body marker + WebUI 筛选通过 marker 实现。
  - 实施方案 T1 行 406-436：新增 `test_d9a_concept_card_with_capture_marker` + `test_d9a_entity_card_uses_inspiration_marker` 两个测试，断言 `type == "concept"` + `capture_type == "video-transcript"` + `v2_origin is True` + body 顶部含 capture marker。
  - 验收清单 §K 行 467-470：D9a 验收方法 4 条（type=concept 100% / capture marker 100% / `capture_type` 字段写入 / `_ko_extra.video_id` 非空）。
  - ADR-0008 行 8-12：明确 D9a 决策已被采纳。
- **如何验证**：T1 实施后跑 `pytest tests/test_wiki_migrate/test_v2_frontmatter.py -k "d9a"` + 验收 §K-D9a 抽样 50 张卡。
- **新引入风险**：
  1. **真实场景**：D9a 让 v2 概念卡仍走 `wiki/concepts/`，但 capture 子类型仅作 body marker；如果未来 WebUI 增加"按 capture_type 筛选"，需要 V6 schema 字段 `capture_type` 写入盘（已落地 ✅）；同时 D9a 让 WebUI"source 视图"看不到 v2 内容（行 369 已明示），但用户已接受这个权衡 → **风险已被用户拍板接受**。
  2. **真实场景**：`test_d9a_entity_card_uses_inspiration_marker` 行 429-435 注释说"entity 卡是否要 marker 留给调用方决策（默认不加）"，但 D9a 决策要求"body 顶部插入 capture marker"；entity 卡的 marker 注入存在歧义 → **需要在 T1 实现时明确 entity 卡是否注入 marker**。
- **判定**：✅ **通过**（D9a 决策已落地；entity 卡 marker 行为需 T1 明确）

---

### ①-3 v2 tag 不兼容（命名空间 + mandatory pair 强制）

- **整改后状态**：✅ **已修复**（V6 tag 命名空间扩展 + mandatory pair 条件化）
- **证据**：
  - ADR-0008 §"V6 Tag Namespace 扩展" D5-D7（行 66-86）：`TAG_PREFIXES` 加 5 前缀 `tool/scene/status/media/author`；`MANDATORY_PAIRS` 改为条件强制（仅当 `page_type == source` 且 platform 是 video 类时要求）；T1 转换器 `normalize_tags()` 把 v2 free-form 映射到受控 `prefix/value`，映射失败保留到 `_ko_extra._v2_legacy_tags`。
  - 实施方案 §"PR 2"（行 154-196）：4 个 TDD 用例（`test_v2_freetext_tag_no_longer_raises` / `test_source_card_with_video_platform_still_needs_mandatory` / `test_source_card_with_article_platform_no_mandatory` / `test_v2_namespace_prefix_recognized`）。
  - 验收清单 §V-2（行 369-377）：TAG_PREFIXES 新增 5 前缀、validate_tag_compliance 新参数、source 卡 + video 仍需 mandatory、concept/entity/synthesis 不强制、≥ 4 测试用例。
- **如何验证**：PR 2 合并后跑 `pytest tests/test_wiki_features/test_tag_namespace.py -k "v6 or v2"` + 抽样 50 个 v2 tag 输入 `validate_tag_compliance`。
- **新引入风险**：
  1. **真实场景**：D7（行 83-86）说"v2 自由文本 tag 自动归一化（不改原值，仅在迁移期）"，但 T1 实现是把 free-form CJK 标签（`网文创作`、`读者视角`）"映射到受控 prefix/value"——如果 `LEGACY_PREFIX_MAP`（行 46-55 `tag_namespace.py`）不含 `网文创作 / 读者视角 / 自审方法 / 写作技巧`，这些标签会落到 `_ko_extra._v2_legacy_tags`（保留原值），但**frontmatter `tags` 字段可能为空或只含 `tool/python` 等受控项** → 与 v2 原意（tag 是分类索引）不一致 → **方案需要明确归一化规则 + 哪些归一化失败可接受**。
  2. **真实场景**：`MANDATORY_PAIRS` 条件化的判定仅看 `page_type == "source"` + platform 是 video。但 v2 的概念卡也来自视频转录稿（按 D9a 决策），其 `platform` 字段在 `_ko_extra.platform` 而非新字段 `platform`（V6 写盘后为顶层 `platform`）；如果 T1 实现 `normalize_tags` 时不读取 `_ko_extra.platform` 而读 V6 字段，则 v2 概念卡的 mandatory pair 行为可能被错误判定 → **需要在 T1 + V6 schema 落地时同步约定 `_ko_extra.platform` 与顶层 `platform` 字段一致性**。
- **判定**：✅ **通过**（D5-D7 设计完整；但 tag 归一化失败兜底规则 + `_ko_extra.platform` 同步需要 T1 明确）

---

### ①-4 vector rebuild 不存在 + 默认 384 维 + provider 未配

- **整改后状态**：✅ **已修复**（PR 3 + scripts/rebuild_vectors.py）
- **证据**：
  - ADR-0008 §"V6 Migration Tooling" D8（行 88-94）：新增 `scripts/rebuild_vectors.py`，接受 `--project <id>` 参数，内置 provider 自检（`llm-providers list` + health check）。
  - 实施方案 §"PR 3"（行 200-235）：文件清单含 `scripts/rebuild_vectors.py` + `tests/test_wiki_migrate/test_rebuild_vectors.py`。
  - 实施方案 §"Phase 4" T10 步骤 3（行 875）：明确"如果命令不存在，写一个 `scripts/rebuild_vectors.py`"——但 **ADR-0008 D8 已经把这个脚本纳入 PR 3**，所以 T10 步骤 3 不需要"如果命令不存在"分支。
  - 验收清单 §E1（行 180-185）：向量维度 "1536"——这里有歧义：事实核查发现 `src/vector/store.py:39` `DEFAULT_EMBEDDING_DIM = 384`（不是 1536！）；调研报告 §4.3 行 137 写"1536-dim 向量库"——**文档与代码不一致**。
- **如何验证**：PR 3 合并后跑 `python scripts/rebuild_vectors.py --project <id> --dry-run` → 断言 provider 已配 + 维度匹配。
- **新引入风险**：
  1. **真实场景（严重）**：验收清单 §E1（行 185）"向量维度 1536" 与 `src/vector/store.py:39` `DEFAULT_EMBEDDING_DIM = 384` 不一致——如果 user 配的 embedding provider 是 384-dim（MiniMax / Kimi / GLM），rebuild_vector_schema(dim=1536) 会失败；如果配的是 1536-dim（OpenAI text-embedding-3-small），则与 DEFAULT_EMBEDDING_DIM 不匹配，需要 `rebuild_vector_schema(paths, dim=1536)` → **验收 §E1 必须改为"`expected_dim = embedding_provider.dim()`而非硬编码 1536"**。
  2. **真实场景**：T10 步骤 1（行 873）要求先 `serve`，但 `init_vector_store_for_paths(WikiPaths)` 在 server lifespan 自动调（CLAUDE.md 行 75）；如果 user 没配 LLM provider，server 启动时 `embedding_runtime.get_embedding_provider()` 抛 RuntimeError → **T10 必须前置 step 0：`python -m src.cli llm-providers list` 验证 provider 已配**，目前方案未明确要求。
  3. **真实场景**：Round 1 综合报告 ①-4 行 75 说"video-notes-wiki 项目没有 LLM provider 配置（`~/.config/ruflo-kb/llm-providers.json` 不存在）"——ADR-0008 D8（行 94）已加 provider 自检，但**文档未列出 user 在 Phase 0 PoC 前必须执行的步骤**（如 `python -m src.cli llm-providers add <name> ...`）。
- **判定**：⚠️ **需补充**（`scripts/rebuild_vectors.py` 已规划；但**维度 384 vs 1536 文档与代码不一致 + provider 前置配置步骤缺失**需立即修复）

---

## 重大隐患 ②（8 项 · 验证）

### ②-1 slug_aliases 反向格式 → 改用正向格式

- **整改后状态**：⚠️ **部分修复**（决策改了，但**测试代码自相矛盾**）
- **证据**：
  - 事实核查 `src/wiki/features/slug_aliases.py:57`：`self.aliases: dict[str, str] = {}` 是**正向** `{alias: canonical}`；`save()`（行 75-85）写盘 `payload = {"aliases": self.aliases, ...}` 即正向。
  - 调研报告 §12 行 391：决策"**正向格式** `{alias: canonical}` 写入 `.llm-wiki/slug_aliases.json`（修正自 ②-1 重大隐患）"——✅ 决策正确。
  - 验收清单 §K-D5（行 458）："**正向格式**（②-1 修复）| JSON 结构是 `{"alias": "canonical"}` 不是 `{"canonical": [aliases]}` | 正向"——✅ 验收正确。
  - **但实施方案 T3 `test_extract_aliases_from_entity_card`（行 513-517）仍然写 `assert aliases["Claude Code"] == ["claude-code", "ClaudeCode"]`**——这是**反向格式**！注释行 548 也写"输出格式与 ruflo-kb `SlugAliasRegistry` 兼容（`{canonical_slug: [aliases...]}`）"——**与 ADR-0008 决策矛盾**！
- **如何验证**：T3 实施时该测试必须改为正向格式，例如 `assert aliases == {"claude-code": "Claude Code", "ClaudeCode": "Claude Code"}`。
- **新引入风险**：
  1. **真实场景**：如果 implementer 直接照抄 T3 测试代码，会写出"反向格式"JSON，落盘到 `slug_aliases.json` → `_load()` 第 71-73 行 `for alias, canonical in self.aliases.items():` 会把反向 JSON 当正向遍历，得到"alias='claude-code', canonical=['claude-code', 'ClaudeCode']"——`aliases_rev['['claude-code', 'ClaudeCode']'] = ['claude-code']` → `get_canonical('claude-code')` 永远返回 None → **C3 验收 FAIL**。
  2. **真实场景**：T3 测试 `test_write_aliases_to_registry`（行 531-543）传入 `registry = {"Claude Code": ["claude-code", "ClaudeCode"]}` 然后断言 `data["Claude Code"] == [...]`——如果实现按正向格式，会写 `{"aliases": {"Claude Code": [...]}}` 然后断言通过，但 `_load()` 第 69 行 `self.aliases = dict(raw.get("aliases") or {})` 把 `"Claude Code"` 当 alias key，`["claude-code", "ClaudeCode"]"` 当 canonical value → **后续 get_canonical 失效**。
- **判定**：❌ **仍需修复**（T3 测试代码本身违反 ADR 决策；这是把 Round 1 的"逻辑断层"原样复制到了整改后文档）

---

### ②-2 raw 撞名 126 个 → --on-collision fail + dry-run 报告

- **整改后状态**：✅ **已修复**
- **证据**：
  - 调研报告 §7.2 行 240："若有撞名时再加前缀" + D4 决策（行 347）："--on-collision fail（②-2 修复）"。
  - 实施方案 D4（行 282）："`--add-platform-prefix` flag 仅用户显式开启；撞名时 `--on-collision fail`（②-2 修复）"。
  - 实施方案 T5 `test_collision_detection`（行 666-674）：覆盖两个 v2 文件映射到同一目标的撞名检测。
  - 验收清单 §K-D4（行 455-456）："`raw_filename_collisions.csv` ≤ 126 行（实测撞名数）| `--on-collision` 默认 fail | 撞名时迁移器 abort"——把"撞名报告 0 行"改为"≤ 126 行"，符合实测数据。
- **如何验证**：Phase 2 全量迁移前跑 `--dry-run`，断言 `collision_report.csv` 行数 ≤ 126 + 全部条目含 `src_path/dst_path/suggested_resolution`。
- **新引入风险**：
  1. **真实场景**：默认 `--on-collision fail` 意味着 126 个撞名中任何一个都会让整个迁移 abort——这与"保守迁移、保留 v2 原貌"原则冲突：v2 自己就跑得好好的，迁移器撞名就 abort 太激进 → **建议改为默认 `skip` + 输出 collision_report.csv + 用户审查后决策**（仅在 user 显式 `--on-collision fail` 时才 abort）。但当前方案已经定调，可接受。
  2. **真实场景**：撞名报告的 `suggested_resolution` 字段在 D4 / T5 中都没明确生成规则（如"加 bilibili__ 前缀 / 加 douyin__ 前缀 / 保留 v2 原名 / 跳过"）——**需要 T5 实现时显式定义 4 种 resolution 的判定逻辑**。
- **判定**：✅ **通过**（行为已定义；`suggested_resolution` 规则待 T5 实现时补全）

---

### ②-3 wikilink 静默改写 → 手工 yaml.dump 绕过 write_page

- **整改后状态**：⚠️ **部分修复**（方案 B 选定，但**未在 T1 实现细节中体现**）
- **证据**：
  - 事实核查 `src/wiki/storage/page_writer.py:117-121`：`page.body = materialize_relations(rewrite_wikilinks(page.body, target_slugs), page.relations, target_slugs, ...)`——✅ 确实会静默改 body。
  - Round 1 综合报告 ②-3 行 124-127：整改建议"方案 B（推荐）：迁移器手工 `yaml.dump + safe_write`，完全绕过 `write_page`"。
  - **但实施方案 T1（行 318-444）** 的 `convert_frontmatter` 函数只描述了 dict 转换 + `_ko_extra` 注入 + D9a type/capture marker，**未明确提到手工 yaml.dump + safe_write**；T1 的 acceptance 行 442 写"100% v2 字段在输出 dict 中可访问"——这是 dict 层面，没说如何写盘。
  - 验收清单 §V-5 `verify_v6_fields_persisted.py`（行 405-433）用 `md.read_text(encoding="utf-8")` + `yaml.safe_load(fm_text)` 反推 frontmatter——**间接验证了手工写盘的可行性**（绕开 page_writer.read_page）。
- **如何验证**：T1 实现后跑 Phase 0 PoC，抽样 5 张卡，断言 `cat wiki/concepts/BV1xxx.md` 显示的 wikilink 形态与 v2 原文件 `cat 20_wiki/concepts/BV1xxx.md | grep '\[\['` 完全一致。
- **新引入风险**：
  1. **真实场景**：T1 如果仍用 `write_page`（仅靠 PR 1 的 V6 schema 修复 9 字段写盘），则 wikilink 形态仍被 rewrite_wikilinks 改写 → **C1 验收 FAIL**（"v2 原 body 形态被破坏"）。
  2. **真实场景**：手工 `yaml.dump + safe_write` 绕开 page_writer，但 page_writer 的 `append_to_index` + `log_event`（CLAUDE.md 行 96）也被绕开 → **T1 实施后 wiki/index.md 和 wiki/log.md 不会自动更新**——这正是 ③-2 优化疏漏的根因！
- **判定**：⚠️ **需补充**（T1 实施细节必须显式声明"手工 yaml.dump + safe_write + 手工 append_to_index + 手工 log_event"；当前方案 T1 描述只覆盖了一半）

---

### ②-4 pending 富元数据丢失 → 追加到 main `_ko_extra`

- **整改后状态**：⚠️ **部分修复**（D1 决策改了，但**元数据追加机制未在 T1/T6 体现**）
- **证据**：
  - Round 1 综合报告 ②-4 行 130-138：整改建议"pending 的 `_ko_extra.view_count/uploader/video_published_at` 等**追加到 main 的 `_ko_extra`**"。
  - 调研报告 §12 行 344：D1 决策"`_to_recompile/` 155 张草稿如何处理？保留为 `wiki/_pending/` 子目录"——只说保留为子目录，**未提到把 pending 的 `view_count/uploader/video_published_at` 合并到 main 的 `_ko_extra`**。
  - 实施方案 T6（行 686-734）：只覆盖 pending 检测 + main_wins 冲突 + 写入 `_pending/` 子目录——**未实现 pending 元数据追加到 main `_ko_extra` 的逻辑**。
  - 验收清单 §K-D1（行 447-449）：D1 验收只检查 `_pending/` 子目录文件数 + `pending_decisions.csv` 存在——**未检查 main 的 `_ko_extra` 是否含 pending 的 view_count/uploader**。
- **如何验证**：Phase 2 全量迁移后抽样 20 张 pending 与 main 同名的卡（如 `BV1AtwLzTEtB`），读 main `wiki/concepts/BV1AtwLzTEtB.md` frontmatter，断言 `_ko_extra.view_count` / `_ko_extra.uploader` / `_ko_extra.video_published_at` 非空。
- **新引入风险**：
  1. **真实场景**：D1 决策把 pending 移到 `_pending/`，main 仍在 `concepts/`——如果 user 后续 promote pending 为 main（手动编辑），main 已经有部分字段，pending 又有另一部分字段，**手动合并很容易丢失字段**。方案应提供 `tools/promote_pending.py` 把 pending 字段 diff 出来作为合并指导，但未规划。
  2. **真实场景**：未实现的"pending 元数据追加到 main `_ko_extra`"导致 view_count（视频热度）/ uploader（UP 主识别）数据永久丢失 → **违背用户 §16 5 重视频 ID 追溯诉求**（行 547-553）。
- **判定**：❌ **仍需修复**（pending 富元数据合并机制未在 T6 实现；验收 §K-D1 缺字段检查项）

---

### ②-5 Phase 4 失败无回滚 → rollback_phase1to3

- **整改后状态**：✅ **已修复**（文档层面）
- **证据**：
  - 调研报告 §12 行 394：D8 决策"Single-run 全量迁移；失败时回滚"——已含回滚。
  - 实施方案 D8（行 286）："Phase 4 失败时回滚 Phase 1-3（②-5 修复）"——已绑定 ②-5 修复。
  - 验收清单 §K-D8（行 466）："`python -m src.cli migrate-v2 --rollback-phase1to3` | 工作"——已定义回滚子命令。
  - 实施方案 Audit Rollback（行 894-901）：列出 Phase 0-1 / Phase 2-3 / Phase 4 / 完全回滚 4 级方案。
- **如何验证**：实施时跑 `python -m src.cli migrate-v2 --apply`，中途 Ctrl+C 后跑 `--rollback-phase1to3`，断言 `wiki/concepts/*.md` 全部回退到迁移前状态。
- **新引入风险**：
  1. **真实场景**：rollback_phase1to3 是 Phase 1-3 数据回滚的子命令，但 Phase 0 PoC 阶段（迁移 5 张卡）如果失败，没有回滚机制——**需要在 Phase 0 PoC 也加 rollback 子命令或确认 `--dry-run` 不写盘**。
  2. **真实场景**：回滚子命令的实现没具体说明如何"删 wiki/concepts/*.md"——可能误删 novel-wiki 同名文件 → **rollback 必须限定 `--target video-notes-wiki` 项目 ID + 仅删 `<project_root>/wiki/` 树**。
- **判定**：✅ **通过**（已规划子命令；实施时需明确回滚路径限定）

---

### ②-6 CWD 路径稳定性 → --target 语义 + 绝对路径

- **整改后状态**：⚠️ **部分修复**（语义基本定义，但**未明确 CWD 处理 + PowerShell 中文路径**）
- **证据**：
  - 实施方案 T7（行 738-773）`--target <target>` 参数已定义；但**未说明 `--target` 是项目名 / UUID / 路径**。
  - 实施方案 T8（行 786）：步骤 2 "Dry-run 一次：`python -m src.cli migrate-v2 --v2-path <v2 路径> --target <target> --dry-run > dry_run.log`"——`<v2 路径>` 是相对还是绝对？中文+空格路径如何处理？
  - 调研报告 §15（行 487-495）已确认目标项目路径是 `D:\5-Project\20260903\llm-wiki-base\knowledge\video-notes-wiki`（含连字符无空格），但 v2 路径 `D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\` **含中文+空格**（`5- 项目`）。
  - 实施方案 Audit Rollback（行 901）：`python -m src.cli project forget e3a0472c-06af-41e4-8d06-083146f195f7 --delete-data`——UUID 形式 OK；但 migrate-v2 的 --target 仍是占位符。
- **如何验证**：PoC 时用 `python -m src.cli migrate-v2 --v2-path "D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\" --target e3a0472c-06af-41e4-8d06-083146f195f7 --dry-run`，断言成功找到项目。
- **新引入风险**：
  1. **真实场景**：PowerShell 调用 `Set-Location "D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\"` 后 `python -m src.cli project list` 会失败（CLAUDE.md 行 35："CLI is CWD-sensitive"），因为 `src/lib/project.py:31` `ProjectContext.resolve()` 依赖全局注册表 → **T7 必须显式 `cd` 到 video-notes-wiki 根目录而非 v2 根目录，或用 `--project <uuid>` 全局参数**。
  2. **真实场景**：v2 路径 `D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\` 含中文 + 空格，PowerShell 直接传字符串会因词法拆分错位 → **T7 必须强制 `--v2-path` 接绝对路径并用 `pathlib.Path` 处理**。
- **判定**：⚠️ **需补充**（`--target` 语义需在 T7 明确为 UUID；PowerShell 中文路径处理需在 T7 实现时用 pathlib）

---

### ②-7 capture marker 未实现 → T1 注入 marker

- **整改后状态**：✅ **已修复**（T1 测试已加 capture marker 注入）
- **证据**：
  - 调研报告 §12 行 379：D9a "T1 同步在 `page.body` 顶部插入 `<!-- capture-type: video-transcript -->\n\n`（如果 v2 body 不含此 marker）"。
  - 实施方案 T1 `test_d9a_concept_card_with_capture_marker`（行 406-427）：明确断言 `body.startswith("<!-- capture-type: video-transcript -->")`。
  - 验收清单 §K-D9a（行 468）："body 顶部 capture marker | 抽样 50 张卡 → 100% 以 `<!-- capture-type: video-transcript -->` 开头"。
- **如何验证**：T1 实施后跑 `pytest -k d9a` + Phase 0 PoC 抽样 5 张概念卡 `head -1 wiki/concepts/BV1xxx.md`。
- **新引入风险**：
  1. **真实场景**：marker 仅对 video-transcript 注入，但 v2 卡里 `02_抖音视频笔记/` 也用同一类型——OK；但 `01_B站视频转录/` 和 `02_抖音视频笔记/` 都属 video-transcript，但 `_to_recompile/` 草稿的 concept 卡是否也要 marker？D9a 决策行 379 写"如果 v2 body 不含此 marker"——T1 实现需要确认 `processing_depth == "memory"` 的卡（v2 草稿常见）是否也要注入 marker。
  2. **真实场景**：T1 marker 注入仅对 concepts/*.md（concept 类型），但 entity 卡 `test_d9a_entity_card_uses_inspiration_marker`（行 429-435）注释"entity 卡是否要 marker 留给调用方决策（默认不加）"——**entity 卡 marker 行为不明确**，需要 ADR-0008 或 T1 文档补一句。
- **判定**：✅ **通过**（核心修复到位；entity 卡 marker 行为待 T1 实现时确认）

---

### ②-8 migration_target 字样残留 → 全部替换为 video-notes-wiki

- **整改后状态**：✅ **已修复**
- **证据**：
  - 实施方案 Audit Rollback（行 894-901）：Phase 2-3 "删除 `knowledge/video-notes-wiki/` 目录" / "删除 `.index/lancedb/`，重新 init" / "完全回滚：`git revert` 全部 commit + 删除 `knowledge/video-notes-wiki/` 目录"——已用 `video-notes-wiki`，未保留 `migration_target` 字样。
  - 实施方案 §"目标项目"（行 11-18）：明确"实例名 = `video-notes-wiki`"、"项目根路径 = `D:\5-Project\20260903\llm-wiki-base\knowledge\video-notes-wiki`"。
  - 验收清单 §"目标项目"（行 7-11）：已用 `video-notes-wiki`。
  - 调研报告 §15（行 487-495）：已用 `video-notes-wiki`。
- **如何验证**：`grep -rn "migration_target" docs/` 应 0 命中。
- **新引入风险**：无（仅是字样替换，无逻辑风险）。
- **判定**：✅ **通过**

---

## 优化疏漏 ③（9 项 · 验证）

### ③-1 wiki_pages.confidence 未迁

- **整改后状态**：❌ **未修复**
- **证据**：
  - Round 1 综合报告 ③-1 行 186："v2 SQLite `wiki_pages.confidence` 字段未迁移（LLM 自评置信度）"。
  - 整改后调研报告 §8（行 248-256）数据库处置：仅说"导出为 CSV 留在 v2 项目根目录"，**未提及 confidence 字段保留到 `_ko_extra.confidence`**。
  - 实施方案 D3（行 281）："v2 业务字段 → `_ko_extra`" 列举 12+ 字段，但**未显式包含 confidence**。
  - 验收清单 §B2（行 70-87）：`_ko_extra` 字段抽样列表含 14 项 + `_v2_origin`，**不含 confidence**。
- **如何验证**：T1 实施后抽样 50 张卡断言 `_ko_extra.confidence` 存在（如 SQLite 中 record.confidence = 0.85）。
- **新引入风险**：低，但 LLM 自评置信度对 v2 知识可信度评估有用。
- **判定**：❌ **未修复**（confidence 字段未被列入 `_ko_extra` 字段清单；建议补充到 T1 acceptance + 验收 §B2）

---

### ③-2 index.md / log.md 重生成

- **整改后状态**：⚠️ **部分修复**（依赖手工路径，未自动生成）
- **证据**：
  - Round 1 综合报告 ③-2 行 187："`wiki/index.md` + `wiki/log.md` 自动重生成步骤缺失"。
  - 整改后实施方案 T1 acceptance（行 442）只说 v2 字段在 dict 中可访问；**未提到手工触发 `append_to_index` + `log_event`**。
  - 调研报告 §17（行 605）"`docs/migration/2026-09-06-v2-migration-log.md`（执行日志）"——这是 docs/ 下的文档，不是 `wiki/log.md`（CLAUDE.md 行 35：`wiki/log.md` 是 wiki 内部审计轨迹）。
  - 验收清单 §A1（行 19-29）只检查文件数对账，**未检查 `wiki/index.md` 和 `wiki/log.md` 是否包含迁移条目**。
- **如何验证**：Phase 2 全量迁移后 `cat wiki/index.md | wc -l` ≥ 1924；`cat wiki/log.md | grep -c "migrated_from_v2"` ≥ 1。
- **新引入风险**：
  1. **真实场景**：如果 T1 用手工 `yaml.dump + safe_write`（②-3 整改），则 `append_to_index` 和 `log_event` 不会自动调（CLAUDE.md 行 96），`wiki/index.md` + `wiki/log.md` 会停留在初始（空或只有几条 v2 启动条目）状态 → **Phase 0 PoC 必须验证 `wiki/index.md` 包含迁移条目**。
- **判定**：⚠️ **需补充**（T1 必须显式调 `append_to_index(paths, page)` + `log_event("v2_migration", ...)`；验收 §A 增新检查项）

---

### ③-3 F1 60 秒假设过乐观

- **整改后状态**：❌ **未修复**
- **证据**：
  - 验收清单 §F1（行 306-313）："全量迁移 1924 张卡耗时 | ≤ 60 秒"。
  - **未重新评估**：调研报告 §11 行 332 标注"8-13 天（单人串行，TDD per task）"——开发工时包含 TDD；运行工时 60 秒假设未实测。
  - 调研报告 §9 R8（行 271）："raw 文件体量 3.2 GB；纯文件 IO，5 分钟内完成"——但 wiki 卡转换（frontmatter 解析 + wikilink 提取 + slug_aliases 校验 + safe_write）含 yaml.dump + 1919 张卡的逐卡 IO，单测或 PoC 时大概率超过。
- **如何验证**：Phase 0 PoC 跑 5 张卡测时；Phase 2 全量时用 `time python -m src.cli migrate-v2 --apply` 测时。
- **新引入风险**：
  1. **真实场景**：60 秒假设未实测，若实际耗时 5-10 分钟，F1 FAIL 触发"任何耗时超阈值 2x → WARN"（行 517），虽不阻塞但用户体验差 → **建议改为 ≤ 5 分钟**。
- **判定**：❌ **未修复**（60 秒假设未经实测验证；建议改为 ≤ 5 分钟）

---

### ③-4 H5 密度检查必 FAIL

- **整改后状态**：⚠️ **部分修复**（验收 §D1 H5 注明"v2 标签集中 taxonomy_sub → WARN 或 PASS"）
- **证据**：
  - 验收清单 §D1 H5（行 146）："密度（单 taxonomy_sub ≤ 150）| WARN 或 PASS"——✅ 已知 WARN 可接受。
  - 调研报告 §9 R10（行 273）：未提及 H5 风险。
- **新引入风险**：低（WARN 不阻塞迁移）。
- **判定**：✅ **通过**（H5 已在验收中接受 WARN）

---

### ③-5 `_v2_origin is True` 严格断言

- **整改后状态**：⚠️ **部分修复**（ADR-0008 + 实施方案已明确"v2_origin 字段"，但**未说明是否为 bool 还是 str**）
- **证据**：
  - ADR-0008 D1 表行 56："`v2_origin` | bool | `False` | 迁移标记"——✅ 类型 bool。
  - 实施方案 T1 `test_d9a_concept_card_with_capture_marker`（行 425）：`assert fm["v2_origin"] is True`——✅ 严格断言 bool。
  - Round 1 综合报告 ③-5 行 190："`_v2_origin` 用 `is True` 严格断言（容错性差）"——若 YAML 解析时把 `True` 写成 `true`，可能解析为 bool True（OK）；但若写为字符串 `"true"`，`is True` 失败 → **T1 必须保证 yaml.dump 时 v2_origin 是 bool**。
- **如何验证**：T1 实施后抽样 50 张卡，Python `yaml.safe_load` 后断言 `fm["v2_origin"] is True`（布尔值）。
- **新引入风险**：
  1. **真实场景**：PyYAML `yaml.dump({"v2_origin": True})` 会写 `v2_origin: true`（小写）→ `yaml.safe_load` 解析回 `True`（bool）——✅ OK。但若 T1 写 `v2_origin: "true"`（带引号字符串）则解析为字符串 `"true"`，`is True` 失败 → **T1 必须明确 yaml.dump 时不带引号**。
- **判定**：⚠️ **需补充**（T1 acceptance 增一条"yaml.dump 时 v2_origin 不带引号"约束）

---

### ③-6 tests/test_wiki_migrate/ conftest.py 缺失

- **整改后状态**：✅ **已修复**
- **证据**：
  - 实施方案 §"PR 3" Files（行 215）："`tests/test_wiki_migrate/conftest.py`"——✅ 已列入。
  - 实施方案 T1 Files（行 325）："`tests/test_wiki_migrate/conftest.py`"——✅ 已列入。
  - 事实核查 `tests/test_wiki_migrate/`：当前不存在（glob 无命中）——这符合 PR 3 实施前的预期。
- **如何验证**：PR 3 合并后 `tests/test_wiki_migrate/conftest.py` 文件存在 + 跑 `pytest tests/test_wiki_migrate/ -v` 不报 collection error。
- **新引入风险**：低（CLAUDE.md 行 36 已说明 conftest.py 是 stub heavy deps 的关键，需 copy 一个现有 conftest.py）。
- **判定**：✅ **通过**

---

### ③-7 dry-run 输出格式未定义

- **整改后状态**：⚠️ **部分修复**（T7 测试覆盖 --dry-run 输出，但不定义具体格式）
- **证据**：
  - Round 1 综合报告 ③-7 行 192："dry-run 输出格式未定义"。
  - 整改后实施方案 T7 `test_dry_run_outputs_plan`（行 747-750）："expect: stdout 包含 'DRY RUN', 不创建任何 wiki 文件"——只定义了部分关键字。
  - **未定义**：dry-run 输出的 CSV 格式 / JSON 格式 / 行数 / 字段清单。
- **如何验证**：Phase 0 PoC 跑 `--dry-run`，断言输出含每张卡的转换结果（输入路径 + 输出路径 + 字段数 + 撞名标记 + D9a type）。
- **新引入风险**：
  1. **真实场景**：用户审查 dry-run 时无标准格式可比对 → **建议在 T7 实施时定义 `dry_run_report.csv` schema**（列：source_path, target_path, file_type, v2_field_count, ko_extra_count, has_wikilinks, capture_type, v2_origin）。
- **判定**：⚠️ **需补充**（T7 应明确定义 dry-run 输出 schema）

---

### ③-8 v2 Changelog 无自动化

- **整改后状态**：⚠️ **部分修复**（D7 决策已锁定为"文档 + 流程（无代码）"，但**无具体执行步骤**）
- **证据**：
  - 调研报告 §12 行 350：D7 "v2 vault 迁移后冻结 | 追加 v2 `30_System/Changelog.md`「v2 已迁出」条目 | 文档 + 流程（无代码）"——✅ 决策锁定。
  - 验收清单 §K-D7（行 463-464）："v2 Changelog 追加条目 | 含 'v2 已迁出 2026-09-06'"——✅ 验收方法。
  - **但实施方案 T8 步骤（行 786-792）无 Changelog 步骤**：1-7 步全在跑迁移器，未列"追加 Changelog"步骤。
- **如何验证**：Phase 4 完成后 `cat "D:\5- 项目\000-Nico\LLM_Knowledge_base_v2\30_System\Changelog.md" | tail -3` 含迁移条目。
- **新引入风险**：低（仅文档级，user 可手动追加或 T8 步骤前加 step 8 "追加 Changelog"）。
- **判定**：⚠️ **需补充**（T8 步骤增 step 8 "追加 v2 Changelog 条目"）

---

### ③-9 WebUI smoke test 态度矛盾

- **整改后状态**：⚠️ **部分修复**（验收 §F-bis-5 仍标 WebUI 按钮，但 §E3 WebUI 是"可选"）
- **证据**：
  - 验收清单 §E3（行 201-208）："WebUI `http://127.0.0.1:19828/web/` | 页面加载（可选）"——✅ "可选"。
  - 验收清单 §F-bis-5（行 260-268）："WebUI 一键回溯 | 卡片详情页有'原视频'按钮 | 是 | [ ]"——**要求按钮必须存在**。
  - 矛盾点：§E3 WebUI 加载是可选，§F-bis-5 WebUI 按钮必须存在 → **如果 WebUI 加载是可选，§F-bis-5 的按钮必然无法验收**。
- **新引入风险**：
  1. **真实场景**：若 user 实际部署时不开 WebUI（只 CLI），§F-bis-5 验收无法跑 → **建议 §F-bis-5 加 "WebUI smoke test 通过为前提" 前置条件**，或拆分为 `f-bis-5a WebUI 按钮存在（仅当启用 WebUI）` + `f-bis-5b CLI 端 sources[0] URL 可访问（始终验证）`。
- **判定**：⚠️ **需补充**（§F-bis-5 与 §E3 的 WebUI 态度矛盾需调和）

---

## 新发现

### 新-1 ⚠️ V6 schema 17-key 写盘可能影响现有 PageType 路由

- **位置**：ADR-0008 §"Decision" D1 表 + 实施方案 §"PR 1"
- **风险**：V6 schema 加 9 字段后，`WikiPage.to_frontmatter_dict()` 输出从 8-key 增至 17-key，但 `_TYPE_TO_DIR` 映射（`types.py:137-142`）只基于 `type: PageType` 决定落盘目录，与 frontmatter 大小无关——✅ **无实际风险**，但 ADR-0008 未显式说明。
- **判定**：仅是文档完善项，无阻塞。

### 新-2 ⚠️ V6 字段 `platform` 与 v2 `_ko_extra.platform` 数据冗余

- **位置**：ADR-0008 §"Decision" D1 + 实施方案 D9a 实施细节
- **风险**：V6 schema `platform`（顶层）+ v2 `_ko_extra.platform`（逃生口）→ **同一字段两份存储**。T1 转换时如何处理？写入顶层 `platform` 后，是否同步保留到 `_ko_extra.platform`？
- **真实场景**：如果保留 `_ko_extra.platform`，则 `to_frontmatter_dict()` 17-key + `_ko_extra.platform` 共存；若不保留，则 §K-D3（行 452）"`_ko_extra.platform` 100% 非空" 验收 FAIL。
- **建议**：T1 写入 V6 顶层 `platform` + 同时保留 `_ko_extra.platform`（数据冗余可接受）；或者 V6 schema 实施时把 `_ko_extra.platform` 移除。
- **判定**：⚠️ **需明确**（T1 acceptance 增一条"platform 字段同步策略"）

### 新-3 ⚠️ PR 1/2/3 顺序与 Round 1.5 复审位置矛盾

- **位置**：实施方案 §"V6 路线图工时汇总"（行 240-251）
- **风险**：路线图说"Plan-Audit Round 1.5 复审在 PR 1+2 通过后，PR 3 之前"——但本次复审（Round 1.5）是在 PR 1+2+3 **全部设计完成（仅文档）**后做的，不是 PR 1+2 代码合并后做的。
- **真实场景**：如果 user 严格执行路线图顺序，先 PR 1 合并 → Round 1.5 复审 → PR 2 合并 → 又是 PR 1+2 复审 → PR 3 合并——这是多次复审，不是单次 Round 1.5。
- **建议**：本次复审实际上是"设计完成度审查"，应在 PR 1+2+3 **全部合并后**做综合复审；当前复审文档称之为 Round 1.5 与路线图描述不一致。
- **判定**：⚠️ **流程不一致**（不影响方案正确性，但流程文档需更新）

### 新-4 ⚠️ 验收清单 §K-D4 内部矛盾（撞名行数两处说法）

- **位置**：验收清单 §K-D4（行 454-456 + 487-488）
- **风险**：§K-D4 在第一处（行 454-456）写"≤ 126 行（实测撞名数）"；在第二处（行 487-488）写"不存在或 0 行"——**两处要求矛盾**。
- **真实场景**：第二处（行 487-488）似乎是整改前的旧版本残留，未删除。
- **判定**：⚠️ **需删除冗余段落**（行 477-498 是 §K 的副本，重复了第一处；保留一处即可）

### 新-5 ⚠️ 验收清单 §V-5 维度检查遗漏 `capture_type` 字段

- **位置**：验收清单 §V-5 `verify_v6_fields_persisted.py`（行 405-433）
- **风险**：`for v6_key in ["processing_depth", "source_grade", "platform", "category", "taxonomy_sub", "use_context", "workflow_state", "v2_origin"]:`——**8 个字段，V6 schema 是 9 字段，遗漏 `capture_type`**。
- **判定**：⚠️ **需补充 `capture_type`**（`capture_type` 字段写入持久化是 D9a 决策的关键交付，必须验证）

---

## 复审总结

| 维度 | Round 1 | Round 1.5 修复数 | 新引入问题 | 最终状态 |
|---|---|---|---|---|
| 致命缺陷 ①（4 项） | 4 | **3 ✅ + 1 ⚠️** | 0 | **3 ✅ 通过 / 1 ⚠️ 需补充** |
| 重大隐患 ②（8 项） | 8 | **5 ✅ + 2 ⚠️ + 1 ❌** | 0 | **5 ✅ / 2 ⚠️ / 1 ❌** |
| 优化疏漏 ③（9 项） | 9 | **2 ✅ + 5 ⚠️ + 2 ❌** | 0 | **2 ✅ / 5 ⚠️ / 2 ❌** |
| 新发现 | — | — | **5 项** | **1 ⚠️ 流程 + 4 ⚠️ 细节** |
| **总计** | 21 | **10 ✅ + 8 ⚠️ + 3 ❌** | **5** | **10 ✅ / 8 ⚠️ / 3 ❌ + 5 新发现** |

### 关键判定

| Round 1 问题 | 复审判定 | 必须修复项 |
|---|---|---|
| ①-1 `_ko_extra` 不持久化 | ✅ 通过 | 无 |
| ①-2 capture type 冲突 | ✅ 通过 | 无 |
| ①-3 v2 tag 不兼容 | ✅ 通过 | 无 |
| ①-4 vector rebuild + 384 vs 1536 | ⚠️ 需补充 | ①-4 验收维度改为 `embedding_provider.dim()`；T10 前置 step 0 验 provider |
| ②-1 slug_aliases 反向格式 | ❌ 仍需修复 | **T3 测试代码改为正向格式**（这是把 Round 1 逻辑断层原样复制） |
| ②-2 raw 撞名 126 | ✅ 通过 | T5 实现时定义 `suggested_resolution` 规则 |
| ②-3 wikilink 静默改写 | ⚠️ 需补充 | T1 显式声明"手工 yaml.dump + safe_write + 手工 append_to_index + 手工 log_event" |
| ②-4 pending 富元数据丢失 | ❌ 仍需修复 | **T6 实现 pending 元数据追加到 main `_ko_extra`；验收 §K-D1 增字段检查** |
| ②-5 Phase 4 回滚 | ✅ 通过 | rollback 路径限定项目 ID |
| ②-6 CWD 路径稳定性 | ⚠️ 需补充 | T7 明确 `--target` 是 UUID；用 pathlib 处理中文路径 |
| ②-7 capture marker | ✅ 通过 | entity 卡 marker 行为待 T1 明确 |
| ②-8 migration_target 字样 | ✅ 通过 | 无 |
| ③-1 confidence 未迁 | ❌ 未修复 | **T1 acceptance + 验收 §B2 增 `confidence` 字段** |
| ③-2 index.md / log.md 重生成 | ⚠️ 需补充 | T1 显式调 `append_to_index` + `log_event`；验收 §A 增检查 |
| ③-3 F1 60 秒假设 | ❌ 未修复 | **建议改为 ≤ 5 分钟** |
| ③-4 H5 密度 | ✅ 通过 | 无 |
| ③-5 v2_origin 严格断言 | ⚠️ 需补充 | T1 增 yaml.dump 不带引号约束 |
| ③-6 conftest.py | ✅ 通过 | 无 |
| ③-7 dry-run 输出格式 | ⚠️ 需补充 | T7 定义 `dry_run_report.csv` schema |
| ③-8 v2 Changelog 自动化 | ⚠️ 需补充 | T8 步骤增 step 8 "追加 Changelog" |
| ③-9 WebUI 态度矛盾 | ⚠️ 需补充 | §F-bis-5 拆分 5a WebUI（仅当启用） + 5b CLI URL 验证 |

### 新发现

| 新发现 | 判定 | 必须修复项 |
|---|---|---|
| 新-1 V6 17-key 写盘与 PageType 路由 | ⚠️ 文档完善 | ADR-0008 补一句 |
| 新-2 V6 `platform` 与 `_ko_extra.platform` 数据冗余 | ⚠️ 需明确 | T1 acceptance 增同步策略 |
| 新-3 Round 1.5 复审时机与路线图矛盾 | ⚠️ 流程 | 路线图描述更新 |
| 新-4 验收 §K-D4 内部矛盾 | ⚠️ 需删除 | 删除行 477-498 重复段落 |
| 新-5 §V-5 维度遗漏 `capture_type` | ⚠️ 需补充 | `verify_v6_fields_persisted` 循环增 `capture_type` |

---

## 总体判定

⚠️ **部分整改后需再复审（不能直接进入 Round 2 压力测试 / Phase 0 PoC）**

### 不通过的 3 个 ❌ 项（必须修复）

1. **②-1 slug_aliases 反向格式 → T3 测试代码自相矛盾**
   - 位置：实施方案 T3 `test_extract_aliases_from_entity_card`（行 513-517）+ 验收 §T3 acceptance（行 548）
   - 修复：T3 测试改为正向格式断言，例如 `assert aliases == {"claude-code": "Claude Code", "ClaudeCode": "Claude Code"}`
   - **这是把 Round 1 的"逻辑断层"原样复制到整改后文档**，优先级最高

2. **②-4 pending 富元数据丢失 → T6 未实现合并逻辑**
   - 位置：实施方案 T6（行 686-734）+ 验收 §K-D1（行 447-449）
   - 修复：T6 实现 pending view_count/uploader/video_published_at 合并到 main `_ko_extra`；验收 §K-D1 增字段检查项

3. **③-1 wiki_pages.confidence 未迁**
   - 位置：调研报告 §8 + 实施方案 D3 + 验收 §B2
   - 修复：T1 acceptance + 验收 §B2 `_ko_extra` 字段列表增 `confidence`（SQLite wiki_pages.confidence 字段保留）

### 必须补充的 8 个 ⚠️ 项（PR 3 实施前补全）

- **①-4**：验收 §E1 向量维度改为 `embedding_provider.dim()`；T10 前置 step 0 验 provider；ADR-0008 注明 `embedding_provider` 是 user 责任
- **②-3**：T1 显式声明"手工 yaml.dump + safe_write + 手工 append_to_index + 手工 log_event"
- **②-6**：T7 明确 `--target` 语义为 UUID；用 pathlib 处理中文路径
- **③-2**：T1 显式调 `append_to_index` + `log_event`；验收 §A 增 `wiki/index.md` 行数检查
- **③-3**：F1 时间假设改为 ≤ 5 分钟
- **③-5**：T1 增 yaml.dump 不带引号约束（v2_origin 字符串歧义）
- **③-7**：T7 定义 `dry_run_report.csv` schema
- **③-8**：T8 步骤增 step 8 "追加 v2 Changelog 条目"
- **③-9**：§F-bis-5 拆分为 5a WebUI（仅当启用） + 5b CLI URL 验证（始终验证）

### 必须处理的 5 个新发现

- **新-1**：ADR-0008 补一句"17-key 写盘不影响 _TYPE_TO_DIR 路由"
- **新-2**：T1 acceptance 增 `platform` 字段同步策略（V6 顶层 + `_ko_extra` 副本）
- **新-3**：路线图更新"Round 1.5 复审在 PR 1+2+3 全部合并后"
- **新-4**：验收清单删除行 477-498 重复段落
- **新-5**：`verify_v6_fields_persisted.py` 循环增 `capture_type` 字段

---

## 下一步建议

⚠️ **不能直接进入 Round 2 压力测试**

**流程**：

```
Round 1.5 复审（本次）──► 整改上述 3 ❌ + 8 ⚠️ + 5 新发现 ──► Round 1.6 复审
                                                              │
                                                              ▼
                                                   Round 2 压力测试
                                                              │
                                                              ▼
                                                   人工复核 + 最终拍板
                                                              │
                                                              ▼
                                                   Phase 0 PoC
                                                              │
                                                              ▼
                                                   Phase 1-4 TDD 实施
```

**关键结论**：

- 致命缺陷 ①-1 / ①-2 / ②-7 已被 ADR-0008 + 实施方案 T1 + D9a 决策**结构性修复**
- 重大隐患 ②-1（slug_aliases）看似修复，但 **T3 测试代码本身违反 ADR 决策**——这是整改文档自相矛盾
- 优化疏漏 ③-2 / ③-3 / ③-7 / ③-8 / ③-9 都是"已知问题但未落地具体步骤"，需在 PR 3 实施时补全
- 新发现 5 项都是细节完善项，可在 Round 1.6 复审时一并处理

**报告结束 · 21 项 Round 1 + 5 项新发现 = 26 项 · 10 ✅ + 11 ⚠️ + 5 ❌**

---

## 附录：复审过程中发现的关键证据点

### A. ruflo-kb 源码事实（已交叉验证）

| 引用位置 | 验证内容 | 状态 |
|---|---|---|
| `src/wiki/core/types.py:194-224` | `to_frontmatter_dict()` 8-key 白名单（V5） | ✅ 已确认 |
| `src/wiki/core/types.py:129-142` | `_TYPE_TO_DIR` 路由（4 种 PageType） | ✅ 已确认 |
| `src/wiki/storage/page_writer.py:117-121` | `rewrite_wikilinks` + `materialize_relations` 静默改 body | ✅ 已确认 |
| `src/services/capture.py:118-122` | `_TYPE_MAP` 写死 `video-transcript → source` | ✅ 已确认 |
| `src/wiki/features/slug_aliases.py:57-145` | `aliases` 正向 `{alias: canonical}` + `aliases_rev` 推导 | ✅ 已确认 |
| `src/wiki/features/tag_namespace.py:18-89` | `TAG_PREFIXES` 12 个中文前缀 + `MANDATORY_PAIRS` 硬性 | ✅ 已确认 |
| `src/vector/store.py:39` | `DEFAULT_EMBEDDING_DIM = 384`（不是 1536） | ✅ 已确认 |

### B. 整改后文档交叉引用

| 整改项 | 调研报告 | 实施方案 | 验收清单 | ADR-0008 |
|---|---|---|---|---|
| ①-1 V6 schema 9 字段 | §18（行 617-685） | PR 1（行 79-150） | §V-1/V-5 | D1-D4 |
| ①-2 D9a type=concept | §12（行 352-396） | T1（行 406-436） | §K D9a（行 467-470） | D9a |
| ①-3 V6 tag namespace | §18（行 639-660） | PR 2（行 154-196） | §V-2 | D5-D7 |
| ①-4 vector rebuild | §18（行 663-669） | T10（行 875） | §E1 | D8 |
| ②-1 slug_aliases 正向 | §12 行 391 | T3（行 506-548） | §K-D5（行 458） | — |
| ②-4 pending 富元数据 | §12 行 344 | T6（行 686-734） | §K-D1 | — |

### C. 整改后新发现的具体引用

| 新发现 | 具体引用 |
|---|---|
| 新-1 | ADR-0008 §"Decision" D1-D4（行 42-65） |
| 新-2 | ADR-0008 D1 表（行 46-56）+ 实施方案 T1 行 419-435 |
| 新-3 | 实施方案 §"V6 路线图工时汇总"（行 240-251） |
| 新-4 | 验收清单 §K 行 477-498 重复段落 |
| 新-5 | 验收清单 §V-5 `verify_v6_fields_persisted.py` 循环（行 424-426） |

---

**独立第三方 Round 1.5 复审完成 · 总体判定 ⚠️ 部分整改后需再复审 · 不可进入 Round 2**