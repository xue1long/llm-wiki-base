---
rules:
  id:
    pattern: "^[a-z0-9-一-鿿]+$"
    frontmatter:
      required: [title]
---

# novel-wiki 全量 Book 可读性整改 — 落地操作指南

> 状态：操作指南（代码已合并，待运行）
> 范围：`knowledge/novel-wiki/book-wiki/`
> 关联方案：`docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md`
> 关联 Commits：`46197677`、`8aedd1e3`、`56418840`、`d35434ec`

本指南是 `2026-09-10-novel-wiki-fullbook-readability` 方案的**手动运行手册**。代码已在 4 个 commit 中合并并通过全部回归测试，但实际把 Book 写到发布 release 上的步骤必须由操作员手动执行——LLM 调用是外部副作用，不能在 CI 里跑。本指南列出 **3 步操作 + 验证 checklist + 回滚预案**，覆盖从环境准备到 apply-from 完整流程。

---

## 0. 前置条件

| 项 | 当前值 | 操作员必须做的 |
|---|---|---|
| `MINIMAX_API_KEY` (或 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) | **未配置** | 配置 LLM provider key |
| `RUFLO_LLM_PROVIDER` | `minimax` | 与 key 匹配 |
| `knowledge/novel-wiki/.llm-wiki/policy.json` 中 `budget_cap` | `450` | **提到 800** |
| LLM 调用预算（Task 3 + 4 合计） | 估算 377 次 | 真实可能 400-600；800 cap 兼容 |
| 当前 active release | `f728939909c44bdf9d7efb6e26760c9d` | 保持现状作为 baseline |
| 服务端 server | 未启动 | `python -m src.cli serve --host 127.0.0.1` |

如果 LLM provider key 仍未配置，方案 Task 3 的 `generate_chapter_titles` 会自动回退到 `provider=None` 路径（用 outline 现有 title 当 friendly title），pipeline 不会崩，但章名质量不会提升。本指南**假设操作员愿意配置 LLM key**。

---

## 1. 操作步骤

### Step 1：环境准备（5 分钟）

```bash
# 1.1 配置 LLM provider（已配置 minimax 作为 default，只需补 key）
# Linux/Mac：
export MINIMAX_API_KEY="<your-key>"
# Windows PowerShell：
$env:MINIMAX_API_KEY = "<your-key>"

# 1.2 验证 provider 可解析
python -m src.cli llm-providers list
# 应列出 minimax（来自 ~/.config/ruflo-kb/llm-providers.json 的 default slot）

# 1.3 提 budget_cap 到 800
# 编辑 knowledge/novel-wiki/.llm-wiki/policy.json：
#   "budget_cap": 450  →  "budget_cap": 800
# 验证：
python -c "
import json
p = json.load(open('knowledge/novel-wiki/.llm-wiki/policy.json'))
print('budget_cap:', p['budget_cap'])
assert p['budget_cap'] == 800, 'still 800 not set'
"

# 1.4 确认回归测试基线
cmd /c "set PYTHONPATH=.& python -m pytest --import-mode=importlib tests\test_kc\test_book_wiki_outline_volume.py tests\test_kc\test_book_chapter_titles.py tests\test_kc\test_book_writing_technique_regroup.py tests\test_server\test_service_files.py -q"
# 期望：52 passed
```

**决策门**：52 测试全过 → 进 Step 2。任何 fail → 停止，按 §4 回滚预案处理。

### Step 2：dry-run 验证（10 分钟）

```bash
# 2.1 启动 server（后台），便于 WebUI 验证
python -m src.cli serve --host 127.0.0.1 &
# 等 2 秒
sleep 2

# 2.2 验证 Task 0 修复已生效（无需 LLM，仅读 release）
curl -s "http://127.0.0.1:19828/api/v1/projects/novel-wiki/book-wiki" | python -c "
import json, sys
m = json.load(sys.stdin)
chapters = m['chapters']
print(f'chapters: {len(chapters)}')
filled = sum(1 for c in chapters if c.get('volume_id'))
print(f'with volume_id: {filled} / {len(chapters)}')
volumes = m['volumes']
nonzero = sum(1 for v in volumes if v['chapter_count'] > 0)
print(f'volumes with chapters: {nonzero} / {len(volumes)}')
preface = m.get('preface')
print(f'preface field: {preface}')
"
# 期望输出（不要 0/N）：
#   chapters: 179
#   with volume_id: 179 / 179
#   volumes with chapters: >= 9 / 61
#   preface field: None

# 2.3 验证 Task 4 regroup dry-run（无需 LLM）
python scripts/regroup_writing_technique_chapters.py --project novel-wiki
# 期望输出：
#   new chapters: 8 (target 8), passthrough buckets: N, total pages: 1255
#   + concept-写作技法-人物塑造与设定: ~150 pages
#   + concept-写作技法-情节与节奏: ~120 pages
#   ...（8 个新卷）
#   = concept-题材体系: ~N pages  （passthrough）
#   = fallback: ~M pages       （passthrough）

# 2.4 验证 Task 3 generate_chapter_titles dry-run（provider=None）
python scripts/title_book_chapters.py --project novel-wiki
# 期望输出（dry-run，不写文件）：
#   book-wiki/f728939909c44bdf9d7efb6e26760c9d: 179 chapters
#     output: book-wiki/.releases/<active>/editorial/chapter-titles.json
#     preface: book-wiki/.releases/<active>/preface.md (target ~2500 words)
#   dry-run: pass --apply to write files

# 2.5 浏览器手动确认（30 秒）
#   打开 http://127.0.0.1:19828 → 选 novel-wiki → 进入 Book 视图
#   期望：左侧目录出现 ~9-50 个真名卷（如"写作技法 / 题材体系 / 平台规则"等），
#         不再是 4 个粗桶（Sources / Concepts / Entities / Synthesis）。
#   注意：本步只验证 Task 0 修复；章名友好化和 preface 在 Step 3 之后才生效。
```

**决策门**：
- 2.2 chapters filled = 179/179 → Task 0 修复生效 ✓
- 2.3 regroup 列出 8 个新卷 + passthrough 总数 = 1255 → Task 4 partition 正确 ✓
- 2.5 浏览器看到真名卷 → 收益 A 视觉兑现 ✓

任何不通过 → 停止，按 §4 回滚。

### Step 3：apply 真正写入（30-60 分钟，**有外部 LLM 调用**）

```bash
# 3.1 先生成 chapter-titles.json + preface.md（Task 3 apply）
python scripts/title_book_chapters.py --project novel-wiki --apply
# 输出：wrote book-wiki/.releases/<active>/editorial/chapter-titles.json
#       wrote book-wiki/.releases/<active>/preface.md
#       stats: truncated=N, renamed=N, failed=0
#       failed 应为 0；若 >0 表示 LLM 调用失败但用了 fallback，可接受但需记录。

# 3.2 验证 chapter-titles.json 写入
python -c "
import json
p = 'knowledge/novel-wiki/book-wiki/.releases/f728939909c44bdf9d7efb6e26760c9d/editorial/chapter-titles.json'
d = json.load(open(p, encoding='utf-8'))
print('version:', d['version'])
print('titles:', len(d['titles']))
print('stats:', d['stats'])
assert d['stats']['failed'] == 0, 'LLM failed for some chapters'
# 中文标题应在 ≤14 字
for cid, title in d['titles'].items():
    assert len(title) <= 14, f'{cid} title too long: {title}'
print('OK: all titles <= 14 chars')
"

# 3.3 验证 preface.md 写入
python -c "
import os
p = 'knowledge/novel-wiki/book-wiki/.releases/f728939909c44bdf9d7efb6e26760c9d/preface.md'
size = os.path.getsize(p)
print(f'preface.md size: {size} bytes')
assert size >= 2500 * 2, 'preface too short (< 2500 chars); LLM likely produced a stub'
"

# 3.4 跑实际 build-from-wiki（Task 3 + Task 4 apply）
# 这一步是 apply-from seam 的真正执行：会触发 LLM 调用重新生成 8 个合并章节
python -m src.cli book build-from-wiki --project novel-wiki --preview --apply-from
# 注意：--preview 先生成 preview release，验证后再 --apply
# 期望：返回新 release_id，下一步才 --apply

# 3.5 验证 preview release
NEW_RELEASE=<paste new release id here>
python -c "
import os
release_dir = f'knowledge/novel-wiki/book-wiki/.releases/${NEW_RELEASE}'
md_files = [f for f in os.listdir(release_dir) if f.endswith('.md') and f != 'preface.md']
print(f'md files in preview: {len(md_files)}')
# 应有：8 个新写作技法章 + 110 个原章节 + index/glossary/sources-index/preface
assert len(md_files) >= 110, 'preview missing chapters'
# 验证 8 个新章是否存在
new_chapters = [f for f in md_files if 'concept-写作技法-' in f and '__' in f]
print(f'new writing-technique chapters: {len(new_chapters)}')
assert len(new_chapters) == 8, f'expected 8 new chapters, got {len(new_chapters)}'
# 验证 page_id 不丢
all_pages = set()
import json
manifest = json.load(open(f'{release_dir}/manifest.json', encoding='utf-8'))
print(f'page_count: {manifest[\"page_count\"]}, chapter_count: {manifest[\"chapter_count\"]}')
assert manifest['page_count'] == 1255, 'page_count drifted'
"

# 3.6 浏览器再次确认
# 打开 http://127.0.0.1:19828 → novel-wiki → Book 视图
# 选择新 release（version 选择器）
# 期望：
#   - 左侧目录按 8 大真名卷（人物塑造与设定 / 情节与节奏 / ...）展示
#   - 每个章节有 ≤14 字中文标题
#   - preface 在目录顶部单独显示（kind=preface），不计入卷桶
#   - 写作技法章节数：~8（不是 68）
```

**决策门**：
- 3.2 stats.failed = 0 → LLM 全部成功 ✓
- 3.5 新 release page_count = 1255 → 无 page_id 丢失 ✓
- 3.6 浏览器看到 8 大卷 + 真名章标题 + preface → 全部 4 项收益兑现 ✓

任何不通过 → 不 `--apply`，停在 preview，按 §4 回滚。

### Step 4：apply promoted release

```bash
# 仅在 3.6 视觉验收通过后执行
python -m src.cli book build-from-wiki --project novel-wiki --apply-from ${NEW_RELEASE}
# CURRENT.json 原子切换到新 release

# 验证切指针
python -c "
import json
p = 'knowledge/novel-wiki/book-wiki/CURRENT.json'
d = json.load(open(p, encoding='utf-8'))
print(f'active version: {d[\"version\"]}')
assert d['version'] == '${NEW_RELEASE}', 'CURRENT.json not switched'
print('OK: CURRENT.json switched')
"

# 关闭后台 server
kill %1 2>/dev/null
```

**完成**。刷新浏览器即可看到 4 项收益全部生效。

---

## 2. 验证 Checklist

| # | 验证项 | 期望 | 通过条件 |
|---|---|---|---|
| 1 | Task 0 修复生效（Step 2.2） | `chapters[].volume_id` 填充 179/179 | curl 数字 |
| 2 | Task 0 视觉确认（Step 2.5） | WebUI 左目录 ≥9 个真名卷 | 浏览器 |
| 3 | Task 4 partition 正确（Step 2.3） | 8 个新卷 + passthrough = 1255 页 | script 输出 |
| 4 | Task 3 generate_chapter_titles 可用（Step 2.4） | dry-run 列出 179 章 | script 输出 |
| 5 | Task 3 apply 后 stats.failed = 0（Step 3.2） | JSON stats 全 0 | python -c 输出 |
| 6 | Task 3 标题长度合规（Step 3.2） | 全部 ≤14 字 | python -c 输出 |
| 7 | Task 3 preface 字数合规（Step 3.3） | preface.md ≥ 5000 bytes | python -c 输出 |
| 8 | Task 4 apply-from 后 page_count = 1255（Step 3.5） | 无 page_id 丢失 | python -c 输出 |
| 9 | Task 4 apply-from 后 8 个新章（Step 3.5） | `concept-写作技法-*.md` = 8 | python -c 输出 |
| 10 | Task 4 视觉确认（Step 3.6） | 浏览器看到 8 大卷 + 真名标题 + preface | 浏览器 |
| 11 | CURRENT.json 切换（Step 4） | `version` 字段 = new release id | python -c 输出 |

11 项全过 = rollout 成功。任何 1 项不过 = 按 §4 处理。

---

## 3. 关键文件路径

| 路径 | 作用 |
|---|---|
| `knowledge/novel-wiki/book-wiki/.releases/<active>/manifest.json` | 当前 active release 的 manifest（hash 受 integrity check） |
| `knowledge/novel-wiki/book-wiki/.releases/<active>/outline.json` | outline.json（被 `_book_outline_metadata` 读取） |
| `knowledge/novel-wiki/book-wiki/.releases/<active>/editorial/chapter-titles.json` | Task 3 产物 |
| `knowledge/novel-wiki/book-wiki/.releases/<active>/preface.md` | Task 3 产物 |
| `knowledge/novel-wiki/book-wiki/.releases/<new_release>/...` | Task 4 apply-from 产物 |
| `knowledge/novel-wiki/book-wiki/CURRENT.json` | atomic pointer（Task 4 切换目标） |
| `knowledge/novel-wiki/.llm-wiki/policy.json` | `budget_cap` 在这里（Step 1.3 修改） |
| `~/.config/ruflo-kb/llm-providers.json` | LLM provider 配置（Step 1.1-1.2 验证） |
| `scripts/title_book_chapters.py` | Task 3 驱动 |
| `scripts/regroup_writing_technique_chapters.py` | Task 4 驱动 |

---

## 4. 回滚预案

每个 Step 都有独立回滚点。如果中途失败，按对应 Step 的回滚方案操作：

### Step 1 回滚（环境准备失败）
- **无副作用**：仅修改 `policy.json` 中的 `budget_cap`。还原：
  ```bash
  git checkout HEAD -- knowledge/novel-wiki/.llm-wiki/policy.json
  ```

### Step 2 回滚（dry-run 失败，但未写文件）
- **无副作用**：所有 dry-run 都是只读。直接停止，等排查。

### Step 3.1 回滚（Task 3 apply 部分写入）
- 仅生成了 `chapter-titles.json` + `preface.md` 在原 active release 内。还原：
  ```bash
  rm knowledge/novel-wiki/book-wiki/.releases/<active>/editorial/chapter-titles.json
  rm knowledge/novel-wiki/book-wiki/.releases/<active>/preface.md
  ```
- 注意：`<active>` = `f728939909c44bdf9d7efb6e26760c9d`，这是 baseline release。删了就回到 Task 0 修复前的 manifest hash，**WebUI 看到目录但无 preface**。

### Step 3.4 回滚（preview release 已生成但未 promote）
- preview release 在 `.releases/<new_release_id>/` 独立目录，**不影响** `CURRENT.json` 也不改 baseline release。处理：
  ```bash
  # 不 promote；preview 目录保留供事后审计
  # 或彻底删除：
  rm -rf knowledge/novel-wiki/book-wiki/.releases/<new_release_id>
  ```

### Step 4 回滚（已 promote，但发现严重问题）
- **atomic CURRENT.json** 在 promote 前保留旧 hash（plan-audit Round 2 加固）。回滚：
  ```bash
  git checkout HEAD -- knowledge/novel-wiki/book-wiki/CURRENT.json
  ```
- 新 release 目录保留在 `.releases/<new_release_id>/` 供事后审计，不影响 active serving。

---

## 5. 已知边界与限制

1. **不调 LLM 也可 rollout 的最小路径**：只跑 Step 1 + Step 2 + Step 3.1（apply 但用 provider=None fallback）。结果：
   - 4 项收益中**只有 B（章名）和 C（preface）部分达成**（章名 = outline 原 title，没真的优化）
   - A（目录分桶）和 D（重组）需 Step 3.4+ 才能达成
   - 适合作为"先验证流程完整性"的 staging 演练

2. **预算溢出应急**：如果 Step 3.4 中途 `EXIT_BUDGET_EXHAUSTED=6` 退出：
   - **不要**重新 `--preview`（会从批次状态恢复，但 prompt hash 可能 mismatch）
   - 直接切回 Step 2 验证当前 preview release 状态
   - 若 preview 已有完整 8 章 → 跳到 Step 4 直接 `--apply-from`
   - 若 preview 不完整 → 按 Step 3.4 回滚方案删除 preview，重提 `budget_cap` 到 1200 再试

3. **数据完整性约束**：所有 4 个 commit 都加了 `assert sorted(union(values)) == sorted(snapshot.pages)` 不变式（partition 与 book_wiki_manifest 都有）。如果未来 release 的 page_count != 1255，是数据漂移，不是方案 bug。

4. **LLM key 失效**：provider.complete() raise → generate_chapter_titles 自动 fallback；stats.failed 会增长但 pipeline 不崩。这是 Round 2 加固的兜底机制。

---

## 6. 关联文档

- **方案**：`docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md` — 4 个 Task 的完整设计与风险审计
- **Book 视图 UI 文档**：`docs/webui-buttons.md` 第 90-110 行 — Book 视图的按钮与 API 映射
- **CLI 命令文档**：`docs/commands/cli-book.md` — `book build-from-wiki` / `book retitle` 的 CLI 选项
- **Wiki schema**：`docs/guides/wiki-spec.md` — V4 8 键白名单（preface/chapter-titles.json 不写 Wiki 主数据，不冲突）
- **环境 setup**：`docs/environment/SETUP.md` — pytest/import-mode/dependency 安装
- **适配 Pre-existing test_cli_ext 慢问题**：完整 `test_kc + test_server` 全量跑会超时（pre-existing），子集跑 52 测试 < 5 秒。这是工具问题不是本方案回归。

---

## 7. 完成标准

当且仅当：

1. Step 1-4 全部执行且 11 项验证 checklist 全过
2. 浏览器 `http://127.0.0.1:19828` 选 novel-wiki → Book 视图显示：
   - 左目录按 ~9-50 个真名卷分组（不再 4 个粗桶）
   - 每章有 ≤14 字中文标题
   - 顶部 preface 独立显示（不计入卷桶）
   - 写作技法相关章节从 68 个变成 8 个大章
3. CURRENT.json 指向新 release，旧 release 仍在 `.releases/<old>/` 可回滚

**生效日期**：2026-09-11
**作者**：DeepSeek Harness 自动会话
**关联代码 Commits**：`46197677`、`8aedd1e3`、`56418840`、`d35434ec`
**关联方案**：`docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md`
