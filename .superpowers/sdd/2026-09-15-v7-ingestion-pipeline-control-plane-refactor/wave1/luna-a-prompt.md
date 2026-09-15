# Luna-A Prompt — Task 1 provenance + `_page_id.py`

> **本文件由主 agent 生成,Luna-A subagent 直接按此执行。**
> **不要修改本文件,只读。**

## 你的角色

你是 **Luna-A**,Wave 1 三个并行 lane 之一(主会话因模型约束改为串行派发)。
你的工作是 **Task 1:脚本接管 item/page ID,Stage 5 输入契约收紧**。

## 全局上下文(必读)

- 计划文件:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
- Wave 0 产出:`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/wave0/`
- 当前 commit:`9e641367`(Wave 0 已 commit)
- 共享 fixture:`tests/fixtures/v7_control_plane/{source_a.md, source_b.md, expected_ids.json}`
- 冲突表:`wave0/conflict-table.md`(**你的写集合在表中列出,严格遵守**)

## 任务范围(Task 1)

### 修改文件

- 🆕 创建 `src/pipeline/v7_extract/_page_id.py`(独立 helper 模块,H2 加固)
- 🟡 修改 `src/pipeline/v7_extract/slot_filler.py`(Stage 5 输入契约)
- 🟡 修改 `src/pipeline/v7_extract/prompts/builtin/fill_slots.toml`(LLM 输出字段)
- 🟡 修改 `scripts/extract_pilot.py`(`_extract_one()` 接入 `_page_id`)
- 🟡 可选 `src/pipeline/v7_extract/topic_clusterer.py`(复用 canonical item 映射,仅在需要时)

### 测试文件

- `tests/test_pipeline/test_v7_extract_slot_filler.py`(扩展)
- `tests/test_pipeline/test_v7_extract_topic_clusterer.py`(扩展)
- `tests/test_scripts/test_extract_pilot.py`(扩展)
- 🆕 `tests/test_pipeline/test_v7_extract_page_id.py`(`_page_id.py` 单元测试)

### 不允许碰的文件

- `src/pipeline/v7_extract/failures.py`(Luna-B 的写集合)
- `src/pipeline/v7_extract/wiki_writer.py`(Wave 3 Luna-E 的写集合)
- `src/pipeline/v7_extract/_legacy.py`(v3 实施,本次不动)
- `scripts/extract_full.py`(Wave 3 Luna-F 的写集合)
- 其他 lane 的测试文件

## 实现要求(plan §4 Task 1 + H2 加固)

### 1. 创建 `_page_id.py`(H2 加固,独立 helper)

```python
# src/pipeline/v7_extract/_page_id.py
import hashlib
import re
from pathlib import Path

_SLUG_RE = re.compile(r"[^\w-]+", re.UNICODE)


def _slugify(title: str) -> str:
    """Lowercase title, replace non-word chars with '-', trim, cap at 32 chars."""
    s = _SLUG_RE.sub("-", title.lower()).strip("-")
    return s[:32] or "untitled"


def _stable_page_id(relative: str, topic_title: str) -> str:
    """Generate a stable page ID from source relative path + topic title.
    
    Cross-OS consistency: convert '\\' to '/' so Windows and POSIX paths
    produce the same ID.
    """
    rel = relative.replace("\\", "/")
    digest = hashlib.md5(rel.encode("utf-8")).hexdigest()[:8]
    slug = _slugify(topic_title)
    return f"{digest}-{slug}"


def validate_page_id(page_id: str) -> None:
    """Raise ValueError if page_id contains path separators or '..'."""
    if any(char in page_id for char in "/\\") or ".." in page_id:
        raise ValueError(f"page id escapes concept directory: {page_id!r}")
```

### 2. 修改 `slot_filler.py`

- Stage 5 prompt 给 LLM 的 evidence 输入改为带序号的 item 列表
- 输出字段改为 `item_index`,不再要求 LLM 回填 item ID
- `_payload_to_page()` 校验 index 是整数、在当前 topic 的范围内
- 然后映射为 `Topic.item_ids[index]`
- 无效 index / 缺失 evidence / 空 body → 标记 `needs_review`(`__other__` 仍标记 blocked)
- `source_text_excerpt` 保留为人工参考,不再做全文精确匹配硬门

### 3. 修改 `fill_slots.toml`

- 在 prompt 模板里说明 evidence 输入是带序号的 item 列表
- 要求 LLM 输出 `item_index`(整数)而不是 `item_id`(字符串)
- 添加约束:"item_index 必须是 0..N-1 范围内的整数"

### 4. 修改 `extract_pilot.py:144` 的 `_extract_one()`

- 接入 `_page_id._stable_page_id(relative, topic.id)`,生成 page.id
- **删除** `page.__dict__["topic_id"] = topic.id` 动态注入(改为正式字段)
- 异常路径改为只记录 `failure_stage` 与截断 reason,不打印完整 traceback

## 必须通过的回归测试

写到 `tests/test_pipeline/test_v7_extract_page_id.py`:

```python
# 测试要点(至少 6 个测试):
# 1. _stable_page_id 同 relative + topic → 相同 ID(确定性)
# 2. 不同 relative + 同 topic → 不同 ID
# 3. Windows 路径('raw\\sources\\a.md')与 POSIX('raw/sources/a.md')同 logical → 同 ID
# 4. 空 title 兜底为 "untitled"
# 5. validate_page_id 拒绝包含 '/', '\\', '..' 的 ID
# 6. _slugify 中文标题保留(unicode word 字符)
```

写到 `tests/test_pipeline/test_v7_extract_slot_filler.py`:

```python
# 至少 4 个新增测试:
# 1. 合法 item_index → canonical item ID 映射(relative#item-N 格式)
# 2. 越界/负数/非整数 index → needs_review,不入 Writer
# 3. 两个 source 返回相同 topic slug → page ID 不相同(共享 fixture source_a/b)
# 4. 缺失 evidence → 走 blocked 分支(永远不 written)
```

## TDD 节奏

1. **先写测试**:`tests/test_pipeline/test_v7_extract_page_id.py` 6 个测试,**确认失败**
2. **实现** `_page_id.py`,6 个测试通过
3. **写 slot_filler 测试**:`tests/test_pipeline/test_v7_extract_slot_filler.py` 4 个新测试,**确认失败**
4. **修改 slot_filler.py + fill_slots.toml**,4 个新测试通过
5. **写 extract_pilot 测试**:跨 lane fixture 复用,page ID 唯一性测试
6. **修改 extract_pilot.py**,所有相关测试通过
7. **跑全套验证**:
   ```powershell
   $env:PYTHONPATH = "."
   python -m pytest tests/test_pipeline/test_v7_extract_page_id.py tests/test_pipeline/test_v7_extract_slot_filler.py tests/test_pipeline/test_v7_extract_topic_clusterer.py tests/test_scripts/test_extract_pilot.py -q
   python -m compileall -q src/pipeline/v7_extract
   git diff --check
   ```
8. **commit**(单一逻辑 commit,中文描述,含 Task 编号 T1):
   ```bash
   git add src/pipeline/v7_extract/_page_id.py \
           src/pipeline/v7_extract/slot_filler.py \
           src/pipeline/v7_extract/prompts/builtin/fill_slots.toml \
           scripts/extract_pilot.py \
           tests/test_pipeline/test_v7_extract_page_id.py \
           tests/test_pipeline/test_v7_extract_slot_filler.py \
           tests/test_pipeline/test_v7_extract_topic_clusterer.py \
           tests/test_scripts/test_extract_pilot.py
   git commit -m "fix(v7-extract): make Stage 5 provenance script-owned (T1, H2 加固)"
   ```

## 完成报告(回到主 agent 时给我)

- commit hash
- 新增/修改文件清单
- 测试结果(passed N / failed 0)
- 任何与 plan 的偏离(必须说明)

## 失败处理

- 单个测试失败 → 不 commit,先修实现
- 跨 lane 接口变化 → 通知主 agent,不能擅自改 Luna-B 的写集合
- `_page_id.py` 设计争议 → 优先用 plan 给的模板,有更好方案请说明

## 不要做的事

- 不要碰 `failures.py` / `wiki_writer.py` / `extract_full.py` / `_legacy.py`
- 不要新增依赖
- 不要改动 WikiPage frontmatter schema
- 不要重写 Stage 1/3/4 的语义
