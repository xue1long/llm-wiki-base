# novel-wiki Book 可读性整改 rollout 执行 — 2026-09-10

## 实际执行结果

执行 plan `2026-09-10-novel-wiki-fullbook-readability.md` 的 rollout 指南时，发现 **3 个实现 bug + 1 个 rollout 文档缺漏**：

1. `scripts/regroup_writing_technique_chapters.py` 调 `scan_wiki_snapshot(ctx.path)` 而不是 `(ctx.path / "wiki")`，导致 dry-run 永远返回 0 chapters
2. `scripts/title_book_chapters.py` 没有 `load_dotenv()`，脚本绕过 `src/cli.py:89-96` 的 .env 自动加载，导致 `RUFLO_LLM_PROVIDER=minimax` 不生效、永远 fallback
3. 同上脚本把 `ChapterTitleResult` 当 dict 用（`titles["titles"]`），但它是 frozen dataclass（`titles.titles`）
4. **rollout guide 没强调 `book build-from-wiki --apply` 默认 scope 是 pilot，且会自动 promote 到 CURRENT.json**——这导致我误把 pilot 2-chapter release promote 上去覆盖了 baseline 179-chapter release

## 滚回经验（重要！）

**`book build-from-wiki --apply` 是 destructive 操作**——它会自动 `git mv` 切换 CURRENT.json 到新 release。我跑这个命令没加 `--scope full_knowledge` 时生成了一个 12-page pilot release 并覆盖了 179-chapter baseline，**整个 baseline 暂时下线**。

恢复方法（已验证）：
```python
import hashlib, json
from pathlib import Path
manifest = Path(r"...\.releases\f728939909c44bdf9d7efb6e26760c9d\manifest.json")
sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
# sha = fa93076435f38e1fd393cc1b2cfbffa24337ae016b7fefb89b23f806cfa110cb
Path(r"...\CURRENT.json").write_text(
    json.dumps({"version": "f728939909c44bdf9d7efb6e26760c9d",
                "manifest_sha256": sha}) + "\n",
    encoding="utf-8"
)
```

`resolve_project('novel-wiki', by_id_only=True)` + `book_wiki_manifest('novel-wiki')` 验证 179/179 chapters 重新可见。

## 复现 / 验证步骤（修改后）

```bash
# Setup: 必须设 RUFLO_PROJECT_ROOT 或在 knowledge/ 下运行
export RUFLO_PROJECT_ROOT=E:\002-Pr\20260910\llm-wiki-base

# 验证 Task 0 修复（registry UUID 0ff37d87 指向 live project）
curl -s "http://127.0.0.1:19828/api/v1/projects/0ff37d87-de3d-4a99-82bb-6cf288c65410/book-wiki" \
  | python -c "import json, sys; m = json.load(sys.stdin); print(f'{sum(1 for c in m[\"chapters\"] if c.get(\"volume_id\"))}/{len(m[\"chapters\"])}')"
# 输出: 179/179

# Dry-run 验证 Task 4 partition
python scripts/regroup_writing_technique_chapters.py --project novel-wiki
# 输出: new chapters: 7 (target 8), passthrough buckets: 45, total pages: 1255
# 实际 8 个 bucket 中 1 个因 first-match-wins 没人匹配（情节与节奏），其他 7 个有 page

# Dry-run 验证 Task 3 title 生成
python scripts/title_book_chapters.py --project novel-wiki
# 输出: book-wiki/f728939909c44bdf9d7efb6e26760c9d: 179 chapters

# Apply 真实 LLM
python scripts/title_book_chapters.py --project novel-wiki --apply
# 输出: stats: truncated=0, renamed=0, failed=0  (minimax 全部成功)
#       wrote .../editorial/chapter-titles.json
#       wrote .../preface.md
```

## LLM 调用成本（实测）

- `title_book_chapters --apply`：**1 次** MiniMax 调用（单 prompt 处理 179 章 batch）
- 每次 batch prompt 约 30-60 秒 + 8k tokens output
- 实际写出的 chapter-titles.json **179/179 ≤14 chars**（如 `人物开篇指引`、`大纲格式解析`、`故事叙事技巧` 等友好标题）
- preface 仍是占位符（脚本的 `_write_preface_skeleton` 写硬编码文案，不调 LLM）
  - 真实 preface 需要在 full_knowledge rebuild 时生成，那时每个 chapter 单独调 LLM

## 当前 Novel-Wiki Book 状态（2026-09-11 14:50）

- **CURRENT.json 指向 baseline f728939909...**（179 chapters / 61 volumes / 1255 pages，已回滚）
- **Task 0 修复完全生效**：WebUI 现在显示 53 个真名卷（之前是 4 个粗桶），每章带真名 volume_title
- **Task 3 产出落盘**：`editorial/chapter-titles.json` 179 标题 + `preface.md`（65 字符占位符）已写入 baseline release 目录
- **Task 4 重组尚未执行**：`scripts/regroup_writing_technique_chapters.py` dry-run 验证有效，但 merge 68→8 章到 baseline manifest 需要 full_knowledge rebuild（pipeline 默认 pilot scope 太短）
- **Task 4 视觉收益部分生效**：WebUI 已经按 outline 真名分组（53 个卷，每个有真名 volume_title）；但 179 章是按 179 个 chapter_id 切片而非 8 大主题聚合——这是 baseline release 的固有结构，不是 Task 0 修复可以解决的

## 已交付 Commits（这次 rollout）

- `46197677` `fix(book)` outline key 双索引
- `8aedd1e3` `test(book)` 回归 + 集成 smoke
- `56418840` `feat(book)` preface + generate_chapter_titles + retitle CLI
- `d35434ec` `feat(book)` partition_writing_technique_merged
- `87fa6bdb` `docs(guides)` rollout guide
- `814fda48` `docs(guides)` rollout env 修正
- `4a92a203` `memory` memory capture for plan completion
- **`1663a793` `fix(scripts)` rollout 时发现的 3 个 bug**

## 仍未交付

1. **preface.md 真实内容（2500-4000 字）**：当前是 65 字符占位符。需 full_knowledge rebuild + LLM 生成。脚本 `_write_preface_skeleton` 写硬编码文案，需要扩展为 `await generate_preface(provider, ...)`。
2. **Task 4 重组 baseline release**：8 大章合并。需 `book build-from-wiki --apply --scope full_knowledge` 完整跑完（目前默认 pilot scope 太小 + LLM budget 可能超 800 cap）。
3. **rollout guide 升级**：明确说明 `--scope full_knowledge` 在 apply 时必填、`--apply` 是 destructive 且会自动切 CURRENT.json、建议先 `--preview` 验证 release 目录内容再 `--apply`。

## 工程教训（未来 LLM Book rollout 必读）

1. **`book build-from-wiki --apply` = git push force**——必须先用 `--preview` 验证 release 内容再 `--apply`。  
2. **CLI 默认参数不一定符合预期**：`--scope pilot` 是默认；不显式 `--scope full_knowledge` 永远只生成 2 章 pilot release。  
3. **`.env` 自动加载只在 `src/cli.py:cli_main()` 内执行**——直接跑 scripts 必须显式 `load_dotenv`，否则 `RUFLO_LLM_PROVIDER` 拿不到。  
4. **`return_object.subscript` vs `return_object.attr`**：frozen dataclass 返回值只能用 attribute access，scripts 里 `titles["titles"]` 会 TypeError。  
5. **`scan_wiki_snapshot(wiki_root)` 期望 wiki 子目录**：compiler.py:1138 传 `root / "wiki"`，scripts 也必须传子目录；传项目根会静默返回 0。  
6. **registry 是 stale data 的高发地**：novel-wiki 在 registry 里有两个 entry（0ff37d87 旧路径 + be05372f 真路径），且 `0ff37d87` 的 path 是错的（`D:\5-Project\2026814\...staging`）。**所有 rollout 操作前先 `cat registry.json` 检查实际路径**。  
7. **TestClient 替代 uvicorn** 验证 manifest 数据：本机 uvicorn 启动卡 health check（其他 provider 连不上），TestClient 直接同步调 app，无网络依赖，验证更快。

## 关联 memory

- `feedback-novel-wiki-book-readability-2026-09-10.md` — 4 个 Task 的代码 + 测试 + 文档交付清单
- `feedback-novel-wiki-fullbook-published-2026-09-10.md` — 179-chapter baseline release 的历史来源
- `feedback-book-llm-republish-hardening-2026-09-09.md` — LLM 调用硬化的根因（response shape retry budget）

## Pinned issues for next round

- [ ] 升级 `scripts/title_book_chapters.py` 加 `generate_preface()` 真正调 LLM
- [ ] 升级 `docs/guides/novel-wiki-book-readability-rollout.md` Step 3.4 强调 `--scope full_knowledge` 是必填
- [ ] 修复 `registry.json` 中 0ff37d87 的 path 指向当前 live project（当前我手动改过但 git 没追踪，下次重 install 还得改）
- [ ] 给 `accept_book_artifacts.py` 或类似脚本加 manifest 注入能力，把 editorial/ 文件纳入 baseline manifest 的 `files` 字典（当前 baseline manifest 不含它们，integrity check 看不到，但 files 字典也不校验 orphan 文件，所以 manifest hash 不变）
- [ ] 写 `scripts/inject_editorial_into_release.py`：把 baseline manifest + editorial/chapter-titles.json + preface.md 合并成新 manifest hash，更新 CURRENT.json；这样不跑 full_knowledge rebuild 也能生效 B（章名）和 C（preface）收益

## Net Status

| 收益维度 | 实施状态 | 路径 |
|---|---|---|
| A. WebUI 目录分桶 | **ACTIVE** | 53 个真名卷（baseline release 直接生效 Task 0 修复） |
| B. 章名可读性 | **PARTIAL** | chapter-titles.json 写盘 + 179 个 ≤14 字友好标题已生成，但 baseline manifest 未注册 → WebUI 不读 |
| C. 总序导读 | **PARTIAL** | preface.md 写盘（但只是 65 字符占位符）；baseline manifest 未注册 → WebUI 不读 |
| D. 写作技法可读性 | **DRY-RUN ONLY** | partition 函数验证 7 个新卷 + 1255 pages，merge 到 baseline manifest 待 full_knowledge rebuild |

要 100% 收益需要一次 full_knowledge rebuild（约 132+ LLM calls，按 `feedback-novel-wiki-fullbook-published-2026-09-10.md` 历史 6 次 resume 经验约 1-2 小时 + 800 cap 风险）。
