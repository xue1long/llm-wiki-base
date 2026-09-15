# Luna-B Prompt — Task 3 queue core + 稳定 hash ID

> **本文件由主 agent 生成,Luna-B subagent 直接按此执行。**
> **不要修改本文件,只读。**

## 你的角色

你是 **Luna-B**,Wave 1 三个并行 lane 之一。
你的工作是 **Task 3 的 queue 基础能力 + 稳定 review ID**(注意:**不**含 Writer 集成,
Writer 集成是 Wave 3 Luna-E 的工作)。

## 全局上下文(必读)

- 计划文件:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
- Wave 0 产出:`.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/wave0/`
- 当前 commit:`9e641367`(Wave 0 已 commit)
- 共享 fixture:`tests/fixtures/v7_control_plane/{source_a.md, source_b.md, expected_ids.json}`
- 冲突表:`wave0/conflict-table.md`

## 关键发现(避免重复劳动)

`src/pipeline/v7_extract/failures.py:125-153` **已实现** `enqueue_failure(source_id, stage,
reason, payload=None, *, queue_path=...)`,但:

1. **签名缺** `page_id / topic_id / content_hash` 参数 → 无法生成稳定 hash ID
2. **review ID 用** `uuid4().hex[:12]` 随机 → 重跑不幂等(同失败产生新 ID)

**你的任务不是新建方法,而是改造现有 `enqueue_failure` 签名 + ID 算法。**

## 任务范围

### 修改文件

- 🟡 修改 `src/pipeline/v7_extract/failures.py`(扩展 `enqueue_failure` 签名 + ID 算法)
- ❌ **不要碰** `src/wiki/storage/reviews_queue.py`(v3 实施 T9 已有独立 queue,本次不动)

### 测试文件

- `tests/test_pipeline/test_v7_extract_failures.py`(扩展)
- 🆕 `tests/test_pipeline/test_v7_extract_failures_idempotency.py`(稳定 ID 幂等性专项测试)

### 不允许碰的文件

- `slot_filler.py` / `_page_id.py` / `topic_clusterer.py`(Luna-A 的写集合)
- `wiki_writer.py`(Wave 3 Luna-E)
- `extract_pilot.py` / `extract_full.py`(Wave 2/3)
- `_legacy.py` / `__init__.py`(v3 实施)

## 实现要求

### 1. 扩展 `enqueue_failure` 签名

```python
# 改造后签名(plan §4 Task 3 第 2 个 checkbox):
def enqueue_failure(
    source_id: str,
    stage: str,
    *,
    page_id: str = "",
    topic_id: str = "",
    reason: str,  # 必填,放 keyword 强制显式
    content_hash: str = "",
    payload: dict | None = None,
    queue_path: Path | str = _DEFAULT_QUEUE_PATH,
) -> str:
    """Record a v7 failure to the shared reviews queue.

    Returns:
        The generated review_id (stable hash prefix).
    """
    # 稳定 ID 算法(plan §4 Task 3):
    identity = (
        f"{source_id}\0{stage}\0{page_id}\0{topic_id}\0"
        f"{reason}\0{content_hash}"
    )
    review_id = "v7fail-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    # ... 去重 + 更新已有项的 attempts/last_seen_at
```

**关键点:**
- `reason` 改为 keyword-only 必填,避免位置参数误用
- 新增 `page_id / topic_id / content_hash` 参数
- ID 算法: `sha1(source + stage + page_id + topic_id + reason + content_hash)[:12]`,前缀 `v7fail-`
- 命中已有项:**更新** `attempts` 与 `last_seen_at`,**不**新增条目(幂等)
- P12 加固:`reason` 字符串拼接 `prompt_kind` 与 `provider` 标签(可选,签名加 `provider: str = ""` 与 `prompt_kind: str = ""` 参数)

### 2. 持久化顺序

读取 → 查重(按 `id`) → 命中:更新 `attempts += 1`,`last_seen_at = now_ms()`,重新写盘
→ 未命中:append 新条目 → 写盘。

## 必须通过的回归测试

写到 `tests/test_pipeline/test_v7_extract_failures_idempotency.py`:

```python
# 至少 6 个测试:
# 1. 同 (source, stage, page_id, topic_id, reason, content_hash) 调用两次
#    → 返回相同 review_id,queue 条目数不增加(attempts=2)
# 2. 仅 page_id 不同 → 不同 review_id
# 3. 仅 reason 不同 → 不同 review_id
# 4. content_hash 空 vs 非空 → 不同 review_id(若 reason 同)
# 5. last_seen_at 在第二次调用时更新
# 6. queue_path 显式传入自定义路径 → 写到该路径(不写 CWD)
```

写到 `tests/test_pipeline/test_v7_extract_failures.py`(扩展):

```python
# 至少 3 个新测试:
# 1. enqueue_failure 新签名可调用,所有 keyword 参数生效
# 2. P12 加固:provider + prompt_kind 标签进入 queue item
# 3. payload 含 api_key/email/phone 仍被 sanitize(R15/D11 不破坏)
```

## TDD 节奏

1. **先写幂等性测试**:`tests/test_pipeline/test_v7_extract_failures_idempotency.py` 6 个测试,**确认失败**
2. **改造 `failures.py`** 的 `enqueue_failure` 签名 + ID 算法,6 个测试通过
3. **扩展现有测试**:`tests/test_pipeline/test_v7_extract_failures.py` 3 个新测试通过
4. **跑全套验证**:
   ```powershell
   $env:PYTHONPATH = "."
   python -m pytest tests/test_pipeline/test_v7_extract_failures.py tests/test_pipeline/test_v7_extract_failures_idempotency.py -q
   python -m compileall -q src/pipeline/v7_extract
   git diff --check
   ```
5. **commit**(单一逻辑 commit,中文描述,含 Task 编号):
   ```bash
   git add src/pipeline/v7_extract/failures.py \
           tests/test_pipeline/test_v7_extract_failures.py \
           tests/test_pipeline/test_v7_extract_failures_idempotency.py
   git commit -m "fix(v7-extract): stabilize enqueue_failure review ID (T3 queue core)"
   ```

## 完成报告(回到主 agent 时给我)

- commit hash
- 签名变更摘要(旧 → 新)
- ID 算法摘要(sha1 输入字段列表)
- 测试结果(passed N / failed 0)
- 现有 `enqueue_failure` 调用方是否需要更新(`git grep "enqueue_failure"` 列出)

## 失败处理

- 现有调用方不兼容新签名 → **不破坏向后兼容**,保留 `reason` 作为位置参数 fallback
  或在 deprecation 警告中提供 1-2 个 release 的过渡
- `__init__.py` 或其他模块引用 `enqueue_failure` 失败 → 通知主 agent

## 不要做的事

- 不要碰 `reviews_queue.py`(v3 T9 已有独立 queue)
- 不要新建并行 queue 系统
- 不要新增数据库依赖
- 不要碰 Luna-A / Wave 3 的写集合
