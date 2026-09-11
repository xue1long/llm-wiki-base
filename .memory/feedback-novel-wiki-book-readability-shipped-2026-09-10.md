# novel-wiki Book 可读性整改 — 4 项收益全部落地 — 2026-09-10

## 最终状态（WebUI 实测，非推测）

用 `book_wiki_manifest`（WebUI 实际调用的 service）端到端验证，release
`f728939909c44bdf9d7efb6e26760c9d`：

| 收益 | 结果 | 证据 |
|---|---|---|
| A. 目录分桶 | **PASS** | 109/109 章节带 volume_id，57 个卷全部 chapter_count > 0 |
| B. 章名可读性 | **PASS** | 109/109 章节标题 ≤14 字且不含 `:`（如「主角开篇指引」） |
| C. 总序导读 | **PASS** | manifest 返回 `preface: {path, kind, word_count, size}` |
| D. 写作技法重组 | **PASS** | 7 个命名主题章（原 77 个 `concept-写作技法:N` 碎片） |

关键不变量：`page_count` 保持 **1255** 不变，`coverage_ratio` 1.0 —— 无内容丢失。
`chapter_count` 179 → 109。

7 个重组章（源章数 / 体积）：

- 人物塑造与设定 — 33 源 / 228 KB
- 情节与节奏 — 15 源 / 99 KB
- 开头与签约 — 9 源 / 81 KB
- 描写与文笔 — 10 源 / 82 KB
- 题材与世界观 — 4 源 / 34 KB
- 套路与爽点 — 4 源 / 20 KB
- 平台与读者 — 2 源 / 16 KB

（7 而非 8：`情节与节奏` 规则在 first-match-wins 下从不胜出——其关键词
被 `人物塑造与设定` / `描写与文笔` 先行吃掉。在方案的 6-8 章区间内。）

## 本次 rollout 的 8 个 commit

| Commit | 类型 | 内容 |
|---|---|---|
| `46197677` | fix(book) | `_book_outline_metadata` 双 key 索引（Task 0 根因修复） |
| `8aedd1e3` | test(book) | 10 回归 + 2 HTTP 集成 smoke |
| `56418840` | feat(book) | preface 字段 + `generate_chapter_titles` + `book retitle` CLI |
| `d35434ec` | feat(book) | `partition_writing_technique_merged` + regroup 脚本骨架 |
| `87fa6bdb` | docs(guides) | rollout 手动操作指南 |
| `814fda48` | docs(guides) | 修正 env 说明（`.env` 已配置，无需 export） |
| `1663a793` | fix(scripts) | rollout 时发现的 3 个脚本 bug |
| `09884d27` | feat(book) | 路径 1 注入：`book_wiki_manifest` 读 chapter-titles.json + inject 脚本 |
| `62eeca3a` | feat(book) | **Task 4 实际重组**：77 → 7 命名主题章 |

## 三条落地路径（重要！）

Task 3/4 的产出**不会自动出现在 WebUI**，因为 `book_wiki_manifest` 只遍历
`manifest.files`，而 `editorial/` 下的产物未注册。三条路径：

1. **路径 1（最小代价，已用）**：`scripts/inject_editorial_to_baseline.py`
   把 `editorial/chapter-titles.json` 复制到 release 根、连同 `preface.md`
   一起写入 `manifest.files`，重算 manifest sha 并更新 `CURRENT.json`。
   无 LLM 调用，秒级完成。
   - 前提：`_verified_book_release` 拒绝任何**子路径**条目
     （`Path(name).name != name`），所以文件必须在 release 根目录，不能放 `editorial/`。
   - 配套：`book_wiki_manifest` 增加读取 release 根 `chapter-titles.json`
     的逻辑，用其 `chapter_id -> title` 映射覆盖 outline 原标题。

2. **路径 2（中代价，已用）**：`scripts/apply_writing_technique_regroup.py`
   用 `partition_writing_technique_merged` 的分桶结果，把 77 个来源章正文
   物理合并成 7 个 .md，重写 `outline.json` + `manifest.json` + `CURRENT.json`。
   无 LLM 调用。带 `*.bak.regroup` 备份 + 幂等守卫 + `--dry-run`。

3. **路径 3（高代价，未用）**：`book build-from-wiki --apply --scope full_knowledge`
   全量 LLM 重建。实测跑了 16 次 MiniMax 调用、约 30 分钟，产出
   `release_status=partial`（`budget_exhausted` + MiniMax `list[str]` 响应），
   且**章节结构仍是 179/61 完全没变**——因为 `build_from_wiki` 走的是
   `build_chapter_chunks`，根本不调用 `partition_writing_technique_merged`。
   **结论：路径 3 对 Task 4 无效，不要指望它。**

## 踩坑清单（下次必读）

### 1. `book build-from-wiki --apply` 是 destructive 且默认 scope=pilot

不显式传 `--scope full_knowledge` 时，它生成 12 页 pilot release 并
**自动把 CURRENT.json 切过去**，把 179 章 baseline 顶下线。恢复方法：

```python
import hashlib, json
from pathlib import Path
mp = Path(".../.releases/f728939909.../manifest.json")
Path(".../CURRENT.json").write_text(json.dumps({
    "version": "f728939909c44bdf9d7efb6e26760c9d",
    "manifest_sha256": hashlib.sha256(mp.read_bytes()).hexdigest(),
}) + "\n", encoding="utf-8")
```

**先 `--preview` 验证，再 `--apply`。**

### 2. 磁盘上的中文文件名**是正确的 UTF-8**，乱码只是终端显示

`sys.getfilesystemencoding()` 是 utf-8，`p.name` 里的 `写` 就是 U+5199。
PowerShell / `cmd /c` 用 cp936 渲染，看起来像 `д`。

**但陷阱在于**：如果你在脚本里手打 `д`（以为在打 `写`），实际写进去的可能是
**U+0434 西里尔字母** —— 屏幕上完全一样，`str` 比较却永远失败。本次开发中
因此在 `startswith` 匹配上反复失败多轮。

**正确做法**：
- 需要匹配中文时用 `chr(0x5199)` 等显式码点，或直接复用
  `DEFAULT_WRITING_TECHNIQUE_REGROUP` 的 canonical keys。
- 幂等守卫尤其要用 canonical keys 比较，不要手打前缀——
  本次守卫漏打一个 `作` 字（`concept-写技法-` vs `concept-写作技法-`），
  导致守卫静默失效、二次运行会重复合并。

### 3. 改 `outline.json` 必须同步刷新 `manifest.files['outline.json']` 的 sha

否则 `_verified_book_release` 完整性校验失败 → WebUI 返回 404
`No active book-wiki release`。脚本里**先序列化 outline、再序列化 manifest**。

### 4. `write_text` 在 Windows 会做 `\n` → `\r\n` 转换

用 `write_text` 写文件、却用 `body.encode("utf-8")` 算 sha，记录的 sha 与
磁盘实际字节不符 → 同样导致 404。**一律用 `write_bytes`。**

### 5. `scan_wiki_snapshot(wiki_root)` 要的是 `wiki/` 子目录

传项目根会静默返回 0 页。`compiler.py:1138` 传 `root / "wiki"`，脚本照做。

### 6. 直接跑 `scripts/*.py` 不会自动加载 `.env`

`src/cli.py:89-96` 的 `load_dotenv` 只在 `cli_main()` 里执行。脚本自己
import `src.*` 时不会触发，于是 `RUFLO_LLM_PROVIDER` 读不到、永远走 fallback。
**脚本开头显式 `load_dotenv(_REPO / ".env")`。**

### 7. registry 路径可能指向旧安装

`~/.config/ruflo-kb/registry.json`（Windows 实际是
`%LOCALAPPDATA%\ruflo-kb\ruflo-kb\registry.json`）里 `novel-wiki`
有两个 entry，较新的那个路径指向已失效的 `D:\5-Project\...staging`。
`ProjectContext.resolve` 优先 registry 而非 `RUFLO_PROJECT_ROOT`。
**rollout 前先 dump registry 确认真实路径。**

### 8. `.env` / `policy.json` / `book-wiki/.releases/` 都不进 git

- `.env`：被 gitignore
- `knowledge/*/.llm-wiki/`（含 `policy.json`）：被 gitignore
- `knowledge/*/book-wiki/.releases/`：未被 gitignore 但也从未提交

所以 release 状态变更**不会有 git 历史**，务必依赖脚本自建的
`*.bak.regroup` 备份。

## 未完成 / 遗留

- **preface 内容仍是 65 字符占位符**（`_write_preface_skeleton` 写死文案，
  不调 LLM）。真正的 2500-4000 字总序需要在 build pipeline 里接一个
  `generate_preface()`，尚未实现。
- **`chapter_sources` 元数据未重建**：合并后的 7 个章在 manifest 的
  `chapter_sources` 里查不到（旧 key 是旧文件名），WebUI 章节信息面板的
  「来源」会显示 0 个。正文内容与 provenance 都在合并后的 .md 里，未丢。
- **`volume-index.json` / `chapter-index.json` 是 stale 的**（内容仍是
  旧的 61 卷 179 章）。它们的 sha 与 manifest 一致所以不影响完整性校验，
  且 `book_wiki_manifest` 不读它们。若要对外发布需一并重建。
- **路径 1 + 路径 2 都是"原地改写 active release"**（run_id 不变、manifest
  sha 变）。未走 `--apply-from` seam。回滚靠 `*.bak.regroup`。

## 关联 memory

- `feedback-novel-wiki-book-readability-2026-09-10.md` — 4 个 Task 的设计与交付清单
- `feedback-novel-wiki-book-rollout-2026-09-10.md` — rollout 执行与 4 个 bug
- `feedback-novel-wiki-fullbook-published-2026-09-10.md` — 179 章 baseline 来源
- `feedback-book-llm-republish-hardening-2026-09-09.md` — LLM 响应形状重试硬化
