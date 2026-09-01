# ruflo-kb 重复代码 / 语义匹配分析报告

- **生成时间**：2026-09-01
- **分析目标**：`D:\5-Project\2026814\llm-wiki-base.bak.20260822`
- **方法说明**：codebase-memory-MCP 当前处于频率限制窗口（19:13 UTC+8 重置），无法直接拉取 `SIMILAR_TO`(247 对) / `SEMANTICALLY_RELATED`(151 对) 语义边。改用**本地 AST 结构克隆检测 + 跨函数惯用法扫描**对磁盘上的真实源码做等价分析（更落地：带文件路径与行号，可直接写封装示例）。
- **扫描范围**：`src/` + `scripts/` + `tools/`（MCP 限频解除后再用图谱语义边交叉校验）
- **扫描量**：473 个 `.py` 文件 → 解析成功 472 个 → 2,224 个函数/方法；结构克隆集群 71 个（其中 **35 个跨文件** `n_files>=2`）

> 判断依据：本报告"存放位置"建议直接沿用 `docs/codebase-graph-stats-2026-09-01.md` §5.5 的依赖矩阵结论——`src.lib` / `src.utils` / `src.services` / `src.searcher` / `src.events` 不稳定性指标 `I=0.00`（纯叶子设施，被全网依赖、自身不依赖他人），是**唯一合理的"基础设施层 / 公共 utils"落点**。

---

## 一、重复逻辑总览（按可抽取价值排序）

| # | 重复逻辑 | 出现次数 | 跨文件数 | 适宜度 | 建议落点 |
|---|---|---:|---:|---|---|
| A | 内容/文件哈希（body_hash / compute_md5 / compute_sha256 / _simulate_rebuild_hash / _compute_md5） | 5+ 函数 + `hashlib.md5` 13 文件 | 5 | **P0 高** | `src/lib/hashing.py` |
| B | 毫秒时间戳（`_now_ms` = `int(time.time()*1000)`） | 3 函数 + `time.time/datetime.now` 139 处 + `strftime` 30 处 | 3+ | **P0 高** | `src/lib/time.py` |
| C | 路由处理器 try/except→HTTPException 包装（5 个 handler 同构） | 5 函数（同构体更多） | 2+ | **P1 高** | `src/server/_route.py` |
| D | 实体按 key 获取（`get_approval/get_batch/get_ku/get_evidence/get_claim/get_node/get_edge`） | 7 函数 | 4 | **P1 中** | `src/knowledge/storage` 或 `src/lib/store.py` |
| E | `subprocess.run` 脚本调用封装（`_run_script`） | 2 函数 + `subprocess.run` 11 文件 | 2+ | **P1 高** | `src/lib/shell.py` |
| F | 重试/退避（`for _ in range(n): try...`） | 21 处 / 17 文件 | 多 | **P1 高** | `src/lib/retry.py` |
| G | 保序去重（`_dedupe_preserve_order` / `_ordered_unique`） | 2 函数（同逻辑） | 2 | **P1 高** | `src/lib/iter.py` |
| H | 标题抽取（`_extract_html_title` / `_extract_title`） | 2 函数 | 2 | **P2 中** | `src/collector/_title.py` |
| I | slug/id 合法性校验（`is_valid_id` / `has_slug`） | 2 函数 | 2 | **P2 中** | `src/lib/slug.py` |
| J | 懒加载单例（`_get_client` / `get_default_pipeline_service` / `get_idempotency_cache`） | 3 函数 | 3 | **P2 中** | `src/lib/lazy.py` |
| K | 自动打标（`_auto_tag_ugc`，35–37 行近乎一致） | 2 函数（大块） | 2 | **P0 高** | `src/orchestrator/auto_tag.py` |
| L | Provider `close()` / `chat()` 同构 | 3 函数 | 3 | **P2 中** | `src/llm/base.py`（抽象基类） |
| M | CLI 上下文解析（`_resolve_ctx` / `_resolve`） | 4 函数 | 4 | **P2 低** | `src/cli_ext/_ctx.py` |
| N | 路径解析（`_resolve_paths`） | 3 函数 | 3 | **P2 低** | `src/lib/paths.py`（已有 paths 模块） |

> 另有 **同文件内**相似 helper（未计入跨文件清单，但建议就地参数化合并）：`src/wiki/core/paths.py` 内 10 个 `wiki_*()` 取路径函数、`src/kc/views/book/id_policy.py` 内 4 个 `generate_*_id()`、`src/kc/integrity/gates.py` 内 3 个 `__init__()`。

---

## 二、跨文件结构克隆明细（Top，带文件与行号）

### A. 哈希/指纹（P0）
| 函数 | 文件:行 | 实现 |
|---|---|---|
| `body_hash` | `src/vector/pending.py:59` | `hashlib.sha256(body.encode()).hexdigest()[:16]` |
| `compute_md5` | `src/sync/snapshot_store.py:62` | `hashlib.md5(...)` |
| `compute_sha256` | `src/wiki/templates/state.py:113` | `hashlib.sha256(...)` |
| `_compute_md5` | `scripts/sync_wiki_spec.py:27` | `hashlib.md5(...)` |
| `_simulate_rebuild_hash` | `scripts/kc_book_rebuild_dryrun.py:103` / `scripts/kc_wiki_rebuild_dryrun.py:97` | 同上（两脚本重复） |

**判断**：✅ 高度适合抽取。5+ 处哈希实现、算法/截断长度不统一（有的 `[:16]`、有的全量），易引入"同内容不同指纹"的隐藏 bug。

### B. 毫秒时间戳（P0）
| 函数 | 文件:行 |
|---|---|
| `_now_ms` | `src/maintenance/cache_cleanup.py:37` / `src/server/ingest_tracker.py:29` / `src/wiki/features/cascade_delete.py:128` |

三者实现均为 `int(time.time() * 1000)`；另有 139 处裸 `time.time()/datetime.now`、30 处 `strftime`。
**判断**：✅ 适合抽取。`now_ms()` 统一一处，避免"秒/毫秒"混用。

### C. 路由处理器包装（P1）
`src/server/routes/analysis.py:14/24/33`、`files.py:45`、`tags.py:10` 五个 handler 均为：
```python
try:
    return service.x(project_id)
except ProjectNotFoundError as e:
    raise HTTPException(404, str(e))
```
**判断**：✅ 适合抽取为装饰器/高阶函数（见 §四示例），消除 5+ 处重复的异常翻译。

### D. 实体获取 getter（P1）
`src/kc/governance/approval.py:196` `get_approval` / `src/kc/publish/batch.py:130` `get_batch` / `src/kc/views/book/core_view.py:133/137/141` `get_ku/get_evidence/get_claim` / `src/knowledge/graph/builder.py:181/215` `get_node/get_edge` —— 均为"按 id/key 从 store 取对象，取不到返回 None/抛错"的同构模式。
**判断**：⚠️ 中。建议抽 `get_by_key(store, key)` 泛型，但各 store 接口不一，需先统一存储门面再抽取，否则只是把重复挪位置。

### E. subprocess 脚本封装（P1）
`src/cli_ext/batch_cmd.py:53` `_run_script` / `src/cli_ext/scripts_cmd.py:23` `_run_script`（实现一致：构造 env + `subprocess.run([sys.executable, ...])` + `sys.exit(returncode)`）。全仓 `subprocess.run` 出现 11 文件。
**判断**：✅ 适合抽取 `run_script(name, argv)`。

### G. 保序去重（P1）
`src/kc/views/book/diff.py:17` `_dedupe_preserve_order` 与 `src/kc/views/book/rebuild.py:46` `_ordered_unique` 实现逐字相同（set+list 保序）。
**判断**：✅ 典型 2 行工具函数，抽 `dedupe(seq)`。

### K. 自动打标（P0，大块重复）
`src/orchestrator/batch_runner.py:330` `_auto_tag_ugc`（35 行）与 `scripts/phase4_batch.py:299` `_auto_tag_ugc`（37 行）近乎逐行一致——这是**最高优先级的"复制粘贴跨文件"**，应立刻抽出到 `src/orchestrator/auto_tag.py` 由两处共同引用。

---

## 三、跨函数惯用法统计（统计类重复，非整函数克隆）

| 惯用法 | 总次数 | 文件数 | 是否建议抽取 | 说明 |
|---|---:|---:|---|---|
| `Path.read_text()` | 225 | 127 | ❌ 已是规范写法 | pathlib 标准用法，无需再包 |
| `Path.write_text()` | 100 | 70 | ❌ 已是规范写法 | 同上 |
| `time.time()/datetime.now` | 139 | 68 | ✅ 部分 | 裸调用分散；时间戳/格式化统一走 `src/lib/time.py` |
| `logging.getLogger` | 98 | 93 | ❌ 已是规范写法 | 仅建议统一 logger 命名约定 |
| `strftime 时间戳` | 30 | 16 | ✅ 部分 | 纳入 `src/lib/time.py` |
| `os.environ.get` | 28 | 10 | ⚠️ 可选 | 抽 `get_env(name, default, cast=)` 统一类型转换 |
| `retry for-range` | 21 | 17 | ✅ 高 | 抽 `@retry(times=, delay=)` 装饰器 |
| `with open(...) as f` | 21 | 11 | ❌ 多已可被 pathlib 替代 | 仅二进制/特殊模式保留 |
| `hashlib.md5` | 13 | 13 | ✅ 高 | 纳入 `src/lib/hashing.py` |
| `subprocess.run` | 11 | 8 | ✅ 高 | 纳入 `src/lib/shell.py` |
| `dict.setdefault/defaultdict` | 11 | 7 | ❌ 已是规范写法 | |

---

## 四、统一封装示例（建议代码）

### `src/lib/hashing.py`（P0 — 覆盖 A + hashlib.md5）
```python
"""集中式哈希/指纹工具。统一算法与截断长度，杜绝"同内容不同指纹"。"""
from __future__ import annotations
import hashlib
from pathlib import Path

DEFAULT_ALGO = "sha256"
FINGERPRINT_LEN = 16  # 全仓原先混用全量/[:16]，统一为 16 位前缀

def content_hash(text: str, *, algo: str = DEFAULT_ALGO,
                 length: int | None = FINGERPRINT_LEN) -> str:
    digest = hashlib.new(algo, text.encode("utf-8")).hexdigest()
    return digest if length is None else digest[:length]

def body_hash(body: str) -> str:
    """Stable page-body fingerprint (was body_hash in vector/pending.py)."""
    return content_hash(body or "", algo="sha256")

def file_md5(path: str | Path) -> str:
    h = hashlib.md5()
    data = Path(path).read_bytes()
    h.update(data)
    return h.hexdigest()
```
> 迁移：`vector/pending.body_hash` → `from src.lib.hashing import body_hash`；`sync/snapshot_store.compute_md5`、`wiki/templates/state.compute_sha256`、`scripts/*._compute_md5/_simulate_rebuild_hash` 全部改为 `content_hash`/`file_md5`。

### `src/lib/time.py`（P0 — 覆盖 B + strftime + 部分 time.now）
```python
"""统一时间戳工具，避免秒/毫秒混用与分散的 strftime 格式。"""
from __future__ import annotations
import time
from datetime import datetime, timezone

def now_ms() -> int:
    return int(time.time() * 1000)

def now_ts(format: str = "%Y-%m-%dT%H:%M:%S") -> str:
    return datetime.now(timezone.utc).strftime(format)

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```
> 迁移：`maintenance/cache_cleanup._now_ms`、`server/ingest_tracker._now_ms`、`wiki/features/cascade_delete._now_ms` 删除，改用 `now_ms()`。

### `src/server/_route.py`（P1 — 覆盖 C 路由处理器包装）
```python
"""FastAPI 路由统一异常→HTTPException 翻译，消除各 handler 重复的 try/except。"""
from __future__ import annotations
from functools import wraps
from fastapi import HTTPException

def translate(not_found: type[Exception] = ProjectNotFoundError, status: int = 404):
    def deco(fn):
        @wraps(fn)
        async def wrap(*a, **k):
            try:
                return await fn(*a, **k)
            except not_found as e:
                raise HTTPException(status, str(e))
        return wrap
    return deco

# 用法：
# @router.get("/projects/{project_id}/wiki/graph")
# @translate(ProjectNotFoundError, 404)
# async def wiki_graph(project_id: str):
#     return analysis_service.graph(project_id)
```

### `src/lib/shell.py`（P1 — 覆盖 E + subprocess.run）
```python
"""subprocess 调用统一封装。"""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

def run_script(name: str, argv: list[str], *, scripts_dir: Path) -> None:
    """运行 scripts/<name>.py <argv...> 并传播退出码。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(scripts_dir.parent)
    proc = subprocess.run(
        [sys.executable, str(scripts_dir / f"{name}.py"), *argv], env=env)
    sys.exit(proc.returncode)

def run_cmd(args: list[str], *, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, cwd=cwd)
```

### `src/lib/retry.py`（P1 — 覆盖 F 重试/退避）
```python
"""指数退避重试装饰器，替代散落的 for-range+try。"""
from __future__ import annotations
import time
from collections.abc import Callable
from functools import wraps

def retry(times: int = 3, delay: float = 1.0, backoff: float = 2.0,
          exceptions: tuple[type[Exception], ...] = (Exception,)):
    def deco(fn: Callable):
        @wraps(fn)
        def wrap(*a, **k):
            d = delay
            for i in range(times):
                try:
                    return fn(*a, **k)
                except exceptions:
                    if i == times - 1:
                        raise
                    time.sleep(d); d *= backoff
        return wrap
    return deco
```

### `src/lib/iter.py`（P1 — 覆盖 G 保序去重）
```python
from collections.abc import Iterable, Hashable
from typing import TypeVar
T = TypeVar("T", bound=Hashable)

def dedupe(items: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    out: list[T] = []
    for it in items:
        if it not in seen:
            seen.add(it); out.append(it)
    return out
# 迁移：diff._dedupe_preserve_order / rebuild._ordered_unique → dedupe(seq)
```

---

## 五、抽取落地顺序（优先级）

| 优先级 | 项 | 动机 | 落点 |
|---|---|---|---|
| **P0** | K 自动打标 `_auto_tag_ugc` | 35–37 行逐行复制，改动需同步两处，最易漂移 | `src/orchestrator/auto_tag.py` |
| **P0** | A 哈希集中化 | 算法/截断不统一，隐藏"同内容异指纹" bug | `src/lib/hashing.py` |
| **P0** | B 时间戳 `now_ms` | 秒/毫秒混用风险 | `src/lib/time.py` |
| **P1** | E subprocess 封装 | 11 文件裸调用 | `src/lib/shell.py` |
| **P1** | F 重试装饰器 | 17 文件散落重试 | `src/lib/retry.py` |
| **P1** | C 路由异常包装 | 5+ handler 重复 | `src/server/_route.py` |
| **P1** | G 保序去重 | 逐字重复 | `src/lib/iter.py` |
| **P2** | D 实体 getter | 需先统一 store 门面 | `src/lib/store.py` |
| **P2** | H/I/J/L/M/N | 同逻辑小函数或基类层面收敛 | 对应 `src/lib/*` 或基类 |

> **不要抽取**：`Path.read_text/write_text`（已是规范写法）、`logging.getLogger`、`dict.setdefault/defaultdict`、`with open()`（多数可被 pathlib 替代）。这些"重复"是 Python 惯用法本身，硬抽反而增加间接层。

---

## 六、存放位置与依赖关系依据

- **基础设施层 = `src.lib` + `src.utils`**：来自 `codebase-graph-stats-2026-09-01.md` §5.5，二者不稳定性指标 `I=0.00`（纯叶子设施：被依赖、自身不依赖他人），是**唯一正确**的公共 utils 落点。新增 `src/lib/hashing.py`、`time.py`、`shell.py`、`retry.py`、`iter.py`、`slug.py`、`lazy.py`、`store.py` 不会引入新的循环依赖。
- **路由层专属**：C 类（路由包装）放 `src/server/_route.py`，因为它耦合 FastAPI，不属于通用 lib。
- **编排层**：K 类（`_auto_tag_ugc`）放 `src/orchestrator/auto_tag.py`，因为它编排 ingest 流程、依赖 orchestrator 内部状态。
- **抽象基类**：L 类（Provider `close/chat`）应回归 `src/llm/base.py` 的 Provider 抽象基类，而非新 lib。

---

## 七、与 codebase-memory-MCP 语义边的交叉校验计划

本报告为 AST 结构克隆（同构检测）。MCP 限频（19:13 重置）后，将用以下查询补做**嵌入级语义匹配**（捕捉"结构不同但语义相同"的重复，本地法会漏掉）：

```cypher
MATCH (a:Function)-[:SIMILAR_TO]-(b:Function)
WHERE a.file_path ENDS WITH '.py' AND b.file_path ENDS WITH '.py'
RETURN a.qualified_name, b.qualified_name, a.file_path, b.file_path
```
```cypher
MATCH (a:Function)-[:SEMANTICALLY_RELATED]-(b:Function)
WHERE a.file_path ENDS WITH '.py' AND b.file_path ENDS WITH '.py'
RETURN a.qualified_name, b.qualified_name
```
预计可再补 ~247 对语义克隆，届时与本报告的 35 个跨文件结构集群合并，形成最终去重清单。

---

*方法：本地 AST 结构签名（mask 标识符/字符串，保留关键字/操作符/数字）+ 正则惯用法扫描；脚本 `src` 见 `.workbuddy/dup_scan.py`，原始结果 `.workbuddy/dup_scan.json`。本报告聚焦"分散在不同文件"的重复（35 个跨文件集群），同文件内相似 helper 仅在 §一末段提示就地参数化。*
