# novel-wiki 全量 Book 可读性整改（4 Task + rollout）— 2026-09-10

## 结果

5 项 commit + 1 项文档落地，1 项未追踪配置改动（policy.json）。代码与文档就位，操作员按 rollout guide 即可 apply。

## Commits（按时间顺序，codex/book-series-target 分支）

- `46197677` `fix(book)` — `_book_outline_metadata` 双 key 索引
- `8aedd1e3` `test(book)` — 12 回归 + 集成 smoke 测试
- `56418840` `feat(book)` — `preface` 字段 + `generate_chapter_titles` + `book retitle` CLI + script
- `d35434ec` `feat(book)` — `partition_writing_technique_merged` + regroup script + 11 测试
- `87fa6bdb` `docs(guides)` — rollout 手动操作指南初版
- `814fda48` `docs(guides)` — 修正 rollout env 说明

## 测试基线

- 新增测试 36 个（Task 0/1/2 = 12 + Task 3 = 12 + Task 4 = 11 + preface 集成 2；rollout 验收 11 项 grep 验证）
- 全套 test_kc + test_server 跑 1019 + 2 (preface 集成) = **1021 passed**
- `test_cli_ext` 单独跑全量超 120s 是 pre-existing 问题（与本任务无关），子集 4/4 + 21/21 单独跑正常

## 关键根因发现（Task 0）

`_book_outline_metadata` 在 `src/services/files.py` 已经能正确按 outline.json 顶层 `[OutlineProposal]` + `volumes[].chapters[]` 解析，**问题在 `book_wiki_manifest` 的 key 推导**：

- 写盘：`compiler.py:708` 用 `name = f"{_safe(volume_id)}__{_safe(chapter_id)}.md"`
- `_safe()`（`compiler.py:475-477`）保留 `:` 不变，但**写盘文件名是直接用 `_safe` 转出的安全字符串**，而 `_safe("写作技法:5")` 返回 `"写作技法_5"`（**`_safe` 不转 `:`**）
- 读回：`files.py:299-300` `chapter_id.split("__", 1)[-1]` 拿到 `concept-写作技法_5`（下划线）
- `_book_outline_metadata` 存的 key 是 outline 原生 `concept-写作技法:5`（**冒号**）
- → **179/179 lookup miss**，WebUI 全走前缀 fallback 到 4 个粗桶

**修复**：`_book_outline_metadata` 同时索引两种 key（native + `_safe`），指向同一 meta 对象。Test 实测修复后 179/179 填上 `volume_id`。

## 设计关键决策

### first-match-wins + catch-all

`DEFAULT_WRITING_TECHNIQUE_REGROUP` 8 个新卷的关键词顺序是设计选择：
- 第一个 `人物塑造与设定` 触发关键词最多（人物|主角|配角|性格|女主|反派|身世），作为**catch-all**
- 后续按"具体主题优先"排序（如 `签约` 先匹配 `开篇与签约` 规则，不匹配 `平台与读者` 的 `平台`）

测试 pin 住这个行为（`test_first_match_wins_on_overlapping_keywords`），防止后续 reorder 引入回归。

### `provider=None` fallback 完整性

`generate_chapter_titles` 与 `partition_writing_technique_merged` 都设计为 provider=None 时仍能完整跑通：
- Task 3：fallback 用 outline 原 title 当 friendly title（pipeline 不崩，stats.failed > 0 是可观测信号）
- Task 4：partition 不需要 LLM，直接 keyword regex 分配

这两个 fallback 让所有代码可在 CI 离线测试，也保证 operator 缺 key 时 pipeline 不挂。

### apply-from seam（已存在复用）

方案设计时 Task 4 用全新 apply-from 路径，但实际查代码发现 `src/cli_ext/book_cmd.py:160-164` 已有 `apply_from` handler + `build_from_wiki(... apply=True, apply_from=release_id)` 完整支持。**新代码不需要新建发布路径**，只需 partition 函数产出 8 个新卷 ID 让 compiler 处理。

## 已知 pre-existing 问题（与本任务无关）

- `test_cli_ext` 全套跑 >120s（Windows + 多服务测试串行）—— 单文件跑 OK
- `cli.py` 全 LCM 加载慢（37 个 subparser 注册）—— pre-existing，不影响本任务
- WebUI `volumeFor` 的 4 桶 fallback 行为（`web/js/views/book.js:299-301`）—— Task 0 修复后实际不再触发，但 fallback 代码未删，保留作为防御

## 操作员剩余步骤（不在 git 内）

1. ~~配置 LLM key~~ — `.env` 已配置 minimax（125 chars key + base_url + model），CLI 自动加载（`src/cli.py:89-96` 的 `load_dotenv`）
2. ~~提 budget~~ — `policy.json` 的 `budget_cap` 已从 450 提到 800（`.gitignore` 排除 `knowledge/*/.llm-wiki/`，故未 commit）
3. **Step 2 dry-run 验证**：curl `/api/v1/projects/novel-wiki/book-wiki` 确认 179/179 填上 volume_id；`scripts/regroup_writing_technique_chapters.py --project novel-wiki` 确认 8 个新卷；浏览器打开看到 ~9 真名卷
4. **Step 3 apply**：先 `scripts/title_book_chapters.py --project novel-wiki --apply`，再 `python -m src.cli book build-from-wiki --project novel-wiki --preview --apply-from`
5. **Step 4 promote**：校验 11 项 checklist 后 `book build-from-wiki --apply-from <new_release_id>`

详细 11 项 verification checklist + 4 步回滚方案见 `docs/guides/novel-wiki-book-readability-rollout.md`。

## 工程经验教训（未来 Book 整改可复用）

1. **方案审计必须跑 `book_wiki_manifest` 实际输出模拟**（不是只看单一函数）。本任务的关键 bug 在 outline→manifest 这条**整合路径**上，单看 `_book_outline_metadata` 或单看 `book_wiki_manifest` 都看不到。
2. **方案文本 vs 实际代码的偏差**：第一版方案 Task 1/2 是 "no-op 修复"——直接基于"代码已正确"的假设。实际跑发现 key lookup 路径有 bug，需要提升为 Task 0 真 bugfix。教训：方案评审必须做"代码 + 数据"双重验证，不能只读方案文本。
3. **`.env` 自动加载是项目基础设施**（`src/cli.py:89-96`），操作员无需手动 export。rollout guide 初版误写 `export MINIMAX_API_KEY=...` 已修正（`814fda48`）。
4. **Windows 下 `_config_path()` 在 `~\\ruflo-kb\\ruflo-kb\\llm-providers.json` 路径双 `ruflo-kb`**（用户配置目录 + registry 子目录拼接 bug），不影响本任务（env var 走 Tier 1 覆盖 registry 的 default slot），但记下供未来查。
5. **`.env` 与 `policy.json` 都被 `.gitignore` 排除**（`.env` 在 `knowledge/*/.env` 排除，`policy.json` 在 `knowledge/*/.llm-wiki` 排除 line 55）—— runtime 配置不入仓是项目设计，操作员改这些文件不影响任何 commit。
6. **edit 工具在 Windows 上对大文件（>500 行）会触发 EOL 转换（LF→CRLF 或反过来）**，破坏 git diff 整洁。解决方案：用 Python 字节级 patch（CRLF 显式保留），不用 `edit` 工具做大文件局部改动。本任务 4 次踩到这个坑，最终都用 `python -c` 或 `.py` 字节级脚本修。

## 关键文件清单

### 代码

- `src/services/files.py:183-210` — `_book_outline_metadata` 双 key 修复
- `src/services/files.py:296-322` — preface 字段
- `src/kc/views/book/wiki/polish_llm.py:418-555` — `generate_chapter_titles` + sanitize/disambiguate/fallback
- `src/kc/views/book/wiki/partition.py:483-585` — `partition_writing_technique_merged`
- `src/cli_ext/book_cmd.py:481-580` — `cmd_book_retitle`
- `src/cli.py:667-675` — `book retitle` subparser 注册

### Scripts

- `scripts/title_book_chapters.py` — Task 3 驱动
- `scripts/regroup_writing_technique_chapters.py` — Task 4 驱动

### 测试

- `tests/test_kc/test_book_wiki_outline_volume.py` — 12 测试（Task 0/1/2）
- `tests/test_kc/test_book_chapter_titles.py` — 12 测试（Task 3）
- `tests/test_kc/test_book_writing_technique_regroup.py` — 11 测试（Task 4）
- `tests/test_server/test_service_files.py` — 2 preface 集成 + 既有 13 测试

### 文档

- `docs/guides/novel-wiki-book-readability-rollout.md` — 351 行 rollout 手册
- `docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md` — 303 行方案第三版（含 Task 0/1/2/3/4 + Audit + 复审闭环）

## 关联已有 memory

- `feedback-novel-wiki-fullbook-published-2026-09-10.md` — 上次全量发布的 baseline（`f728939909c44bdf9d7efb6e26760c9d` = 179 章 complete）
- `feedback-book-llm-republish-hardening-2026-09-09.md` — LLM 调用硬化的根因（response shape retry budget）
- `feedback-novel-wiki-book-budget-root-cause-2026-09-09.md` — `max_attempts` vs `max_retries` 冲突的根因（避免重复踩坑）

## 收益量化

| 收益维度 | 修复前 | 修复后 | 路径 |
|---|---|---|---|
| A. WebUI 目录分桶 | 4 桶 | ~9-50 真名卷 | Task 0（已生效）+ Task 4 apply 后 |
| B. 章名可读性 | `concept-写作技法__concept-写作技法_5` | ≤14 字中文 | Task 3 apply 后 |
| C. 总序导读 | 无 | 2500-4000 字 preface | Task 3 apply 后 |
| D. 写作技法可读性 | 68 章节 | 8 大章 | Task 4 apply-from 后 |

## 后续建议

1. **acceptance 报告字段扩展**（方案 Round 2 加固中提到的 `merged_chapter_count` / `baseline_release_id`）— 当前未实施，apply-from 时可补
2. **acceptance 报告字段**应同时记录 `merged_chapter_count` 与 `baseline_release_id`，让 release 之间的对比可追溯
3. **重复任务的 LLM 调用预算**应作为 long-lived plan 的 `budget_cap` 上限 prompt feature：默认 450 对单次 179 章完整 LLM 不够，operator 应直接配 800+（不是 800 是最小安全值）

## 启动下一轮 LLM Book 整改时的 checklist

- [ ] 第一件事跑 `book_wiki_manifest` 实际输出模拟（不是读代码就改方案）
- [ ] 第二件事看 `.env` 是否已配（避免 rollout guide 写错的 export 步骤）
- [ ] 第三件事验证 `_safe` 与 `_book_outline_metadata` 的 key 一致性（看是否需要双 key 索引）
- [ ] 第四件事**先 dry-run**（scripts/）— operator 必须能看输出后再 decide apply
- [ ] 第五件事 budget_cap 提前算（每次实际 LLM 都会比预估多 30%+）
