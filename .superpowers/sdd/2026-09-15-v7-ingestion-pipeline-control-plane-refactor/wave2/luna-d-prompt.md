# Luna-D Prompt — Task 2 统一 `_extract_one()` 到 `ExtractionResult`

> **本文件由主 agent 生成,Luna-D subagent 直接按此执行。**
> **不要修改本文件,只读。**

## 你的角色

你是 **Luna-D**,Wave 2 唯一执行 lane(plan §6 串行)。
你的工作是 **Task 2:把 `_extract_one()` 收敛到 `ExtractionResult`**,统一 source outcome 序列化。

## 工作目录

```
D:\201\llm-wiki-base\20260910\llm-wiki-base
```

直接 cd 进去执行。**所有命令必须在工作目录内运行。**

## 全局上下文

- 项目:`ruflo-kb`,Python 3.11+
- 当前 commit:`caa61dd0`(Wave 1 完成 + pre-existing bug 详细记录)
- tag:`v7-control-plane-wave1` 已打(回滚快照点)
- 计划文件:`docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
- Wave 0 ledger:`.superpowers/sdd/.../wave0/`
- Wave 1 ledger:`.superpowers/sdd/.../wave1/`
- Wave 2 README:`.superpowers/sdd/.../wave2/README.md`(本目录,包含关键约束)

## Wave 1 已落地的关键事实(必须遵守)

| 文件 | Wave 1 状态 | 你能扩展吗? |
|---|---|---|
| `_page_id.py` | 提供 `_stable_page_id(relative, topic_title)` + `validate_page_id` | ❌ 不动 |
| `slot_filler.py` | Stage 5 接受 `item_index` 整数 | ❌ 不动 |
| `failures.py` | `enqueue_failure(source_id, stage, *, page_id="", topic_id="", reason, content_hash="", prompt_kind="", provider="", payload=None, queue_path=...)`,返回稳定 sha1 ID | ✅ **扩展 `ExtractionResult` 与 `ExtractionStatus`** |
| `extract_pilot.py` | `_extract_one()` 返回 `dict[str, Any]`,有 `error`/`failure_stage` 字段 | ✅ **改成返回 `ExtractionResult`** |
| `extract_full.py` | 消费 dict 字段,`errors`/`pages` summary | ✅ **改成消费 `ExtractionResult`** |
| `ConceptPage.topic_id` | 正式字段,默认 None | ❌ 不动 |
| `wiki_writer.py` | v3 + Wave 1 未动 | ❌ 不动(Wave 3) |

## 任务范围(Task 2)

### 修改文件(3 个 src + 3 个 tests)

- 🟡 `src/pipeline/v7_extract/failures.py`(扩展 `ExtractionStatus` 与 `ExtractionResult`)
- 🟡 `scripts/extract_pilot.py`(`_extract_one()` 改返回类型)
- 🟡 `scripts/extract_full.py`(消费新对象)
- 🟡 `tests/test_pipeline/test_v7_extract_failures.py`(扩展)
- 🟡 `tests/test_scripts/test_extract_pilot.py`(扩展)
- 🟡 `tests/test_scripts/test_extract_full.py`(扩展)

### 绝对不允许碰

- `src/pipeline/v7_extract/_page_id.py` / `slot_filler.py` / `topic_clusterer.py` / `fill_slots.toml`
- `src/pipeline/v7_extract/wiki_writer.py`(Wave 3)
- `src/pipeline/v7_extract/_legacy.py` / `__init__.py`(v3 实施)
- `src/pipeline/v7_extract/_queue_lock.py`(Wave 0)
- Luna-A/B/C 已扩展过的测试文件
- `src/pipeline/v7_extract/llm_client.py` / `audit_logger.py`

## 实现要求(plan §4 Task 2 + §2.2.1 映射)

### 1. 扩展 `ExtractionStatus`(plan §2.2.1)

```python
# src/pipeline/v7_extract/failures.py
class ExtractionStatus(str, Enum):
    """v3 三态 + 本次 plan 五态。"""
    # v3 既有(向后兼容):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    INCOMPLETE = "incomplete"
    # 本次 plan 新增(§2.2.1):
    WRITTEN = "written"           # 至少 1 page 写入或幂等跳过
    BLOCKED = "blocked"           # 全部 page 因质量规则被阻断
    FAILED = "failed"             # 技术失败(LLM 抛异常/IO/写盘 retry 耗尽)
    SKIPPED = "skipped"           # md5 命中已有终局
```

### 2. 扩展 `ExtractionResult` dataclass

```python
@dataclass
class ExtractionResult:
    """Per-document processing result — 五态 + legacy_status 兼容字段."""

    status: ExtractionStatus
    source_id: str
    source_md5: str = ""                 # 本次 plan 新增(§2.2)
    pages: list[Any] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    blocked_topic_ids: list[str] = field(default_factory=list)  # D7
    failure_stage: str | None = None     # stage1/3/4/5/7
    attempts: int = 1                    # 本次 plan 新增(§2.2)

    # 五态细分字段(本次 plan 新增,§2.2):
    written_page_ids: list[str] = field(default_factory=list)
    blocked_page_ids: list[str] = field(default_factory=list)
    failed_page_ids: list[str] = field(default_factory=list)

    # legacy 兼容(本次 plan 新增,§2.2.1):
    legacy_status: ExtractionStatus | None = None  # v3 三态字段

    def to_dict(self) -> dict[str, Any]:
        """统一序列化,所有 caller 必须用此方法。"""
        return {
            "status": self.status.value,
            "legacy_status": (self.legacy_status or self._legacy_from_status()).value,
            "source_id": self.source_id,
            "source_md5": self.source_md5,
            "pages": [p.id if hasattr(p, "id") else p for p in self.pages],
            "written_page_ids": list(self.written_page_ids),
            "blocked_page_ids": list(self.blocked_page_ids),
            "failed_page_ids": list(self.failed_page_ids),
            "review_reasons": list(self.review_reasons),
            "blocked_topic_ids": list(self.blocked_topic_ids),
            "failure_stage": self.failure_stage,
            "attempts": self.attempts,
        }

    def _legacy_from_status(self) -> ExtractionStatus:
        """五态 → v3 三态映射(§2.2.1)。"""
        mapping = {
            ExtractionStatus.WRITTEN: ExtractionStatus.OK,
            ExtractionStatus.BLOCKED: ExtractionStatus.NEEDS_REVIEW,
            ExtractionStatus.FAILED: ExtractionStatus.NEEDS_REVIEW,
            ExtractionStatus.INCOMPLETE: ExtractionStatus.INCOMPLETE,
            ExtractionStatus.SKIPPED: ExtractionStatus.OK,  # skip 命中时
            ExtractionStatus.OK: ExtractionStatus.OK,  # legacy 旧值
            ExtractionStatus.NEEDS_REVIEW: ExtractionStatus.NEEDS_REVIEW,  # legacy 旧值
        }
        return mapping.get(self.status, ExtractionStatus.NEEDS_REVIEW)

    @classmethod
    def from_v3_status(
        cls,
        status: ExtractionStatus,
        source_id: str,
        *,
        pages: list[Any] | None = None,
        **kwargs: Any,
    ) -> "ExtractionResult":
        """从 v3 旧 ExtractionStatus 构造,自动推导五态。"""
        new_status = {
            ExtractionStatus.OK: ExtractionStatus.WRITTEN,
            ExtractionStatus.NEEDS_REVIEW: ExtractionStatus.BLOCKED,
            ExtractionStatus.INCOMPLETE: ExtractionStatus.INCOMPLETE,
        }.get(status, ExtractionStatus.BLOCKED)
        return cls(
            status=new_status,
            source_id=source_id,
            legacy_status=status,
            pages=pages or [],
            **kwargs,
        )
```

**关键点:**
- `legacy_status` 字段让 v3 旧消费者仍能读
- `to_dict()` 是**唯一**序列化入口(plan §4 Task 2 第 1 个 checkbox)
- `_legacy_from_status()` 实现 §2.2.1 映射表

### 3. 修改 `extract_pilot.py:152` 的 `_extract_one()`

返回类型从 `dict[str, Any]` 改为 `ExtractionResult`:

```python
async def _extract_one(
    root: Path,
    path: Path,
    relative: str,
    *,
    llm: Any = None,
    page_sink: Callable[[Any], None] | None = None,
) -> ExtractionResult:
    """v3 + Wave 1 + Task 2: 统一返回 ExtractionResult 五态对象。"""
    source_md5 = hashlib.md5(path.read_bytes()).hexdigest()
    try:
        # ... 现有逻辑,但 result 改为逐步构造 ExtractionResult ...
        result = ExtractionResult(
            status=ExtractionStatus.WRITTEN,  # 默认,后面按需修改
            source_id=relative,
            source_md5=source_md5,
        )
        # 失败时:
        #   result.status = ExtractionStatus.FAILED
        #   result.failure_stage = "extract_one"
        #   result.review_reasons.append(reason)
        # 完整时:
        #   result.written_page_ids.append(page_id)
        # incomplete 时:
        #   result.status = ExtractionStatus.INCOMPLETE
        return result
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"[:_EXC_REASON_LIMIT]
        log.warning("_extract_one failed for %r: %s", relative, reason)
        return ExtractionResult(
            status=ExtractionStatus.FAILED,
            source_id=relative,
            source_md5=source_md5,
            failure_stage="extract_one",
            review_reasons=[reason],
        )
```

**关键点:**
- **保留向后兼容层**:如果调用方用 `item["error"]` 仍能工作,加 `ExtractionResult` 兼容 dict-like 行为(`__getitem__` / `get`)
- **不要破坏** Luna-A 已扩展的 `page.topic_id = topic.id` 与 `_stable_page_id` 接入
- **source_md5 计算**:用文件内容 md5(不是 relative 路径),跨文件内容变化可检测

### 4. 修改 `extract_full.py`

`run_full()` 与 `_with_retries()` 消费 `ExtractionResult` 而不是 dict:

```python
# scripts/extract_full.py:run_full()
# 旧:
#   if any(item["error"] for item in batch_results): ...
# 新:
#   if any(r.status == ExtractionStatus.FAILED for r in batch_results): ...

# summary 字段更新(plan §4 Task 5 第 1 块,提前部分落地):
#   summary["by_status"] = {"written": N, "blocked": N, "failed": N, "incomplete": N, "skipped": N}
#   summary["by_legacy_status"] = {"ok": N, "needs_review": N, "incomplete": N}
#   summary["errors"] = sum(by_status["failed"])  # errors = failed 数量,不再混 blocked
#   summary["pages"] = sum(len(r.written_page_ids) for r in results)  # 仅 written page
```

**关键点:**
- `_with_retries` 内部 `result["attempts"] = attempt` 改为 `result.attempts = attempt`
- `summary["errors"]` 现在严格等于 `failed` 数量,plan §4 Task 5 的语义

### 5. 兼容层(dict-like 行为)

如果某些调用方仍用 dict 风格访问,在 `ExtractionResult` 加:

```python
def __getitem__(self, key: str) -> Any:
    """向后兼容 dict 风格访问:result['error'] → review_reasons 非空?"""
    return self.to_dict().get(key)

def get(self, key: str, default: Any = None) -> Any:
    return self.to_dict().get(key, default)
```

让旧 `item["error"]` 在测试中仍可工作(直到 Wave 3/4 全部迁移)。

## 必须通过的回归测试

写到 `tests/test_pipeline/test_v7_extract_failures.py`(扩展),至少 5 个新测试:

```python
# 1. 五态枚举值正确(written/blocked/failed/incomplete/skipped)
# 2. ExtractionResult.to_dict() 输出含 status + legacy_status + 5 个细分字段
# 3. WRITTEN → legacy_status="ok" 映射
# 4. BLOCKED → legacy_status="needs_review" 映射
# 5. FAILED → legacy_status="needs_review" 映射(plan §2.2.1)
# 6. from_v3_status(OK) → 新 status=WRITTEN, legacy_status=OK
# 7. from_v3_status(NEEDS_REVIEW) → 新 status=BLOCKED, legacy_status=NEEDS_REVIEW
# 8. ExtractionResult.__getitem__("error") 等价 review_reasons 非空判断(向后兼容)
```

写到 `tests/test_scripts/test_extract_pilot.py`(扩展),至少 3 个新测试:

```python
# 1. _extract_one() 返回 ExtractionResult 实例(不是 dict)
# 2. ExtractionResult.to_dict() 字段齐全 + source_md5 是 32 hex
# 3. 异常路径返回 status=FAILED, failure_stage="extract_one"
# 4. page_sink 仍接收 ConceptPage 对象(签名不变)
```

写到 `tests/test_scripts/test_extract_full.py`(扩展),至少 3 个新测试:

```python
# 1. run_full() summary["by_status"] 含 5 个 key,值是 int
# 2. summary["errors"] == by_status["failed"](不再含 blocked)
# 3. summary["pages"] 仅统计 written_page_ids,不含 blocked/failed
```

## TDD 节奏

1. **先扩展 failures.py dataclass**:增加新字段(不改现有字段),运行 `pytest tests/test_pipeline/test_v7_extract_failures.py -q`,**确认不破坏现有 27 测试**
2. **写 5 个新 failures 测试**,**确认失败**
3. **实现 to_dict() / from_v3_status() / _legacy_from_status()**,5 个新测试通过
4. **修改 extract_pilot.py `_extract_one()` 返回 ExtractionResult**,加兼容层
5. **写 3 个新 extract_pilot 测试**,**确认失败**
6. **实现 extract_pilot 改造**,3 个新测试通过
7. **修改 extract_full.py**,3 个新测试,**确认失败**
8. **实现 extract_full 改造**,3 个新测试通过
9. **跑全套验证**:
   ```powershell
   $env:PYTHONPATH = "."
   python -m pytest tests/test_pipeline/test_v7_extract_failures.py \
                      tests/test_pipeline/test_v7_extract_page_id.py \
                      tests/test_pipeline/test_v7_extract_slot_filler.py \
                      tests/test_pipeline/test_v7_extract_topic_clusterer.py \
                      tests/test_pipeline/test_v7_extract_stage4.py \
                      tests/test_pipeline/test_v7_extract_stage5.py \
                      tests/test_pipeline/test_v7_extract_stage7.py \
                      tests/test_scripts/test_extract_pilot.py \
                      tests/test_scripts/test_extract_full.py \
                      --import-mode=importlib -q
   python -m compileall -q src/pipeline/v7_extract scripts/extract_full.py scripts/extract_pilot.py
   git diff --check
   ```
10. **commit**(单一逻辑 commit,中文描述):
    ```bash
    git add src/pipeline/v7_extract/failures.py \
            scripts/extract_pilot.py \
            scripts/extract_full.py \
            tests/test_pipeline/test_v7_extract_failures.py \
            tests/test_scripts/test_extract_pilot.py \
            tests/test_scripts/test_extract_full.py
    git commit -m "refactor(v7-extract): unify source extraction outcomes (T2, F3 + §2.2.1 映射)"
    ```

## 环境注意事项

- `PYTHONPATH=.` 必须设置
- pytest 用 `--import-mode=importlib`
- 不要用代理变量

## 完成报告(回到主 agent 时给我)

```
commit_hash: <git rev-parse HEAD>
files_changed: <git diff --stat 输出>
test_result: passed N, failed 0
new_status_field_count: <ExtractionStatus 枚举值总数,期望 7>
new_result_fields: <ExtractionResult 新增字段列表>
compatibility_layer: <dict-like __getitem__ 是否实现>
deviations: <任何与 plan 的偏离;否则 "无">
notes: <主 agent 应注意的细节>
```

## 失败处理

- 单个测试失败 → 不 commit,先修实现
- 现有 caller 不能适配 → 加兼容层或更新 caller(若在写集合内)
- `to_dict()` 性能问题 → profile + cache,不要重新设计

## 不要做的事

- 不要碰 `_page_id.py` / `slot_filler.py` / `topic_clusterer.py` / `fill_slots.toml`
- 不要碰 Luna-B 的 `enqueue_failure` 签名
- 不要碰 `wiki_writer.py`(Wave 3 Luna-E)
- 不要碰 `_legacy.py` / `__init__.py`(v3 实施)
- 不要碰 `_queue_lock.py`(Wave 0)
- 不要碰 Luna-A/B/C 已扩展过的测试文件
- 不要新增 pip 依赖
- 不要 `git push`

## 开始

确认你理解了任务范围后,**先调研当前 callers**(`git grep -rn "_extract_one\|ExtractionResult\|item\[\"error\"\]" src/ scripts/ tests/`),列出所有依赖方,在报告中说明兼容策略。然后开始 TDD 节奏第 1 步。
