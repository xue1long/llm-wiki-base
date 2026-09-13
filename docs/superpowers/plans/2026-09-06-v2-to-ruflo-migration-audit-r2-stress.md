# Plan-Audit Round 2 压力测试报告：v2 → ruflo-kb 数据迁移

> **审计人**：独立第三方（Round 2 压力测试 · 失败路径推演）
> **审计日期**：2026-09-06
> **待审**：v2 → ruflo-kb 方案（已完成 Round 1 综合 + Round 1.5 复审；10 ✅ / 11 ⚠️ / 5 ❌）
> **审计范围**：5 份文档 + ruflo-kb 5 个关键源文件（`atomic_ctx.py` / `write_hooks.py` / `slug_aliases.py` / `store.py` / `capture.py`）

---

## 维度 1：失败路径推演（12 个具体场景）

### 场景 1.1.1：迁移中途终端被关闭（Ctrl+C / PowerShell 窗口 X）
- **触发条件**：用户运行 `python -m src.cli migrate-v2 --apply` 中途按 Ctrl+C 或关闭终端。
- **推演链条**：
  1. 进程收到 SIGINT → Python 抛 KeyboardInterrupt → `AtomicContext.__exit__(exc_type=KeyboardInterrupt, ...)` 检测到 `exc_type is not None`，执行 `write_hooks._current_bucket().clear()`（`atomic_ctx.py:75-78`），丢弃所有 buffered 写入。
  2. 但已写入磁盘的前 N 张卡（前 N < 1919）**已不可逆**：每个 `safe_write` 在非 suspended 路径下走 `tmp + os.replace`（`write_hooks.py:97-121`），每张卡的写盘是原子的，所以已写卡完整、后续卡零。
  3. `_pending_writes` 缓冲被清空 → 不会"半张卡"。
  5. 关键问题：**`wiki/index.md` 和 `wiki/log.md` 没自动更新**（验收清单 §A1 §D2 仅对账文件数，不查 `index.md` 行数）。已迁移的 N 张卡既未追加到 `index.md` 也未写入 `log.md`，状态不一致。
- **现状兜底**：
  - ✅ AtomicContext 在异常时丢弃 pending（`atomic_ctx.py:75-78` 行为正确）—— **不会产生半张卡**。
  - ✅ 单卡写盘原子（`safe_write` 的 `os.replace`），不会产生破碎文件。
  - ❌ **没有 `--resume` 子命令**：用户 Ctrl+C 后必须用 `--rollback-phase1to3` 全回滚后重跑，没有任何"从第 N 张继续"机制—— **1919 张卡的 PoC→全量流程若失败一次就要从头来**，耗时复利。
  - ⚠️ `wiki/index.md` / `log.md` 不会反映已迁移的 N 张卡，**`--rollback-phase1to3` 不知道要回滚哪些文件**（除非显式扫描磁盘 + 比对 UUID 列表）。
- **是否足够**：⚠️
- **加固建议**：
  1. **P1**：迁移器每次循环开始时把"已成功卡片列表"追加到 `migration_progress.json`（持久化）；`--resume` 子命令读此文件跳过已完成卡。
  2. **P1**：`--rollback-phase1to3` 实现必须扫描磁盘（`wiki/concepts/*.md` 找 `_v2_origin: True` 的卡）而不是依赖外部状态簿——否则无法精确回滚"已写未记账"的卡。
  3. **P2**：迁移器 catch KeyboardInterrupt 后输出 `migration_interrupted.json`（中断时已写卡列表 + 中断位置）供用户决策。

---

### 场景 1.1.2：实施人员请假，无人补位
- **触发条件**：Day 3 实施 PR 3（migration tools）中途主实施人病假 3 天。
- **推演链条**：
  1. PR 3 共 5-6 天、11 个 commit（实施方案 §"PR 3" 工作量 + 行 226 commit 列表）。中途停摆意味着代码库处于"半新半旧"状态。
  2. 替班人员接手需重新读 T1-T10 全部 Task 描述（约 1000 行实施方案），加上 round 1+1.5 的 26 个整改项。
  3. 替班人员**没有 context**：V6 schema 9 字段的字段顺序、`_ko_extra` 与顶层字段的同步策略、D9a 的 capture marker 注入细节——这些都在 ADR-0008 + T1 测试 + D9a 决策里散落，无单一入口。
  4. 替班人员最可能的动作：**直接重读调研报告 §12 决策表 + 实施方案 §"决策锁定 SSOT" 行 277-287 + ADR-0008**——这是约 200 行 SSOT，可在一小时内吃透，但**T1-T10 实施细节的"为什么这么写"全部丢失**。
- **现状兜底**：
  - ✅ 决策表 SSOT（调研 §12 + 实施方案 §"决策锁定 SSOT" 行 277-287）明确——替班人员看 SSOT 即可知决策边界。
  - ✅ 每个 Task 的 TDD test 给出可执行 acceptance（实施方案 T1-T10）。
  - ⚠️ **替班人员无法验证"是否和原作者理解一致"**——T1 的 `convert_frontmatter` 字段映射细节、T6 的 `merge_pending_metadata` 冲突解决规则（原值胜出）都没有独立说明。
  - ❌ **`tests/test_wiki_migrate/` 是新目录**，无 conftest.py 历史教训（CLAUDE.md 行 36 警告 sibling-conftest cascade），替班人员很可能踩坑。
- **是否足够**：⚠️
- **加固建议**：
  1. **P1**：每个 Task 增加一段"Implementation Notes"（决策表之外的具体解释，例如 T6 行 760-799 的 `merge_pending_metadata` 行为需明确"main 胜出，pending 新字段追加"——目前仅测试代码有，文档无）。
  2. **P1**：替班交接 checklist（`.memory/` 沉淀）：`tests/test_wiki_migrate/conftest.py` 必须 stub `platformdirs/lancedb/pyarrow/pypdf/docx/openpyxx/mcp/tavily`；跑测试必须 `PYTHONPATH=. pytest --import-mode=importlib`。
  3. **P2**：关键字段映射决策画 ER 图或决策树（v2 field → V6 field / `_ko_extra` / `sources` 的判定逻辑），存 `docs/architecture/v2-to-v6-field-mapping.md`。

---

### 场景 1.1.3：LLM Embedding 服务限流，无人工调整
- **触发条件**：Phase 4 LanceDB 重建时调用 OpenAI / MiniMax embedding API，单卡 ~250 ms，1924 张卡 + pending 总 ~2200 张卡 × 250 ms ≈ 9.2 分钟（理论）；实际 embedding API **频繁限流**（OpenAI Tier-1 默认 60 req/min、5M token/min），1924 张卡的 tokens 容易超限。
- **推演链条**：
  1. `scripts/rebuild_vectors.py` 调 `vector_upsert_chunks` → `pipeline.librarian._embedding_provider.embed(...)` → 收到 HTTP 429 Too Many Requests。
  2. 若无重试：单次 429 → 全量重建中断 → **已 upsert 的 N 张卡留在 lancedb**，未 upsert 的卡 wiki/concepts/ 已有但 lancedb 无 → **检索时部分卡命中、部分卡 miss**（用户感知："为啥搜 '网文创作' 只能搜到 800 张卡而不是 2000 张？"）。
  3. 若有重试：retry 5 次后放弃 → 同样上述后果。
  4. 用户从未配过 `RUFLO_RETRY_MAX` / `RUFLO_BACKOFF` env，限流后无任何自动降速 → 全部失败。
- **现状兜底**：
  - ✅ Circuit breaker (`src/circuit_breaker.py`)：连续 3 次失败 OPEN、60 秒后 HALF_OPEN；但 circuit breaker 是**进程全局**，不会持久化限流计数。
  - ❌ **脚本无 429 专项处理**：`scripts/rebuild_vectors.py` 方案未写明 retry / backoff 策略。
  - ❌ **lancedb 没有 atomic upsert**：`vector_upsert_chunks` 调用 LanceDB API 失败时，**之前已 upsert 的卡不会回滚**——partial commit 必然。
  - ⚠️ Phase 4 失败时按 D8 决策回滚 Phase 1-3 写盘的数据，但 lancedb 是 Phase 4 产物，回滚 Phase 1-3 **不会删 lancedb 已写入的向量**——下次重建会重复 upsert。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：`scripts/rebuild_vectors.py` 必须显式 `tenacity` retry + exponential backoff，针对 429 / 500 / 502 / 503 重试 5 次，base delay 2 秒。
  2. **P0**：实现 `vector_upsert_chunks` 的 **checkpoint 机制**：每 100 张卡 flush 到磁盘 + 写 `rebuild_progress.json`；中断后续跑。
  3. **P1**：LanceDB 重建脚本**显式调** `db.drop_table("chunks")` 然后 `db.create_table(...)` 在重建开始时；保证不残留旧向量。
  4. **P1**：Phase 4 失败的回滚必须**包括 `.index/lancedb/` 目录删除**——目前 D8 仅说"回滚 Phase 1-3 写盘数据"，未提 lancedb。
  5. **P2**：用户文档增 "embedding 限流降级方案"：临时降低 batch size 到 32 → 单卡延迟 ~300ms；或切到本地 sentence-transformers（384 维但免费）。

---

### 场景 1.2.1：磁盘空间不足（3.2 GB raw + 1924 wiki + .index/lancedb）
- **触发条件**：目标盘 `D:\5-Project\20260903\llm-wiki-base\knowledge\video-notes-wiki` 仅剩 2 GB 空闲（满盘常见状况）；raw 搬运到一半写盘失败。
- **推演链条**：
  1. 2180 raw 文件 × 平均 1.5 KB（小文件）到 50 KB（视频转录稿）→ 平均约 5 KB × 2180 ≈ **11 MB**（实际调研报告 §2 行 30 写"3.2 GB"是 B 站转录 .txt 单文件 2-50 KB + 部分大文件）。**真实总占用 ~ 3.2 GB**。
  2. 加上 1924 张 wiki 卡（每张 ~3-5 KB frontmatter + body）≈ ~10 MB；`.index/lancedb/` 1924 张卡 × 1536 维 float32 ≈ 1924 × 1536 × 4 = **11.3 MB**（向量化后）；`rebuild_vectors` 临时 staging 区域 ≈ 100 MB。
  3. **总磁盘需求 ~ 3.4 GB** + 操作系统 + Python 环境（2 GB+）= 至少 **5 GB 空闲**。
  4. 满盘 2 GB → raw 搬运到第 1500 个文件（约 1.5 GB）时 `safe_write` 抛 `OSError: No space left on device`（`write_hooks.py:97-121` 没特殊处理） → **1500 张 raw 已拷、第 1501 张失败** → 迁移器 abort。
- **现状兜底**：
  - ✅ `AtomicContext` 在异常时清空 pending bucket（`atomic_ctx.py:75-78`）→ **wiki 卡不会半写**。
  - ❌ **raw 拷贝不走 AtomicContext**：T5 raw 搬运用 `shutil.copy2` 或类似直接 IO，无原子保证 → 已拷 1500 张未记账，迁移器 abort 时**无法精确回滚**。
  - ❌ **没有磁盘预检**：T8 步骤 4 `--apply` 前未跑 `df -h` 检查磁盘空间。
  - ❌ **失败后无 `--resume-from-raw` 机制**：用户只能手动删 1500 张 raw 重来。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：T8 步骤 0 增加磁盘预检：`shutil.disk_usage(target_root).free > 5 GB` 才允许 `--apply`。
  2. **P0**：T5 raw 搬运器维护 `raw_progress.json`（已成功拷贝的文件名列表），中断后续跑。
  3. **P1**：raw 搬运支持 `--resume` 自动跳过已存在的同名文件（用 md5 校验一致性）。
  4. **P1**：raw 搬运可分批：先 `_archive/`（637 个）→ 再 `01_B站`（482）→ 再 `02_抖音`（1435）→ 再 `03_小红书`（485）→ 失败时报告当前批次进度。

---

### 场景 1.2.2：Embedding API 配额耗尽
- **触发条件**：用户 OpenAI 账户本月剩余 $5，按 1924 张卡的 tokens 计费约 $0.50-2.00（取决于 chunk size）→ 配额定不够。
- **推演链条**：
  1. `scripts/rebuild_vectors.py` 启动 → 假设 OpenAI `text-embedding-3-small` $0.02/M tokens，1924 张卡每张 ~500-2000 tokens → 总 ~1-4 M tokens ≈ $0.02-0.08 → **理论上够**。
  2. 但**真实 token 数远超估算**：v2 转录稿常常 5-20 KB Markdown，**单卡 chunk 后 2000-5000 tokens**；1924 张卡总 ~3-10 M tokens = $0.06-0.20。
  3. 若用户实际账户余额 $0.01（试用账户）→ 第一个 chunk 就 402 Payment Required → `vector_upsert_chunks` 失败。
- **现状兜底**：
  - ✅ `--dry-run` 选项可预演但不调 API（实施方案 T7 行 818-822）。
  - ❌ **dry-run 不估算 token 成本**：用户 dry-run 跑完后不知道实际成本。
  - ❌ **没有按 provider 切换降级**：用户临时切本地 `sentence-transformers` (384-dim) 也无自动机制——但**这反而暴露 384 vs 1536 维度问题**（验收 §E1 写 1536）。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：`--dry-run` 必须统计预计 token 数 + 估算 USD 成本（基于 provider 单价表 hardcode 或 env var `EMBEDDING_COST_PER_M_TOKENS`）。
  2. **P0**：scripts/rebuild_vectors.py 加 `--provider <openai|local|minimax>` 选项，允许临时切换到本地（384 维但免费）。
  3. **P1**：方案文档明确"ruflo-kb 默认 384-dim，OpenAI 1536-dim 是非默认配置；用户应使用匹配的 provider 避免维度不匹配"——目前 §E1 与 store.py:39 不一致。

---

### 场景 1.2.3：内存峰值超过 1 GB
- **触发条件**：yaml 解析 + safetensors 加载 + 1919 张卡的 frontmatter 同时驻留。
- **推演链条**：
  1. v2 转录稿单文件 5-50 KB，但 v2 YAML frontmatter 不规则：有的卡 body 长达 100 KB（含完整视频转录正文）。
  2. 1919 张卡 × 平均 30 KB = 57.6 MB，加 Python dict 开销 ~2-3 倍 = **150-200 MB**。
  3. yaml 解析生成 dict 对象（PyYAML 用 C loader 时 ~3 倍原文内存）→ 瞬时峰值 **400-600 MB**。
  4. 加上 LanceDB 重建时 1924 张卡的 chunks × 1536 dim float32 = 11.3 MB embedding 数组 + Python list ≈ **30 MB**。
  5. 加上 safetensors（CLAUDE.md 提到 "raw 文件实际加载"——若方案误用 safetensors 加载 raw）：单 safetensors 文件 5-50 KB，开销 ~10 倍 = 5-50 MB。
  6. **总峰值 ~500 MB**，理论上 1 GB 阈值内 OK；但 Python GC + yaml 解析瞬时峰值可能冲到 **1.5 GB**（特别是用 `yaml.load_all` 一次性加载所有文件时）。
- **现状兜底**：
  - ✅ 验收 §F1 设 ≤ 1 GB 内存峰值，但**无实施侧强制检查**。
  - ⚠️ 实施方案 T8 步骤未指定**逐卡流式处理**还是**批量加载**——如果用 `yaml.load_all(files)` 一次性读 1924 张卡，**内存峰值必然破 1 GB**。
- **是否足够**：⚠️
- **加固建议**：
  1. **P1**：T8 明确**逐卡处理**：单卡 `read → convert → safe_write` 后释放（局部变量 GC）。
  2. **P1**：迁移器加 `--max-memory-mb <N>` 阈值 + `tracemalloc` 监控，超阈值后强制 `gc.collect()` 并 sleep 100ms。
  3. **P2**：可选 `--batch-size 100` 选项批量处理 wiki 卡，平衡 IO 与内存。

---

### 场景 1.2.4：网络中断（_ko_extra.video_id URL HEAD 请求需要网络）
- **触发条件**：验收 §F-bis-2 行 237 "URL 真实可访问（HEAD 请求）"——5% 的卡 URL 不可达；网络断网时 100% 不可达。
- **推演链条**：
  1. Phase 4 完成后跑 F-bis-2 验收 → 对 50 张 B 站 URL 发 HEAD 请求 → 第 30 张时网络中断（家里路由器重启）→ `requests.head()` 抛 `ConnectionError`。
  2. 验收脚本如果不做 retry → 直接报 FAIL，用户不知道是"网络问题"还是"URL 真的失效"。
  3. **真实场景**：B 站对自动化 HEAD 请求会返回 403/412（反爬），即使网络 OK 也 FAIL。
- **现状兜底**：
  - ⚠️ **F-bis-2 验收方法本身的可行性存疑**：50 张 B 站 URL 走 HEAD 触发反爬概率 > 50%。
  - ❌ 验收脚本未定义网络异常处理逻辑。
- **是否足够**：⚠️
- **加固建议**：
  1. **P1**：F-bis-2 改为 "URL 模板可生成 100%"（不实际访问），仅对 B 站公开 BV 字段做格式校验（`re.match(r'^BV[1-9A-HJ-NP-Za-km-z]{10}$', bv)`）。
  2. **P2**：增加"可选"网络抽查脚本 `scripts/spot_check_urls.py` 跑 5 张抽样，超时 5 秒、断网时 retry 1 次，否则 WARN 不阻塞。

---

### 场景 1.3.1：validate_tag_compliance 仍 raise TagValidationError
- **触发条件**：v2 有 1919 张卡的 tags 包含 `网文创作 / 读者视角 / 自审方法 / 写作技巧` 等自由 CJK 文本 + `tool/python / scene/视频笔记 / status/Agent核心记忆` 等带前缀文本（调研 §5 + ADR-0008 §"Context" 行 32-35）。
- **推演链条**：
  1. PR 2 (V6 tag namespace) 加 5 新前缀（`tool/scene/status/media/author`） + `MANDATORY_PAIRS` 条件化（`tag_namespace.py` 修改）。
  2. `validate_tag_compliance` 改为可选 `page_type/platform` 参数 → source + video 才检查 mandatory pair。
  3. **但 v2 概念卡（按 D9a 决策）走 `wiki/concepts/` + `type=concept` → mandatory pair 不强制**，T1 转换器不会触雷。
  4. **但** v2 概念卡虽然 `type=concept`，其 v2 tag 仍受 V6 tag 校验约束：
     - "网文创作"（无前缀）→ V6 schema 不识别 → 落到 `_ko_extra._v2_legacy_tags`（ADR-0008 §D7 行 83-86）→ frontmatter `tags` 可能空。
     - "tool/python"（带前缀）→ V6 PR 2 加 `tool/` 前缀 → 接受 → frontmatter `tags: [tool/python]`。
     - "scene/视频笔记" → 加 `scene/` 前缀 → 接受。
  5. **但仍有漏网**：v2 tag 含 17 种 taxonomy_sub 字符串 + 各种 CJK 名词，**5 新前缀不可能覆盖全部**——必然有标签落到 `_v2_legacy_tags`。
  6. **T1 acceptance 没说怎么处理 `_v2_legacy_tags` 中的标签**：是丢弃？是保留到 `_ko_extra._v2_legacy_tags`？验收 §B2 行 70-87 检查 `tags` 字段，未检查 `tags` 与 `_ko_extra._v2_legacy_tags` 的总和——可能 v2 tag 部分丢失无告警。
- **现状兜底**：
  - ✅ V6 PR 2 已经条件化 mandatory pair，不会因 missing pair raise。
  - ⚠️ **未识别 tag 静默落入 `_v2_legacy_tags`**——v2 tag 信息**部分丢失**（特别是 taxonomy_sub 相关的分类标签如 `写作技巧` 很重要）。
  - ❌ **未实现 T1 的 `normalize_tags()` 函数**：ADR-0008 D7 说"写盘前通过 normalize_tags() 映射"，但实施方案 T1 测试未包含 `normalize_tags` 的 unit test，仅有 `test_concept_card_full` 等通用测试（行 333-381）。**T1 测试覆盖缺失 → 实施时极可能跳实现 `normalize_tags`**。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：T1 acceptance 增加 `test_v2_tag_normalization` 测试，覆盖 `网文创作 → _ko_extra._v2_legacy_tags` + `tool/python → tags: [tool/python]` + `taxonomy_sub → _ko_extra._v2_legacy_tags`。
  2. **P0**：验收 §B2 增一项："v2 原 tag 总数 == frontmatter `tags` 长度 + `_ko_extra._v2_legacy_tags` 长度"（不丢信息）。
  3. **P1**：ADR-0008 §"Consequences" 增"未识别 tag 落到 `_v2_legacy_tags` 是已知行为，不视为 BUG；用户可手动迁移"——明确语义。

---

### 场景 1.3.2：slugify() 对 CJK 标题失败
- **触发条件**：v2 有 `Nano-Banana-Pro-Gemini3分镜控制.md`（小红书收藏夹）+ `Obsidian.md` + `Claude Code.md` 等 CJK + 空格文件名。
- **推演链条**：
  1. ruflo-kb 的 `slugify()` 实现位置（`src/wiki/features/relations.py` 或 `slug_aliases.py`）——事实核查：`slug_aliases.py` 不 slugify；slugify 在 `Relation.from_dict` 调用。
  2. CJK 标题 `Claude Code` 走 slugify → `claude-code`（拉丁化）；但 v2 文件名是 `Claude Code.md`（带空格）→ **`slugify('Claude Code') == 'claude-code'` 与文件 stem `'Claude Code'` 不一致**。
  3. `resolve_wikilink(root, target='claude-code')` 在 `paths.wiki_entities.glob('*.md')` 找 `claude-code.md`（无，因为实际是 `Claude Code.md`）→ 断链 → 落入 `KnowledgeGapStore`。
  4. 实体卡 alias 通过 `slug_aliases.json` 解析：T3 已经写 `{"ClaudeCode": "Claude Code"}` 正向 → `resolve_wikilink` 走 `SlugAliasRegistry.get_canonical("ClaudeCode") == "Claude Code"` → 找到。
  5. **但 alias 必须穷举**：如果某 wikilink 写成 `[[claude code]]`（小写 + 空格）→ 不在 alias map → 断链。
- **现状兜底**：
  - ✅ T3 已经为 5 张 entity 卡的每个 alias 显式写 mapping（实施方案 §"T3 acceptance"）。
  - ⚠️ **slug_aliases 接受链式解析**（`slug_aliases.py:131-139`）：如果 alias chain 长度 > 8（`_MAX_ALIAS_DEPTH=8`），`get_canonical` 返回 None → 断链。
  - ❌ **`slug_aliases.json` 只覆盖 entity 卡**：v2 概念卡的 CJK 标题（如 `某概念标题.md`）无 alias 注册 → wikilink 解析失败。
- **是否足够**：⚠️
- **加固建议**：
  1. **P0**：T1 acceptance 增加"v2 概念卡 CJK 标题 wikilink 解析"测试：构造 body 含 `[[Claude Code]]` 与 `[[网文萌新如何建立"读者马甲"自审作品]]`，断言 relations 列表非空且 target slug 与文件 stem 一致。
  2. **P1**：T2 `extract_relations` 对 wikilink target 先尝试 `Path(file_stem)` 直接匹配（v2 风格），fallback 到 `slugify`（ruflo-kb 风格）——双匹配优先于 alias。
  3. **P2**：T3 实施时把每个 v2 wiki 卡的所有 CJK 变体（小写、空格、无空格、英文）都注册到 `slug_aliases.json`——目前仅 entity 卡注册，概念卡**未注册**。

---

### 场景 1.3.3：safe_write atomic rename 冲突（Phase 2 多进程并发）
- **触发条件**：T7 迁移器如果支持 `--workers N` 并发（虽然方案未明示），多个 Python 进程同时 `safe_write` 不同 wiki 卡到同一目录。
- **推演链条**：
  1. 进程 A 写 `wiki/concepts/BV1.md`，tmp 文件 `BV1.md.tmp`。
  2. 进程 B 同时写 `wiki/concepts/BV2.md`，tmp 文件 `BV2.md.tmp`。
  3. `_atomic_replace` 用 `os.replace(tmp, target)`（`write_hooks.py:68-94`）—— Windows 下 `os.replace` 原子，但**多个进程对同一目录并发写**时无问题（不同 tmp 文件）。
  4. **真正问题**：`wiki/index.md` 和 `wiki/log.md` 是**单文件多进程写**——若 `--workers 4`，4 个进程同时追加同一文件 → 内容交叉污染。
- **现状兜底**：
  - ✅ `AtomicContext` per-thread 隔离（`write_hooks.py:11-16` 注释明确）→ 单进程多线程 OK。
  - ❌ **多进程（multi-process）共享 `index.md` 无文件锁**：Windows 没有 fcntl，Python `fcntl.flock` 不可用，需用 `msvcrt.locking`。
  - ⚠️ **方案 T7 未明确 `--workers` 是否存在**：从 T7 测试（行 818-838）看是单进程 CLI——但用户可能自己包一层并行。
- **是否足够**：✅（单进程默认情况下足够）
- **加固建议**：
  1. **P2**：T7 文档明确"迁移器单进程运行；不支持 `--parallel`"。
  2. **P2**：若未来要并行，加 `index.md` 的 `msvcrt.locking(fd, msvcrt.LK_LOCK, size)` 文件锁。

---

### 场景 1.3.4：init_vector_store_for_paths 时 provider 未配置 → RuntimeError
- **触发条件**：用户跑 `scripts/rebuild_vectors.py --project e3a0472c-06af-41e4-8d06-083146f195f7` 但 `~/.config/ruflo-kb/llm-providers.json` 不存在。
- **推演链条**：
  1. `scripts/rebuild_vectors.py` 启动 → `embedding_runtime.get_embedding_provider()` → 注册表为空 → RuntimeError。
  2. **但 `rebuild_vectors.py` 是 T10.0 任务（ADR-0008 §D8）—— 应该有 provider 自检**（ADR-0008 行 92-93 "内置 provider 自检（llm-providers list + health check）"）。
  3. 但 **CLAUDE.md 提到 server lifespan 在启动时自动调 `init_vector_store_for_paths`** ——如果 server 启动时 provider 未配，server 也会启动失败。
- **现状兜底**：
  - ✅ 实施方案 T10 行 873 步骤 1 要求 `serve`，但**未要求 provider 预检**。
  - ⚠️ **ADR-0008 D8 说 provider 自检，但 Round 1.5 复审 行 75-78 已指出"文档与代码不一致（1536 vs 384）+ provider 前置步骤缺失"**——但整改未见。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：T10 步骤 0 增加 `python -m src.cli llm-providers list --json | jq 'length > 0'` 前置检查，失败则 abort。
  2. **P0**：scripts/rebuild_vectors.py 启动时调 `embedding_runtime.get_embedding_provider()` 试 1 次，失败则打印用户友好的错误信息："未配置 LLM provider，请先运行 `python -m src.cli llm-providers add <name> <type> ...`"。

---

### 场景 1.4.1：全量迁移超过 5 分钟
- **触发条件**：1924 张 wiki 卡 × 100ms/卡（frontmatter parse + wikilink extract + yaml dump + safe_write） ≈ **192 秒** ≈ 3.2 分钟。加上 raw 3.2 GB IO + LanceDB 重建 9-20 分钟 → **总 13-30 分钟**。
- **推演链条**：
  1. 验收 §F1 行 311 写"全量迁移 1924 张卡耗时 ≤ 60 秒" ——Round 1.5 复审已指出"60 秒过乐观"（行 240-250）但未实际修正阈值。
  2. 即使改为 ≤ 5 分钟（Round 1.5 建议），实际可能 10 分钟 → F1 FAIL → WARN 不阻塞但用户体验差。
  3. 用户可能误以为"超时 = 卡死" → Ctrl+C → 半残状态。
- **现状兜底**：
  - ⚠️ T8 步骤无进度条或 ETA 输出——用户看不到迁移状态。
  - ❌ **F1 阈值未实测**：Round 1.5 复审行 240 指出"未重新评估"，目前仍是 60 秒。
- **是否足够**：⚠️
- **加固建议**：
  1. **P1**：F1 阈值改为 ≤ 10 分钟（含 raw + wiki + LanceDB upsert），并实测 Phase 0 PoC 5 张卡后线性推算。
  2. **P1**：T8 迁移器每 100 张卡打印进度：`[1234/1924] (64%) elapsed 2m30s eta 1m15s`。
  3. **P2**：迁移器写 `migration_progress.json` 含 start_time / last_update_time / eta_seconds；外部 watchdog 可查询。

---

### 场景 1.4.2：LLM Embedding 单次调用超过 30 秒
- **触发条件**：网络抖动或 OpenAI 服务降级时，单次 embed 调用可能 30+ 秒。
- **推演链条**：
  1. `scripts/rebuild_vectors.py` 调 `provider.embed(chunk)` → 默认 httpx timeout 30 秒 → 超时 → `httpx.TimeoutException`。
  2. 无 retry → 单卡失败 → 全量重建中断（与 1.1.3 类似）。
- **现状兜底**：
  - ⚠️ `pipeline.librarian._embedding_provider` 是 process-global singleton，无 per-call timeout 配置。
  - ❌ **scripts/rebuild_vectors.py 方案未写 timeout / retry**。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：scripts/rebuild_vectors.py 用 `httpx.Client(timeout=60.0)` + tenacity retry（指数退避 5 次）。
  2. **P1**：超时阈值改为可配置：`--embedding-timeout 60`。

---

### 场景 1.4.3：--rollback-phase1to3 在数据半残时挂起
- **触发条件**：用户跑 `--apply` 中途断电 / Ctrl+C，跑 `--rollback-phase1to3` 回滚——但**哪些卡已写？哪些卡未写？** 状态簿不明确。
- **推演链条**：
  1. Ctrl+C 后：部分 wiki 卡已写、部分未写、`migration_report.csv` 未生成（中断时未 flush）。
  2. 跑 `--rollback-phase1to3` → 实施 §"Audit Rollback" 行 894-901 说"删除 knowledge/video-notes-wiki/ 目录"——**这是粗暴删除整个项目**，**不是 Phase 1-3 已写入数据的精确回滚**。
  3. 若用户在迁移中段已手编辑 `wiki/concepts/BV1xxx.md`（D9a capture marker 已加），--rollback-phase1to3 会**误删用户手编辑的内容**。
- **现状兜底**：
  - ❌ 实施方案 §"Audit Rollback" 仅"删除 `knowledge/video-notes-wiki/` 目录"——**不是精确回滚**。
  - ❌ 没有"已迁移卡列表"持久化机制（migration_report.csv 是迁移完成后才生成）。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：迁移器实时写 `migration_already_written.jsonl`（每张卡写盘后追加一行），`--rollback-phase1to3` 读此文件精确回滚。
  2. **P1**：`--rollback-phase1to3` 必须 **校验** 卡有 `_v2_origin: True` 标记才删——避免误删 novel-wiki 同名卡（虽然不同项目不共享路径，但若用户多项目共用目录可能误伤）。
  3. **P2**：支持 `--dry-run-rollback` 显示要删除的文件清单，等用户确认再真删。

---

### 场景 1.5.1：用户在迁移过程中手动编辑了 wiki/concepts/X.md
- **触发条件**：用户看到迁移器跑得慢，趁等待时手动编辑某张卡（添加新 tag、改 title）。
- **推演链条**：
  1. 用户编辑 `wiki/concepts/BV1xxx.md` → frontmatter 改成 `tags: [网文创作, 自定义新tag]` + 改 title。
  2. 迁移器 T1 转换 v2 同名 `BV1xxx.md` → 写盘 `safe_write('wiki/concepts/BV1xxx.md', new_content)`。
  3. **`safe_write` 是 `os.replace(tmp, target)`**（`write_hooks.py:120`）→ **原子覆盖** → **用户手编辑全部丢失**（无任何告警）。
  4. 用户发现编辑丢失 → 对迁移器失去信任。
- **现状兜底**：
  - ❌ **safe_write 无冲突检测**：v2 与已存在卡同名 → 静默覆盖。
  - ⚠️ `--on-collision fail` 是 raw 文件级别的（D4 决策），**不涉及 wiki 卡覆盖**。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：T1 写盘前检测文件是否已存在 + frontmatter `_v2_origin` 标记 → 若存在但**无** `_v2_origin` 标记 → 视为用户手编辑 → **拒绝覆盖并写入 `collision_wiki_cards.csv`**。
  2. **P1**：增加 `--on-wiki-collision {skip, fail, backup}` 选项，默认 `backup`（保留用户版本为 `X.md.bak`）。
  3. **P2**：迁移开始前 md5 整个 `wiki/concepts/` 目录存 `wiki_pre_migration_hash.json`，结束后比对，差异报告。

---

### 场景 1.5.2：novel-wiki 项目同时在做其他操作（注册表共享冲突）
- **触发条件**：用户同时跑 novel-wiki 的 capture / ingest（CLAUDE.md 行 73 HTTP API）和 v2 迁移（HTTP API 也走 ProjectContext resolve）。
- **推演链条**：
  1. video-notes-wiki 迁移注册到 `ProjectContext` 全局注册表（`src/lib/project.py:31`）。
  2. novel-wiki ingest 走 `services.ingest.enqueue_source` → `resolve_project` → 可能解析到 video-notes-wiki（取决于注册顺序）。
  3. novel-wiki 写入的 wiki 卡可能落 `video-notes-wiki/wiki/` 而非 `novel-wiki/wiki/`。
- **现状兜底**：
  - ✅ ruflo-kb 注册表按 UUID 区分（CLAUDE.md 行 75-77）——理论上 UUID 不冲突。
  - ⚠️ 但若用户 CWD 在 novel-wiki 目录，`src/cli.py` 自动 detect `.llm-wiki/project.json` → 解析到 novel-wiki → OK。
  - ❌ **多进程并发 `init_vector_store_for_paths` 共享 `_per_project` dict**（`store.py:57`）→ 多进程不冲突（dict 是 per-process），但 server 启动 + CLI 同时跑可能混淆 `current_project_key`。
- **是否足够**：⚠️
- **加固建议**：
  1. **P1**：迁移期间明确禁止 novel-wiki ingest：方案文档加警告。
  2. **P2**：迁移器开始时校验 `current_project_key == e3a0472c-...` 才继续，否则提示"切换项目或迁移项目不是当前项目"。

---

### 场景 1.5.3：v2 vault 在迁移期间被修改（D7 冻结失效）
- **触发条件**：用户在迁移过程中误编辑 v2 vault（虽然 D7 写"冻结"，但技术无强制）；或同事在迁移期间往 `10_raw/` 加新文件。
- **推演链条**：
  1. T5 raw 搬运已开始 → 用户加新文件 `10_raw/02_抖音视频笔记/新视频.md`。
  2. T5 已遍历完 `02_抖音` 目录但未拷新文件 → 新文件永久丢失。
  3. 或 T1 转换器已读 `BV1xxx.md` 的旧内容 → 用户编辑后再读 → 不一致。
- **现状兜底**：
  - ✅ D7 决策写"v2 vault 迁移后冻结"+ Changelog 追加（调研 §12 行 350）——**仅文档层**。
  - ❌ **无技术冻结**：v2 vault 没有 chmod -R readonly 或 git commit lock。
  - ❌ **无 mtime 检测**：迁移器未记录 v2 vault 起始 mtime，结束时不校验完整性。
- **是否足够**：❌
- **加固建议**：
  1. **P1**：迁移开始前 `tar -czf v2_vault_pre_migration.tar.gz <v2_vault>` 备份（虽然 3.2 GB 但安全性高）。
  2. **P1**：T5 / T1 在结束时校验"开始时扫描的文件数 == 已处理文件数 + 跳过的文件数"。
  3. **P2**：提供 `tools/v2_vault_freeze.sh` 脚本（`chmod -R 444`）让用户在迁移前显式冻结；`tools/v2_vault_unfreeze.sh` 解冻。

---

### 场景 1.5.4：PowerShell 中文路径在迁移中段突然变更 CWD
- **触发条件**：用户在 PowerShell 多 Pane 窗口中切换 Tab，CWD 跳到 `D:\5- 项目\000-Nico\`（v2 根目录）而非 `D:\5-Project\20260903\llm-wiki-base\`（ruflo-kb 根）。
- **推演链条**：
  1. 迁移器跑 `python -m src.cli migrate-v2 --apply` → Python 子进程继承父 CWD `D:\5- 项目\000-Nico\`。
  2. `ProjectContext.resolve()` 依赖 CWD 找 `.llm-wiki/project.json`（CLAUDE.md 行 31）→ 找不到 → 解析失败 → 迁移器 abort。
  3. **或**：子进程 CWD 是 v2 → `ProjectContext.resolve()` 找到 v2 vault 根目录的 `.llm-wiki/`（如果有）→ 解析到错误项目。
- **现状兜底**：
  - ⚠️ 实施方案 §"T7" 行 738-7 提到 `--target <target>` 但**未强制 `--target` 必须是 UUID**。
  - ❌ **Round 1.5 复审行 168-176 已指出 "CWD 不稳定" 未充分修复**—— T7 未明确"迁移器必须用 `--project <uuid>` 全局参数"。
- **是否足够**：❌
- **加固建议**：
  1. **P0**：T7 文档强制 `python -m src.cli migrate-v2 --project <uuid> --v2-path <绝对路径> --apply`，**不依赖 CWD**。
  2. **P0**：方案文档加警告："PowerShell 多 Pane 用户请用 `--project` 全局参数，避免 CWD 切换导致解析错误"。
  3. **P1**：迁移器启动时显式 `os.chdir(<ruflo-kb 根>)` 到默认安全位置。

---

## 维度 2：连锁反应分析

### 场景 2.1：safe_write atomic rename 失败 → 半残数据
- **触发**：T1 转换器第 800 张卡写盘时 Windows Defender 实时扫描触发 `PermissionError`，`safe_write` 5 次重试后 fallback `unlink + rename`（`write_hooks.py:89-94`），但 unlink 时文件被另一进程持有（Antivirus 持有）→ `PermissionError` → **第 800 张卡未写盘但无错误抛出**（被 except 吞了）？
- **实际分析**：看 `_atomic_replace` 代码（`write_hooks.py:68-94`），fallback 用 `os.unlink` + `os.rename`，**这两个调用本身不抛 OSError**，但**如果 antivirus 真的卡住**，进程会 hang 而非抛错。
- **连锁路径**：
  1. 第 800 张卡 hang（30 秒 + antivirus scan 1-2 分钟）→ 迁移器看起来"卡死"
  2. 用户 Ctrl+C → KeyboardInterrupt → AtomicContext 清空 pending → 已写 799 张完整、800-1919 张未写
  3. **第 800 张卡的 tmp 文件残留**：`wiki/concepts/BV800.md.tmp` 永久留在磁盘上 → 后续增量或健康度检查可能误读
  4. 用户跑 `--rollback-phase1to3` → 删整个 `knowledge/video-notes-wiki/` 目录 → 用户**手编辑的 5 张卡**（若有）一起丢
- **最坏后果**：用户失去全部迁移数据 + 任何手动调整
- **当前能否承受**：❌（`_atomic_replace` 无上限超时；tmp 文件残留无清理机制；rollback 是粗粒度删除）
- **加固建议**：
  1. **P0**：`_atomic_replace` 加 `subprocess.run(['esentutl', '/y', tmp], timeout=10)` Windows 专用路径 + 超时 fallback。
  2. **P0**：迁移器启动时 `clean_stale_tmp_files(root)`：删 `<wiki>/**/*.tmp`。
  3. **P1**：`--rollback-phase1to3` 实现用 `migration_already_written.jsonl` 精确回滚，不用粗暴删目录。
  4. **P2**：方案明确"迁移期间临时禁用 Windows Defender 实时扫描（白名单 `knowledge/video-notes-wiki/`）"。

---

### 场景 2.2：validate_tag_compliance raise → 全量中断 → 用户不知如何处理
- **触发**：PR 2 V6 tag namespace 实施时漏写某自由 CJK tag 的映射规则 → T1 第 50 张卡写盘时调用 `validate_tag_compliance` raise TagValidationError。
- **连锁路径**：
  1. T1 转换第 1-49 张卡成功（tag 都是 `tool/python` 等受控）→ 第 50 张 tag `奇葩词` → validate raise → T1 中断
  2. 50 张卡已写 + `migration_report.csv` 未生成 + 进度未持久化
  3. 用户看到错误："TagValidationError: 奇葩词 is not in TAG_PREFIXES" → **不知道是迁移器问题还是 v2 数据问题** → **不知道是修改 PR 2 还是 v2 tag**
  4. 用户**无从下手**：rollback 没有（已写 50 张卡无状态簿），retry 同样错误（除非修改 v2 或 PR 2）
  5. 项目卡在"半迁移状态"几天
- **最坏后果**：用户放弃迁移 → v2 vault 不冻结（已写 50 张卡到 ruflo-kb 但不完整）→ 双系统混乱
- **当前能否承受**：❌（T1 无 try/except 包裹 validate；无 fail-soft 策略；无错误分类提示）
- **加固建议**：
  1. **P0**：T1 用 `try: validate_tag_compliance(tags, page_type=page.type) except TagValidationError as e: log_warning(f"卡 {slug} tag 不合规: {e}; 保留原 tag 到 _ko_extra._v2_legacy_tags")` **不 raise 终止**。
  2. **P0**：迁移器写 `migration_warnings.csv`（卡 id + 警告类型 + 详情），允许完成后用户审查。
  3. **P1**：默认行为改 "skip + report" 而非 "fail + abort"（用户可显式 `--strict` 才 fail）。

---

### 场景 2.3：LanceDB rebuild 失败 → Phase 1-3 数据已写但向量未建
- **触发**：`scripts/rebuild_vectors.py` 跑到第 1000 张卡时 embedding provider 限流 + 无 retry → 中断。
- **连锁路径**：
  1. Phase 1-3 已写 1924 张 wiki 卡到 `wiki/concepts/` ✓
  2. lancedb 已有 1000 张卡的向量 ✗（缺 924 张）
  3. `wiki/index.md` 已 1924 行（Phase 1-3 完成）
  4. 用户看到 wiki 卡完整 → 以为成功 → 跑 `python -m src.cli search "网文创作"` → 仅命中 1000 张 → **用户认为"迁移后检索效果不好" → 不会想到是 LanceDB 部分失败**
  5. 验收 §E1 行 184 "lancedb 行数 == wiki 卡数" → FAIL 但**用户不知道是哪一阶段失败**
- **最坏后果**：用户认为迁移成功但实际残缺 → 实际数据丢失的是"语义检索"能力（关键词检索仍可用）
- **当前能否承受**：❌（scripts/rebuild_vectors.py 无进度持久化；无 resume；Phase 4 失败无回滚 lancedb 机制）
- **加固建议**：
  1. **P0**：`scripts/rebuild_vectors.py` 写 `rebuild_progress.jsonl`（每张卡 upsert 后追加）；`--resume` 自动跳过已 upsert。
  2. **P0**：Phase 4 失败回滚必须**包括 `.index/lancedb/` 目录删除 + 重新 init**（避免下次重建前残留旧向量与新维度冲突）。
  3. **P1**：脚本输出"已完成 N/1924 (M%)"实时进度；用户随时知道是否完整。
  4. **P2**：增加 `python -m src.cli migrate-v2 --status` 查询当前 Phase 状态（在哪一阶段 + 进度）。

---

### 场景 2.4：Phase 1-3 完成 + Phase 4 中断 → rollback 命令误删 novel-wiki
- **触发**：用户在两项目都用 ruflo-kb（novel-wiki + video-notes-wiki）共宿主目录，跑 `--rollback-phase1to3` 但回滚逻辑未限定 project_id。
- **连锁路径**：
  1. 实施 §"Audit Rollback" 行 901：`python -m src.cli project forget e3a0472c-... --delete-data` → 删 `video-notes-wiki/` 目录。
  2. 但 `--rollback-phase1to3`（实施方案 §"D8" 行 286-287）说"Phase 4 失败时回滚 Phase 1-3"——**实现细节未给出**，可能误删 novel-wiki 同名文件。
  3. 例如：novel-wiki 有 `wiki/concepts/test.md` + video-notes-wiki 也有 `wiki/concepts/test.md`（同一主机）→ rollback 用 glob `wiki/concepts/*.md` 删 → novel-wiki 同名卡**也被删**。
- **最坏后果**：novel-wiki 数据丢失（用户主 KB 被误删）
- **当前能否承受**：❌（实施方案未限定回滚路径必须 `--project e3a0472c-...`）
- **加固建议**：
  1. **P0**：`--rollback-phase1to3` 必须强制接收 `--project <uuid>` 参数；rollback 路径限定 `<project_root>/wiki/` 树。
  2. **P0**：rollback 前 dry-run 显示"将删除 N 个文件 / 涉及 project UUID"给用户确认。
  3. **P1**：rollback 移到 trash 而非 rm（`send2trash` 包或 PowerShell `Microsoft.VisualBasic.FileIO.FileSystem.DeleteFile(path, 'OnlyErrorDialogs', 'SendToRecycleBin')`）。

---

## 维度 3：兜底机制覆盖度

| 兜底机制 | 覆盖失败路径 | 未覆盖失败路径 | 建议补充 |
|---|---|---|---|
| **AtomicContext**（`atomic_ctx.py`） | ✅ 单进程多步原子（异常时清 pending）<br>✅ 嵌套 no-op | ❌ **多进程并发**（per-thread 隔离，多进程独立）<br>❌ **`safe_write` 在非 suspended 路径失败后未回滚已写其他卡**（单卡原子但不整体原子）<br>❌ **KeyboardInterrupt 后无状态簿** | 进程级 advisory lock；提供 `process_atomic_lock` 跨进程锁；migration 启动时 acquire |
| **safe_write**（`write_hooks.py`） | ✅ 单卡 atomic write（tmp+replace）<br>✅ DELETE_SENTINEL 队列化删除<br>✅ 5 次 retry + fallback unlink+rename | ❌ **`_atomic_replace` 无超时**（antivirus 持有文件时 hang）<br>❌ **未清理 stale .tmp 文件**（上次中断残留）<br>❌ **`DELETE_SENTINEL` 非 suspended 路径直接 unlink**（不走 atomic）<br>❌ **`flush_pending_writes` 部分失败时已写其他卡不补偿**（raise `AtomicCommitError` 但 partial commit 已发生） | 添加 `safe_write_timeout`；迁移器启动 `clean_stale_tmp`；非 suspended DELETE 也走 tmp 模式；flush 失败时记录 `partial_commit_paths.json` |
| **rollback-phase1to3**（实施方案 §D8） | ✅ Phase 4 失败时回滚（**文档级**） | ❌ **实现细节未给出**——可能粗暴删 `video-notes-wiki/` 目录<br>❌ **未限定 project_id**——可能误删 novel-wiki<br>❌ **无 `--dry-run-rollback`**<br>❌ **无状态簿**（migration_report.csv 是迁移完成后才生成） | 强制 `--project <uuid>` 参数；用 `migration_already_written.jsonl` 精确回滚；支持 dry-run；移到 trash |
| **pending_decisions.csv**（T6） | ✅ 记录 `_to_recompile/` 草稿的处置决策（pending vs main_wins）<br>✅ 用户可手工审查 | ❌ **仅覆盖 D1 决策**（pending 处理）<br>❌ **不覆盖其他类型的 pending 决策**（如 wikilink 解析失败、tag 校验失败、字段缺失）<br>❌ **不是结构化恢复工具**——用户看到 CSV 不知如何 "promote pending → main" | 扩展为 `migration_warnings.csv` 覆盖所有失败类型；提供 `tools/promote_pending.py` 一键恢复 |
| **safe_write AtomicCommitError**（`write_hooks.py:39-55`） | ✅ Flush 部分失败时 raise + failed_paths 列表<br>✅ 调用方必须 observe | ❌ **失败时已 commit 的卡不会自动回滚**—— `AtomicContext.__exit__` raise 时只清 bucket，但**其他线程已 flush 的内容仍在磁盘** | 文档化"partial commit 已发生，调用方负责 rollback"；提供 `partial_commit_paths.json` 自动记录 |
| **`--dry-run`**（T7） | ✅ 跑完不写盘（仅生成报告） | ❌ **dry-run 输出格式未定义**（Round 1.5 复审 ③-7 已指出）<br>❌ **dry-run 不检查磁盘空间、provider 配置、网络** | 实施 T7 时定义 `dry_run_report.csv` schema；预检 4 项前置条件 |
| **V6 schema PR 1 失败时的 PR 2/3** | ✅ PR 拆分独立可测<br>✅ PR 1 失败 = 整体 V6 升级失败，PR 2/3 不应继续 | ❌ **PR 1 失败的合并冲突**（main 分支别人改 `types.py`）→ rebase 成本<br>❌ **PR 1 失败时 PR 2 已合并** → PR 2 tag namespace 引用了 PR 1 新字段 → **build 失败** | PR 1 必须先合；PR 2 实施时假定 PR 1 在 main；CI 加"V6 fields exist" 守卫 |
| **PR 1 V6 schema 字段写盘**（ADR-0008 D1-D2） | ✅ 9 字段持久化<br>✅ V5 向后兼容（from_dict 填默认）<br>✅ 17-key round-trip | ❌ **`platform` 与 `_ko_extra.platform` 数据冗余**（Round 1.5 新-2）<br>❌ **下游 grep `_ko_extra.platform` 的代码失效**（Round 1.5 ①-1 新引入风险） | ADR-0008 显式列出下游读取 `_ko_extra` 字段的代码位置；T1 acceptance 增"platform 双写策略" |
| **`scripts/rebuild_vectors.py`**（T10.0 / ADR-0008 D8） | ✅ 内置 provider 自检（**理论上**）<br>✅ 接受 `--project` 参数 | ❌ **provider 自检逻辑未在方案中给出**——可能仅 echo "providers exist" 不实际测试<br>❌ **无 retry / backoff / checkpoint**<br>❌ **维度冲突未处理**（384 vs 1536） | 实施时 provider 自检验证 `provider.dim()` 实际可调；retry 5 次 + checkpoint |
| **`slug_aliases.json` 正向格式**（D5） | ✅ v2 entity 卡的 aliases 正确解析<br>✅ canonical = file stem（带空格） | ❌ **仅覆盖 5 张 entity 卡**——v2 概念卡 CJK 标题**未注册 alias** | T3 把所有 v2 概念卡的 CJK 标题变体（小写、空格、英文）也注册 |

---

## 维度 4：边界临界点

### 临界点 4.1：v2 vault 损坏率 > 5% 时迁移进入"半成功半失败"灰色地带
- **现状**：1924 张 wiki 卡中损坏率 5% = 96 张卡；这些卡 yaml 解析失败 / frontmatter 缺失关键字段 / 文件 0 字节。
- **临界分析**：
  - T1 转换器 catch `yaml.YAMLError` 后**默认行为未定义**——可能 raise → 中断；可能 skip → 静默丢失。
  - 当前方案未规定 corrupt card 处理策略。
  - **96 张损坏卡不修复就迁移**：迁移器产出的 KB **不完整**（用户误以为成功）。
  - **96 张损坏卡走严格 fail 模式**：迁移器中断 → 用户需手工修复 96 张卡 → 1-2 天工作量。
- **现状**：无法承受
- **加固建议**：
  1. **P0**：T1 默认 `--on-corrupt {skip, fail, quarantine}`；默认 `quarantine`（损坏卡移到 `.index/quarantine/corrupt/` + 报告）。
  2. **P0**：损坏卡**永不静默丢弃**——必须写入 `corrupt_cards.csv`。
  3. **P1**：损坏率 > 阈值（5%）时 abort 并提示用户批量修复。

---

### 临界点 4.2：LLM Embedding API 配额 < 200 次时 Phase 4 必然失败
- **现状**：1924 张卡 × 1 卡 1 次 embed 调用（如果 chunk size = card size）≈ 1924 次 API call；若卡有 sub-chunk（avg 3 chunks）≈ 5772 次。
- **临界分析**：
  - OpenAI Tier-1 free $5 credit 通常够 1924 次 embed，但**新账户**可能仅 $1。
  - MiniMax/Kimi 等国产 API 通常无免费层或极少免费次数。
  - **配额 < 200 次** → Phase 4 第 201 张卡必失败 → 用户中断 → **Phase 1-3 数据已写 + LanceDB 半残**。
- **现状**：无预检，无优雅降级
- **加固建议**：
  1. **P0**：scripts/rebuild_vectors.py 启动时调 `provider.remaining_quota()` 估算；不够 abort + 用户提示。
  2. **P0**：默认 `--provider local` (sentence-transformers)——384 维但免费；与 §E1 验收 1536 冲突需明确。
  3. **P1**：支持 batch 切换：先用本地 embed 跑 80%，剩余 20% 用 OpenAI（避免超限）。

---

### 临界点 4.3：v2 raw 撞名数 > 126（实测数）时 dry-run 无法精准预测
- **现状**：实测 126 个撞名（Round 1 综合 ②-2 行 105-114）；D4 决策默认 `--on-collision fail`。
- **临界分析**：
  - 用户撞 126 个 = 迁移器 abort at 第 N 个撞名 → **无法精准预测是哪个撞名**。
  - 若 v2 在迁移前又被用户编辑 + 新增撞名（撞 200 个）→ abort 时已处理 150 张卡 → 仍半残。
  - 若 0 个撞名（理论极端）→ D4 决策的 `--on-collision fail` 配置无意义 → **用户为不存在的失败模式付复杂度代价**。
- **现状**：默认 fail 太激进；默认 skip 又掩盖了问题
- **加固建议**：
  1. **P1**：默认 `--on-collision skip`（保守：用户 v2 自己跑得好好的，不应让撞名阻塞迁移）；用户显式 `--strict` 才 fail。
  2. **P0**：`collision_report.csv` 必须含 `suggested_resolution` 列（bilibili__ 前缀 / douyin__ 前缀 / 保留原名 / 跳过 4 种规则）。
  3. **P2**：自动 resolve 模式：撞名时按平台优先级（前缀最短者优先）自动 rename，不 abort。

---

### 临界点 4.4：迁移时间 > 30 分钟时 Ctrl+C 概率 > 80%
- **现状**：实测/推算全量迁移 ~13-30 分钟（不含 raw）；raw 搬运 ~5 分钟；LanceDB 重建 9-20 分钟。**总 30-55 分钟**。
- **临界分析**：
  - 用户专注时间平均 15 分钟（番茄工作法）→ 30 分钟内必然 1 次中断尝试。
  - 用户执行 Ctrl+C 时**很可能不看输出** → **半残状态用户不知道** → **过几天发现检索不全**。
  - **30 分钟是单次可接受阈值的临界**——超过 30 分钟应分批可恢复。
- **现状**：无 checkpoint / 无 resume
- **加固建议**：
  1. **P0**：所有 Phase 写 checkpoint：migration_progress.jsonl（wiki 卡）+ raw_progress.jsonl（raw 文件）+ rebuild_progress.jsonl（lancedb）。
  2. **P0**：所有子命令支持 `--resume`：默认 true（中断后自动续跑）。
  3. **P1**：Phase 1-4 拆为 4 个独立子命令 `migrate-v2-wiki` / `migrate-v2-raw` / `migrate-v2-rebuild-vectors`，用户可分批跑。

---

### 临界点 4.5：v2 sqlite `compile_db.sqlite` 损坏时无法导出 snapshot
- **现状**：v2 `compile_db.sqlite` 约 840 KB（调研 §2 行 37），可能因 v2 vault 历史编辑损坏。
- **临界分析**：
  - T8 步骤 7 行 863 "compile_db.sqlite 快照：导出为 CSV"——若 sqlite 文件损坏，`sqlite3.connect` 抛 `DatabaseError`。
  - **无 catch 策略** → 迁移器 abort。
  - 但 sqlite snapshot 仅供查阅用（CLAUDE.md 调研 §8 行 248-256"不迁移 records 表"）—— **非阻塞**。
- **现状**：可能误阻塞迁移
- **加固建议**：
  1. **P1**：T8 步骤 7 用 `try: ... except sqlite3.DatabaseError: log_warning("compile_db 损坏，跳过 snapshot 步骤")`；snapshot 失败不阻塞 wiki / raw 迁移。
  2. **P2**：sqlite 损坏时尝试 `.recover` 命令（sqlite3 CLI）转储为 SQL 文本作为替代。

---

### 临界点 4.6：v2 `_to_recompile/` pending 卡数 > 1000 时 pending_decisions.csv 不可管理
- **现状**：实测 155 张 pending（D1 决策行 344）。
- **临界分析**：
  - **当前 155 张** → 用户可手工审查（每张 2-5 分钟 = 5-13 小时工作）。
  - **若 > 500 张** → 手工审查不现实（每张 2-5 分钟 = 17-42 小时）。
  - **若 > 1000 张** → 必须自动化 promote 策略，否则永不完成。
- **现状**：方案仅描述 155 张时的处理
- **加固建议**：
  1. **P1**：T6 加 `--pending-policy {manual, auto-promote-latest, auto-archive}` 选项。
  2. **P1**：auto-promote-latest 模式：mtime 最新者胜出（避免手工）。
  3. **P2**：pending 数 > 500 时建议用户先用 `--pending-policy auto-archive` 把 stale pending 归档。

---

### 临界点 4.7：ruflo-kb 服务启动时 video-notes-wiki 已部分迁移但 LanceDB 未建
- **现状**：Phase 1-3 完成 + Phase 4 未跑 → 服务启动 → search 返回 0 命中（lancedb 空）。
- **临界分析**：
  - 用户以为 Phase 1-3 完成 = 迁移完成 → 跑 `serve` → 检索失败。
  - **无明确"Phase 4 未完成"提示**。
  - ruflo-kb 服务启动无 `lancedb 行数 vs wiki 卡数` 不匹配检测。
- **现状**：用户困惑，无明确错误信息
- **加固建议**：
  1. **P1**：`python -m src.cli serve` 启动时检测 `lancedb rows vs wiki 卡数`，差距 > 5% 时 WARN："建议跑 `python -m src.cli migrate-v2 --rebuild-vectors`"。
  2. **P0**：migration_report.csv 显式标"Phase 4 状态：PENDING"或"COMPLETE"。

---

### 临界点 4.8：ruflo-kb 默认 384-dim vs 验收 §E1 写 1536-dim 文档与代码冲突
- **现状**：`store.py:39 DEFAULT_EMBEDDING_DIM = 384` vs 验收 §E1 行 185 "向量维度 1536"。
- **临界分析**：
  - 用户配 OpenAI `text-embedding-3-small` (1536) → `init_vector_store_for_paths(paths, expected_dim=1536)` → 创建 1536 维 chunks table ✓
  - 但用户配 MiniMax `bge-large-zh-v1.5` (1024) → `expected_dim=1024` → 现有 1536 table 抛 `VectorDimensionMismatchError`（`store.py:42-49`）→ 用户必须显式 `rebuild_vector_schema(paths, dim=1024)`。
  - **方案未明示维度判定流程**——用户可能在 384 / 1024 / 1536 之间混乱。
- **现状**：Round 1.5 复审行 75-78 已指出未修复
- **加固建议**：
  1. **P0**：验收 §E1 改为"`expected_dim = embedding_provider.dim()`"——不再写死 1536。
  2. **P0**：scripts/rebuild_vectors.py 显式 `print(f"embedding dim: {provider.dim()}")`；不匹配 abort。
  3. **P1**：方案文档增"维度决策树"：`provider → dim → init` 一张表。

---

## 维度 5：加固方案汇总

| 加固项 | 优先级 | 工作量 | 阻塞 PR 3 编码 |
|---|---|---|---|
| **G1**：T1 用 try/except 包裹 validate_tag_compliance（fail-soft）| P0 | 0.5 天 | 是 |
| **G2**：scripts/rebuild_vectors.py 加 retry/backoff/checkpoint | P0 | 1 天 | 是 |
| **G3**：`--rollback-phase1to3` 强制 `--project <uuid>` + 精确回滚（migration_already_written.jsonl）| P0 | 1 天 | 是 |
| **G4**：T1 写盘前检测 `_v2_origin` 标记（避免覆盖用户手编辑）| P0 | 0.5 天 | 是 |
| **G5**：T1 `normalize_tags()` 实现 + 单元测试 + 验收 §B2 增"tag 总和"检查 | P0 | 1 天 | 是 |
| **G6**：T10 步骤 0 增加 provider 预检 + 文档维度决策树 | P0 | 0.5 天 | 是 |
| **G7**：迁移器全程 checkpoint（migration_progress.jsonl / raw_progress.jsonl / rebuild_progress.jsonl）+ `--resume` 默认 true | P0 | 1.5 天 | 是 |
| **G8**：磁盘预检 `shutil.disk_usage > 5 GB` 在 --apply 前 | P0 | 0.25 天 | 是 |
| **G9**：corrupt card 处理器（`--on-corrupt quarantine` 默认）| P1 | 1 天 | 否（但建议） |
| **G10**：`_atomic_replace` 加超时 + 启动时 `clean_stale_tmp_files` | P1 | 0.5 天 | 否 |
| **G11**：T7 dry-run 报告 schema 明确定义（CSV 列清单）| P1 | 0.5 天 | 否 |
| **G12**：wiki 卡覆盖策略 `--on-wiki-collision {skip, fail, backup}` | P1 | 0.5 天 | 否 |
| **G13**：T3 把所有 v2 概念卡的 CJK 标题变体注册到 `slug_aliases.json` | P1 | 1 天 | 否 |
| **G14**：F1 阈值改为 ≤ 10 分钟（含 raw + wiki + LanceDB）+ 实时进度输出 | P1 | 0.5 天 | 否 |
| **G15**：T1 acceptance 增 CJK 标题 wikilink 解析测试 | P1 | 0.25 天 | 否 |
| **G16**：`migration_warnings.csv` 通用警告收集器（覆盖 tag / wikilink / corrupt / pending / quorum 等）| P1 | 1 天 | 否 |
| **G17**：迁移期间 v2 vault 备份 `tar -czf v2_vault_pre_migration.tar.gz` | P1 | 0.25 天 | 否 |
| **G18**：方案文档增 "embedding 限流降级方案" + provider 切换降级 | P2 | 0.5 天 | 否 |
| **G19**：方案文档明确"迁移器单进程运行；不支持 --parallel" | P2 | 0.1 天 | 否 |
| **G20**：`scripts/rebuild_vectors.py --provider <openai|local|minimax>` 选项 | P2 | 0.5 天 | 否 |
| **G21**：`python -m src.cli serve` 启动检测 lancedb vs wiki 卡数差距 + WARN | P2 | 0.5 天 | 否 |
| **G22**：F-bis-2 改为 URL 模板生成检查（非实际 HEAD 请求）| P2 | 0.25 天 | 否 |
| **G23**：T6 `--pending-policy {manual, auto-promote-latest, auto-archive}` 选项 | P2 | 0.5 天 | 否 |
| **G24**：pending 数 > 500 时自动建议 `--pending-policy auto-archive` | P2 | 0.25 天 | 否 |
| **G25**：sqlite `compile_db.sqlite` snapshot 失败不阻塞（try/except log warning）| P2 | 0.1 天 | 否 |
| **G26**：`wiki_pre_migration_hash.json` md5 对账（迁移前/后差异报告）| P2 | 0.5 天 | 否 |

---

## 总体判定

### 方案鲁棒性评级：⭐⭐⭐⭐（4 星 / 5 星满分）

**评估依据**：
- ✅ 核心架构（V6 schema + PR 拆分 + D9a 决策 + rollback 子命令）设计正确
- ✅ AtomicContext + safe_write 兜底机制在源码层完善（`atomic_ctx.py:75-78`、`write_hooks.py:97-121`）
- ✅ Round 1+1.5 已修复 26 个问题，致命缺陷结构性解决
- ⚠️ 但 Round 2 暴露**大量"实施细节未到位"**的兜底缺口
- ❌ **关键 P0 加固项必须在 PR 3 编码前完成**，否则 Phase 4 失败概率 > 50%

### 可承受的失败模式（已覆盖）

- 单卡写盘原子失败（`safe_write` 的 `os.replace` + 5 次 retry + fallback）
- 进程异常时清理 pending（`AtomicContext.__exit__` 清 bucket）
- 单进程多线程并发（per-thread bucket 隔离）
- V5 → V6 schema 升级（`from_dict` 容忍 + 默认值填充）
- v2 free-form tag（V6 PR 2 加 5 新前缀 + mandatory pair 条件化）
- slug_aliases.json 正向格式（D5 决策）
- Phase 4 失败回滚 Phase 1-3（**文档级**，实施时需精确化）
- capture marker 注入（D9a 决策）

### 不可承受的失败模式（未覆盖）

- **P0**：迁移中途中断后无法精确恢复（无 checkpoint / resume）—— 用户必须全量回滚重来
- **P0**：LanceDB rebuild 失败后无 resume / 无回滚 lancedb 残留
- **P0**：rollback 命令未限定 project_id，**可能误删 novel-wiki 同名卡**
- **P0**：用户手编辑与迁移器写盘冲突，无冲突检测（**用户手编辑可能丢失**）
- **P0**：tag 校验失败时迁移器 abort，无 fail-soft 策略
- **P0**：embedding API 配额耗尽 / 限流 → Phase 4 必失败无降级
- **P1**：磁盘满 / 内存溢出 / 网络中断无预检
- **P1**：corrupt card 无处理策略（默认 raise 中断）
- **P2**：维度冲突（384/1024/1536）未明示决策流程

### 总体判定：⚠️ **需先加固 8 项 P0 才能进入 Phase 0 PoC**

**必须修复的 8 项 P0**：
1. **G1**（T1 fail-soft tag 校验）+ **G5**（normalize_tags 单元测试）
2. **G2**（rebuild_vectors retry/checkpoint）
3. **G3**（rollback 限定 project_id + 精确回滚）
4. **G4**（wiki 卡覆盖冲突检测）
5. **G6**（provider 预检 + 维度决策树）
6. **G7**（全程 checkpoint + resume）
7. **G8**（磁盘预检）

**整改后流程**：
```
Round 2 压力测试（本报告）
        ↓
人工复核 + 用户拍板 G1-G8 加固项
        ↓
执行 G1-G8 加固（约 5.25 天工作量）
        ↓
Round 2.5 复审（验证加固落地）
        ↓
Phase 0 PoC（5 张样本卡试跑）
        ↓
Phase 1-4 TDD 实施
```

### 下一步建议

1. **立即**：用户拍板 G1-G8 P0 加固项是否进入 PR 3 编码（5.25 天工作量）
2. **同步**：更新调研报告 §"Round 2 整改记录" + 实施方案 §"V6 路线图工时汇总"加入 P0 加固项
3. **同步**：验收清单 §V-3 §V-5 增加 G1/G5/G7 相关检查项（normalize_tags / checkpoint / tag 总和）
4. **复审**：G1-G8 完成后 Round 2.5 复审，确认 8 项 P0 全部修复
5. **PoC**：Phase 0 PoC 必须先验证 G2（rebuild_vectors retry）+ G3（rollback 精确回滚）+ G4（手编辑保护）

---

**报告结束 · 12 个失败路径场景 + 4 个连锁反应分析 + 9 个兜底机制评估 + 8 个边界临界点 + 26 项加固方案**

**独立第三方 Round 2 压力测试完成 · 总体判定 ⚠️ 需先加固 8 项 P0 才能进入 Phase 0 PoC**