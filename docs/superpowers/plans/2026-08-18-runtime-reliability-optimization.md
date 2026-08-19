# Runtime Reliability Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变摄入、检索和门禁业务语义的前提下，消除生产向量写入对“最近初始化项目”的隐式依赖，为服务器启动建立可验证的时延上界，并移除 lint 的逐页重复配置读取。

**Architecture:** 复用现有 `WikiPaths`、`get_table(paths)`、`upsert_chunks_to_table(table, chunks)` 三个接口，把项目隔离落实在既有向量存储 seam，而不引入新的存储抽象。服务器只新增一个聚合 Provider 健康探测的深模块，lifespan 保留必要同步初始化，将非关键网络检查移到受管后台任务。lint 仅把项目级配置提升到扫描循环外，不改变规则实现。

**Tech Stack:** Python 3.11+、FastAPI lifespan、asyncio、LanceDB、pytest、pytest-asyncio。

**Spec:** `docs/superpowers/plans/2026-08-18-runtime-reliability-optimization.md#设计契约`（本计划内嵌最小设计说明，避免复制一份独立 spec）。

## Global Constraints

- 不新增第三方依赖；复用 stdlib、FastAPI、LanceDB 和现有项目接口。
- 不修改 Collector → Analyzer → Generator → Writer 的业务语义，不调整 LLM prompt、质量阈值、PageType 或 WikiPage frontmatter。
- 不删除无参 `get_table()` 和 `vector_upsert_chunks(chunks)` 兼容入口；本轮只禁止生产路径继续依赖它们。
- 所有向量写入必须先用目标项目的 `WikiPaths` 解析 table，并用实际 embedding 维度调用 `init_vector_store_for_paths(paths, expected_dim=...)`。
- 所有向量 mutation（upsert、delete、clear、rebuild）都必须经过显式 `WikiPaths`；Task 1 的静态审计覆盖整个 `src/`，不能只搜索 `vector_upsert_chunks(`。
- 写入前必须校验本批所有 embedding 非空、维度一致且与目标 table 兼容；任何不一致都使任务失败并记录可检索的错误，不得写入部分结果。
- Provider 健康检查失败只能降级并记录日志，不得阻止 `/health` 服务启动。
- Provider 探测支持 `RUFLO_PROVIDER_PROBE=0` 关闭（默认开启）；关闭时返回 `skipped` 状态并不得发起外部网络调用。
- `/health` 明确定义为 liveness；Provider 探测状态单独暴露为内部状态/日志，不得把“尚未探测完成”误报为语义能力已就绪。
- Provider 探测最多并发 4 个；每个 Provider 的健康检查、响应格式检查和关闭均有独立超时，禁止无限等待。
- 启动预算以 lifespan 进入到 `yield` 的墙钟时间计量，目标为 15 秒；预算超出必须在 smoke 记录中失败，不能只验证 `/health` 最终返回 200。
- 每个任务使用 TDD、一个逻辑切片一个 commit；不得使用 `git add .`。
- 现有 `knowledge/novel-wiki/` 批处理产生的大量工作区改动属于用户数据，本计划的实现不得暂存、回滚或格式化这些文件。
- 修改 `src/server/` 后必须运行真实 `python -m src.cli serve --port <free>` 并请求 `/health`。
- 计划进入编码前必须人工复核本文件的 Audit 部分；当前 `Human review` 未通过前禁止执行任务。
- 编码前必须保存触及区域测试基线（收集数量、失败节点、环境版本）；验收采用“无新增失败”，不得要求历史已知失败凭空消失。

status: planned
branch: codex/2026-08-18-runtime-reliability-optimization

---

## 设计依据

### 已确认事实

1. `src/vector.store` 已按项目路径缓存 LanceDB handle；`get_table(paths)` 能返回指定项目 table。
2. `src.vector.upsert.upsert_chunks_to_table(table, chunks)` 已存在，正好是显式写入接口，无需再建 Repository、Manager 或 Adapter。
3. 以下生产调用仍无参写入“当前项目”table：
   - `src/pipeline/librarian.py:131`
   - `src/pipeline/stages/indexer.py:148`
   - `src/orchestrator/batch_runner.py:382`
4. `src/server/app.py` 在 lifespan 的 `yield` 前串行探测所有 Provider；单个 Provider 最坏执行 `health_check` 与 `check_response_format` 两个 10 秒等待。
5. `src/wiki/features/lint.py:411` 在每个页面循环中重新读取 `.index/quality_settings.json`。
6. `hybrid_search(query, top_k, paths=paths)` 当前已经同时把项目路径传给向量检索和关键词扫描，本计划不重复修复该问题。

### 优化前基线

| 热点 | 当前规模 | 本计划处置 |
|---|---:|---|
| `generate_ingest` | 559 行，圈复杂度 47 | 不在本计划重构；先确认 candidate/unified 契约 |
| `parse_llm_json` | 204 行，圈复杂度 48 | 不动；已有集中解析回归测试 |
| `run_batch` | 300 行，圈复杂度 46 | 仅修正其向量 table 解析，不拆状态机 |
| `lint_wiki` | 355 行，圈复杂度 40 | 只消除项目配置重复 I/O |
| `create_app` | 207 行，圈复杂度 37 | 只抽取 Provider 探测模块并收敛 lifespan |

## 设计契约

### Module：项目向量表解析

- **Interface：** 继续使用 `init_vector_store_for_paths(paths, expected_dim)`、`get_table(paths)`、`upsert_chunks_to_table(table, chunks)`。
- **Invariant：** 生产写入的 table 必须由同一次调用链中的 `paths` 解析，不能由 `_current_project_key` 推断。
- **Ordering：** 先取得 embedding → 用 `len(embedding)` 校验/初始化 schema → 取得 table → upsert。
- **Batch validation：** 在初始化 schema 前校验本批每条 embedding 非空、维度一致且数值有限；混合维度或空向量直接失败。
- **Error mode：** 维度不匹配继续抛 `VectorDimensionMismatchError`，禁止自动 drop 或重建。
- **Atomicity：** 维度校验失败时不得调用 upsert；调用方必须将任务标为失败/可重试，不得留下部分向量结果。
- **Compatibility：** legacy CLI/测试仍可用无参 `get_table()`，但 `src/pipeline/`、`src/orchestrator/` 不得调用无参向量写入。

### Module：Provider 后台探测

- **Interface：**

  ```python
  async def probe_configured_providers(timeout_s: float = 10.0) -> dict[str, str]: ...
  ```

- **Depth：** 调用方只需启动一个 coroutine；配置加载、单 Provider 超时、响应格式检查、日志和关闭均隐藏在模块内部。
- **Concurrency：** Provider 之间并发但最多 4 个；单 Provider 内 `health_check` 成功后才执行 `check_response_format`。
- **Error mode：** 单 Provider 失败不取消其他探测；所有创建成功的 Provider 都必须在 `finally` 中关闭。
- **Result contract：** 返回每个 Provider 的 `ok`、`timeout`、`error` 或 `skipped` 状态；调用方记录汇总，但不阻塞 liveness。
- **Operational control：** `RUFLO_PROVIDER_PROBE=0` 时不创建 Provider、不访问外部端点，返回所有配置项的 `skipped` 状态。
- **Timeout contract：** 健康检查、响应格式检查、Provider close 各自受独立超时约束；取消和关闭异常必须被记录且不能拖住 shutdown。
- **Lifecycle：** lifespan 用 `asyncio.create_task` 启动并保留 task；shutdown 时取消未完成 task，再用 `asyncio.gather(..., return_exceptions=True)` 回收。
- **Startup bound：** 后台 Provider 探测不计入启动关键路径；embedding Provider 构造与 smoke test 共用 5 秒预算，超时进入既有 fallback。lifespan 从进入到 `yield` 的实测总时长必须小于 15 秒。

### Module：Wiki lint

- **Interface：** `lint_wiki(paths, project_id="default", page_ids=None) -> LintReport` 保持不变。
- **Invariant：** 同一次 lint 使用同一份项目级 raw-paste 阈值快照。
- **Performance：** `_load_raw_paste_thresholds(paths)` 每次 `lint_wiki` 最多调用一次。

## 任务依赖

```text
Task 1 向量写入隔离 ─┐
                      ├─> Task 4 全量验证与文档同步
Task 2 启动时延上界 ─┤
                      │
Task 3 lint I/O ──────┘
```

Task 1、2、3 的代码彼此独立，但为避免共享工作区冲突，按编号串行执行；每个任务完成后独立 review。

---

### Task 1: 生产向量写入绑定显式项目 table

**Files:**

- Modify: `src/pipeline/librarian.py:32,131`
- Modify: `src/vector/upsert.py`（新增批量 embedding 校验）
- Modify: `src/pipeline/stages/indexer.py:28,110-149`
- Modify: `src/orchestrator/batch_runner.py:337-384`
- Test: `tests/test_vector/test_explicit_write_project_isolation.py`
- Test: `tests/test_pipeline/test_librarian_project_table.py`
- Test: `tests/test_pipeline/test_indexer.py`
- Test: `tests/test_scripts/test_batch_executor.py`

**Interfaces:**

- Consumes: `init_vector_store_for_paths(paths: WikiPaths, expected_dim: int | None) -> None`
- Consumes: `get_table(project_paths: WikiPaths | None = None) -> LanceDBTable`
- Consumes: `upsert_chunks_to_table(table, chunks: list[VectorChunk]) -> None`
- Consumes: `validate_embedding_batch(chunks: list[VectorChunk]) -> None`
- Produces: 三条生产写入路径都满足“调用链 paths → table → upsert”的项目隔离 invariant。

- [ ] **Step 1: 写跨项目 table 行为测试**

  新建 `tests/test_vector/test_explicit_write_project_isolation.py`：

  ```python
  from src.types import VectorChunk
  from src.vector.store import get_table, init_vector_store_for_paths
  from src.vector.upsert import upsert_chunks_to_table
  from src.wiki.core.paths import WikiPaths
  from src.wiki.storage.ensure import ensure_knowledge_base


  def _chunk(chunk_id: str, task_id: str, embedding: list[float]) -> VectorChunk:
      return VectorChunk(
          id=chunk_id,
          task_id=task_id,
          content=task_id,
          embedding=embedding,
          path=f"raw/sources/{task_id}.md",
          updated_at=1,
      )


  def test_explicit_tables_do_not_follow_current_project(tmp_path):
      paths_a = ensure_knowledge_base(tmp_path / "a")
      paths_b = ensure_knowledge_base(tmp_path / "b")
      init_vector_store_for_paths(paths_a, expected_dim=2)
      table_a = get_table(paths_a)
      init_vector_store_for_paths(paths_b, expected_dim=2)  # B becomes current
      table_b = get_table(paths_b)

      upsert_chunks_to_table(table_a, [_chunk("a-1", "a", [1.0, 0.0])])
      upsert_chunks_to_table(table_b, [_chunk("b-1", "b", [0.0, 1.0])])

      assert table_a.count_rows() == 1
      assert table_b.count_rows() == 1
      assert table_a.to_pandas().iloc[0]["task_id"] == "a"
      assert table_b.to_pandas().iloc[0]["task_id"] == "b"
  ```

- [ ] **Step 2: 运行测试并确认基线**

  Run:

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_vector/test_explicit_write_project_isolation.py -v
  ```

  Expected: PASS；该测试锁定既有显式 table 能力，后续调用点迁移不得破坏它。

- [ ] **Step 3: 为 librarian 写失败测试，证明它使用 paths 对应 table**

  在 `tests/test_pipeline/test_librarian_project_table.py` 用 monkeypatch 捕获显式 table：

  ```python
  async def test_archive_upserts_to_table_resolved_from_paths(monkeypatch, tmp_path):
      paths = ensure_knowledge_base(tmp_path)
      note = paths.wiki_sources / "note.md"
      note.write_text("可索引内容", encoding="utf-8")
      expected_table = object()
      captured = {}

      monkeypatch.setattr(librarian, "get_embedding_provider", lambda: FakeEmbeddingProvider([[1.0, 0.0]]))
      monkeypatch.setattr(librarian, "vector_search_chunks", lambda *a, **kw: [])
      monkeypatch.setattr(librarian, "init_vector_store_for_paths", lambda p, expected_dim: captured.update(paths=p, dim=expected_dim))
      monkeypatch.setattr(librarian, "get_table", lambda p: expected_table)
      monkeypatch.setattr(librarian, "upsert_chunks_to_table", lambda table, chunks: captured.update(table=table, chunks=chunks))

      await librarian.archive("task-a", str(note), paths)

      assert captured["paths"] is paths
      assert captured["dim"] == 2
      assert captured["table"] is expected_table
  ```

  `FakeEmbeddingProvider` 直接放在测试文件内，只实现 `async embed(texts)`；不得新增共享测试抽象。

- [ ] **Step 4: 运行 librarian 测试并验证先红**

  Run:

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_pipeline/test_librarian_project_table.py -v
  ```

  Expected: FAIL，因为当前 `archive` 仍调用 `vector_upsert_chunks(lance_chunks)`。

- [ ] **Step 5: 最小迁移 librarian**

  将导入和写入替换为：

  ```python
  from ..vector.store import get_table, init_vector_store_for_paths
  from ..vector.upsert import upsert_chunks_to_table

  validate_embedding_batch(lance_chunks)
  dimension = len(lance_chunks[0].embedding)
  init_vector_store_for_paths(paths, expected_dim=dimension)
  upsert_chunks_to_table(get_table(paths), lance_chunks)
  ```

  不修改 archive 的参数、异常契约或 dedup 行为。

- [ ] **Step 6: 以相同 invariant 迁移 IndexerStage 和 BatchRunner**

  两处都在生成 `lance_chunks` 后使用同一最小代码：

  ```python
  validate_embedding_batch(lance_chunks)
  dimension = len(lance_chunks[0].embedding)
  init_vector_store_for_paths(paths, expected_dim=dimension)
  upsert_chunks_to_table(get_table(paths), lance_chunks)
  ```

  `validate_embedding_batch` 放在现有 vector upsert 模块，复用同一校验逻辑；校验失败必须沿用调用方现有任务失败/重试路径，禁止吞异常或继续写页面。

  `IndexerStage._upsert_vectors` 已保证 `lance_chunks` 非空；`_upsert_batch_vectors` 在每页循环内已有 chunks/embeddings 非空判断。不得把 schema mismatch 吞掉。

- [ ] **Step 7: 运行触及区域测试**

  Run:

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_vector/ tests/test_pipeline/test_librarian_project_table.py tests/test_pipeline/test_librarian_uses_runtime.py tests/test_pipeline/test_librarian_zero_vector_guard.py tests/test_pipeline/test_indexer.py tests/test_scripts/test_batch_executor.py -v
  ```

  Expected: PASS。

- [ ] **Step 8: 静态审计全部向量 mutation 调用点**

  Run:

  ```powershell
  rg -n "vector_upsert_chunks\(|upsert_chunks_to_table\(|vector_delete|vector_clear|get_table\(\)" src
  ```

  Expected: 除 `src/vector/` 兼容实现及明确 legacy 边界外，生产代码无无参 mutation；每一处都能追溯到同一次调用链的 `paths`。

- [ ] **Step 9: 增加真实 A/B 并发隔离验收**

  用两个独立项目并发执行 librarian/indexer/batch 的写入，随后分别读取两个 LanceDB table，断言行数、task_id 和 embedding 均不串项目；再调用删除/清理路径确认不会误删另一项目数据。

- [ ] **Step 10: Commit**

  ```powershell
  git add src/vector/upsert.py src/pipeline/librarian.py src/pipeline/stages/indexer.py src/orchestrator/batch_runner.py tests/test_vector/test_explicit_write_project_isolation.py tests/test_pipeline/test_librarian_project_table.py tests/test_pipeline/test_indexer.py tests/test_scripts/test_batch_executor.py
  git commit -m "fix(vector): bind production writes to project tables"
  ```

---

### Task 2: 为服务器启动建立时延上界

**Files:**

- Create: `src/server/provider_health.py`
- Modify: `src/server/app.py:95-191,222-241`
- Test: `tests/test_server/test_provider_health.py`

**Interfaces:**

- Consumes: `ProviderRegistry.load()`、`provider.health_check()`、`provider.check_response_format()`、`provider.close()`。
- Produces: `probe_configured_providers(timeout_s: float = 10.0) -> dict[str, str]`，返回每个 Provider 的最终状态。
- Produces: lifespan 启动一个受管 `provider_probe_task`，不会等待所有聊天 Provider 网络探测完成才 `yield`。

- [ ] **Step 1: 写 Provider 并发与关闭失败测试**

  新建 `tests/test_server/test_provider_health.py`：

  ```python
  import asyncio
  import time

  from src.server import provider_health


  class FakeProvider:
      def __init__(self, delay: float, ok: bool = True):
          self.delay = delay
          self.ok = ok
          self.closed = False

      async def health_check(self):
          await asyncio.sleep(self.delay)
          return {"ok": self.ok, "detail": "fake"}

      async def check_response_format(self):
          await asyncio.sleep(self.delay)
          return {"ok": self.ok, "detail": "fake"}

      async def close(self):
          self.closed = True


  async def test_probe_is_concurrent_and_closes_every_provider(monkeypatch):
      providers = {"a": FakeProvider(0.03), "b": FakeProvider(0.03)}
      monkeypatch.setattr(
          provider_health.ProviderRegistry,
          "load",
          lambda: {"a": "a", "b": "b"},
      )
      monkeypatch.setattr(
          provider_health,
          "_create_from_config",
          lambda config: providers[config],
      )

      started = time.perf_counter()
      await provider_health.probe_configured_providers(timeout_s=0.2)

      assert time.perf_counter() - started < 0.11
      assert all(p.closed for p in providers.values())
  ```

  实现时可把测试 factory 简化为按 config 字典取 provider；关键断言是总耗时接近单 Provider 而不是两者相加，且均已关闭。

- [ ] **Step 2: 写单 Provider 超时不拖累其他 Provider 的测试**

  ```python
  async def test_timeout_does_not_cancel_other_provider(monkeypatch, caplog):
      providers = {"slow": FakeProvider(1.0), "fast": FakeProvider(0.0)}
      monkeypatch.setattr(
          provider_health.ProviderRegistry,
          "load",
          lambda: {"slow": "slow", "fast": "fast"},
      )
      monkeypatch.setattr(
          provider_health,
          "_create_from_config",
          lambda config: providers[config],
      )

      await provider_health.probe_configured_providers(timeout_s=0.01)

      assert providers["slow"].closed is True
      assert providers["fast"].closed is True
      assert "timed out" in caplog.text
      # The returned state is part of the contract; it is not log-only.
      result = await provider_health.probe_configured_providers(timeout_s=0.01)
      assert result["slow"] == "timeout"
      assert result["fast"] == "ok"
  ```

- [ ] **Step 2a: 写探测关闭和外部调用隔离测试**

  设置 `RUFLO_PROVIDER_PROBE=0`，断言返回值全部为 `skipped`，且 `_create_from_config` 未被调用；该测试用于防止重启时无意访问敏感或计费 Provider。

- [ ] **Step 3: 运行测试并验证先红**

  Run:

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_server/test_provider_health.py -v
  ```

  Expected: FAIL with `ModuleNotFoundError: src.server.provider_health`。

- [ ] **Step 4: 实现深模块，不新增 Adapter 层**

  `src/server/provider_health.py` 的完整接口形状：

  ```python
  import asyncio
  import logging
  import os

  from ..llm.provider_factory import _create_from_config
  from ..llm.registry import ProviderRegistry

  logger = logging.getLogger(__name__)


  async def _probe_one(name, config, timeout_s: float, semaphore) -> str:
      provider = None
      try:
          async with semaphore:
              provider = _create_from_config(config)
              health = await asyncio.wait_for(provider.health_check(), timeout=timeout_s)
              if not health.get("ok"):
                  logger.warning("[startup] provider %r unreachable: %s", name, health.get("detail"))
                  return "error"
              response_format = await asyncio.wait_for(
                  provider.check_response_format(), timeout=timeout_s
              )
              if not response_format.get("ok"):
                  logger.warning(
                      "[startup] provider %r response_format incompatible: %s",
                      name,
                      response_format.get("detail"),
                  )
                  return "error"
              return "ok"
      except asyncio.TimeoutError:
          logger.warning("[startup] provider %r health-check timed out", name)
          return "timeout"
      except Exception:
          logger.warning("[startup] provider %r health-check error", name, exc_info=True)
          return "error"
      finally:
          if provider is not None:
              try:
                  await asyncio.wait_for(provider.close(), timeout=min(timeout_s, 2.0))
              except Exception:
                  logger.warning("[startup] provider %r close failed", name, exc_info=True)


  async def probe_configured_providers(timeout_s: float = 10.0) -> dict[str, str]:
      try:
          configs = ProviderRegistry.load()
      except Exception:
          logger.warning("[startup] provider registry load failed", exc_info=True)
          return {}
      if os.getenv("RUFLO_PROVIDER_PROBE", "1") == "0":
          return {name: "skipped" for name in configs}
      semaphore = asyncio.Semaphore(4)
      results = await asyncio.gather(
          *(_probe_one(name, config, timeout_s, semaphore) for name, config in configs.items()),
          return_exceptions=True,
      )
      return {
          name: (result if isinstance(result, str) else "error")
          for name, result in zip(configs, results)
      }
  ```

  这是内部深模块，不定义 Protocol、ABC、factory class 或健康状态 dataclass。信号量必须覆盖单 Provider 的完整健康检查和响应格式检查；close 独立受超时保护，避免关闭阶段占满探测槽位；`zip(configs, results)` 保证单项异常也产生确定状态；取消异常仍需向 lifespan 传播，以便 shutdown 正确回收。

- [ ] **Step 5: 将 lifespan 串行循环替换成受管后台 task**

  在 `src/server/app.py`：

  ```python
  from .provider_health import probe_configured_providers

  startup_started = asyncio.get_running_loop().time()
  provider_probe_task = asyncio.create_task(probe_configured_providers())
  cleanup_task = asyncio.create_task(_periodic_cache_cleanup())
  if asyncio.get_running_loop().time() - startup_started >= 15:
      raise RuntimeError("lifespan startup exceeded 15s budget")
  yield
  for task in (provider_probe_task, cleanup_task):
      task.cancel()
  await asyncio.wait_for(
      asyncio.gather(provider_probe_task, cleanup_task, return_exceptions=True),
      timeout=5,
  )
  ```

  删除原有 `for name, config in ProviderRegistry.load().items()` 串行循环。保留 shutdown 的 `ProviderRegistry.aclose_all()`，它负责请求期创建的 Provider。

- [ ] **Step 6: 给 embedding smoke test 增加 5 秒硬上界**

  将 Provider candidate 的构造和 smoke 调用纳入同一 5 秒预算；若构造函数是同步阻塞，必须通过现有异步入口或 `asyncio.to_thread` 包装，超时统一走当前 local fallback，不能只给 `embed()` 加超时。将：

  ```python
  test_result = await candidate.embed(["test"])
  ```

  改为：

  ```python
  test_result = await asyncio.wait_for(candidate.embed(["test"]), timeout=5)
  ```

  超时沿用当前 exception fallback 路径；不得新增第二套 retry。

- [ ] **Step 7: 写取消探测仍关闭 Provider 的测试**

  在 `tests/test_server/test_provider_health.py` 增加：

  ```python
  import pytest


  async def test_cancelled_probe_closes_created_provider(monkeypatch):
      started = asyncio.Event()

      class BlockingProvider(FakeProvider):
          async def health_check(self):
              started.set()
              await asyncio.Event().wait()

      provider = BlockingProvider(0.0)
      monkeypatch.setattr(
          provider_health.ProviderRegistry,
          "load",
          lambda: {"blocking": "blocking"},
      )
      monkeypatch.setattr(
          provider_health,
          "_create_from_config",
          lambda _config: provider,
      )

      task = asyncio.create_task(
          provider_health.probe_configured_providers(timeout_s=60.0)
      )
      await asyncio.wait_for(started.wait(), timeout=0.2)
      task.cancel()
      with pytest.raises(asyncio.CancelledError):
          await task

      assert provider.closed is True
  ```

  该测试锁定 `_probe_one` 的 `finally` 清理；lifespan 是否正确 cancel/gather 由 Step 9/10 的启动与 shutdown 验收共同验证，不为测试增加一行式 wrapper。

- [ ] **Step 8: 运行 server 单测**

  Run:

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_server/test_provider_health.py tests/test_server/test_app.py tests/test_server/test_routes.py tests/test_llm/test_aclose_all.py -v
  ```

  Expected: PASS。

- [ ] **Step 9: 验证启动预算与关闭上界**

  增加 lifespan 测试：从进入 lifespan 到 `yield` 的计时必须 `< 15s`；使用永不返回的 Provider 验证 `/health` 仍可返回，shutdown 在 5 秒内完成且无 pending-task 或未关闭 client 警告。

- [ ] **Step 10: 真实启动 smoke test**

  在 PowerShell 选择空闲端口，例如 8876：

  ```powershell
  $proc = Start-Process -WindowStyle Hidden -PassThru python -ArgumentList '-m','src.cli','serve','--host','127.0.0.1','--port','8876'
  try {
      $response = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8876/health -TimeoutSec 15
      if ($response.StatusCode -ne 200) { throw "health status $($response.StatusCode)" }
  } finally {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      Wait-Process -Id $proc.Id -Timeout 5 -ErrorAction SilentlyContinue
      if (Get-NetTCPConnection -LocalPort 8876 -ErrorAction SilentlyContinue) { throw 'port 8876 still occupied' }
  }
  ```

  Expected: lifespan 实测 `< 15s`，15 秒内返回 200；不可因任一未连通 Provider 阻塞；finally 后端口必须释放。

- [ ] **Step 11: Commit**

  ```powershell
  git add src/server/provider_health.py src/server/app.py tests/test_server/test_provider_health.py
  git commit -m "perf(server): bound provider checks outside startup path"
  ```

---

### Task 3: 每次 lint 只读取一次项目阈值

**Files:**

- Modify: `src/wiki/features/lint.py:315-412`
- Test: `tests/test_wiki/test_lint.py`

**Interfaces:**

- Consumes: `_load_raw_paste_thresholds(paths) -> tuple[int, int]`
- Produces: `lint_wiki(...)` 行为和返回类型不变；每次调用最多读取一次阈值文件。

- [ ] **Step 1: 写失败测试**

  在 `tests/test_wiki/test_lint.py` 增加：

  ```python
  def test_lint_loads_raw_paste_thresholds_once_per_run(tmp_path, monkeypatch):
      paths = ensure_knowledge_base(tmp_path)
      for index in range(3):
          write_page(paths, WikiPage(
              id=f"page-{index}",
              title=f"Page {index}",
              type=PageType.CONCEPT,
              body="## 定义\n正文",
              sources=[f"raw/sources/{index}.md"],
          ))

      calls = 0

      def fake_thresholds(_paths):
          nonlocal calls
          calls += 1
          return 1200, 1600

      monkeypatch.setattr("src.wiki.features.lint._load_raw_paste_thresholds", fake_thresholds)
      lint_wiki(paths)

      assert calls == 1
  ```

- [ ] **Step 2: 运行测试并验证先红**

  Run:

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_wiki/test_lint.py::test_lint_loads_raw_paste_thresholds_once_per_run -v
  ```

  Expected: FAIL，`calls == 3`。

- [ ] **Step 3: 最小实现**

  在进入目录/页面循环前读取一次：

  ```python
  T_source, T_non = _load_raw_paste_thresholds(paths)

  for sub in (...):
      ...
  ```

  删除循环内原调用。不要缓存到模块全局，因为不同项目允许不同阈值，运行期间后续 lint 也必须看到新配置。

- [ ] **Step 4: 运行完整 wiki lint 测试**

  Run:

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_wiki/test_lint.py tests/test_wiki/test_lint_cache.py -v
  ```

  Expected: PASS。

- [ ] **Step 4a: 验证项目隔离和可测收益**

  创建两个不同 `quality_settings.json` 的项目，分别运行 lint，断言阈值不串；对固定数量页面记录修改前后的阈值文件读取次数和墙钟耗时，报告实际收益而不是只报告单元测试通过。

- [ ] **Step 5: Commit**

  ```powershell
  git add src/wiki/features/lint.py tests/test_wiki/test_lint.py
  git commit -m "perf(wiki): load lint thresholds once per run"
  ```

---

### Task 4: 全量验证、文档同步与图谱更新

**Files:**

- Modify: `docs/environment/SETUP.md`（仅当测试命令或已知坑事实发生变化）
- Modify: `.superpowers/sdd/progress.md`
- Create: `.memory/feedback-runtime-reliability-optimization.md`
- Create or Modify: `.memory/MEMORY.md`
- Generated update: `graphify-out/`

**Interfaces:**

- Consumes: Task 1-3 的三个独立 commit。
- Produces: 可恢复的验证记录、进度账本和代码图谱更新；不产生业务代码变化。

- [ ] **Step 1: 运行触及区域回归**

  在实施前先保存 `pytest --collect-only`、失败节点、Python/依赖版本和当前 git 状态；实施后只允许新增失败数为 0。既有失败必须逐项标注为 baseline，不得用“全量 PASS”掩盖。

  ```powershell
  $env:PYTHONPATH='.'
  python -m pytest --import-mode=importlib tests/test_vector/ tests/test_pipeline/ tests/test_scripts/test_batch_executor.py tests/test_server/ tests/test_wiki/test_lint.py -v
  ```

  Expected: 相对基线无新增收集错误、无新增失败；若出现 `conftest.py` 兄弟级联问题，按 `docs/environment/SETUP.md` §4 记录证据，不得把真实回归标记成基础设施问题。

- [ ] **Step 2: 运行静态检查**

  ```powershell
  python -m ruff check src/pipeline/librarian.py src/pipeline/stages/indexer.py src/orchestrator/batch_runner.py src/server/app.py src/server/provider_health.py src/wiki/features/lint.py
  python -m mypy src/server/provider_health.py src/vector/upsert.py
  ```

  若 `ruff`/`mypy` 未安装，先记录工具版本并按项目既有方式安装；不得以跳过检查代替。Expected：所有本次修改文件无新增 lint/type 错误；既存错误按文件和行号单独记录。

- [ ] **Step 3: 再次运行真实 server smoke test**

  重复 Task 2 Step 9，确认 `/health` 返回 200，shutdown 无未回收 task 警告。

  同时记录 lifespan `yield` 前墙钟耗时、Provider 探测状态摘要、shutdown 耗时和端口释放结果；任一超过 15s/5s 即验收失败。

- [ ] **Step 3a: 运行端到端项目隔离与降级验收**

  用两个项目并发执行真实写入和查询，验证向量、删除/清理均不串项目；模拟一个 Provider 超时，验证 `/health` 仍为 liveness 200、语义能力状态被记录为 degraded、请求路径不产生未处理异常。

- [ ] **Step 4: 更新 graphify**

  ```powershell
  graphify update .
  ```

  执行前记录 `graphify-out/` 的 dirty 文件清单，执行后只接受由本次代码变更产生的增量；命令不可用时记录版本/错误并将其标为环境阻塞，不得伪造成功证据。

- [ ] **Step 5: 更新进度与记忆**

  `.superpowers/sdd/progress.md` 记录每个 commit、测试命令、真实 server smoke 结果。参照 `.memory/feedback-host-process-spawn-0xC0000142.md` 的现有格式创建 `feedback-runtime-reliability-optimization.md`，记录显式项目 table invariant、Provider 后台任务生命周期和 lint 配置快照语义；若 `.memory/MEMORY.md` 不存在则创建并写入索引。

- [ ] **Step 6: 最终差异检查**

  ```powershell
  git status --short
  git diff --stat
  git diff -- src tests docs/superpowers/plans .superpowers/sdd .memory
  ```

  Expected: 每一行变化都能追溯到 Task 1-4；`knowledge/novel-wiki/` 用户数据未被暂存。

  额外检查：`git diff --cached --name-only` 不得包含 `knowledge/novel-wiki/` 或实施前已存在的 `graphify-out/` 文件；保存 A/B 隔离、启动计时、Provider 降级和测试基线证据路径。

- [ ] **Step 7: Commit 文档与账本**

  ```powershell
  git add .superpowers/sdd/progress.md docs/environment/SETUP.md
  git commit -m "docs(optimize): record runtime reliability verification"
  ```

  `docs/environment/SETUP.md` 未变化时不得强行暂存；`git add` 中删除该路径即可。`.memory/` 当前由工作区忽略，完成本地记忆写入但不使用 `git add -f`。`graphify-out/` 若执行前已 dirty，只运行更新并记录命令结果，不自动暂存既有图谱差异。

## 验收门槛（未全部满足不得标记完成）

1. **项目隔离：** 全 `src/` mutation 审计无未解释的无参路径；A/B 并发写入、查询、删除和清理均无串项目。
2. **向量完整性：** 空向量、混合维度、既有表维度冲突均在 upsert 前失败；无部分写入；任务失败/重试和日志可追踪。
3. **启动预算：** lifespan 进入到 `yield` `< 15s`；embedding 构造与 smoke 共用 5 秒预算；Provider 探测不阻塞 liveness；shutdown `< 5s` 且无 pending task、端口和 client 泄漏。
4. **Provider 降级：** 每个 Provider 返回结构化状态；单个失败不影响其他探测；模拟超时后 `/health` 仍为 200，并有明确 degraded 记录。
5. **Lint：** 每次运行阈值读取一次；不同项目阈值隔离；同一运行使用固定快照；提供至少一次前后 I/O/耗时对比。
6. **验证基线：** 记录实施前收集结果和失败清单；实施后无新增失败；静态检查覆盖所有修改文件。
7. **工作区安全：** 最终暂存区不含用户数据、既有 graphify dirty 文件或非本计划改动。

---

## 明确延期项

以下建议有价值，但不与本计划混做：

1. **`generate_ingest`/candidate/unified 契约统一：** 当前源码仍执行 chunked → unified → two-step fallback，而 AGENTS.md 描述 candidate 为默认路径。必须先写独立设计说明，确认生产真源后再删除 legacy；本计划不猜测正确语义。
2. **16 个目录级 `conftest.py` 收敛：** `test_vector`、`test_searcher`、`test_mcp_server` 需要真实依赖，其他目录安装 stubs，属于独立测试架构迁移；先做 prototype 证明单一根 conftest 不会再次污染 `sys.modules`，再另立计划。
3. **`parse_llm_json` 重写：** 虽然复杂度高，但它承担模型不规范输出兼容且已有回归资产；没有失败率或性能数据前不动。
4. **CLI `main` 拆分：** 397 行主要是 argparse 声明，圈复杂度仅 1；拆文件不会明显降低调用方认知负担。
5. **删除 legacy 无参向量接口：** 本轮保留兼容入口；只有 `rg` 和运行遥测证明无调用者后，才在单独 breaking-change 任务删除。

## Audit

### Round 1：全面漏洞审计 — completed

| 分级 | 漏洞位置 | 真实失败场景 | 整改 |
|---|---|---|---|
| ① 致命缺陷 | 初稿把关键词索引列为全局串库 | 重复改已修复代码，制造无价值 diff | 复查当前 `hybrid_search(..., paths)` 后从范围删除 |
| ① 致命缺陷 | 初稿拟让 `get_table(paths)` 懒初始化后直接写 | 远程 1536 维 embedding 先遇到默认 384 维新表，首次写即失败 | 明确先按实际 embedding 长度调用 `init_vector_store_for_paths(..., expected_dim)` |
| ② 重大隐患 | 直接删除无参向量接口 | legacy CLI 和既存测试在同一版本全部破坏 | 本轮只迁生产调用点，保留兼容入口 |
| ② 重大隐患 | 把 embedding smoke 也完全后台化 | 服务刚返回健康，首个 ingest 在 provider 尚未配置时失败 | embedding 初始化保留同步，但添加 5 秒硬超时 |
| ② 重大隐患 | 后台 Provider task 不受 lifespan 管理 | shutdown 时遗留 pending task/httpx client | 保存 task，shutdown cancel + gather；单 Provider close 放 finally |
| ② 重大隐患 | 串行 Provider 改并发但一个异常传播 | 一个 Provider 异常取消整组，其他 provider 未关闭 | `_probe_one` 内部吞并记录单项错误，gather 等待全部完成 |
| ② 重大隐患 | 在 Phase 4 全量重摄入中拆 `generate_ingest` | 正在运行的批次语义改变，恢复账本不可比 | 从本计划删除，列为全量重摄入后的独立计划 |
| ③ 优化疏漏 | lint 阈值提升出循环未说明配置可见性 | 同一次 lint 中途修改设置不会影响后半页，行为被误解 | 明确“一次 lint 一份快照”；下次调用重新读取，不做全局缓存 |
| ③ 优化疏漏 | 只写单元测试不跑真实 server | import/lifespan 错误在测试桩环境中被隐藏 | Task 2 和 Task 4 都要求真实端口 `/health` smoke |
| ③ 优化疏漏 | 工作区已有大量 wiki 变更 | `git add .` 将用户批处理数据混入优化 commit | 全局约束具体文件暂存，最终检查未暂存用户数据 |

**整改后复审：** 未发现剩余致命缺陷；重大隐患均已落实到 Global Constraints、Task 1/2 的测试与回滚条件中。

### Round 2：压力测试推演 — completed

| 压力场景 | 临界点/连锁反应 | 加固方案 |
|---|---|---|
| A/B 两项目并发 ingest，B 最后初始化 | A 的无参 upsert 写入 B，随后 A 搜索缺数据、B 出现污染 | 三条生产写入均从本次调用的 `paths` 显式取 table；跨项目行为测试 |
| 已有 384 维表切换到 1536 维 Provider | schema mismatch；若自动重建则历史向量丢失 | 按实际维度初始化并保留 `VectorDimensionMismatchError`；禁止自动 drop |
| 10 个 Provider 全部不可达 | 原实现最坏约 200 秒后才启动 | Provider 间并发且后台执行；启动关键路径不等待 |
| shutdown 恰逢 Provider 网络调用 | pending task、连接泄漏、测试进程挂住 | cancel + gather；`provider.close()` 放 finally；保留 `aclose_all` |
| 默认 embedding endpoint 永不返回 | lifespan 永远到不了 yield | `wait_for(..., timeout=5)` 后走既有 local fallback |
| Provider registry JSON 损坏 | 后台 task 未捕获异常并打印 unhandled warning | `probe_configured_providers` 捕获 load 异常并返回 |
| lint 10 万页面 | 每页读一次 JSON 放大为 10 万次本地 I/O | 每次 lint 仅读一次配置；页面解析与规则循环本轮不扩改 |
| lint 运行中设置文件被替换 | 前后页面使用不同阈值导致报告不可复现 | 单次运行固定阈值快照，下次运行生效 |
| 测试环境缺少真实 LanceDB | 新隔离测试因 stub 不支持 table API 而误失败 | 测试放入 `tests/test_vector/`，复用其恢复真实 pyarrow/lancedb 的 conftest |
| 用户批处理仍在修改 wiki | 实现/验证时工作区持续变脏，commit 误收数据 | 所有 add 显式列文件；发现并发批处理影响验证时暂停实施而非清理用户文件 |

**压力测试结论：** Task 1-3 可分别回滚，不形成必须整体上线的雪崩链。方案失效边界是“真实 LanceDB 测试环境不可用”或“用户未暂停会修改同一源码文件的并发开发”；前者按 SETUP.md 修复环境，后者停止实施并协调，不以跳过测试处理。

### Human review: pending

人工复核重点（逐项签字后才能执行 Task 1）：

1. 是否接受 `/health` 仅表示 liveness，Provider 未完成时由内部状态标记 degraded；
2. 是否接受 `RUFLO_PROVIDER_PROBE=0` 作为外部调用禁用开关，以及默认最多 4 并发；
3. embedding 构造与 smoke 的 5 秒预算、lifespan 15 秒预算和 shutdown 5 秒预算是否适合部署环境；
4. Phase 4 批处理是否会在实施窗口修改 `src/orchestrator/batch_runner.py`；
5. 是否同意把 test conftest 收敛与 candidate/unified 统一拆成后续独立计划；
6. 是否已保存测试基线并确认用户数据/既有 graphify dirty 文件不会进入暂存区。

### Round 3：整改后复审 — completed

本轮针对四角色评审重新检查：

- 项目隔离已从“3 个 upsert 调用点”扩展为全 `src/` mutation 审计，并增加 A/B 并发、删除和清理验收；
- 维度校验、失败原子性、任务失败/重试和可追踪日志已成为明确契约；
- Provider 探测补充并发上限、关闭超时、结构化状态、禁用开关和 shutdown 预算；
- 启动验收改为测量 lifespan 墙钟时间，不再只用 `/health` 返回 200 代替；
- 测试改用基线差异判定，并补充 lint 项目隔离、性能记录、工具不可用和工作区安全证据。

剩余阻塞只有人工复核签字和真实环境证据，未取得前不得进入编码。

### Open risks

1. `asyncio.to_thread` 只能限制等待方，不能强制终止已卡住的原生线程；若 Provider 构造进入不可中断的 native call，仍可能留下后台线程，必须在真实 smoke 中记录并单独阻断该 Provider 配置。
2. `ProviderRegistry.load()` 返回对象的具体映射类型需在 Task 2 测试中按当前实现锁定；不得为测试改变 registry interface。
3. `tests/test_vector/` 依赖真实本机 wheel；若环境缺失，必须按 `docs/environment/SETUP.md` 安装，不能把隔离测试降级成只断言 mock 调用。

### Rollback

- Task 1：恢复三个调用点为 `vector_upsert_chunks(lance_chunks)` 即可；不改 LanceDB schema、数据目录或表内容。
- Task 2：恢复 app.py 原串行循环并删除 `provider_health.py`；没有持久化格式变化。
- Task 3：把阈值读取移回页面循环；没有数据迁移。
- 每个任务独立 commit，优先使用 `git revert <commit>`；禁止对有用户改动的工作区执行 `git reset --hard`。

## Completion evidence

- Final commit: pending
- Tests: pending
- Static checks: pending
- Server smoke: pending
- Documentation updated: 本计划已创建；实现完成后更新 progress/memory，SETUP.md 仅在事实变化时更新
- Graph updated: pending
- Progress ledger updated: no
